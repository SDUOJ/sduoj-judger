"""Bounded internal authorization RPC for each new debug execution."""

import asyncio
import json
import os
import logging
from urllib.parse import urlsplit
import httpx
from ide_intelligence.toolchain import timeout
from .profiles import DebugError


class Resolver:
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(3.0, connect=0.5),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            follow_redirects=False,
            trust_env=False,
        )
        self.permits = asyncio.Semaphore(8)
        self.waiting = 0

    async def resolve(self, body, user):
        url = os.getenv("AUTOLAB_DEBUG_RESOLVER_URL", "")
        token = os.getenv("AUTOLAB_IDE_TOOLCHAIN_TOKEN", "")
        parts = urlsplit(url)
        if (
            parts.scheme not in ("http", "https")
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.path != "/internal/ide/debug/resolve"
            or parts.query
            or parts.fragment
            or not token
        ):
            raise DebugError("DEBUG_AUTHORIZATION_UNAVAILABLE", 503)
        if self.waiting >= 32:
            raise DebugError("DEBUG_AUTHORIZATION_BUSY", 503)
        self.waiting += 1
        try:
            async with timeout(4.0):
                async with self.permits:
                    for attempt in range(2):
                        try:
                            return await self.fetch(body, user, url, token)
                        except httpx.TransportError:
                            if attempt:
                                raise
        except DebugError:
            raise
        except Exception as error:
            logging.getLogger(__name__).warning('Debug authorization RPC failed category=%s',
                                               type(error).__name__)
            raise DebugError("DEBUG_AUTHORIZATION_UNAVAILABLE", 503) from error
        finally:
            self.waiting -= 1

    async def fetch(self, body, user, url, token):
        async with self.client.stream(
            "POST",
            url,
            headers={"sduoj-token": token},
            json={
                "judgeTemplateId": body.judgeTemplateId,
                "user": user,
                "problemCode": body.problemCode,
                "context": body.context.dict(),
            },
        ) as response:
            if response.status_code in (400, 403, 404):
                raise DebugError("DEBUG_CONTEXT_FORBIDDEN", 403)
            response.raise_for_status()
            chunks = []
            size = 0
            async for data in response.aiter_bytes():
                size += len(data)
                if size > 524288:
                    raise ValueError("Oversize authorization response")
                chunks.append(data)
            value = json.loads(b"".join(chunks))
            if str(value["template"]["id"]) != body.judgeTemplateId or not isinstance(
                value["sourcePrefix"], str
            ):
                raise ValueError("Invalid debug specification")
            return value

    async def close(self):
        await self.client.aclose()
