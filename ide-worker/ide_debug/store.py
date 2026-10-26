"""Redis metadata and ownership, never a queue for live debugger commands."""

import json
from .profiles import DebugError

PREFIX = "autolab:debug:v1:"
COMPARE_EXPIRE = """
if redis.call('GET',KEYS[1]) == ARGV[1] then
  return redis.call('EXPIRE',KEYS[1],ARGV[2])
end
return 0
"""
COMPARE_DELETE = """
if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end
return 0
"""


class Store:
    def __init__(self, redis):
        self.redis = redis

    async def claim_node(self, incarnation):
        # First implementation assigns the entire approved budget to ONE agent.
        # Additional HTTP processes must proxy to it, not allocate another pool.
        return bool(await self.redis.set(PREFIX + "agent", incarnation, nx=True))

    async def open_receipt(self, user, command):
        raw = await self.redis.get(PREFIX + "open:" + str(user) + ":" + command)
        return json.loads(raw) if raw else None

    async def save_open_receipt(self, user, command, fingerprint, session):
        await self.redis.set(
            PREFIX + "open:" + str(user) + ":" + command,
            json.dumps({"hash": fingerprint, "sessionId": session}),
            ex=2100,
        )

    async def renew_node(self, incarnation):
        if await self.redis.get(PREFIX + "agent") != incarnation:
            return False
        await self.redis.set(PREFIX + "agent-heartbeat", incarnation, ex=12)
        return True

    async def release_node(self, incarnation):
        return await self.redis.eval(COMPARE_DELETE, 1, PREFIX + "agent", incarnation)

    async def claim_user(self, user, session, ttl):
        key = PREFIX + "user:" + str(user)
        if await self.redis.set(key, session, nx=True, ex=ttl):
            return None
        return await self.redis.get(key)

    async def release_user(self, user, session):
        await self.redis.eval(COMPARE_DELETE, 1, PREFIX + "user:" + str(user), session)

    async def save(self, session):
        snapshot = session.snapshot()
        # Caller already bounds event/command results; source goes in a separate
        # key and is deleted at termination, never embedded in logs/snapshots.
        await self.redis.set(
            PREFIX + "session:" + session.id,
            json.dumps(snapshot, ensure_ascii=True),
            ex=2100,
        )

    async def save_spec(self, session, spec):
        await self.redis.set(PREFIX + "spec:" + session.id, json.dumps(spec), ex=2100)

    async def terminal(self, session):
        pipe = self.redis.pipeline(transaction=True)
        pipe.delete(PREFIX + "spec:" + session.id)
        pipe.set(
            PREFIX + "session:" + session.id, json.dumps(session.snapshot()), ex=300
        )
        await pipe.execute()
        await self.release_user(session.user, session.id)

    async def get(self, session_id, user):
        raw = await self.redis.get(PREFIX + "session:" + session_id)
        if not raw:
            raise DebugError("DEBUG_SESSION_LOST", 410)
        value = json.loads(raw)
        if value["userId"] != user:
            raise DebugError("DEBUG_SESSION_NOT_FOUND", 404)
        return value
