"""Redis-backed best-effort IDE sessions.

Redis is the source of truth for the short-lived lease. A process-local worker
may keep a language server alive, but a missing Redis record always means that
the browser must recreate the logical session.
"""

import asyncio
from dataclasses import dataclass
import hashlib
import json
import secrets
import time
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from .config import IdeConfig
from .models import TextEdit
from .performance import measured


_REAL_REDIS = None
_REAL_REDIS_LOOP = None
_UNLOCK = "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end; return 0"


class SessionMissing(Exception):
    pass


class RevisionConflict(Exception):
    def __init__(self, server_revision: int):
        super().__init__("IDE revision conflict")
        self.server_revision = server_revision


class SessionCapacity(Exception):
    pass


@dataclass(frozen=True)
class Session:
    session_id: str
    owner_id: int
    client_hash: str
    language: str
    context_hash: str
    document_name: str
    document_uri: str
    revision: int
    code: str
    expires_at_ms: int
    toolchain: Optional[dict] = None


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _column_index(line: str, column: int) -> int:
    if column < 1:
        raise ValueError("Invalid column")
    units, index = 0, 0
    while index < len(line) and units < column - 1:
        units += _utf16_units(line[index])
        index += 1
    if units != column - 1:
        raise ValueError("Column is not a UTF-16 boundary")
    return index


def apply_edits(code: str, edits: Iterable[TextEdit]) -> str:
    lines = code.splitlines(keepends=True)
    if not lines:
        lines = [""]
    materialized = list(edits)

    def offset(line: int, column: int) -> int:
        if line > len(lines):
            if line == len(lines) + 1 and column == 1:
                return len(code)
            raise ValueError("Invalid line")
        before = sum(len(item) for item in lines[:line - 1])
        return before + _column_index(lines[line - 1], column)

    spans = []
    for edit in materialized:
        start, end = offset(edit.startLine, edit.startColumn), offset(edit.endLine, edit.endColumn)
        if end < start:
            raise ValueError("Edit end precedes start")
        spans.append((start, end, edit.text))
    result = code
    for start, end, text in sorted(spans, key=lambda item: (item[0], item[1]), reverse=True):
        result = result[:start] + text + result[end:]
    return result


