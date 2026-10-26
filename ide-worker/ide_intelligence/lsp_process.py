"""Async stdio LSP transport: one reader, bounded frames, cancellable RPCs."""

import asyncio
import contextlib
import json
import os
from pathlib import Path
import signal
import re
import shutil
import time
from uuid import uuid4
from urllib.parse import unquote, urlsplit
from weakref import WeakValueDictionary

from .workspace import prepare, prepare_document, prepare_workspace
from .toolchain import configured_path, require_runtime


_C_HEADERS = frozenset(('assert ctype errno fenv float inttypes iso646 limits locale math '
    'setjmp signal stdalign stdarg stdatomic stdbool stddef stdint stdio '
    'stdlib stdnoreturn string tgmath threads time uchar wchar wctype').split())
_STANDARD_HEADERS = (frozenset(name + '.h' for name in _C_HEADERS)
    | frozenset('c' + name for name in _C_HEADERS)
    | frozenset(('algorithm any array atomic barrier bit bitset charconv chrono codecvt '
        'compare complex concepts condition_variable coroutine deque exception '
        'execution filesystem format forward_list fstream functional future '
        'initializer_list iomanip ios iosfwd iostream istream iterator latch '
        'limits list locale map memory memory_resource mutex new numbers numeric '
        'optional ostream queue random ranges ratio regex scoped_allocator '
        'semaphore set shared_mutex source_location span sstream stack stdexcept '
        'stop_token streambuf string string_view strstream syncstream system_error '
        'thread tuple type_traits typeindex typeinfo unordered_map unordered_set '
        'utility valarray variant vector version bits/stdc++.h').split()))
_UNSAFE_PREAMBLE_CHAR = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x85\u2028\u2029\ufeff]')
_STANDARD_INCLUDE = re.compile(r'#[ \t]*include[ \t]*<([A-Za-z0-9_./+]+)>[ \t]*')
_DECLARATION_START = re.compile(r'(?:int|void|char|float|double|long|short|signed|unsigned|bool|class|struct|union|enum|typedef|using|namespace|template|extern|static|const|volatile|auto|inline|constexpr)\b')


class LspUnavailable(RuntimeError):
    pass


def diagnostics_proven(metadata, revision):
    actual = metadata.get('diagnosticRevision')
    snapshot = metadata.get('diagnosticSnapshotRevision')
    return (type(actual) is int and actual == revision or
            metadata.get('diagnosticIdentity') == 'immutable-uri'
            and type(snapshot) is int and snapshot == revision)


