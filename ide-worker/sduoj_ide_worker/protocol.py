"""Versioned Redis transport. Only authenticated Gateway writes jobs."""
import json
import os
import re
import time
from dataclasses import dataclass

PREFIX = os.environ.get('SDUOJ_IDE_PREFIX', 'sduoj:ide:v1:')
IDENTIFIER = re.compile(r'^[A-Za-z0-9_-]{1,80}$')


def key(*parts):
    return PREFIX + ':'.join(str(part) for part in parts)


def encode(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


@dataclass(frozen=True)
class Job:
    request_id: str
    value: dict

    @classmethod
    def parse(cls, raw):
        if not isinstance(raw, str) or len(raw.encode()) > 1048576:
            raise ValueError('Invalid job size')
        value = json.loads(raw)
        for field in ('requestId', 'sessionId', 'sessionEpoch', 'replyTo'):
            if not IDENTIFIER.fullmatch(value.get(field, '')):
                raise ValueError('Invalid transport identifier')
        if value.get('schemaVersion') != 1 or value.get('role') not in ('lsp', 'debug'):
            raise ValueError('Invalid protocol')
        if not isinstance(value.get('ownerId'), str) or not value['ownerId'].isdigit():
            raise ValueError('Invalid owner')
        if not isinstance(value.get('deadlineAt'), int):
            raise ValueError('Invalid deadline')
        return cls(value['requestId'], value)

    @property
    def expired(self):
        return self.value['deadlineAt'] <= int(time.time() * 1000)


# Store first, notify second, in one atomic operation. Pub/Sub is a wake-up only.
RESULT = """
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('PUBLISH', KEYS[2], ARGV[3])
return 1
"""

# Publish a terminal receipt and acknowledge the processing entry atomically.
# A cancellation after Redis commits must never replace a completed result.
RESULT_ACK = """
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2], 'NX')
redis.call('PUBLISH', KEYS[2], ARGV[3])
redis.call('LREM', KEYS[3], 1, ARGV[3])
return 1
"""

HEARTBEAT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('EXPIRE', KEYS[1], 12)
redis.call('SET', KEYS[2], ARGV[2], 'EX', 12)
redis.call('ZADD', KEYS[3], tonumber(ARGV[4])+12000, ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', ARGV[4])
redis.call('EXPIRE', KEYS[3], 24)
return 1
"""

# Cancel only a creation proven not to have entered the runtime. A queued
# request sees the tombstone and cannot start after Gateway timeout cleanup.
CANCEL_CREATE = """
local raw=redis.call('GET',KEYS[1])
if not raw then return 0 end
local meta=cjson.decode(raw)
if meta.ownerId~=ARGV[1] or meta.sessionEpoch~=ARGV[2] then return 0 end
if meta.createPhase~='reserved' and not (meta.createPhase=='claimed' and
   meta.createRequestId==ARGV[4] and ARGV[4]~='') then return 0 end
meta.createPhase='rejected-no-runtime'
meta.createError=ARGV[3]
redis.call('SET',KEYS[1],cjson.encode(meta),'EX',300)
if redis.call('GET',KEYS[2])==meta.sessionId then redis.call('DEL',KEYS[2]) end
if redis.call('GET',KEYS[3])==meta.sessionId then redis.call('DEL',KEYS[3]) end
return 1
"""

ROUTE = """
local raw = redis.call('GET', KEYS[1])
if not raw then return 0 end
local meta = cjson.decode(raw)
if meta.ownerId ~= ARGV[1] or meta.sessionEpoch ~= ARGV[2] then return 0 end
local current = redis.call('GET', KEYS[2])
if current then
  local route = cjson.decode(current)
  if route.workerId ~= ARGV[3] and redis.call('EXISTS', ARGV[5] .. route.workerId) == 1 then
    return 0
  end
end
redis.call('SET', KEYS[2], ARGV[4], 'EX', math.max(1, redis.call('TTL', KEYS[1])))
return 1
"""
