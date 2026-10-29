"""Fail-stop owner of compile -> handoff -> fresh runtime transitions.

Only this process forks launchers, pins their pidfds and changes phase cgroups.
It never runs source code. A separate trusted namespace supervisor compiles
through the official sandbox and copies only after kernel-confirmed drain.
"""
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import socket
import sys
import time

from .cgroups import Cgroups, SessionDomain, namespace_init, process_uids
from .process_identity import open_pidfd, send_pidfd


MAX_FRAME = 262144


def emit(value):
    print(json.dumps(value, separators=(',', ':')), flush=True)


def prepared_wire(spec, digest):
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError('Invalid artifact receipt')
    root = Path(spec['export']) / 'artifacts'
    fd = os.open(root / 'manifest.json', os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        raw = stream.read(131073)
    if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Artifact manifest changed')
    value, wire = json.loads(raw), dict(spec['wire'])
    if (value.get('sourceSha256') != hashlib.sha256(wire['code'].encode()).hexdigest() or
            value.get('templateSha256') != wire['templateSha256'] or
            value.get('nativeSha256') != wire['compileSandboxSha256'] or
            value.get('language') != wire['language']):
        raise ValueError('Artifact receipt identity mismatch')
    wire.update(preparedArtifactSha256=digest, preparedTemplateSha256=wire['templateSha256'])
    return wire


class Guardian:
    def __init__(self, spec, control):
        self.spec, self.control = spec, control
        if spec['version'] != 2:
            raise RuntimeError('Separate compile phases require cgroup v2')
        self.domain = SessionDomain(spec['cgroups'], 2, subuid=spec['subuid'])
        self.trusted = Cgroups(spec['trustedCgroups'], 2)
        self.child = None
        self.pinned = {}
        self.input_fd = self.output_fd = None
        self.output_eof = False
        self.output_buffer = b''
        self.input_buffer = b''
        self.control_buffer = b''
        self.phase, self.prepared = 'compile', None
        self.began = self.heartbeat = time.monotonic()
        self.hard = self.began + spec['lifetime']
        self.idle = self.began + spec['idle']
        self.phase_deadline = min(self.hard, self.began + spec['wire']['compileSeconds'] + 10)
        self.run_deadline, self.run_generation = math.inf, 0

    def reply(self, value):
        self.control.sendall(json.dumps(value, separators=(',', ':')).encode() + b'\n')

    def spawn(self, config, group, wire, capture):
        incoming, outgoing = os.pipe()
        output_read, output_write = os.pipe() if capture else (None, None)
        parent = os.getpid()
        child = os.fork()
        if child == 0:
            try:
                library = ctypes.CDLL(None, use_errno=True)
                if library.prctl(1, int(signal.SIGKILL), 0, 0, 0) != 0 or os.getppid() != parent:
                    os._exit(120)
                os.dup2(incoming, 0)
                if capture:
                    os.dup2(output_write, 1)
                for name in os.listdir('/proc/self/fd'):
                    fd = int(name)
                    if fd > 2:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                os.kill(os.getpid(), signal.SIGSTOP)
                os.execve(self.spec['nsjail'], [self.spec['nsjail'], '--config', config],
                          {'PATH': '/usr/bin:/bin'})
            finally:
                os._exit(121)
        os.close(incoming)
        if capture:
            os.close(output_write)
        self.child = child
        self.pinned[child] = open_pidfd(child)
        _, status = os.waitpid(child, os.WUNTRACED)
        if not os.WIFSTOPPED(status):
            raise RuntimeError('Phase launcher handshake failed')
        group.attach(child)
        os.set_blocking(outgoing, False)
        self.input_fd = outgoing
        self.input_buffer = json.dumps({'spec': wire}, separators=(',', ':')).encode() + b'\n'
        self.output_fd, self.output_eof = output_read, not capture
        self.output_buffer = b''
        if capture:
            os.set_blocking(output_read, False)
        send_pidfd(self.pinned[child], signal.SIGCONT)

    def close_pipes(self):
        for name in ('input_fd', 'output_fd'):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)

    def begin(self):
        for path in set(self.trusted.paths.values()):
            if str(os.getpid()) not in (path / 'cgroup.procs').read_text().split():
                raise RuntimeError('Guardian outside reserved cgroup')
        self.domain.create(self.spec['memory'], self.spec['pids'])
        compile_group = self.domain.branch('compile', self.spec['memory'], self.spec['pids'])
        self.handoff_group = self.domain.branch('handoff', self.spec['memory'], self.spec['pids'])
        control = Cgroups({'memory': str(compile_group.paths['memory'] / 'control')}, 2)
        self.spawn(self.spec['compileConfig'], control, self.spec['wire'], True)
        self.reply({'ready': True, 'startedAt': time.time(), 'hardSeconds': self.hard - time.monotonic()})

    def handoff(self):
        if self.phase != 'compile':
            raise RuntimeError('Unexpected phase transition')
        # Stop the already pinned parent before enumerating PID1. It cannot
        # reap and release a dying child's numeric PID during our handshake.
        send_pidfd(self.pinned[self.child], signal.SIGSTOP)
        _, status = os.waitpid(self.child, os.WUNTRACED)
        if not os.WIFSTOPPED(status):
            raise RuntimeError('Compile launcher did not stop')
        nodes = self.domain.nodes('compile')
        expected = self.domain.root / 'compile' / 'control'
        if set(nodes) != {self.domain.root / 'compile', expected}:
            raise RuntimeError('Native compiler domain has not been removed')
        members = {int(p) for p in (expected / 'cgroup.procs').read_text().split()}
        supervisors = [p for p in members if p != self.child and self.owns_supervisor(p, expected)]
        if len(supervisors) != 1 or members != {self.child, supervisors[0]}:
            raise RuntimeError('Unexpected compile phase processes')
        supervisor = supervisors[0]
        self.pinned[supervisor] = open_pidfd(supervisor)
        if not self.owns_supervisor(supervisor, expected):
            raise RuntimeError('Compile supervisor no longer belongs to the launcher')
        send_pidfd(self.pinned[supervisor], 0)
        send_pidfd(self.pinned[supervisor], signal.SIGSTOP)
        end = time.monotonic() + 1
        while True:
            send_pidfd(self.pinned[supervisor], 0)
            state = dict(line.split(':', 1) for line in
                Path(f'/proc/{supervisor}/status').read_text().splitlines() if ':' in line)
            if state.get('State', '').strip().startswith(('T', 't')):
                break
            if time.monotonic() >= end:
                raise RuntimeError('Compile supervisor did not stop')
            time.sleep(.01)
        if (process_uids(supervisor) != (os.getuid(),) * 4 or
                not namespace_init(supervisor, os.getuid(), self.spec['subuid'])):
            raise RuntimeError('Compile supervisor identity changed')
        self.handoff_group.attach(supervisor)
        self.handoff_group.attach(self.child)
        if not self.domain.drained('compile'):
            raise RuntimeError('Compiler tree is still populated')
        self.phase = 'handoff'
        self.input_buffer += b'freeze\n'
        send_pidfd(self.pinned[supervisor], signal.SIGCONT)
        send_pidfd(self.pinned[self.child], signal.SIGCONT)

    def owns_supervisor(self, pid, group):
        try:
            status = dict(line.split(':', 1) for line in
                Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
            return (str(pid) in (group / 'cgroup.procs').read_text().split() and
                    int(status['PPid'].strip()) == self.child and
                    process_uids(pid) == (os.getuid(),) * 4 and
                    namespace_init(pid, os.getuid(), self.spec['subuid']))
        except (FileNotFoundError, ProcessLookupError):
            return False

    def phase_message(self, value):
        if value == {'phase': 'handoff'}:
            self.handoff()
        elif set(value) == {'prepared'} and self.phase == 'handoff' and self.prepared is None:
            self.prepared = prepared_wire(self.spec, value['prepared'])
        elif value.get('event') == 'compileError' and self.phase in ('compile', 'handoff'):
            emit(value)
        else:
            raise RuntimeError('Invalid compile supervisor response')

    def read_phase(self):
        data = os.read(self.output_fd, 8192)
        if not data:
            self.output_eof = True
            if self.output_buffer:
                raise RuntimeError('Incomplete compile response')
            return
        self.output_buffer += data
        while b'\n' in self.output_buffer:
            line, self.output_buffer = self.output_buffer.split(b'\n', 1)
            if len(line) + 1 > MAX_FRAME:
                raise RuntimeError('Compile response exceeded bound')
            self.phase_message(json.loads(line))
        if len(self.output_buffer) >= MAX_FRAME:
            raise RuntimeError('Compile response exceeded bound')

    def transition(self, status):
        if self.phase == 'runtime':
            return False
        if status != 0 or self.prepared is None or not self.output_eof:
            raise RuntimeError('Compile phase did not complete')
        # Both the native compiler and its trusted setup namespace are now dead.
        for branch in ('compile', 'handoff'):
            if not self.domain.drained(branch):
                raise RuntimeError('Setup namespace descendants remain')
            self.domain.remove_branch(branch)
        self.close_pipes()
        for fd in self.pinned.values():
            os.close(fd)
        self.pinned.clear()
        runtime = self.domain.branch('runtime', self.spec['memory'], self.spec['pids'])
        self.phase = 'runtime'
        self.phase_deadline = math.inf
        self.spawn(self.spec['config'], runtime, self.prepared, False)
        return True

    def control_message(self, req):
        op = req['op']
        now = time.monotonic()
        if op == 'heartbeat':
            self.heartbeat = now
        elif op == 'touch':
            self.idle = min(self.hard, now + self.spec['idle'])
        elif op == 'run':
            seconds, generation = req['seconds'], req['generation']
            if (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0 or
                    type(generation) is not int or generation <= 0 or self.phase != 'runtime'):
                raise RuntimeError('Invalid runtime deadline')
            if generation > self.run_generation:
                self.run_generation = generation
                self.run_deadline = min(self.hard, now + seconds)
        elif op == 'run-end':
            if req['generation'] == self.run_generation:
                self.run_deadline = math.inf
        elif op in ('freeze', 'thaw'):
            if self.phase != 'runtime':
                raise RuntimeError('Cannot freeze an incomplete compile handoff')
            self.domain.freeze(op == 'freeze')
        elif op == 'limit':
            value = req['value']
            if (self.phase != 'runtime' or type(value) is not int or value <= 0 or
                    value > self.spec['memory'] or value % os.sysconf('SC_PAGE_SIZE')):
                raise RuntimeError('Invalid phase grant')
            self.domain.limit(value)
        elif op == 'kill':
            raise EOFError()
        elif op != 'stats':
            raise RuntimeError('Invalid guardian operation')
        self.reply({'id': req['id'], 'ok': True, **self.domain.usage()})

    def loop(self):
        status = None
        while True:
            now = time.monotonic()
            if now >= self.run_deadline:
                self.reply({'event': 'runTimeout'})
                return
            if now >= self.phase_deadline:
                emit({'event': 'compileError', 'body': {'code': 'DEBUG_COMPILE_TIMEOUT', 'output': ''}})
                return
            if now >= min(self.hard, self.idle) or now - self.heartbeat > 12:
                return
            if self.trusted.usage()['cpuSeconds'] >= self.spec['guardianCpuSeconds']:
                self.reply({'event': 'guardianCpuLimit'})
                return
            if status is None:
                pid, value = os.waitpid(self.child, os.WNOHANG)
                if pid:
                    status = value
            if status is not None and (self.phase == 'runtime' or self.output_eof):
                self.child = None
                if not self.transition(status):
                    return
                status = None
            reads = [self.control]
            if self.output_fd is not None and not self.output_eof:
                reads.append(self.output_fd)
            if self.phase == 'runtime' and len(self.input_buffer) < 1048576:
                reads.append(0)
            writes = [self.input_fd] if self.input_fd is not None and self.input_buffer else []
            readable, writable, _ = select.select(reads, writes, [],
                max(0, min(.5, self.hard - now, self.idle - now, self.run_deadline - now,
                           self.phase_deadline - now)))
            for fd in readable:
                if fd == self.control:
                    data = self.control.recv(8192)
                    if not data:
                        return
                    self.control_buffer += data
                    if len(self.control_buffer) > 16384:
                        raise RuntimeError('Unbounded guardian input')
                    while b'\n' in self.control_buffer:
                        line, self.control_buffer = self.control_buffer.split(b'\n', 1)
                        self.control_message(json.loads(line))
                elif fd == self.output_fd:
                    self.read_phase()
                else:
                    data = os.read(0, 8192)
                    if not data:
                        return
                    self.input_buffer += data
            if writable:
                count = os.write(self.input_fd, self.input_buffer[:8192])
                self.input_buffer = self.input_buffer[count:]

    def cleanup(self):
        # These pidfds were obtained before exec or at the guarded PID1 handoff.
        # They cover even a launcher that never created a namespace PID1.
        if self.child is not None and self.child not in self.pinned:
            # No unsafe PID fallback. Exiting this guardian triggers the
            # stopped child's already installed PDEATHSIG; keep its grant held.
            raise RuntimeError('Launcher pidfd acquisition was not confirmed')
        for fd in self.pinned.values():
            try:
                send_pidfd(fd, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.domain.root.exists():
            self.domain.remove()
        if self.child is not None:
            os.waitpid(self.child, 0)
            self.child = None
        self.close_pipes()
        for fd in self.pinned.values():
            os.close(fd)
        self.pinned.clear()


def main():
    spec = json.loads(Path(sys.argv[1]).read_text())
    control = socket.socket(fileno=int(sys.argv[2]))
    control.setblocking(False)
    guardian = Guardian(spec, control)
    try:
        guardian.begin()
        guardian.loop()
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as error:
        print(json.dumps({'stage': 'phase-guardian', 'phase': guardian.phase,
                          'exception': type(error).__name__}), file=sys.stderr, flush=True)
        if guardian.phase != 'runtime':
            emit({'event': 'compileError', 'body': {'code': 'DEBUG_COMPILE_SANDBOX_FAILED', 'output': ''}})
        else:
            try:
                guardian.reply({'error': type(error).__name__})
            except OSError:
                pass
    finally:
        try:
            guardian.cleanup()
            try:
                guardian.reply({'cleaned': True})
            except OSError:
                pass
        except BaseException as error:
            print(json.dumps({'stage': 'phase-cleanup', 'exception': type(error).__name__,
                              'errno': getattr(error, 'errno', None)}), file=sys.stderr, flush=True)
            try:
                guardian.reply({'cleaned': False})
            except OSError:
                pass
            sys.exit(2)


if __name__ == '__main__':
    main()
