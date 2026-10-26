"""Sharing, admission, document ownership and process recovery contracts."""
import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from ide_intelligence.config import load_config
from ide_intelligence.lsp_process import LspUnavailable
from ide_intelligence.pool import PoolBusy
from ide_intelligence.shared_pool import SharedLanguagePool
from tests.test_ide_pool import Store, session


class SharedProcess:
    instances = []
    active = peak = starting = peak_starting = 0
    delay = .01
    start_delay = .01

    def __init__(self, cmd, root, filename, language):
        self.root, self.language = root, language
        self.documents = {}
        self.alive = False
        self.instances.append(self)

    async def start(self, *args):
        SharedProcess.starting += 1
        SharedProcess.peak_starting = max(SharedProcess.peak_starting, SharedProcess.starting)
        try:
            await asyncio.sleep(self.start_delay)
            self.alive = True
        finally:
            SharedProcess.starting -= 1

    async def close(self):
        self.alive = False

    async def open_document(self, key, filename, code, revision):
        self.documents[key] = code
        return (self.root / key / filename).as_uri()

    async def update_document(self, key, code, revision):
        self.documents[key] = code

    async def close_document(self, key):
        self.documents.pop(key, None)

    async def completion_for(self, key, *args):
        SharedProcess.active += 1
        SharedProcess.peak = max(SharedProcess.peak, SharedProcess.active)
        try:
            await asyncio.sleep(self.delay)
            return [{'label': self.documents[key]}]
        finally:
            SharedProcess.active -= 1

    async def signature_for(self, key, *args):
        return {'signatures': [{'label': self.documents[key], 'parameters': []}]}


def test_one_language_process_reuses_documents_and_keeps_session_serial():
    async def run():
        before = len(SharedProcess.instances)
        SharedProcess.peak = 0
        pool = SharedLanguagePool(load_config(), process_factory=SharedProcess)
        store = Store()
        store.records['two'] = replace(session('two'), code='private two')
        try:
            results = await asyncio.gather(*(pool.execute(store, store.records[key], 'completion',
                {'line': 1, 'column': 1}, 1000) for key in ('one', 'two')))
            assert [row['items'][0]['label'] for row in results] == ['x=1', 'private two']
            assert SharedProcess.peak == 2 and len(SharedProcess.instances) == before + 1
            signatures = await asyncio.gather(*(pool.execute(store, store.records[key], 'signatureHelp',
                {'line': 1, 'column': 1}, 1000) for key in ('one', 'two')))
            assert [row['signatures'][0]['label'] for row in signatures] == ['x=1', 'private two']
            process = SharedProcess.instances[-1]
            await pool.release('one')
            assert process.alive and set(process.documents) == {'two'}
            SharedProcess.peak = 0
            await asyncio.gather(*(pool.execute(store, store.records['two'], 'completion',
                {'line': 1, 'column': 1}, 1000) for _ in range(2)))
            assert SharedProcess.peak == 1
            metrics = pool.metrics_snapshot()
            assert metrics['languages']['python']['documents'] == 1
            assert any(row['name'] == 'document_closes' and row['value'] == 1 for row in metrics['counters'])
        finally:
            await pool.close()
    asyncio.run(run())


def test_cold_initialization_survives_timeout_and_dead_process_recovers():
    async def run():
        class Slow(SharedProcess):
            start_delay = .1
        pool = SharedLanguagePool(load_config(), process_factory=Slow)
        store = Store()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await pool.execute(store, session(), 'completion', {'line': 1, 'column': 1}, 10)
            first = next(iter(pool.slots.values()))
            assert not first.startup.cancelled()
            assert (await pool.execute(store, session(), 'completion', {'line': 1, 'column': 1}, 1000))['status'] == 'ready'
            first.process.alive = False
            assert (await pool.execute(store, session(), 'completion', {'line': 1, 'column': 1}, 1000))['status'] == 'ready'
            assert next(iter(pool.slots.values())) is not first
        finally:
            await pool.close()
    asyncio.run(run())


def test_language_admission_does_not_consume_other_language_quota():
    async def run():
        class Slow(SharedProcess):
            delay = .1
        pool = SharedLanguagePool(load_config(), language_waiters={'java': 1}, process_factory=Slow)
        store = Store()
        store.records['one'] = replace(session(), language='java', document_name='Main.java')
        try:
            task = asyncio.create_task(pool.execute(store, store.records['one'], 'completion', {'line': 1, 'column': 1}, 1000))
            await asyncio.sleep(.01)
            with pytest.raises(PoolBusy):
                await pool.execute(store, store.records['one'], 'completion', {'line': 1, 'column': 1}, 1000)
            assert (await pool.execute(store, session('two'), 'completion', {'line': 1, 'column': 1}, 1000))['status'] == 'ready'
            await task
        finally:
            await pool.close()
    asyncio.run(run())


def test_java_startup_is_serial_even_with_multiple_processes():
    async def run():
        SharedProcess.peak_starting = 0
        pool = SharedLanguagePool(load_config(), max_starting=4,
                                  language_processes={'java': 2}, process_factory=SharedProcess)
        try:
            first = pool._new_slot('java', 0)
            second = pool._new_slot('java', 1)
            await asyncio.gather(first.startup, second.startup)
            assert SharedProcess.peak_starting == 1
        finally:
            await pool.close()
    asyncio.run(run())


