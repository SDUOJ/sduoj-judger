"""Per-ASGI-process bounded LSP cache; Redis owns recoverable session state."""

import asyncio
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import tempfile
import time

from .languages import command, normalize_signature, normalize_completion, normalize_locations, normalize_diagnostics
from .lsp_process import LspProcess, LspUnavailable, diagnostics_proven

logger = logging.getLogger(__name__)


class PoolBusy(Exception):
    pass


@dataclass
class Slot:
    session_id: str
    root: object
    process: object = None
    startup: object = None
    revision: int = 0
    users: int = 0
    last_used: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class LspPool:
    def __init__(self, config, max_processes=2, max_concurrency=2, max_starting=1,
                 max_waiters=64, process_factory=LspProcess):
        if min(max_processes, max_concurrency, max_starting, max_waiters) < 1:
            raise ValueError('pool limits must be positive')
        self.config = config
        self.max_processes = max_processes
        self.max_waiters = max_waiters
        self.entries = {}
        self._admission = asyncio.Lock()
        self._execution = asyncio.Semaphore(max_concurrency)
        self._starting = asyncio.Semaphore(max_starting)
        self._factory = process_factory
        self._waiting = 0
        self._closed = False

    async def _dispose(self, slot):
        if slot.startup and not slot.startup.done():
            slot.startup.cancel()
            await asyncio.gather(slot.startup, return_exceptions=True)
        if slot.process:
            await slot.process.close()
        await asyncio.to_thread(slot.root.cleanup)

    async def _reserve(self, session):
        async with self._admission:
            if self._closed:
                raise PoolBusy()
            slot = self.entries.get(session.session_id)
            if slot and slot.startup.done() and slot.users == 0 and (slot.startup.cancelled() or slot.startup.exception() or not slot.process or not slot.process.alive):
                await self._dispose(slot)
                del self.entries[session.session_id]
                slot = None
            if slot is None:
                if len(self.entries) >= self.max_processes:
                    candidates = [row for row in self.entries.values()
                                  if row.users == 0 and row.startup.done()]
                    if not candidates:
                        raise PoolBusy()
                    victim = min(candidates, key=lambda row: row.last_used)
                    await self._dispose(victim)
                    del self.entries[victim.session_id]
                slot = Slot(session.session_id, tempfile.TemporaryDirectory(prefix='sduoj-ide-'))
                self.entries[session.session_id] = slot
                slot.startup = asyncio.create_task(self._initialize(slot, session))
                # Retrieve failures even when every HTTP caller has timed out.
                slot.startup.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
            slot.users += 1
            slot.last_used = time.monotonic()
            return slot

    async def _initialize(self, slot, session):
        async with self._starting:
            root = Path(slot.root.name) / 'source'
            await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
            if session.language in {'c', 'cpp'}:
                arguments = (['clang++' if session.language == 'cpp' else 'clang'] +
                             (session.toolchain['analysisFlags'] if session.toolchain else
                              ['-std=c++20' if session.language == 'cpp' else '-std=c17']))
                database = [{'directory': str(root), 'file': str(root / session.document_name),
                             'arguments': arguments + ['-fsyntax-only', session.document_name]}]
                await asyncio.to_thread((root / 'compile_commands.json').write_text,
                                        json.dumps(database), encoding='utf-8')
            slot.process = self._factory(command(session.language, root), root,
                                         session.document_name, session.language)
            slot.process.toolchain = session.toolchain
            try:
                await slot.process.start(session.code, session.revision)
                slot.revision = session.revision
            except BaseException:
                await slot.process.close()
                raise

    async def execute(self, store, session, operation, request, timeout_ms):
        if self._waiting >= self.max_waiters or self._closed:
            raise PoolBusy()
        self._waiting += 1
        try:
            return await asyncio.wait_for(self._execute(store, session, operation, request), timeout_ms / 1000)
        finally:
            self._waiting -= 1

    async def _execute(self, store, session, operation, request):
        async with self._execution:
            slot = await self._reserve(session)
            try:
                # Cold initialization may outlive one HTTP timeout. Subsequent
                # requests share this task instead of restarting the server.
                await asyncio.shield(slot.startup)
                async with slot.lock:
                    latest = await store.get(session.session_id, session.owner_id, refresh=False)
                    if latest.revision != session.revision:
                        return {'revision': latest.revision, 'status': 'stale'}
                    if slot.revision != latest.revision:
                        await slot.process.update(latest.code, latest.revision)
                        slot.revision = latest.revision
                    if operation == 'completion':
                        value = await slot.process.completion(request['line'], request['column'],
                                                              request.get('triggerKind') or 'invoked', request.get('triggerCharacter'))
                        value = normalize_completion(value)
                    elif operation == 'signatureHelp':
                        value = normalize_signature(await slot.process.signature(request['line'], request['column']))
                    elif operation == 'definition':
                        value = {'locations': normalize_locations(
                            await slot.process.definition(request['line'], request['column']),
                            slot.process.uri, latest.document_uri)}
                    elif operation == 'diagnostics':
                        value = {'diagnostics': normalize_diagnostics(await slot.process.diagnostics())}
                        metadata = getattr(slot.process, 'diagnostics_metadata_for', None)
                        if metadata:
                            value.update(metadata('__default__'))
                    else:
                        raise LspUnavailable('unsupported operation')
                    current = await store.get(session.session_id, session.owner_id, refresh=False)
                    if current.revision != latest.revision:
                        return {'revision': current.revision, 'status': 'stale'}
                    if (operation == 'diagnostics' and session.language == 'java'
                            and hasattr(slot.process, 'diagnostics_metadata_for')
                            and not diagnostics_proven(value, latest.revision)):
                        return {'revision': latest.revision, 'status': 'degraded', 'diagnostics': [],
                                'degradedReason': 'diagnostic-revision-unproven',
                                **{key: value[key] for key in ('diagnosticRevision', 'diagnosticPublicationSequence',
                                    'diagnosticSnapshotRevision', 'diagnosticIdentity') if key in value}}
                    return {'revision': latest.revision, 'status': 'ready', **value}
            finally:
                slot.users -= 1
                slot.last_used = time.monotonic()

    async def release(self, session_id):
        async with self._admission:
            slot = self.entries.get(session_id)
            if slot and slot.users == 0:
                await self._dispose(slot)
                del self.entries[session_id]

    async def sweep(self, store):
        client = await store.redis()
        async with self._admission:
            for key, slot in list(self.entries.items()):
                if slot.users:
                    continue
                if time.monotonic() - slot.last_used > self.config.session_ttl_seconds or not await client.exists(store.session_key(key)):
                    await self._dispose(slot)
                    del self.entries[key]

    async def close(self):
        self._closed = True
        async with self._admission:
            await asyncio.gather(*(self._dispose(slot) for slot in self.entries.values()), return_exceptions=True)
            self.entries.clear()
