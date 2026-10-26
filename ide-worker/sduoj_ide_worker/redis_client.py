"""Keep cancelled Redis RPC responses out of the next command's connection.

The pinned redis-py 4.5.1 read path propagates CancelledError without closing
the socket. LSP deadlines can therefore return a socket with an unread response
to the pool. Its next borrower may receive another command's result. Close the
connection before the pool can reuse it, including cancellation during writes.
"""
import asyncio

import redis.asyncio as redis_async
from redis.asyncio.connection import Connection, SSLConnection


class CancelledConnection:
    async def read_response(self, *args, **kwargs):
        try:
            return await super().read_response(*args, **kwargs)
        except asyncio.CancelledError:
            await self.disconnect(nowait=True)
            raise

    async def send_packed_command(self, *args, **kwargs):
        try:
            return await super().send_packed_command(*args, **kwargs)
        except asyncio.CancelledError:
            await self.disconnect(nowait=True)
            raise


class SafeConnection(CancelledConnection, Connection):
    pass


class SafeSSLConnection(CancelledConnection, SSLConnection):
    pass


def create_redis(url, **kwargs):
    # Let the native URL factory preserve auth, DB and TLS verification.
    # Replace its connection type before first use and own the created pool.
    client = redis_async.Redis.from_url(url, **kwargs)
    pool = client.connection_pool
    safe = {Connection: SafeConnection, SSLConnection: SafeSSLConnection}
    if pool.connection_class not in safe:
        raise ValueError('IDE workers support redis:// and rediss:// only')
    pool.connection_class = safe[pool.connection_class]
    client.auto_close_connection_pool = True
    return client