def test_language_server_flags_enable_shared_ast_results_without_index_candidates():
    from ide_intelligence.languages import command
    cflags = command('c', Path('/tmp/work'), shared=True)
    cppflags = command('cpp', Path('/tmp/work'), shared=True)
    assert '--debug-origin' in cflags and '--completion-parse=always' in cppflags
    assert '--background-index=false' in cflags and cflags.count('--background-index=false') == 1
    assert '--index=false' not in cflags


def test_only_literal_standard_headers_can_contribute_to_shared_preamble():
    from ide_intelligence.lsp_process import LspProcess
    check = LspProcess._trusted_preamble
    assert check('#include <stdio.h>\nint main() { return 0; }')
    assert check('#include <bits/stdc++.h>\nusing namespace std;')
    for text in ['#define printf private_symbol\n#include <stdio.h>\nint main() {}',
                 '#include "private.h"\nint main(){}',
                 '#include <../../other/main.c>\nint main(){}',
                 '#pragma push_macro("printf")\n#include <stdio.h>',
                 '// comment\n#include <stdio.h>', '/* comment */ #define x y\n#include <stdio.h>',
                 '\\' + '\n#define printf secret\n#include <stdio.h>',
                 '??=define printf secret\n#include <stdio.h>',
                 '%:define printf secret\n#include <stdio.h>',
                 '#include <stddef.h>\vint\n#define printf private_secret_A\n#include <stdio.h>\nint main(){}',
                 '#include <stddef.h>\fint\n#define printf private_secret_A\n#include <stdio.h>\nint main(){}',
                 '\ufeff#define printf secret\n#include <stdio.h>']:
        assert not check(text), text


def test_preamble_control_pattern_preserves_original_unicode_boundary():
    from ide_intelligence.lsp_process import _UNSAFE_PREAMBLE_CHAR
    # All Unicode code points: regex optimization must not relax isolation.
    for point in range(0x110000):
        char = chr(point)
        expected = (point < 32 and char not in '\t\r\n') or char in '\x85\u2028\u2029\ufeff'
        assert bool(_UNSAFE_PREAMBLE_CHAR.search(char)) == expected, point


@pytest.mark.parametrize('language,filename', [('c', None), ('cpp', None),
    ('java', None), ('python', None), ('cpp', 'main.cpp')])
def test_document_render_is_once_and_matches_file_and_wire(tmp_path, monkeypatch, language, filename):
    from types import SimpleNamespace
    from ide_intelligence.lsp_process import LspProcess
    async def run():
        process = LspProcess([], tmp_path / 'workspace', filename, language)
        process.process = SimpleNamespace(returncode=None)
        scanned, messages = [], []
        check = process._trusted_preamble
        def counted(code):
            scanned.append(code)
            return check(code)
        async def notify(method, params):
            messages.append((method, params))
        monkeypatch.setattr(process, '_trusted_preamble', counted)
        monkeypatch.setattr(process, 'notify', notify)
        code = '#define private symbol\nint main() {}\n'
        await process.open_document('one', 'main.cpp', code)
        await process.update_document('one', code + '// update\n', 2)
        shared_c = language in {'c', 'cpp'} and filename is None
        assert len(scanned) == (2 if shared_c else 0)
        offset = int(shared_c)
        state = process._documents['one']
        assert state['line_offset'] == offset
        assert state['path'].read_text() == (';\n' if offset else '') + code + '// update\n'
        opened = next(row[1]['textDocument']['text'] for row in messages if row[0] == 'textDocument/didOpen')
        changed = next(row[1]['contentChanges'][0]['text'] for row in messages if row[0] == 'textDocument/didChange')
        assert opened == (';\n' if offset else '') + code
        assert changed == state['path'].read_text()
    asyncio.run(run())


def test_passive_diagnostics_release_execution_permit_and_keep_document_pinned():
    async def run():
        entered, publish = asyncio.Event(), asyncio.Event()
        class Diagnostics(SharedProcess):
            async def diagnostics_for(self, key):
                entered.set()
                await publish.wait()
                return []
        pool = SharedLanguagePool(load_config(), process_factory=Diagnostics,
                                  language_concurrency={'python': 1}, diagnostics_mode='release')
        store = Store()
        pending = asyncio.create_task(pool.execute(store, session(), 'diagnostics', {}, 1000))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert pool.entries['one'].users == 1 and pool.entries['one'].lock.locked()
            result = await pool.execute(store, session('two'), 'completion', {'line': 1, 'column': 1}, 100)
            assert result['status'] == 'ready'
            publish.set()
            assert (await pending)['status'] == 'ready'
            assert pool.entries['one'].users == 0
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await pool.close()
    asyncio.run(run())


def test_deferred_diagnostics_revalidate_revision_and_unpin_on_cancellation():
    async def run():
        entered, publish = asyncio.Event(), asyncio.Event()
        class Diagnostics(SharedProcess):
            async def diagnostics_for(self, key):
                entered.set()
                await publish.wait()
                return []
        pool = SharedLanguagePool(load_config(), process_factory=Diagnostics, diagnostics_mode='release')
        store = Store()
        try:
            pending = asyncio.create_task(pool.execute(store, session(), 'diagnostics', {}, 1000))
            await asyncio.wait_for(entered.wait(), 1)
            store.records['one'] = replace(session(), revision=2, code='new')
            publish.set()
            assert await pending == {'revision': 2, 'status': 'stale'}
            entered.clear()
            publish.clear()
            pending = asyncio.create_task(pool.execute(store, store.records['one'], 'diagnostics', {}, 1000))
            await asyncio.wait_for(entered.wait(), 1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert pool.entries['one'].users == 0
        finally:
            await pool.close()
    asyncio.run(run())
