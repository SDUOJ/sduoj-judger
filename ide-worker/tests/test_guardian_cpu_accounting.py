"""Exercise actual guardian loop with virtual time, not native isolation proof."""
import asyncio
import json
import os
import signal
from pathlib import Path
import pytest
from ide_debug import guardian
from ide_debug.launcher import Sandbox as Launcher


def exercise(tmp_path, monkeypatch, run_seconds=60, control_cpu_rate=.01, heartbeat=True):
    now = [0.]
    trusted_path = tmp_path / 'guardian'
    trusted_path.mkdir()
    (trusted_path / 'cgroup.procs').write_text(str(os.getpid()))
    spec = {'cgroups': {'memory': str(tmp_path / 'jail')}, 'version': 2,
            'trustedCgroups': {'memory': str(trusted_path)}, 'memory': 1234,
            'pids': 64, 'lifetime': 1800, 'idle': 300, 'guardianCpuSeconds': 30,
            'nsjail': '/not-executed', 'config': '/not-read'}
    filename = tmp_path / 'guardian.json'
    filename.write_text(json.dumps(spec))
    messages, groups, signals = [], {}, []

    class Group:
        def __init__(self, paths, version):
            self.paths = {key: Path(path) for key, path in paths.items()}
            self.trusted = paths == spec['trustedCgroups']
            self.removed, self.reads = False, 0
            groups['trusted' if self.trusted else 'jail'] = self
        def create(self, memory, pids):
            self.created = (memory, pids)
        def attach(self, pid):
            self.attached = pid
        def usage(self):
            self.reads += 1
            # Target/compile aggregate already exceeds the old 30s at startup.
            return {'cpuSeconds': now[0] * control_cpu_rate if self.trusted else 1000 + now[0],
                    'memory': 100, 'pids': 3}
        def remove(self):
            self.removed = True

    class Control:
        reads = 0
        def setblocking(self, value):
            pass
        def sendall(self, data):
            messages.append(json.loads(data))
        def recv(self, count):
            self.reads += 1
            request = ({'op': 'run', 'seconds': run_seconds, 'generation': 1}
                       if self.reads == 1 else {'op': 'heartbeat'})
            return json.dumps(dict(request, id=self.reads)).encode() + b'\n'

    control = Control()
    def select(read, write, error, timeout):
        now[0] += timeout
        return ([control], [], []) if heartbeat else ([], [], [])
    monkeypatch.setattr(guardian, 'Cgroups', Group)
    monkeypatch.setattr(guardian.socket, 'socket', lambda **kwargs: control)
    monkeypatch.setattr(guardian.sys, 'argv', ['guardian', str(filename), '42'])
    monkeypatch.setattr(guardian.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(guardian.select, 'select', select)
    monkeypatch.setattr(guardian.os, 'fork', lambda: 1234)
    monkeypatch.setattr(guardian.os, 'kill', lambda pid, sig: signals.append((pid, sig)))
    monkeypatch.setattr(guardian.os, 'waitpid', lambda pid, flags:
        (pid, (int(signal.SIGSTOP) << 8) | 0x7f) if flags == os.WUNTRACED else
        (0, 0) if flags == os.WNOHANG else (pid, 0))
    guardian.main()
    assert groups['jail'].created == (1234, 64)
    assert groups['jail'].attached == 1234
    assert signals == [(1234, signal.SIGCONT)]
    assert groups['jail'].removed and {'cleaned': True} in messages
    return messages, now[0], groups


@pytest.mark.parametrize('seconds', [40, 60])
def test_large_target_cpu_reaches_authoritative_wall_deadline(tmp_path, monkeypatch, seconds):
    messages, elapsed, groups = exercise(tmp_path, monkeypatch, run_seconds=seconds)
    assert {'event': 'runTimeout'} in messages
    assert {'event': 'guardianCpuLimit'} not in messages
    assert seconds <= elapsed <= seconds + .5
    assert groups['trusted'].reads > 0 and groups['jail'].reads > 0


def test_guardian_own_cpu_exhaustion_is_typed_and_cleans_target(tmp_path, monkeypatch):
    messages, elapsed, groups = exercise(tmp_path, monkeypatch, control_cpu_rate=3)
    assert {'event': 'guardianCpuLimit'} in messages
    assert {'event': 'runTimeout'} not in messages
    assert 10 <= elapsed < 11 and groups['jail'].removed


def test_stale_heartbeat_still_cleans_target(tmp_path, monkeypatch):
    messages, elapsed, _ = exercise(tmp_path, monkeypatch, heartbeat=False)
    assert 12 < elapsed <= 12.5
    assert not any('event' in message for message in messages)


def test_launcher_preserves_typed_guardian_limit_before_eof():
    async def check():
        value = Launcher.__new__(Launcher)
        value.control_reader = asyncio.StreamReader()
        value.control_reader.feed_data(b'{"event":"guardianCpuLimit"}\n{"cleaned":true}\n')
        value.control_reader.feed_eof()
        value.ready = asyncio.get_running_loop().create_future()
        value.ready.set_result({})
        value.cleaned = asyncio.get_running_loop().create_future()
        value.guard_pending = {}
        events = []
        value.event = lambda name, body: events.append((name, body))
        await value.read_guard()
        assert events == [('guardianCpuLimit', {}), ('guardianLost', {})]
        assert value.cleaned.result() is True
    asyncio.run(check())


@pytest.mark.parametrize('compiled', [False, True])
def test_runtime_preserves_control_failure_reason_and_reaps(compiled):
    from tests.test_debug_runtime import Runtime, Store, Sandbox, policy, manifest, ROW, body, wait_for, GiB
    async def check():
        runtime = Runtime(policy(), Store(), manifest(), Sandbox, lambda: 100 * GiB)
        await runtime.start()
        try:
            created = await runtime.create(7, body(), ROW)
            session = runtime.sessions[created['sessionId']]
            await wait_for(lambda: session.frozen and not session.actor.locked())
            sandbox = session.sandbox
            session.compiled = compiled
            runtime.adapter_event(session, 'guardianCpuLimit', {})
            runtime.adapter_event(session, 'guardianLost', {})
            await wait_for(lambda: session.state == 'terminated')
            assert session.reason == 'DEBUG_GUARDIAN_CPU_LIMIT'
            assert sandbox.killed
            assert runtime.view_metrics()['resident'] == 0
            assert runtime.view_metrics()['grantedBytes'] == 0
        finally:
            await runtime.close()
    asyncio.run(check())
