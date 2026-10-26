"""Async LSP transport and local cache bounds, without installed language servers."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from ide_intelligence.config import load_config
from ide_intelligence.languages import command, normalize_locations
from ide_intelligence.lsp_process import LspProcess, LspUnavailable
from ide_intelligence.pool import LspPool, PoolBusy
from ide_intelligence.session_store import Session


def session(key='one'):
    return Session(key, 7, 'client', 'python', 'context', 'main.py', 'sduoj://ide/'+key+'/main.py', 1, 'x=1', 0)


class Store:
    def __init__(self):
        self.records = {key: session(key) for key in ('one', 'two', 'three')}

    async def get(self, key, owner, refresh=False):
        return self.records[key]


class Process:
    instances = []
    active = 0
    peak = 0
    delay = .01
    start_delay = .01

    def __init__(self, cmd, root, filename, language):
        self.uri = (root / filename).as_uri()
        self.closed = False
        self.alive = False
        self.instances.append(self)
        self.code = None

    async def start(self, code, revision=1):
        await asyncio.sleep(self.start_delay)
        self.alive = True
        self.code = code

    async def update(self, code, revision):
        self.code = code

    async def completion(self, *args):
        Process.active += 1
        Process.peak = max(Process.active, Process.peak)
        try:
            await asyncio.sleep(self.delay)
            return [{'label': self.code}]
        finally:
            Process.active -= 1

    async def close(self):
        self.closed = True
        self.alive = False

    async def signature(self, *args):
        return {'signatures': [{'label': self.code, 'parameters': []}]}


def test_pool_evicts_only_idle_and_rechecks_revision():
    async def run():
        pool = LspPool(load_config(), max_processes=1, process_factory=Process)
        store = Store()
        try:
            await pool.execute(store, session(), 'completion', {'line':1,'column':1}, 1000)
            first = Process.instances[-1]
            root = Path(pool.entries['one'].root.name)
            await pool.execute(store, session('two'), 'completion', {'line':1,'column':1}, 1000)
            assert first.closed and not root.exists()
            assert set(pool.entries) == {'two'}
            store.records['two'] = replace(session('two'), revision=2, code='new')
            result = await pool.execute(store, session('two'), 'completion', {'line':1,'column':1}, 1000)
            assert result['status'] == 'stale' and result['revision'] == 2
        finally:
            await pool.close()
    asyncio.run(run())


def test_busy_process_is_not_evicted_and_different_sessions_run_concurrently():
    async def run():
        Process.peak = 0
        pool = LspPool(load_config(), max_processes=2, max_concurrency=2, max_starting=2, process_factory=Process)
        store = Store()
        try:
            results = await asyncio.gather(*[pool.execute(store, session(key), 'completion', {'line':1,'column':1}, 1000) for key in ('one','two')])
            assert all(row['status'] == 'ready' for row in results)
            assert Process.peak == 2
            slot = pool.entries['one']
            slot.users = pool.entries['two'].users = 1
            with pytest.raises(PoolBusy):
                await pool._reserve(session('three'))
            assert set(pool.entries) == {'one','two'}
            slot.users = pool.entries['two'].users = 0
        finally:
            await pool.close()
    asyncio.run(run())


def test_cold_start_survives_http_timeout_and_capacity_is_bounded():
    async def run():
        class Slow(Process):
            start_delay = .15
        pool = LspPool(load_config(), max_processes=1, max_waiters=1, process_factory=Slow)
        store = Store()
        try:
            before = len(Process.instances)
            with pytest.raises(asyncio.TimeoutError):
                await pool.execute(store, session(), 'completion', {'line':1,'column':1}, 20)
            slot = pool.entries['one']
            assert not slot.startup.cancelled()
            result = await pool.execute(store, session(), 'completion', {'line':1,'column':1}, 1000)
            assert result['status'] == 'ready'
            assert len(Process.instances) == before + 1
            await pool.release('one')
            assert not pool.entries
        finally:
            await pool.close()
    asyncio.run(run())


def test_same_session_is_serial_and_waiter_limit_rejects_excess_work():
    async def run():
        Process.peak = 0
        class Slow(Process):
            delay = .05
        pool = LspPool(load_config(), max_processes=1, max_concurrency=2, max_waiters=2, process_factory=Slow)
        store = Store()
        try:
            tasks = [asyncio.create_task(pool.execute(store, session(), 'completion', {'line':1,'column':1}, 1000)) for _ in range(2)]
            await asyncio.sleep(.01)
            with pytest.raises(PoolBusy):
                await pool.execute(store, session(), 'completion', {'line':1,'column':1}, 1000)
            assert all(row['status']=='ready' for row in await asyncio.gather(*tasks))
            assert Process.peak == 1 and len(pool.entries) == 1
        finally:
            await pool.close()
    asyncio.run(run())


def test_failed_start_releases_slot_for_a_retry():
    async def run():
        class Failing(Process):
            async def start(self, *args):
                raise LspUnavailable('failed to start')
        pool = LspPool(load_config(), max_processes=1, process_factory=Failing)
        store = Store()
        try:
            with pytest.raises(LspUnavailable):
                await pool.execute(store, session(), 'completion', {'line':1,'column':1}, 1000)
            root = Path(pool.entries['one'].root.name)
            pool._factory = Process
            result = await pool.execute(store, session(), 'completion', {'line':1,'column':1}, 1000)
            assert result['status']=='ready' and not root.exists()
        finally:
            await pool.close()
    asyncio.run(run())


def test_fragmented_frames_and_cancelled_request_do_not_break_transport(tmp_path):
    fake = tmp_path / 'fake_lsp.py'
    fake.write_text('''import json,sys,time
while True:
 headers={}
 while True:
  line=sys.stdin.buffer.readline()
  if not line: sys.exit(0)
  if not line.strip(): break
  k,v=line.split(b":",1); headers[k.lower()]=v.strip()
 msg=json.loads(sys.stdin.buffer.read(int(headers[b"content-length"])))
 if 'id' not in msg: continue
 result={'capabilities':{}} if msg['method']=='initialize' else 'x'*100000
 if msg['method']=='slow': time.sleep(.1)
 data=json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}).encode()
 frame=b'Content-Length: '+str(len(data)).encode()+b'\\r\\n\\r\\n'+data
 sys.stdout.buffer.write(frame[:15]); sys.stdout.buffer.flush(); time.sleep(.01)
 sys.stdout.buffer.write(frame[15:]); sys.stdout.buffer.flush()
''')
    async def run():
        process = LspProcess([sys.executable, str(fake)], tmp_path / 'source', 'main.py', 'python')
        try:
            await process.start('x=1')
            with pytest.raises(asyncio.TimeoutError):
                await process.request('slow', {}, .02)
            # The single reader consumes the cancelled request's late response
            # and dispatches the following frame to the correct future.
            assert len(await process.request('fast', {}, 1)) == 100000
            assert process._pending == {}
        finally:
            await process.close()
        assert not process.alive
    asyncio.run(run())


def test_definition_mapping_and_java_workspace(tmp_path):
    one = command('java', tmp_path / 'one')
    two = command('java', tmp_path / 'two')
    assert one[-1] != two[-1] and one[-2] == '-data'
    assert tmp_path / 'one' not in Path(one[-1]).parents
    position = {'start':{'line':2,'character':3}, 'end':{'line':2,'character':8}}
    result = normalize_locations([{'uri':'file:///private/main.py','range':position},
                                  {'uri':'file:///usr/lib/os.py','range':position}],
                                 'file:///private/main.py', 'sduoj://ide/test/main.py')
    assert len(result) == 1 and result[0]['documentUri'] == 'sduoj://ide/test/main.py'


def test_eviction_cleans_child_temporary_files_even_after_forced_exit(tmp_path, monkeypatch):
    import ide_intelligence.pool as module
    fake = tmp_path / 'fake_temp_lsp.py'
    fake.write_text('''import json,sys,tempfile
while True:
 headers={}
 while True:
  line=sys.stdin.buffer.readline()
  if not line: sys.exit(0)
  if not line.strip(): break
  k,v=line.split(b":",1); headers[k.lower()]=v.strip()
 msg=json.loads(sys.stdin.buffer.read(int(headers[b"content-length"])))
 if 'id' not in msg: continue
 if msg['method']=='initialize': result={'capabilities':{}}
 else:
  f=tempfile.NamedTemporaryFile(delete=False); f.write(b'cached preamble'); f.close()
  result={'items':[{'label':f.name}]}
 data=json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}).encode()
 sys.stdout.buffer.write(b'Content-Length: '+str(len(data)).encode()+b'\\r\\n\\r\\n'+data)
 sys.stdout.buffer.flush()
''')
    monkeypatch.setattr(module, 'command', lambda *args: [sys.executable, str(fake)])
    async def run():
        pool = LspPool(load_config(), max_processes=1)
        try:
            result = await pool.execute(Store(), session(), 'completion', {'line':1,'column':1}, 2000)
            child_file = Path(result['items'][0]['label'])
            root = Path(pool.entries['one'].root.name)
            assert child_file.parent == root / 'tmp'
            assert child_file.exists()
            await pool.release('one')
            assert not child_file.exists() and not root.exists()
        finally:
            await pool.close()
    asyncio.run(run())
