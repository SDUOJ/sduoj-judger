"""Optional fleet-wide Redis admission before expensive LSP execution.

Bounded leases survive API cancellation/crash only until a fixed expiry. All
replicas share global/language/owner quotas; this is separate from user rate
windows. It never queues rejected work or falls back to local unlimited access.
"""
from dataclasses import dataclass
from uuid import uuid4

from .config import _int

_ACQUIRE = r'''
local clock=redis.call('TIME')
local now=tonumber(clock[1])*1000+math.floor(tonumber(clock[2])/1000)
local limits={tonumber(ARGV[1]),tonumber(ARGV[2]),tonumber(ARGV[3])}
for i=1,3 do
 redis.call('ZREMRANGEBYSCORE',KEYS[i],'-inf',now)
 if redis.call('ZCARD',KEYS[i])>=limits[i] then return i end
end
local second=math.floor(now/1000)
local rates={tonumber(ARGV[4]),tonumber(ARGV[5])}
for i=4,5 do
 local values=redis.call('HMGET',KEYS[i],'second','count')
 local count=0
 if tonumber(values[1])==second then count=tonumber(values[2]) or 0 end
 if rates[i-3]>0 and count>=rates[i-3] then return i end
end
local until_ms=now+tonumber(ARGV[6])
for i=1,3 do
 redis.call('ZADD',KEYS[i],until_ms,ARGV[7])
 redis.call('PEXPIRE',KEYS[i],tonumber(ARGV[6])+1000)
end
for i=4,5 do
 local previous=redis.call('HGET',KEYS[i],'second')
 if tonumber(previous)~=second then redis.call('HSET',KEYS[i],'second',second,'count',0) end
 redis.call('HINCRBY',KEYS[i],'count',1)
 redis.call('PEXPIRE',KEYS[i],2000)
end
return 0
'''

_RELEASE = r'''
local count=0
for i=1,3 do count=count+redis.call('ZREM',KEYS[i],ARGV[1]) end
return count
'''

REASONS = {1: 'global_active', 2: 'language_active', 3: 'user_active',
           4: 'global_rate', 5: 'language_rate'}


@dataclass(frozen=True)
class Budget:
    active: int
    language_active: dict
    user_active: int
    rate: int
    language_rate: dict
    lease_ms: int = 30000
    namespace: str = 'fleet-admission'

    @classmethod
    def environment(cls):
        active = _int('AUTOLAB_IDE_FLEET_ACTIVE', 0, 0, 4096)
        return cls(active, {lang: _int(f'AUTOLAB_IDE_FLEET_{lang.upper()}_ACTIVE',
            max(1, active), 1, 4096) for lang in ('c', 'cpp', 'java', 'python')},
            _int('AUTOLAB_IDE_USER_ACTIVE', 1, 1, 16),
            _int('AUTOLAB_IDE_FLEET_RPS', 0, 0, 10000),
            {lang: _int(f'AUTOLAB_IDE_FLEET_{lang.upper()}_RPS', 0, 0, 10000)
             for lang in ('c', 'cpp', 'java', 'python')})

    def view(self):
        return {'enabled': self.active > 0, 'active': self.active,
                'languageActive': self.language_active, 'userActive': self.user_active,
                'requestsPerSecond': self.rate, 'languageRequestsPerSecond': self.language_rate,
                'leaseMs': self.lease_ms}


async def acquire(store, owner, language, budget=None):
    budget = budget or Budget.environment()
    if not budget.active:
        return (), None
    if language not in budget.language_active:
        raise ValueError('Unsupported admission language')
    # One hash tag makes the operation atomic even if deployed on Redis Cluster.
    root = 'autolab:ide:{' + budget.namespace + '}'
    keys = (root + ':active', root + ':active:' + language, root + ':owner:' + str(owner),
            root + ':rate', root + ':rate:' + language)
    token = uuid4().hex
    client = await store.redis()
    reason = int(await client.eval(_ACQUIRE, 5, *keys, budget.active,
        budget.language_active[language], budget.user_active, budget.rate,
        budget.language_rate[language], budget.lease_ms, token))
    if reason:
        return None, REASONS.get(reason, 'unknown')
    return (client, keys[:3], token), None


async def release(lease):
    if lease:
        client, keys, token = lease
        await client.eval(_RELEASE, 3, *keys, token)