class RedisSessionStore:
    def __init__(self, config: IdeConfig, redis_client=None):
        self.config = config
        self._redis = redis_client

    async def redis(self):
        global _REAL_REDIS, _REAL_REDIS_LOOP
        loop = asyncio.get_running_loop()
        if self._redis is None:
            if _REAL_REDIS is None or _REAL_REDIS_LOOP is not loop:
                if _REAL_REDIS is not None:
                    try:
                        await _REAL_REDIS.close()
                    except Exception:
                        pass
                import redis.asyncio as async_redis
                from .redis_connection import CancellationSafeConnection
                import os
                address = os.environ.get("AUTOLAB_REDIS_ADDR")
                password = os.environ.get("AUTOLAB_REDIS_PASSWORD")
                if not address or not password:
                    from const import Redis_addr, Redis_pass
                    address, password = Redis_addr, Redis_pass
                redis_max_connections = int(os.environ.get('AUTOLAB_IDE_REDIS_MAX_CONNECTIONS', '2048'))
                if not 256 <= redis_max_connections <= 4096:
                    raise RuntimeError('AUTOLAB_IDE_REDIS_MAX_CONNECTIONS must be between 256 and 4096')
                pool = async_redis.BlockingConnectionPool.from_url(
                    f"redis://{address}/0",
                    connection_class=CancellationSafeConnection,
                    password=password,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    max_connections=redis_max_connections,
                    timeout=2.0,
                    encoding="utf-8",
                    decode_responses=True,
                )
                _REAL_REDIS = async_redis.Redis(connection_pool=pool, auto_close_connection_pool=True)
                _REAL_REDIS_LOOP = loop
            self._redis = _REAL_REDIS
        return self._redis

    @staticmethod
    def session_key(session_id: str) -> str:
        return f"autolab:ide:session:{session_id}"

    @staticmethod
    def source_key(session_id: str) -> str:
        return f"autolab:ide:source:{session_id}"

    @staticmethod
    def client_key(owner_id: int, client_hash: str) -> str:
        return f"autolab:ide:client:{owner_id}:{client_hash}"

    @staticmethod
    def owner_key(owner_id: int) -> str:
        return f"autolab:ide:owner:{owner_id}:sessions"

    @staticmethod
    def lock_key(name: str) -> str:
        return f"autolab:ide:lock:{name}"

    async def _lock(self, name: str):
        client = await self.redis()
        token = secrets.token_urlsafe(18)
        key = self.lock_key(name)
        for _ in range(25):
            if await client.set(key, token, nx=True, ex=5):
                return key, token
            await asyncio.sleep(0.02)
        raise SessionCapacity("IDE session is busy")

    async def _unlock(self, lock):
        if not lock:
            return
        client = await self.redis()
        key, token = lock
        try:
            await client.eval(_UNLOCK, 1, key, token)
        except Exception:
            pass

    @measured('redis_refresh_seconds')
    async def _refresh(self, session_id: str, client_hash: str, owner_id: int) -> int:
        client = await self.redis()
        ttl = self.config.session_ttl_seconds
        async with client.pipeline(transaction=True) as transaction:
            transaction.expire(self.session_key(session_id), ttl)
            transaction.expire(self.source_key(session_id), ttl)
            transaction.expire(self.client_key(owner_id, client_hash), ttl)
            transaction.sadd(self.owner_key(owner_id), session_id)
            transaction.expire(self.owner_key(owner_id), ttl)
            await transaction.execute()
        return ttl

    @measured('redis_snapshot_seconds')
    async def _load(self, session_id: str, owner_id: int) -> Session:
        client = await self.redis()
        # The revision and source must belong to the same snapshot. Separate
        # reads can straddle another replica's atomic sync transaction.
        async with client.pipeline(transaction=True) as transaction:
            transaction.hgetall(self.session_key(session_id))
            transaction.get(self.source_key(session_id))
            transaction.ttl(self.session_key(session_id))
            data, code, ttl = await transaction.execute()
        if not data or int(data.get("owner_id", "-1")) != owner_id:
            raise SessionMissing()
        if code is None:
            raise SessionMissing()
        if ttl <= 0:
            raise SessionMissing()
        return Session(
            session_id=session_id,
            owner_id=owner_id,
            client_hash=data["client_hash"],
            language=data["language"],
            context_hash=data["context_hash"],
            document_name=data["document_name"],
            document_uri=data["document_uri"],
            revision=int(data["revision"]),
            code=code,
            expires_at_ms=int(time.time() * 1000) + ttl * 1000,
            toolchain=json.loads(data["toolchain"]) if data.get("toolchain") else None,
        )

    async def get(self, session_id: str, owner_id: int, refresh: bool = True) -> Session:
        session = await self._load(session_id, owner_id)
        if refresh:
            await self._refresh(session.session_id, session.client_hash, owner_id)
            session = await self._load(session_id, owner_id)
        return session

    @measured('store_create_seconds')
    async def create_or_reuse(
        self,
        owner_id: int,
        client_session_key: str,
        language: str,
        context: dict,
        document_name: str,
        code: str,
        toolchain: Optional[dict] = None,
    ) -> tuple[Session, bool]:
        client_hash = canonical_hash({"owner": owner_id, "client": client_session_key})
        context_hash = canonical_hash(context)
        mapping = self.client_key(owner_id, client_hash)
        lock = await self._lock(f"owner:{owner_id}")
        try:
            client = await self.redis()
            existing_id = await client.get(mapping)
            if existing_id:
                try:
                    existing = await self._load(existing_id, owner_id)
                    if (existing.language == language and existing.context_hash == context_hash
                            and existing.document_name == document_name and existing.toolchain == toolchain):
                        await self._refresh(existing.session_id, existing.client_hash, owner_id)
                        return await self._load(existing.session_id, owner_id), True
                except (SessionMissing, KeyError, ValueError):
                    await client.delete(mapping)
            active = []
            for candidate in await client.smembers(self.owner_key(owner_id)):
                try:
                    await self._load(candidate, owner_id)
                    active.append(candidate)
                except SessionMissing:
                    await client.srem(self.owner_key(owner_id), candidate)
            if len(active) >= self.config.max_sessions_per_user:
                raise SessionCapacity("IDE session limit reached")

            session_id = uuid4().hex
            document_uri = f"sduoj://ide/{session_id}/{document_name}"
            # A lost/cancelled create must not leave source or metadata keys
            # without TTL or an owner index. Commit the entire lease together.
            ttl = self.config.session_ttl_seconds
            # This advisory timestamp is conservative if Redis is delayed.
            # Redis TTL remains authoritative on the next request.
            expires_at_ms = int(time.time() * 1000) + ttl * 1000
            async with client.pipeline(transaction=True) as transaction:
                transaction.hset(self.session_key(session_id), mapping={
                    "owner_id": str(owner_id),
                    "client_hash": client_hash,
                    "language": language,
                    "context_hash": context_hash,
                    "document_name": document_name,
                    "document_uri": document_uri,
                    "revision": "1",
                    "toolchain": json.dumps(toolchain, sort_keys=True) if toolchain else "",
                })
                transaction.expire(self.session_key(session_id), ttl)
                transaction.set(self.source_key(session_id), code, ex=ttl)
                transaction.set(mapping, session_id, ex=ttl)
                transaction.sadd(self.owner_key(owner_id), session_id)
                transaction.expire(self.owner_key(owner_id), ttl)
                await transaction.execute()
            # EXEC confirmed all the fields below. A second snapshot adds a
            # Redis round trip after commit, delaying the HTTP confirmation.
            # Existing-session reuse still reads authoritative current state.
            return Session(session_id, owner_id, client_hash, language,
                           context_hash, document_name, document_uri, 1, code,
                           expires_at_ms, toolchain), False
        finally:
            await self._unlock(lock)

    @measured('store_sync_seconds')
    async def sync(self, session_id: str, owner_id: int, base_revision: int, revision: int,
                   code: Optional[str], edits: Optional[Iterable[TextEdit]]) -> Session:
        lock = await self._lock(f"session:{session_id}")
        try:
            session = await self._load(session_id, owner_id)
            # A valid owner is still active when retrying a stale revision.
            await self._refresh(session_id, session.client_hash, owner_id)
            # The server may commit a full-text sync before its response is
            # lost. Retrying that exact revision/content is idempotent.
            if session.revision == revision and code is not None and session.code == code:
                return await self._load(session_id, owner_id)
            if session.revision != base_revision:
                raise RevisionConflict(session.revision)
            if revision <= base_revision:
                raise RevisionConflict(session.revision)
            next_code = code if code is not None else apply_edits(session.code, edits or [])
            if len(next_code.encode("utf-8")) > self.config.max_code_bytes:
                raise ValueError("Code exceeds IDE limit")
            client = await self.redis()
            # MULTI commits the version and source together even if the HTTP
            # caller disconnects immediately after EXEC.
            async with client.pipeline(transaction=True) as transaction:
                transaction.hset(self.session_key(session_id), "revision", str(revision))
                transaction.set(self.source_key(session_id), next_code)
                for key in (self.session_key(session_id), self.source_key(session_id),
                            self.client_key(owner_id, session.client_hash), self.owner_key(owner_id)):
                    transaction.expire(key, self.config.session_ttl_seconds)
                await transaction.execute()
            return await self._load(session_id, owner_id)
        finally:
            await self._unlock(lock)

    async def close(self, session_id: str, owner_id: int) -> None:
        session = await self._load(session_id, owner_id)
        client = await self.redis()
        await client.delete(
            self.session_key(session_id),
            self.source_key(session_id),
            self.client_key(owner_id, session.client_hash),
        )
        await client.srem(self.owner_key(owner_id), session_id)


async def close_redis():
    global _REAL_REDIS, _REAL_REDIS_LOOP
    if _REAL_REDIS is None:
        return
    close = getattr(_REAL_REDIS, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result
    _REAL_REDIS = None
    _REAL_REDIS_LOOP = None
