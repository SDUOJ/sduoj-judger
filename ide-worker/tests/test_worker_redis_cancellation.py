"""Real Redis regression: a cancelled read cannot feed another command."""
import asyncio
import os
import secrets
from unittest.mock import AsyncMock

import pytest
from redis.asyncio.connection import SSLConnection

from sduoj_ide_worker.redis_client import create_redis, CancelledConnection, SafeConnection, SafeSSLConnection
from tests.test_redis_transport import client, close_client


@pytest.mark.asyncio
async def test_cancelled_blocking_read_cannot_become_the_next_ttl_result():
    name = 'ide-cancel-' + secrets.token_hex(8)
    redis = create_redis(os.getenv('TEST_IDE_REDIS_URL', 'redis://127.0.0.1:17362/15'),
                         decode_responses=True, max_connections=1, client_name=name)
    producer = client()
    queue, marker = name + ':queue', name + ':marker'
    blocking = None
    try:
        await redis.set(marker, 'fixture', ex=30)
        blocking = asyncio.create_task(redis.blpop(queue, timeout=5))
        async def wait_blocked():
            while True:
                if any(row['name'] == name and row['cmd'] == 'blpop' for row in await producer.client_list()):
                    return
                await asyncio.sleep(.001)
        await asyncio.wait_for(wait_blocked(), 2)
        blocking.cancel()
        await asyncio.gather(blocking, return_exceptions=True)
        follow = asyncio.create_task(redis.ttl(marker))
        await producer.rpush(queue, 'fixture')
        await producer.expire(queue, 30)
        remaining = await asyncio.wait_for(follow, 2)
        assert type(remaining) is int and 0 < remaining <= 30
        assert await redis.lrange(queue, 0, -1) == ['fixture']
        assert await redis.ping() is True
    finally:
        if blocking:
            blocking.cancel()
            await asyncio.gather(blocking, return_exceptions=True)
        await producer.delete(queue, marker)
        await close_client(redis)
        await close_client(producer)


@pytest.mark.asyncio
@pytest.mark.parametrize('url,expected', [('redis://localhost/15', SafeConnection),
                                         ('rediss://localhost/15?ssl_cert_reqs=required', SafeSSLConnection)])
async def test_url_factory_preserves_transport_and_pool_lifecycle(url, expected):
    redis = create_redis(url, decode_responses=True, max_connections=7)
    pool = redis.connection_pool
    assert pool.connection_class is expected
    assert pool.max_connections == 7
    assert pool.connection_kwargs['decode_responses'] is True
    assert pool.connection_kwargs['db'] == 15
    assert redis.auto_close_connection_pool is True
    if url.startswith('rediss:'):
        assert issubclass(pool.connection_class, SSLConnection)
        assert pool.connection_kwargs['ssl_cert_reqs'] == 'required'
    await close_client(redis)


@pytest.mark.asyncio
async def test_cancellation_during_a_write_disconnects_before_returning():
    writing = asyncio.Event()
    class Base:
        disconnect = AsyncMock()
        async def send_packed_command(self, *_args, **_kwargs):
            writing.set()
            await asyncio.Event().wait()
    class Safe(CancelledConnection, Base):
        pass
    connection = Safe()
    task = asyncio.create_task(connection.send_packed_command(['payload']))
    await writing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    connection.disconnect.assert_awaited_once_with(nowait=True)
