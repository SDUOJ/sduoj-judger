"""Cancellation-safe transport for the repository's pinned redis-py 4.5.1."""

import asyncio
from redis.asyncio.connection import Connection


class CancellationSafeConnection(Connection):
    async def read_response(self, *args, **kwargs):
        try:
            return await super().read_response(*args, **kwargs)
        except asyncio.CancelledError:
            # 4.5.1 propagates cancellation without disconnecting. The unread
            # reply can then be parsed as the next borrower's response.
            await self.disconnect(nowait=True)
            raise

    async def send_packed_command(self, *args, **kwargs):
        try:
            return await super().send_packed_command(*args, **kwargs)
        except asyncio.CancelledError:
            await self.disconnect(nowait=True)
            raise