class LspProcess:
    def __init__(self, command, root: Path, document_name, language: str):
        if document_name is not None and (Path(document_name).name != document_name
                                          or document_name.startswith('.') or '\\' in document_name):
            raise LspUnavailable('document name must be a single safe filename')
        self.command, self.root = command, root
        self.document_name, self.language = document_name, language
        self.uri = (root / document_name).as_uri() if document_name else None
        self.process = None
        self.sequence, self.version = 0, 1
        self._pending = {}
        self._reader = None
        self._write_lock = asyncio.Lock()
        self._diagnostics = []
        self._diagnostics_ready = asyncio.Event()
        self._documents = {}
        self.closed = False
        self.toolchain = None
        # Experimental correctness path; each Java source URI is written once.
        # Project import/removal costs require separate native performance proof.
        self.java_immutable_uri = (language == 'java' and document_name is None
            and os.getenv('AUTOLAB_IDE_JAVA_IMMUTABLE_URI', '0') == '1')
        self._document_locks = WeakValueDictionary()
        self._immutable_directories = set()
        self._immutable_transition_guard = asyncio.Lock()
        self._immutable_transition_owner = None
        self.document_transition_metrics = {'count': 0, 'secondsTotal': 0., 'secondsMax': 0.,
                                            'cancelled': 0, 'cancelWaitSecondsTotal': 0.}

    @property
    def alive(self):
        return self.process is not None and self.process.returncode is None and not self.closed

    async def start(self, code, revision=1):
        if not self.command:
            raise LspUnavailable('language server command is not configured')
        try:
            require_runtime(self.toolchain)
            if self.document_name is not None:
                await asyncio.to_thread(prepare, self, code)
            else:
                await asyncio.to_thread(prepare_workspace, self)
            # clangd leaves preamble PCH files behind on SIGKILL. Keep all
            # child temporary files inside the slot so eviction removes them.
            temporary = self.root.parent / 'tmp'
            await asyncio.to_thread(temporary.mkdir, parents=True, exist_ok=True)
            child_env = dict(os.environ, TMPDIR=str(temporary), TMP=str(temporary), TEMP=str(temporary))
            self.process = await asyncio.create_subprocess_exec(
                *self.command, cwd=str(self.root), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                limit=16384, start_new_session=True, env=child_env,
            )
            self._reader = asyncio.create_task(self._read_loop())
            folders = [] if self.document_name is None else [{'uri': self.root.as_uri(), 'name': self.root.name}]
            await self.request('initialize', {
                'processId': os.getpid(), 'rootUri': self.root.as_uri() if folders else None,
                'workspaceFolders': folders,
                'initializationOptions': {'workspaceFolders': [row['uri'] for row in folders],
                                          'settings': self._settings(),
                                          'fallbackFlags': (self.toolchain['analysisFlags'] if self.toolchain else
                                              ['-std=c++20'] if self.language == 'cpp' else ['-std=c17'])},
                'capabilities': {'workspace': {'configuration': True, 'workspaceFolders': True}, 'textDocument': {
                    'completion': {'completionItem': {'snippetSupport': True, 'insertReplaceSupport': True,
                        'documentationFormat': ['plaintext'], 'preselectSupport': True,
                        'commitCharactersSupport': True, 'insertTextModeSupport': {'valueSet': [1, 2]}},
                        'completionList': {'itemDefaults': ['editRange', 'insertTextFormat',
                            'insertTextMode', 'commitCharacters']}},
                    'signatureHelp': {'signatureInformation': {'documentationFormat': ['plaintext'],
                        'parameterInformation': {'labelOffsetSupport': True}}},
                    'definition': {}, 'publishDiagnostics': {'versionSupport': True},
                }},
            }, timeout=30 if self.language == 'java' else 5)
            await self.notify('initialized', {})
            if self.document_name is not None:
                await self.open_document('__default__', self.document_name, code, revision)
        except BaseException:
            await self.close()
            raise

    async def close(self):
        if self.java_immutable_uri and self._immutable_transition_owner is not asyncio.current_task():
            return await self._finish_document_transition(self._immutable_process_close())
        return await self._close()

    async def _immutable_process_close(self):
        async with self._immutable_transition():
            await self._close()

    async def _close(self):
        self.closed = True
        if self.process:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.process.wait(), 2)
        if self._reader:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
        for future in self._pending.values():
            if not future.done():
                future.set_exception(LspUnavailable('language server closed'))
        self._pending.clear()
        if self.java_immutable_uri:
            directories = list(self._immutable_directories)
            await asyncio.gather(*(asyncio.to_thread(shutil.rmtree, path, True) for path in directories))
            self._immutable_directories.clear()
            self._documents.clear()

    @staticmethod
    def _safe_document_name(document_name):
        if (Path(document_name).name != document_name or document_name.startswith('.')
                or '\\' in document_name):
            raise LspUnavailable('document name must be a single safe filename')

    def _document_path(self, key, document_name, revision=None):
        self._safe_document_name(document_name)
        if key == '__default__':
            return self.root / document_name
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', key):
            raise LspUnavailable('invalid document key')
        name = key
        if self.java_immutable_uri and revision is not None:
            name += '-r' + str(revision) + '-' + uuid4().hex
        directory = self.root.parent / 'documents' / name
        return directory / 'src' / document_name if self.language == 'java' else directory / document_name

    async def open_document(self, key, document_name, code, revision=1):
        if self.java_immutable_uri:
            return await self._finish_document_transition(self._immutable_open(key, document_name, code, revision))
        return await self._open_document(key, document_name, code, revision)

    def _document_lock(self, key):
        lock = self._document_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._document_locks[key] = lock
        return lock

    @contextlib.asynccontextmanager
    async def _immutable_transition(self):
        # Serialize project lifecycle changes within this fixed JVM. Failure of
        # one document cannot race a different document's filesystem preparation
        # and leave a staged source behind after process retirement.
        async with self._immutable_transition_guard:
            self._immutable_transition_owner = asyncio.current_task()
            try:
                yield
            finally:
                self._immutable_transition_owner = None

    async def _finish_document_transition(self, operation):
        # The pool keeps its same-document lock until this returns. Cancellation
        # must finish one consistent URI/folder transition, never detach cleanup.
        began = time.monotonic()
        task = asyncio.create_task(operation)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel_at = time.monotonic()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if task.done() and not task.cancelled():
                task.exception()
            self.document_transition_metrics['cancelled'] += 1
            self.document_transition_metrics['cancelWaitSecondsTotal'] += time.monotonic() - cancel_at
            raise
        finally:
            seconds = time.monotonic() - began
            self.document_transition_metrics['count'] += 1
            self.document_transition_metrics['secondsTotal'] += seconds
            self.document_transition_metrics['secondsMax'] = max(
                seconds, self.document_transition_metrics['secondsMax'])

    async def _notify_document(self, method, params):
        if self.java_immutable_uri:
            await asyncio.wait_for(self.notify(method, params), 2)
        else:
            await self.notify(method, params)

    async def _immutable_open(self, key, document_name, code, revision):
        async with self._immutable_transition(), self._document_lock(key):
            if key in self._documents:
                raise LspUnavailable('document is already open')
            try:
                return await self._open_document(key, document_name, code, revision)
            except Exception:
                # Unknown partial workspace state cannot be reused as a fresh
                # snapshot. Retire this fixed process slot; no extra process.
                await self.close()
                raise

    async def _open_document(self, key, document_name, code, revision=1, sequence=0,
                             removed_workspace=None):
        if not self.alive:
            raise LspUnavailable('language server is not running')
        path = self._document_path(key, document_name, revision)
        if self.java_immutable_uri:
            self._immutable_directories.add(path.parent.parent)
        wire_code, line_offset, trusted_preamble = self._render_document(code)
        await asyncio.to_thread(prepare_document, self, path, wire_code)
        uri = path.as_uri()
        state = {'document_name': document_name, 'path': path, 'uri': uri,
                 'version': revision, 'diagnostics': [], 'diagnostics_ready': asyncio.Event(),
                 'diagnostic_revision': None, 'diagnostic_publication_sequence': sequence,
                 'diagnostic_snapshot_revision': None, 'immutable_uri': self.java_immutable_uri,
                 'line_offset': line_offset, 'trusted_preamble': trusted_preamble}
        self._documents[key] = state
        if key != '__default__' and self.language in {'java', 'python'}:
            folder = path.parent.parent if self.language == 'java' else path.parent
            state['folder'] = folder
            state['workspace_name'] = folder.name if self.java_immutable_uri else key
            removed = ([{'uri': removed_workspace['folder'].as_uri(),
                         'name': removed_workspace.get('workspace_name', key)}]
                       if removed_workspace else [])
            await self._notify_document('workspace/didChangeWorkspaceFolders', {'event': {
                'added': [{'uri': folder.as_uri(), 'name': state['workspace_name']}],
                'removed': removed}})
        await self._notify_document('textDocument/didOpen', {'textDocument': {
            'uri': uri, 'languageId': self.language, 'version': revision, 'text': wire_code,
        }})
        return uri

    async def close_document(self, key):
        if self.java_immutable_uri:
            return await self._finish_document_transition(self._immutable_close(key))
        return await self._close_document(key)

    async def _immutable_close(self, key):
        async with self._immutable_transition(), self._document_lock(key):
            try:
                return await self._close_document(key)
            except Exception:
                await self.close()
                raise

    async def _close_document(self, key, remove_directory=True, notify_workspace=True):
        state = self._documents.pop(key, None)
        if state and self.alive:
            await self._notify_document('textDocument/didClose', {'textDocument': {'uri': state['uri']}})
            if state.get('folder') and notify_workspace:
                await self._notify_document('workspace/didChangeWorkspaceFolders', {'event': {
                    'added': [], 'removed': [{'uri': state['folder'].as_uri(),
                                             'name': state.get('workspace_name', key)}]}})
        if state and key != '__default__' and remove_directory:
            directory = state['path'].parent.parent if self.language == 'java' else state['path'].parent
            if self.java_immutable_uri:
                await self._remove_java_revision_projects(directory)
            await asyncio.to_thread(shutil.rmtree, directory, True)
            self._immutable_directories.discard(directory)

    async def _remove_java_revision_projects(self, directory):
        # JDTLS creates unmanaged projects inside its own data directory. Its
        # workspace-folder removal compares the project location with the
        # external folder, so it does not remove those internal projects.
        # Resolve and remove only this generated snapshot through JDTLS itself.
        documents = (self.root.parent / 'documents').resolve()
        directory = directory.resolve()
        if directory.parent != documents or directory not in self._immutable_directories:
            raise LspUnavailable('Java revision cleanup ownership mismatch')
        try:
            data = Path(self.command[self.command.index('-data') + 1]).resolve()
        except (ValueError, IndexError):
            raise LspUnavailable('Java revision cleanup data directory unavailable')
        expected_data = (self.root.parent / (self.root.name + '-jdtls-data')).resolve()
        if data != expected_data:
            raise LspUnavailable('Java revision cleanup data ownership mismatch')

        async def owned_projects():
            projects = await self.request('workspace/executeCommand', {
                'command': 'java.project.getAll', 'arguments': []}, timeout=2)
            if not isinstance(projects, list) or not all(isinstance(uri, str) for uri in projects):
                raise LspUnavailable('Java revision cleanup returned invalid projects')
            owned = []
            for uri in projects:
                parts = urlsplit(uri)
                if parts.scheme != 'file' or parts.netloc or parts.query or parts.fragment:
                    continue
                path = Path(unquote(parts.path)).resolve()
                suffix = path.name.removeprefix(directory.name + '_')
                if (path == directory or path.parent == data
                        and path.name.startswith(directory.name + '_')
                        and re.fullmatch(r'[0-9a-f]{1,8}', suffix)):
                    owned.append(uri)
            return owned

        async def remove_and_confirm():
            projects = await owned_projects()
            # Closing a working copy can expose both a visible project and an
            # unmanaged project for the same source folder. Resolve each newly
            # observed identity after the preceding deletion job completes.
            attempts = 0
            while projects:
                attempts += 1
                if attempts > 4:
                    raise LspUnavailable('Java revision project removal did not converge')
                await self.request('workspace/executeCommand', {
                    'command': 'java.project.changeImportedProjects',
                    'arguments': [[], [], projects]}, timeout=2)
                # The command schedules an Eclipse workspace job. Keep source
                # bytes until the server confirms removal, including when the
                # caller is cancelled by the unchanged operation deadline.
                await asyncio.sleep(.02)
                projects = await owned_projects()

        try:
            await asyncio.wait_for(remove_and_confirm(), 2)
        except Exception as error:
            raise LspUnavailable('Java revision project cleanup unconfirmed') from error

    async def update_document(self, key, code, revision):
        if self.java_immutable_uri:
            return await self._finish_document_transition(self._immutable_update(key, code, revision))
        return await self._update_document(key, code, revision)

    async def _immutable_update(self, key, code, revision):
        async with self._immutable_transition(), self._document_lock(key):
            state = self._state(key)
            directory = state['path'].parent.parent
            sequence = state.get('diagnostic_publication_sequence', 0)
            try:
                # JDTLS schedules folder updates as cancellable workspace jobs.
                # Separate remove-only/add-only notifications can cancel the
                # removal job before it finishes. Send this revision swap as a
                # single event so both sides belong to the same workspace job.
                await self._close_document(key, remove_directory=False, notify_workspace=False)
                uri = await self._open_document(key, state['document_name'], code, revision,
                                                sequence, removed_workspace=state)
                await self._remove_java_revision_projects(directory)
                await asyncio.to_thread(shutil.rmtree, directory, True)
                self._immutable_directories.discard(directory)
                return uri
            except Exception:
                await self.close()
                raise

    async def _update_document(self, key, code, revision):
        state = self._documents.get(key)
        if state is None:
            raise LspUnavailable('document is not open')
        wire_code, line_offset, trusted_preamble = self._render_document(code)
        await asyncio.to_thread(state['path'].write_text, wire_code, encoding='utf-8')
        state['version'] = revision
        state['line_offset'] = line_offset
        state['trusted_preamble'] = trusted_preamble
        state['diagnostics'] = []
        state['diagnostic_revision'] = None
        state['diagnostic_snapshot_revision'] = None
        state['diagnostics_ready'].clear()
        await self.notify('textDocument/didChange', {
            'textDocument': {'uri': state['uri'], 'version': revision},
            'contentChanges': [{'text': wire_code}],
        })

    async def update(self, code, revision):
        await self.update_document('__default__', code, revision)

    def _state(self, key):
        state = self._documents.get(key)
        if state is None:
            raise LspUnavailable('document is not open')
        return state

    async def completion(self, line, column, trigger_kind='invoked', trigger_character=None):
        return await self.completion_for('__default__', line, column, trigger_kind, trigger_character)

    async def completion_for(self, key, line, column, trigger_kind='invoked', trigger_character=None):
        state = self._state(key)
        context = {'triggerKind': {'invoked': 1, 'triggerCharacter': 2,
                                  'triggerForIncompleteCompletions': 3}.get(trigger_kind, 1)}
        if trigger_character:
            context['triggerCharacter'] = trigger_character
        value = await self.request('textDocument/completion', {
            'textDocument': {'uri': state['uri']}, 'position': {'line': line-1+state['line_offset'], 'character': column-1},
            'context': context,
        })
        if self.document_name is None and self.language in {'c', 'cpp'}:
            # clangd's dynamic index combines all opened files. Only current
            # AST candidates may cross the HTTP boundary; index docs can also
            # contain another session's comment for the same symbol USR.
            rows = value.get('items', []) if isinstance(value, dict) else value or []
            allowed = []
            for row in rows:
                match = re.match(r'^\[([^\]]+)\]', row.get('label', ''))
                if match and ('A' in match[1] or (state['trusted_preamble'] and 'P' in match[1])):
                    row = dict(row)
                    row['label'] = row['label'][match.end():]
                    row.pop('documentation', None)
                    def unshift_edit(edit):
                        edit = dict(edit)
                        for name in ('range', 'insert', 'replace'):
                            if name in edit:
                                edit[name] = self._unshift_range(edit[name], state['line_offset'])
                        return edit
                    if isinstance(row.get('textEdit'), dict):
                        row['textEdit'] = unshift_edit(row['textEdit'])
                    if row.get('additionalTextEdits'):
                        row['additionalTextEdits'] = [unshift_edit(edit) for edit in row['additionalTextEdits']]
                    allowed.append(row)
            if isinstance(value, dict):
                defaults = dict(value.get('itemDefaults', {}))
                edit_range = defaults.get('editRange')
                if isinstance(edit_range, dict):
                    defaults['editRange'] = ({name: self._unshift_range(part, state['line_offset'])
                                              for name, part in edit_range.items()}
                                             if 'insert' in edit_range else
                                             self._unshift_range(edit_range, state['line_offset']))
                return {**value, 'itemDefaults': defaults, 'items': allowed}
            return allowed
        return value

    async def signature(self, line, column):
        return await self.signature_for('__default__', line, column)

    async def signature_for(self, key, line, column):
        state = self._state(key)
        value = await self.request('textDocument/signatureHelp', {
            'textDocument': {'uri': state['uri']},
            'position': {'line': line - 1 + state['line_offset'], 'character': column - 1},
        })
        if self.document_name is None and self.language in {'c', 'cpp'} and isinstance(value, dict):
            for signature in value.get('signatures', []):
                signature.pop('documentation', None)
                for parameter in signature.get('parameters', []):
                    parameter.pop('documentation', None)
        return value

    async def definition(self, line, column):
        return await self.definition_for('__default__', line, column)

    async def definition_for(self, key, line, column):
        state = self._state(key)
        value = await self.request('textDocument/definition', {
            'textDocument': {'uri': state['uri']}, 'position': {'line': line-1+state['line_offset'], 'character': column-1},
        })
        if state['line_offset']:
            rows = [value] if isinstance(value, dict) else value or []
            mapped = []
            for row in rows:
                row = dict(row)
                if (row.get('uri') or row.get('targetUri')) == state['uri']:
                    for name in ('range', 'targetRange', 'targetSelectionRange'):
                        if name in row:
                            row[name] = self._unshift_range(row[name], state['line_offset'])
                mapped.append(row)
            return mapped
        return value

    async def diagnostics(self, timeout=1.0):
        return await self.diagnostics_for('__default__', timeout)

    async def diagnostics_for(self, key, timeout=1.0):
        state = self._state(key)
        if not state['diagnostics_ready'].is_set():
            try:
                await asyncio.wait_for(state['diagnostics_ready'].wait(), timeout)
            except asyncio.TimeoutError:
                raise LspUnavailable('diagnostics not ready')
        return state['diagnostics']

    def diagnostics_metadata_for(self, key):
        state = self._state(key)
        result = {'diagnosticRevision': state.get('diagnostic_revision'),
                'diagnosticPublicationSequence': state.get('diagnostic_publication_sequence', 0)}
        if state.get('immutable_uri'):
            result.update(diagnosticSnapshotRevision=state.get('diagnostic_snapshot_revision'),
                          diagnosticIdentity='immutable-uri')
        return result

    def document_metadata_for(self, key):
        state = self._documents.get(key)
        return {'uri': state['uri'], 'revision': state['version']} if state else None

    async def notify(self, method, params):
        await self._send({'jsonrpc': '2.0', 'method': method, 'params': params})

    async def request(self, method, params, timeout=3):
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send({'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params})
            return await asyncio.wait_for(future, timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            # Remove the pending future before yielding; late responses are ignored.
            self._pending.pop(request_id, None)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.notify('$/cancelRequest', {'id': request_id}), .1)
            raise
        finally:
            self._pending.pop(request_id, None)
            if future.done() and not future.cancelled():
                future.exception()
            elif not future.done():
                future.cancel()

    async def _send(self, message):
        if not self.alive:
            raise LspUnavailable('language server is not running')
        encoded = json.dumps(message, ensure_ascii=False, separators=(',', ':')).encode()
        async with self._write_lock:
            try:
                self.process.stdin.write(f'Content-Length: {len(encoded)}\r\n\r\n'.encode() + encoded)
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionError) as error:
                raise LspUnavailable('language server pipe closed') from error

    async def _read_message(self):
        headers, size = {}, 0
        while True:
            line = await self.process.stdout.readline()
            if not line:
                raise LspUnavailable('language server exited')
            size += len(line)
            if size > 8192:
                raise LspUnavailable('language-server header exceeds limit')
            if not line.strip():
                if headers:
                    break
                continue
            if b':' not in line:
                raise LspUnavailable('invalid language-server header')
            key, value = line.split(b':', 1)
            headers[key.lower()] = value.strip()
        length = int(headers.get(b'content-length', b'0'))
        if not 0 < length <= 16 * 1024 * 1024:
            raise LspUnavailable('language-server frame exceeds limit')
        return json.loads((await self.process.stdout.readexactly(length)).decode())

    async def _read_loop(self):
        try:
            while True:
                message = await self._read_message()
                if 'method' in message:
                    await self._server_message(message)
                else:
                    future = self._pending.get(message.get('id'))
                    if future and not future.done():
                        if 'error' in message:
                            future.set_exception(LspUnavailable('language server returned an error'))
                        else:
                            future.set_result(message.get('result'))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.closed = True
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(LspUnavailable(str(error)))

    async def _server_message(self, message):
        method, params = message['method'], message.get('params', {})
        if method == 'textDocument/publishDiagnostics':
            for state in self._documents.values():
                if params.get('uri') == state['uri']:
                    version = params.get('version')
                    if version is None or type(version) is int and version == state['version']:
                        state['diagnostics'] = [{**row, 'range': self._unshift_range(row['range'], state['line_offset'])}
                                                for row in params.get('diagnostics', [])
                                                if row.get('range', {}).get('start', {}).get('line', -1) >= state['line_offset']]
                        # Unversioned pushes remain usable by the editor, but
                        # cannot be claimed as a confirmed current revision.
                        state['diagnostic_revision'] = version
                        state['diagnostic_snapshot_revision'] = state['version'] if state.get('immutable_uri') else None
                        state['diagnostic_publication_sequence'] = state.get('diagnostic_publication_sequence', 0) + 1
                        state['diagnostics_ready'].set()
                    break
        if 'id' not in message:
            return
        if method == 'workspace/configuration':
            settings = self._settings()
            result = []
            for item in params.get('items', []):
                current = settings
                for part in item.get('section', '').split('.'):
                    current = current.get(part, {}) if isinstance(current, dict) else {}
                result.append(current)
        elif method == 'workspace/workspaceFolders':
            result = [{'uri': state['folder'].as_uri(), 'name': key}
                      for key, state in self._documents.items() if state.get('folder')]
            if self.document_name is not None:
                result = [{'uri': self.root.as_uri(), 'name': self.root.name}]
        elif method in {'client/registerCapability', 'client/unregisterCapability', 'window/workDoneProgress/create'}:
            result = None
        else:
            await self._send({'jsonrpc': '2.0', 'id': message['id'],
                              'error': {'code': -32601, 'message': 'Unsupported client method'}})
            return
        await self._send({'jsonrpc': '2.0', 'id': message['id'], 'result': result})

    def _settings(self):
        result = {'python': {'analysis': {'typeCheckingMode': 'basic', 'diagnosticMode': 'openFilesOnly',
                'autoImportCompletions': False, 'autoSearchPaths': False}},
                'pyright': {'disableOrganizeImports': True},
                'java': {'import': {'maven': {'enabled': False}, 'gradle': {'enabled': False}},
                         'signatureHelp': {'enabled': True},
                         'configuration': {'updateBuildConfiguration': 'automatic'}}}
        if self.toolchain and self.language == 'python':
            result['python']['pythonPath'] = configured_path(self.toolchain, 'python')
            result['python']['analysis']['pythonVersion'] = self.toolchain['pythonVersion']
        if self.toolchain and self.language == 'java':
            result['java']['configuration']['runtimes'] = [{
                'name': 'JavaSE-' + ('1.8' if self.toolchain['javaVersion'] == '8' else self.toolchain['javaVersion']),
                'path': configured_path(self.toolchain, 'java'), 'default': True}]
        return result

    def _line_offset(self, code):
        return self._render_document(code)[1]

    def _wire_code(self, code):
        # Empty external declaration terminates clangd's preamble before user
        # includes/macros. Headers are loaded by this document's Sema, so AST
        # results include stdlib without trusting another document's index.
        return self._render_document(code)[0]

    def _render_document(self, code):
        # One decision must drive both the file and the didOpen/didChange
        # payload. Other languages and isolated servers need no shared-index
        # preamble check.
        if self.document_name is not None or self.language not in {'c', 'cpp'}:
            return code, 0, False
        trusted = self._trusted_preamble(code)
        offset = int(not trusted)
        return (';\n' + code if offset else code), offset, trusted

    @staticmethod
    def _trusted_preamble(code):
        # Fail-closed fast path, not a C preprocessor: only literal includes
        # of immutable standard headers before an unmistakable language token.
        # Comments, macros, pragmas, digraphs and escaped lines use isolated
        # parsing instead. Untrusted code can never contribute a header symbol
        # to clangd's shared preamble index.
        if _UNSAFE_PREAMBLE_CHAR.search(code):
            return False
        # C preprocessing uses physical newline boundaries. Python splitlines
        # also removes VT/FF/Unicode separators, which would misclassify an
        # ignored include tail as a declaration ending the real preamble.
        for line in code.split('\n'):
            line = line.strip(' \t\r')
            if not line:
                continue
            include = _STANDARD_INCLUDE.fullmatch(line)
            if include:
                if include[1] not in _STANDARD_HEADERS:
                    return False
                continue
            return bool(_DECLARATION_START.match(line) or line.startswith(';'))
        return True

    @staticmethod
    def _unshift_range(value, offset):
        return {key: {**position, 'line': position['line'] - offset}
                for key, position in value.items()}
