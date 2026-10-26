import asyncio
from collections import deque
import json
import secrets
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sduoj_ide_worker.debug import DebugExecution
from sduoj_ide_worker.protocol import key
from tests.test_redis_transport import client, close_client


@pytest.mark.asyncio
async def test_actor_unlock_refreshes_busy_without_replaying_a_command_event():
    redis = client()
    sid = secrets.token_hex(16)
    actor = asyncio.Lock()
    await actor.acquire()
    session = SimpleNamespace(id=sid, cursor=1, version=2, actor=actor, ticket=None,
        events=deque([{'cursor': 1, 'type': 'command', 'data': {'status': 'completed'}}]))
    session.snapshot = lambda: {'sessionId': sid, 'cursor': session.cursor,
        'stateVersion': session.version, 'state': 'stopped', 'busy': actor.locked()}
    execution = DebugExecution(SimpleNamespace(redis=redis, id='mirror-regression'))
    execution.runtime = SimpleNamespace(sessions={sid: session})
    keys = [key('debug', 'state', sid), key('debug', 'events', sid), key('debug', 'event-cursor', sid)]
    try:
        with patch.object(redis, 'pipeline', wraps=redis.pipeline) as pipeline:
            await execution.flush_events()
            assert json.loads(await redis.get(keys[0]))['busy'] is True
            actor.release()
            await execution.flush_events()
            assert json.loads(await redis.get(keys[0]))['busy'] is False
            assert await redis.llen(keys[1]) == 1
            assert await redis.get(keys[2]) == '1'
            await execution.flush_events()
            # Only actual state/event transitions write; no periodic rewrites.
            assert pipeline.call_count == 2
    finally:
        if actor.locked():
            actor.release()
        await redis.delete(*keys)
        await close_client(redis)
