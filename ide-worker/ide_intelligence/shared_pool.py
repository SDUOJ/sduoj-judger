"""Bounded, language-sharded LSP processes with isolated session documents."""

import asyncio
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import tempfile
import time

from .languages import command, normalize_signature, normalize_completion, normalize_locations, normalize_diagnostics
from .lsp_process import LspProcess, LspUnavailable, diagnostics_proven
from .pool import PoolBusy
from .performance import measure, process_sample, process_tree_samples, cgroup_cpu_sample
from .toolchain import profile_hash

SharedPoolBusy = PoolBusy
LANGUAGES = ('c', 'cpp', 'java', 'python')


@dataclass
class Document:
    session_id: str
    document_name: str
    uri: str = ''
    revision: int = 0
    users: int = 0
    last_used: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class LanguageSlot:
    language: str
    number: int
    root: object
    semaphore: object
    process: object = None
    startup: object = None
    documents: dict = field(default_factory=dict)
    admission: asyncio.Lock = field(default_factory=asyncio.Lock)
    toolchain: object = None
    users: int = 0
    last_used: float = field(default_factory=time.monotonic)
    disposal: object = None


class SharedLanguagePool:
    def __init__(self, config, max_concurrency=16, max_starting=2, max_waiters=256,
                 language_concurrency=None, language_processes=None,
                 language_max_documents=128, language_waiters=None,
                 process_factory=LspProcess, diagnostics_mode='hold'):
        self.config = config
        self.max_waiters = max_waiters
        self.max_documents = (dict.fromkeys(LANGUAGES, language_max_documents)
                              if isinstance(language_max_documents, int) else language_max_documents)
        self._starting = asyncio.Semaphore(max_starting)
        # Java cold starts cannot starve C/C++/Python startup.
        self._java_starting = asyncio.Semaphore(1)
        self._execution = asyncio.Semaphore(max_concurrency)
        self.concurrency = dict.fromkeys(LANGUAGES, 4)
        self.concurrency.update(language_concurrency or {})
        self.processes = dict.fromkeys(LANGUAGES, 1)
        self.processes.update(language_processes or {})
        self.waiters = dict.fromkeys(LANGUAGES, max_waiters)
        self.waiters.update(language_waiters or {})
        self.max_processes = sum(self.processes.values())
        if min([max_concurrency, max_starting, max_waiters, *self.max_documents.values(),
                *self.concurrency.values(), *self.processes.values(), *self.waiters.values()]) < 1:
            raise ValueError('pool limits must be positive')
        self._factory = process_factory
        if diagnostics_mode not in {'hold', 'release'}:
            raise ValueError('unknown diagnostics mode')
        self.diagnostics_mode = diagnostics_mode
        self.slots = {}
        self._waiting = Counter()
        self._closed = False
        self._counters = Counter()
        self._durations = {}
        self._completed = Counter()
        self._cleanup_tasks = set()
        self._reservations = {}
        self._selection = {language: asyncio.Lock() for language in LANGUAGES}
        self._language_execution = {language: asyncio.Semaphore(value)
                                    for language, value in self.concurrency.items()}

    @property
    def entries(self):
        return {key: doc for slot in self.slots.values() for key, doc in slot.documents.items()}

    def _observe(self, name, seconds):
        # Fixed memory: cumulative histogram suitable for Prometheus scraping.
        row = self._durations.setdefault(name, {'count': 0, 'sum': 0., 'buckets': Counter()})
        row['count'] += 1
        row['sum'] += seconds
        row['max'] = max(row.get('max', 0.), seconds)
        for upper in (.005, .01, .025, .05, .1, .25, .5, 1., 2., 5., 10., 30.):
            if seconds <= upper:
                row['buckets'][str(upper)] += 1

    def _number(self, session):
        return int(hashlib.sha256(session.session_id.encode()).hexdigest()[:8], 16) % self.processes[session.language]

    def _new_slot(self, language, number, toolchain=None):
        if self._closed:
            raise PoolBusy()
        slot = LanguageSlot(language, number, tempfile.TemporaryDirectory(prefix=f'sduoj-ide-{language}-'),
                            asyncio.Semaphore(self.concurrency[language]), toolchain=toolchain)
        self.slots[(language, number)] = slot
        slot.startup = asyncio.create_task(self._initialize(slot))
        slot.startup.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        return slot

    async def warmup(self):
        # Profile-specific servers are created on demand within the same fixed slots.
        if os.environ.get("AUTOLAB_IDE_TOOLCHAIN_RESOLVER_URL"):
            return
        for language in LANGUAGES:
            for number in range(self.processes[language]):
                if (language, number) not in self.slots:
                    self._new_slot(language, number)
        await asyncio.gather(*(asyncio.shield(slot.startup) for slot in self.slots.values()), return_exceptions=True)

    async def _initialize(self, slot):
        async def start():
            async with self._starting:
                started = time.monotonic()
                self._counters[('start_attempts', slot.language)] += 1
                root = Path(slot.root.name) / 'workspace'
                await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
                slot.process = self._factory(command(slot.language, root, shared=True), root, None, slot.language)
                slot.process.toolchain = slot.toolchain
                try:
                    await slot.process.start('', 1)
                    self._counters[('starts', slot.language)] += 1
                except BaseException:
                    self._counters[('start_failures', slot.language)] += 1
                    await slot.process.close()
                    raise
                finally:
                    self._observe(('startup_seconds', slot.language), time.monotonic() - started)
        if slot.language == 'java':
            async with self._java_starting:
                await start()
        else:
            await start()

    async def _slot(self, session):
        language = session.language
        wanted = profile_hash(session.toolchain, language)
        async with self._selection[language]:
            if self._closed:
                raise PoolBusy()
            # Cancelled HTTP callers can leave an uncancelled cleanup in
            # progress. Keep that numbered slot unavailable until it finishes.
            for key, retiring in list(self.slots.items()):
                if key[0] == language and retiring.disposal is not None:
                    await self._dispose(retiring)
                    del self.slots[key]
            candidates = [slot for (name, _), slot in self.slots.items() if name == language]
            matching = sorted([slot for slot in candidates if profile_hash(slot.toolchain, language) == wanted],
                              key=lambda row: row.number)
            preferred = self.slots.get((language, self._number(session)))
            reservation = self._reservations.get(session.session_id)
            existing = (reservation[0] if reservation and reservation[0] in matching else
                        next((row for row in matching if session.session_id in row.documents), None))
            slot = existing or (preferred if preferred in matching else None)
            if slot is None and preferred is not None and matching:
                slot = matching[int(hashlib.sha256(session.session_id.encode()).hexdigest()[:8], 16) % len(matching)]
            if slot and slot.startup.done() and (slot.startup.cancelled() or slot.startup.exception()
                                                or not slot.process or not slot.process.alive):
                if slot.users:
                    raise PoolBusy()
                await self._dispose(slot)
                del self.slots[(language, slot.number)]
                self._counters[('restarts', language)] += 1
                candidates.remove(slot)
                slot = None
            if slot is None:
                preferred_number = self._number(session)
                missing = (preferred_number if (language, preferred_number) not in self.slots else
                           next((number for number in range(self.processes[language])
                                 if (language, number) not in self.slots), None))
                if missing is None:
                    idle = [row for row in candidates if not row.users and row.startup.done()]
                    if not idle:
                        raise PoolBusy()
                    victim = min(idle, key=lambda row: row.last_used)
                    missing = victim.number
                    # Close the old process before creating a replacement: profile
                    # churn must never exceed the configured process budget.
                    await self._dispose(victim)
                    del self.slots[(language, missing)]
                    self._counters[('profile_switches', language)] += 1
                if self._closed:
                    raise PoolBusy()
                slot = self._new_slot(language, missing, session.toolchain)
            slot.users += 1
            reservation = self._reservations.get(session.session_id)
            self._reservations[session.session_id] = (slot, reservation[1] + 1 if reservation else 1)
            slot.last_used = time.monotonic()
        try:
            await asyncio.shield(slot.startup)
        except BaseException:
            self._unpin(slot, session.session_id)
            raise
        return slot

    def _unpin(self, slot, session_id):
        slot.users -= 1
        reservation = self._reservations.get(session_id)
        if reservation and reservation[0] is slot:
            if reservation[1] == 1:
                del self._reservations[session_id]
            else:
                self._reservations[session_id] = (slot, reservation[1] - 1)

    async def execute(self, store, session, operation, request, timeout_ms):
        language = session.language
        if self._closed or sum(self._waiting.values()) >= self.max_waiters or self._waiting[language] >= self.waiters[language]:
            self._counters[('rejected', language)] += 1
            self._completed[(language, operation, 'busy')] += 1
            raise PoolBusy()
        self._waiting[language] += 1
        self._counters[('admitted', language)] += 1
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(self._execute(store, session, operation, request), timeout_ms / 1000)
            status = result['status']
            self._completed[(language, operation, status)] += 1
            if operation == 'completion' and status == 'ready' and result.get('items'):
                self._counters[('nonempty_completions', language)] += 1
            return result
        except asyncio.TimeoutError:
            self._completed[(language, operation, 'timeout')] += 1
            raise
        except Exception:
            self._completed[(language, operation, 'unavailable')] += 1
            raise
        finally:
            self._observe(('operation_seconds', language), time.monotonic() - started)
            self._waiting[language] -= 1

    async def _execute(self, store, session, operation, request):
        queued = time.monotonic()
        doc = None
        slot = None
        locked = False
        try:
            # Language quota first: one busy language cannot hold global permits
            # while waiting for its own concurrency limit.
            async with self._language_execution[session.language]:
                async with self._execution:
                    self._observe(('queue_seconds', session.language), time.monotonic() - queued)
                    with measure('slot_ready_seconds', session.language):
                        slot = await self._slot(session)
                    async with slot.admission:
                        doc = slot.documents.get(session.session_id)
                        if doc is None:
                            if len(slot.documents) >= self.max_documents[session.language]:
                                candidates = [row for row in slot.documents.values() if not row.users and not row.lock.locked()]
                                if not candidates:
                                    raise PoolBusy()
                                victim = min(candidates, key=lambda row: row.last_used)
                                del slot.documents[victim.session_id]
                                await slot.process.close_document(victim.session_id)
                                self._counters[('evictions', session.language)] += 1
                            doc = Document(session.session_id, session.document_name)
                            slot.documents[session.session_id] = doc
                        doc.users += 1
                    lock_started = time.monotonic()
                    await doc.lock.acquire()
                    locked = True
                    self._observe(('document_lock_wait_seconds', session.language), time.monotonic() - lock_started)
                    latest = await store.get(session.session_id, session.owner_id, refresh=False)
                    if latest.revision != session.revision:
                        return {'revision': latest.revision, 'status': 'stale'}
                    if not doc.uri:
                        with measure('document_open_seconds', session.language):
                            doc.uri = await slot.process.open_document(session.session_id, session.document_name,
                                                                       latest.code, latest.revision)
                        doc.revision = latest.revision
                        self._counters[('document_opens', session.language)] += 1
                    elif doc.revision != latest.revision:
                        with measure('document_update_seconds', session.language):
                            await slot.process.update_document(session.session_id, latest.code, latest.revision)
                        doc.revision = latest.revision
                        self._sync_document_metadata(slot, doc)
                    if operation != 'diagnostics' or self.diagnostics_mode == 'hold':
                        return await self._operation(store, session, latest, slot, doc, operation, request)
            # Keep the same-document serialization (not all LSP diagnostics
            # carry versions), but release permits for other documents' RPCs.
            return await self._operation(store, session, latest, slot, doc, operation, request)
        finally:
            if locked and slot is not None and doc is not None:
                # An immutable-URI transition completes before propagating HTTP
                # cancellation. Keep the pool's URI/revision in the same state.
                self._sync_document_metadata(slot, doc)
            if locked:
                doc.lock.release()
            if doc is not None:
                doc.users -= 1
                doc.last_used = time.monotonic()
            if slot is not None:
                self._unpin(slot, session.session_id)
                slot.last_used = time.monotonic()

    @staticmethod
    def _sync_document_metadata(slot, doc):
        getter = getattr(slot.process, 'document_metadata_for', None)
        current = getter(doc.session_id) if getter else None
        if current:
            doc.uri, doc.revision = current['uri'], current['revision']
        elif getter:
            doc.uri, doc.revision = '', 0

    async def _operation(self, store, session, latest, slot, doc, operation, request):
        with measure('lsp_' + operation + '_seconds', session.language):
            if operation == 'completion':
                value = normalize_completion(await slot.process.completion_for(
                    session.session_id, request['line'], request['column'],
                    request.get('triggerKind') or 'invoked', request.get('triggerCharacter')))
            elif operation == 'signatureHelp':
                value = normalize_signature(await slot.process.signature_for(session.session_id, request['line'], request['column']))
            elif operation == 'definition':
                value = {'locations': normalize_locations(
                    await slot.process.definition_for(session.session_id, request['line'], request['column']),
                    doc.uri, latest.document_uri)}
            elif operation == 'diagnostics':
                value = {'diagnostics': normalize_diagnostics(await slot.process.diagnostics_for(session.session_id))}
                metadata = getattr(slot.process, 'diagnostics_metadata_for', None)
                if metadata:
                    value.update(metadata(session.session_id))
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

    async def release(self, session_id):
        for language in LANGUAGES:
            async with self._selection[language]:
                for (name, _), slot in list(self.slots.items()):
                    if name != language:
                        continue
                    doc = slot.documents.get(session_id)
                    if doc:
                        async with doc.lock:
                            if slot.documents.get(session_id) is doc:
                                try:
                                    await slot.process.close_document(session_id)
                                finally:
                                    # Experimental close finishes physical cleanup
                                    # before cancellation propagates. Drop its cache
                                    # entry even when the HTTP waiter disappeared.
                                    getter = getattr(slot.process, 'document_metadata_for', None)
                                    if getter and getter(session_id) is None:
                                        slot.documents.pop(session_id, None)
                                slot.documents.pop(session_id, None)
                                self._counters[('document_closes', slot.language)] += 1

    async def sweep(self, store):
        client = await store.redis()
        for slot in list(self.slots.values()):
            for key, doc in list(slot.documents.items()):
                if doc.users or doc.lock.locked():
                    continue
                if time.monotonic() - doc.last_used > self.config.session_ttl_seconds or not await client.exists(store.session_key(key)):
                    await self.release(key)

    def metrics_snapshot(self):
        processes = [process_sample(os.getpid(), 'api')]
        for (language, _), slot in self.slots.items():
            process = getattr(slot.process, 'process', None)
            if process and process.returncode is None:
                processes.extend(process_tree_samples(process.pid, language))
        return {'pool': 'shared-language', 'waiting': dict(self._waiting), 'maxProcesses': self.max_processes,
                'sampledAt': time.time(),
                'cgroupCpu': cgroup_cpu_sample(),
                'diagnosticsMode': self.diagnostics_mode,
                'processSamples': [row for row in processes if row is not None],
                'transports': [{'language': language,
                    'pendingRequests': len(getattr(slot.process, '_pending', {})),
                    'javaImmutableUri': bool(getattr(slot.process, 'java_immutable_uri', False)),
                    'documentTransitions': dict(getattr(slot.process, 'document_transition_metrics', {})),
                    'diagnosticsReady': sum(state['diagnostics_ready'].is_set()
                        for state in getattr(slot.process, '_documents', {}).values())}
                    for (language, _), slot in self.slots.items() if slot.process],
                'languages': {language: {'processes': self.processes[language], 'concurrency': self.concurrency[language],
                    'maxDocumentsPerProcess': self.max_documents[language], 'maxWaiters': self.waiters[language],
                    'readyProcesses': sum(bool(slot.process and slot.process.alive and slot.startup.done()
                                               and not slot.startup.cancelled() and not slot.startup.exception())
                                          for (name, _), slot in self.slots.items() if name == language),
                    'documents': sum(len(slot.documents) for (name, _), slot in self.slots.items() if name == language)}
                    for language in self.processes},
                'counters': [{'name': name, 'language': language, 'value': value}
                             for (name, language), value in sorted(self._counters.items())],
                'operations': [{'language': language, 'operation': operation, 'outcome': outcome, 'count': count}
                               for (language, operation, outcome), count in sorted(self._completed.items())],
                'histograms': [{'name': name, 'language': language, **row, 'buckets': dict(row['buckets'])}
                               for (name, language), row in sorted(self._durations.items())]}

    async def _dispose(self, slot):
        if slot.disposal is None:
            slot.disposal = asyncio.create_task(self._cleanup(slot))
            self._cleanup_tasks.add(slot.disposal)
            slot.disposal.add_done_callback(self._cleanup_tasks.discard)
            slot.disposal.add_done_callback(lambda task: task.exception() if not task.cancelled() else None)
        await asyncio.shield(slot.disposal)

    async def _cleanup(self, slot):
        if slot.startup and not slot.startup.done():
            slot.startup.cancel()
            await asyncio.gather(slot.startup, return_exceptions=True)
        if slot.process:
            await slot.process.close()
        await asyncio.to_thread(slot.root.cleanup)

    async def close(self):
        self._closed = True
        # Serialize shutdown with selection, including a profile replacement
        # that was already waiting for its old process to close.
        for language in LANGUAGES:
            async with self._selection[language]:
                entries = [(key, slot) for key, slot in self.slots.items() if key[0] == language]
                await asyncio.gather(*(self._dispose(slot) for _, slot in entries), return_exceptions=True)
                for key, _ in entries:
                    self.slots.pop(key, None)
        if self._cleanup_tasks:
            await asyncio.gather(*self._cleanup_tasks, return_exceptions=True)
