"""Real Redis contract checks; no LSP/toolchain performance credit."""
import asyncio
import json
import os
import secrets
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
import redis.asyncio as async_redis
from ide_debug.config import Policy, MiB, GiB
from ide_intelligence.session_store import SessionMissing
from sduoj_ide_worker.protocol import Job, key, encode, RESULT, ROUTE, HEARTBEAT, CANCEL_CREATE
from sduoj_ide_worker.sessions import ExecutionSessions
from sduoj_ide_worker.debug import DebugStore


def run(coro):
    return asyncio.run(coro)


def client():
    return async_redis.Redis.from_url(os.getenv('TEST_IDE_REDIS_URL', 'redis://127.0.0.1:17362/15'), decode_responses=True)


async def close_client(redis):
    await getattr(redis, 'aclose', redis.close)(close_connection_pool=True)


def test_authoritative_owner_epoch_and_revision_snapshot():
    async def check():
        redis = client()
        sid = secrets.token_hex(16)
        meta = dict(sessionId=sid, sessionEpoch=secrets.token_hex(16), ownerId='9007199254740993',
                    language='python', documentName='main.py', documentUri='sduoj://ide/'+sid+'/main.py',
                    revision=7, code='value=42')
        await redis.set(key('session', sid), encode(meta), ex=60)
        store = ExecutionSessions(redis)
        session = await store.get(sid, 9007199254740993)
        assert session.revision == 7 and session.code == 'value=42'
        with pytest.raises(SessionMissing):
            await store.get(sid, 9007199254740992)
        with pytest.raises(SessionMissing):
            await store.metadata(sid, 9007199254740993, 'stale-epoch')
        assert await redis.ttl(key('session', sid)) <= 60  # worker never refreshes user activity
        await redis.delete(key('session', sid))
        await close_client(redis)
    run(check())


def test_results_survive_missing_gateway_subscriber():
    async def check():
        redis = client()
        rid = secrets.token_hex(16)
        await redis.eval(RESULT, 2, key('result', rid), key('reply', 'missing-gateway'), encode({'requestId': rid}), 30, rid)
        assert json.loads(await redis.get(key('result', rid)))['requestId'] == rid
        await redis.delete(key('result', rid))
        await close_client(redis)
    run(check())


def test_lsp_hot_route_cannot_be_stolen_from_live_owner():
    async def check():
        redis = client()
        sid, epoch = secrets.token_hex(16), secrets.token_hex(16)
        worker = 'test-'+secrets.token_hex(8)
        await redis.set(key('session', sid), encode(dict(ownerId='7', sessionEpoch=epoch)), ex=30)
        await redis.set(key('worker', worker), '{}', ex=30)
        await redis.set(key('route', sid), encode(dict(workerId=worker)), ex=30)
        result = await redis.eval(ROUTE, 2, key('session', sid), key('route', sid), '7', epoch,
                                  'different', encode(dict(workerId='different')), key('worker')+':')
        assert not result
        await redis.delete(key('worker', worker))
        result = await redis.eval(ROUTE, 2, key('session', sid), key('route', sid), '7', epoch,
                                  'different', encode(dict(workerId='different')), key('worker')+':')
        assert result
        await redis.delete(key('session', sid), key('route', sid))
        await close_client(redis)
    run(check())


def test_debug_user_claim_is_atomic_and_accepts_gateway_reservation():
    async def check():
        redis = client()
        user = int.from_bytes(secrets.token_bytes(7), 'big')
        store = DebugStore(redis, Policy(), SimpleNamespace(id='test', epoch='test'))
        await redis.set(key('debug', 'user', user), 'gateway-session', ex=30)
        assert await store.claim_user(user, 'gateway-session', 30) is None
        assert await store.claim_user(user, 'other-session', 30) == 'gateway-session'
        await store.release_user(user, 'other-session')
        assert await redis.get(key('debug', 'user', user)) == 'gateway-session'
        await store.release_user(user, 'gateway-session')
        assert not await redis.exists(key('debug', 'user', user))
        await close_client(redis)
    run(check())


@pytest.mark.parametrize('phase,claim,expected', [
    ('reserved', '', 1), ('claimed', '', 0), ('active', '', 0),
    ('claimed', 'matching-request', 1), ('claimed', 'other-request', 0),
])
def test_create_cancellation_cannot_race_a_claimed_or_active_runtime(phase, claim, expected):
    async def check():
        redis = client()
        sid, epoch, owner = secrets.token_hex(16), secrets.token_hex(16), str(secrets.randbits(52))
        keys = [key('session', sid), key('debug', 'user', owner), key('debug', 'open', owner, sid)]
        meta = dict(sessionId=sid, sessionEpoch=epoch, ownerId=owner, createPhase=phase,
                    createRequestId='matching-request')
        await redis.set(keys[0], encode(meta), ex=30)
        await redis.set(keys[1], sid, ex=30)
        await redis.set(keys[2], sid, ex=30)
        assert await redis.eval(CANCEL_CREATE, 3, *keys, owner, epoch, 'test-rejected', claim) == expected
        assert bool(await redis.exists(keys[1])) == (not expected)
        assert json.loads(await redis.get(keys[0]))['createPhase'] == ('rejected-no-runtime' if expected else phase)
        await redis.delete(*keys)
        await close_client(redis)
    run(check())


def test_worker_registry_prunes_expired_incarnations_and_fences_lease():
    async def check():
        redis = client()
        worker, epoch = 'test-'+secrets.token_hex(8), secrets.token_hex(16)
        keys = [key('node', worker), key('worker', worker), key('registry', 'test', worker)]
        await redis.set(keys[0], epoch, ex=30)
        await redis.zadd(keys[2], {'expired-worker': 1})
        now = int(time.time()*1000)
        assert await redis.eval(HEARTBEAT, 3, *keys, epoch, '{}', worker, now) == 1
        assert await redis.zrange(keys[2], 0, -1) == [worker]
        assert await redis.eval(HEARTBEAT, 3, *keys, 'stale-epoch', '{}', worker, now) == 0
        await redis.delete(*keys)
        await close_client(redis)
    run(check())
