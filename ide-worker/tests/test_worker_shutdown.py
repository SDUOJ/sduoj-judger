"""Shutdown receipts on the real Redis transport; no sandbox/performance credit."""
import asyncio
import json
import secrets
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import redis.asyncio as async_redis

from sduoj_ide_worker.debug import DebugExecution
from sduoj_ide_worker.protocol import Job, encode, key
from sduoj_ide_worker.worker import Worker
from tests.test_redis_transport import client, close_client


def payload():
    return dict(schemaVersion=1, requestId=secrets.token_hex(16), replyTo='shutdown-test',
        sessionId=secrets.token_hex(16), sessionEpoch=secrets.token_hex(16), ownerId='7',
        role='debug', operation='command', body={'commandId': secrets.token_hex(16),
        'operation': 'next'}, deadlineAt=int(time.time() * 1000) + 60000)


@pytest.mark.asyncio
@pytest.mark.parametrize('phase', ['claim', 'process'])
async def test_consumer_failure_logs_stage_and_category_without_private_error_text(caplog, phase):
    redis = SimpleNamespace(blpop=AsyncMock(return_value=('queue', 'request-id')))
    worker = Worker('lsp', 'cpp', redis=redis)
    if phase == 'claim':
        redis.blpop.side_effect = RuntimeError('PRIVATE_PASSWORD_SOURCE')
    else:
        worker.process = AsyncMock(side_effect=RuntimeError('PRIVATE_PASSWORD_SOURCE'))
    await worker.consume()
    assert worker.closed.is_set()
    assert 'language=cpp' in caplog.text and 'phase=' + phase in caplog.text
    assert 'category=RuntimeError' in caplog.text
    assert 'PRIVATE_PASSWORD_SOURCE' not in caplog.text


@pytest.mark.asyncio
async def test_shutdown_drains_ids_moved_before_consumer_received_the_reply():
    redis = client()
    worker = Worker('debug', redis=redis)
    worker.debug = SimpleNamespace(interrupt=AsyncMock())
    keys = []
    try:
        for queue in (worker.queue, worker.control_queue):
            value = payload()
            rid, processing = value['requestId'], queue + ':processing'
            keys.extend([processing, key('job', rid), key('result', rid)])
            await redis.set(key('job', rid), encode(value), ex=60)
            await redis.rpush(processing, rid)
        await worker.drain_processing()
        for index in range(0, len(keys), 3):
            assert await redis.llen(keys[index]) == 0
            receipt = json.loads(await redis.get(keys[index + 2]))
            assert receipt['error'] == 'DEBUG_COMMAND_INTERRUPTED'
        assert worker.debug.interrupt.await_count == 2
    finally:
        await redis.delete(*keys)
        await close_client(redis)


@pytest.mark.asyncio
@pytest.mark.parametrize('cancel_before_execute', [False, True])
async def test_cancellation_returns_terminal_receipt_before_removing_processing(cancel_before_execute):
    redis = client()
    worker = Worker('debug', redis=redis)
    value = payload()
    rid, processing = value['requestId'], worker.queue + ':processing'
    keys = [processing, key('job', rid), key('result', rid)]
    started = asyncio.Event()
    async def executing(_):
        started.set()
        await asyncio.Event().wait()
    worker.debug = SimpleNamespace(execute=executing, interrupt=AsyncMock())
    await redis.set(keys[1], encode(value), ex=60)
    await redis.rpush(processing, rid)
    if cancel_before_execute:
        original_get = redis.get
        async def reading(name):
            if name == keys[1] and not started.is_set():
                started.set()
                await asyncio.Event().wait()
            return await original_get(name)
        redis.get = reading
    task = asyncio.create_task(worker.process(rid, processing))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        result = json.loads(await redis.get(keys[2]))
        assert result['error'] == 'DEBUG_COMMAND_INTERRUPTED'
        assert result['httpStatus'] == 503
        assert result['requestId'] == rid
        assert await redis.llen(processing) == 0
        worker.debug.interrupt.assert_awaited_once()
        # A duplicate id is acknowledged without executing the command again.
        await redis.rpush(processing, rid)
        worker.debug.execute = AsyncMock()
        await worker.process(rid, processing)
        worker.debug.execute.assert_not_awaited()
        assert await redis.llen(processing) == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await redis.delete(*keys)
        await close_client(redis)


@pytest.mark.asyncio
async def test_interruption_after_a_committed_reply_preserves_the_completed_result():
    redis = client()
    value = payload()
    worker = Worker('debug', redis=redis)
    rid, processing = value['requestId'], worker.queue + ':processing'
    keys = [processing, key('result', rid)]
    try:
        await redis.rpush(processing, rid)
        job = Job.parse(encode(value))
        await worker.reply(job, {'accepted': True}, processing=processing)
        completed = await redis.get(keys[1])
        await worker.reply(job, status=503, error='DEBUG_COMMAND_INTERRUPTED', processing=processing)
        assert await redis.get(keys[1]) == completed
        assert await redis.llen(processing) == 0
        assert await redis.ttl(keys[1]) > 0
    finally:
        await redis.delete(*keys)
        await close_client(redis)


@pytest.mark.asyncio
async def test_unconfirmed_terminal_write_keeps_processing_entry_for_inspection():
    redis = client()
    value = payload()
    worker = Worker('debug', redis=redis)
    rid, processing = value['requestId'], worker.queue + ':processing'
    started = asyncio.Event()
    async def executing(_):
        started.set()
        await asyncio.Event().wait()
    worker.debug = SimpleNamespace(execute=executing, interrupt=AsyncMock())
    worker.reply = AsyncMock(side_effect=async_redis.ConnectionError('test disconnect'))
    keys = [processing, key('job', rid), key('result', rid)]
    await redis.set(keys[1], encode(value), ex=60)
    await redis.rpush(processing, rid)
    task = asyncio.create_task(worker.process(rid, processing))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert await redis.lrange(processing, 0, -1) == [rid]
        assert not await redis.exists(keys[2])
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await redis.delete(*keys)
        await close_client(redis)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,matching', [('claimed', True), ('accepted', True), ('claimed', False)])
async def test_interrupted_command_ledger_never_overwrites_other_or_accepted_commands(status, matching):
    from sduoj_ide_worker.debug import digest
    redis = client()
    value = payload()
    ledger = key('debug', 'commands', value['sessionId'])
    command_id = value['body']['commandId']
    prior = {'hash': digest(value['body']) if matching else 'another-payload', 'status': status}
    execution = DebugExecution(SimpleNamespace(redis=redis, id='shutdown-ledger'))
    try:
        await redis.hset(ledger, command_id, encode(prior))
        await redis.expire(ledger, 60)
        await execution.interrupt(Job.parse(encode(value)))
        result = json.loads(await redis.hget(ledger, command_id))
        if status == 'claimed' and matching:
            assert result['status'] == 'rejected' and result['error'] == 'DEBUG_COMMAND_INTERRUPTED'
        else:
            assert result == prior
        assert await redis.ttl(ledger) > 0
    finally:
        await redis.delete(ledger)
        await close_client(redis)
