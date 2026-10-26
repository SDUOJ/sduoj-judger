"""NsJail process launcher, with an external guardian and private async IPC."""

import asyncio
import json
import math
import os
from pathlib import Path
import shutil
import socket
import sys
from .cgroups import delegated_paths, Cgroups
from .profiles import DebugError


def quote(value):
    return json.dumps(str(value))


def nsjail_config(profile, policy):
    """No caller-supplied config fragments, host mounts, network or env."""
    if (not policy.subuid or not policy.subgid or os.getuid() == 0
            or os.geteuid() != os.getuid() or os.getegid() != os.getgid()
            or policy.subuid == os.getuid() or policy.subgid == os.getgid()):
        raise DebugError("DEBUG_NAMESPACE_IDENTITIES_REQUIRED", 503)
    entries = [
        'name: "sduoj-debug"',
        "mode: ONCE",
        'hostname: "debug"',
        'cwd: "/work"',
        f"time_limit: {math.ceil(policy.lifetime)}",
        "log_level: ERROR",
        "keep_env: false",
        "keep_caps: false",
        'cap: "CAP_SETUID"',
        'cap: "CAP_SETGID"',
        'cap: "CAP_KILL"',
        "disable_no_new_privs: false",
        "clone_newuser: true",
        "clone_newns: true",
        "clone_newpid: true",
        "clone_newnet: true",
        "clone_newipc: true",
        "clone_newuts: true",
        "iface_no_lo: false",
        "rlimit_as_type: INF",
        "rlimit_cpu_type: INF",
        "rlimit_core: 0",
        "rlimit_stack: 128",
        "rlimit_stack_type: VALUE",
        "rlimit_fsize: 64",
        "rlimit_nofile: 128",
        # RLIMIT_NPROC counts the UID across all containers/sessions. Reusing
        # the service/subordinate UIDs would make unrelated sandboxes exhaust
        # one another. The per-instance pids cgroup is the hard process cap.
        "rlimit_nproc_type: INF",
        # All mappings use the external helpers. A direct/self gid mapping makes
        # NsJail write setgroups=deny, which the unchanged judge sandbox cannot
        # accept when it drops its compiler child to nobody (65534).
        f'uidmap {{ inside_id: "0" outside_id: "{os.getuid()}" count: 1 use_newidmap: true }}',
        f'uidmap {{ inside_id: "65534" outside_id: "{policy.subuid}" count: 1 use_newidmap: true }}',
        f'gidmap {{ inside_id: "0" outside_id: "{os.getgid()}" count: 1 use_newidmap: true }}',
        f'gidmap {{ inside_id: "65534" outside_id: "{policy.subgid}" count: 1 use_newidmap: true }}',
        f'mount {{ src: {quote(profile.rootfs)} dst: "/" is_bind: true rw: false nosuid: true }}',
        # This mount belongs to one private jail. Both its trusted root launcher
        # and the compiler/adapter nobody identity need access, without granting
        # the launcher CHOWN or DAC_OVERRIDE capabilities.
        f'mount {{ dst: "/work" fstype: "tmpfs" options: "size={profile.tmpfs},mode=0777,uid=0,gid=0" rw: true nosuid: true nodev: true }}',
        'mount { dst: "/tmp" fstype: "tmpfs" options: "size=16777216,mode=1777" rw: true nosuid: true nodev: true noexec: true }',
        'mount { dst: "/proc" fstype: "proc" rw: false nosuid: true nodev: true noexec: true }',
        'mount { dst: "/dev" fstype: "tmpfs" options: "size=1048576,mode=0755" rw: true nosuid: true }',
        'mount { dst: "/dev/pts" fstype: "devpts" options: "newinstance,ptmxmode=0666,mode=0620" rw: true nosuid: true noexec: true }',
        'mount { src: "pts/ptmx" dst: "/dev/ptmx" is_symlink: true }',
        f"seccomp_policy_file: {quote(profile.seccomp)}",
        'envar: "PATH=/usr/bin:/bin"',
        'envar: "HOME=/work"',
        'envar: "TMPDIR=/tmp"',
        'envar: "LANG=C.UTF-8"',
        f"exec_bin {{ path: {quote(profile.python)} arg: {quote(profile.runner)} }}",
    ]
    for device in ("null", "zero", "urandom", "random"):
        entries.append(
            f'mount {{ src: "/dev/{device}" dst: "/dev/{device}" is_bind: true rw: true nosuid: true noexec: true }}'
        )
    return "\n".join(entries) + "\n"


class Sandbox:
    STDERR_TAIL_BYTES = 32768

    def __init__(self, session_id, profile, policy, event):
        self.id, self.profile, self.policy, self.event = (
            session_id,
            profile,
            policy,
            event,
        )
        self.pending, self.guard_pending, self.tasks = {}, {}, []
        self.seq = 0
        self.guard_lock = asyncio.Lock()
        self.cleaned = asyncio.get_running_loop().create_future()
        self.ready = asyncio.get_running_loop().create_future()
        self.closed = False
        self.directory = Path(policy.state_dir) / session_id
        # Trusted operator evidence only. Never forward this stream to IDE
        # events: it can contain private host paths and student diagnostics.
        self.guardian_stderr = bytearray()
        self.guardian_stderr_bytes = 0
        self.guardian_stderr_error = None

    async def start(self, spec):
        self.directory.mkdir(mode=0o700)
        config = self.directory / "nsjail.cfg"
        config.write_text(nsjail_config(self.profile, self.policy))
        config.chmod(0o600)
        paths = delegated_paths(self.policy, self.id)
        guardian_spec = self.directory / "guardian.json"
        guardian_spec.write_text(
            json.dumps(
                {
                    "cgroups": paths,
                    "version": self.policy.cgroup_version,
                    "trustedCgroups": delegated_paths(
                        self.policy, "guardian-" + self.id
                    ),
                    "guardianMemory": self.policy.guardian_memory,
                    "nsjail": self.policy.nsjail,
                    "config": str(config),
                    "memory": self.profile.startup,
                    "pids": self.profile.pids,
                    "lifetime": self.policy.lifetime,
                    "idle": self.policy.idle,
                    "cpuSeconds": self.profile.cpu_seconds,
                }
            )
        )
        guardian_spec.chmod(0o600)
        parent, child = socket.socketpair()
        parent.setblocking(False)
        self.control_reader, self.control_writer = await asyncio.open_connection(
            sock=parent, limit=16384
        )
        trusted_paths = delegated_paths(self.policy, "guardian-" + self.id)
        self.trusted = Cgroups(trusted_paths, self.policy.cgroup_version)
        await asyncio.to_thread(self.trusted.create, self.policy.guardian_memory, 4)
        procs = [str(Path(p) / "cgroup.procs") for p in set(trusted_paths.values())]
        try:
            spawn = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    self.policy.bootstrap,
                    str(len(procs)),
                    *procs,
                    sys.executable,
                    "-m",
                    "ide_debug.guardian",
                    str(guardian_spec),
                    str(child.fileno()),
                    pass_fds=(child.fileno(),),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=262144,
                )
            )
            try:
                self.process = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                # Record the process even when HTTP/service cancellation races
                # fork/exec. Teardown must never mistake a spawned child for an
                # empty reservation.
                self.process = await spawn
                raise
        finally:
            child.close()
            if hasattr(self, "process"):
                # Drain immediately, including the cancelled-spawn path. A full
                # stderr pipe must never keep guardian cleanup from completing.
                self.tasks.append(asyncio.create_task(self.read_stderr()))
        self.tasks.extend([
            asyncio.create_task(self.read_guard()),
            asyncio.create_task(self.read_adapter()),
        ])
        await asyncio.wait_for(asyncio.shield(self.ready), 5)
        wire = dict(
            spec,
            compile=self.profile.compile,
            source=self.profile.source,
            language=self.profile.language,
            python=self.profile.python,
            targetPython=self.profile.target_python,
            debugger=self.profile.debugger,
            javaOptions=self.profile.java_options,
            compileSeconds=self.profile.compile_seconds,
            compileLimits=self.profile.compile_limits,
            compileSandboxSha256=self.profile.compile_sandbox_sha256,
            compilePathEnv=self.profile.compile_path_env,
        )
        self.process.stdin.write(json.dumps({"spec": wire}).encode() + b"\n")
        await self.process.stdin.drain()

    async def read_stderr(self):
        try:
            while True:
                chunk = await self.process.stderr.read(4096)
                if not chunk:
                    return
                self.guardian_stderr_bytes += len(chunk)
                self.guardian_stderr.extend(chunk)
                if len(self.guardian_stderr) > self.STDERR_TAIL_BYTES:
                    del self.guardian_stderr[:-self.STDERR_TAIL_BYTES]
        except (OSError, ConnectionError) as error:
            self.guardian_stderr_error = type(error).__name__

    def guardian_diagnostics(self):
        """Bounded private evidence; HTTP/session snapshots must not expose it."""
        process = getattr(self, "process", None)
        return {
            "pid": getattr(process, "pid", None),
            "returnCode": getattr(process, "returncode", None),
            "stderrTail": bytes(self.guardian_stderr).decode(errors="replace"),
            "stderrBytes": self.guardian_stderr_bytes,
            "stderrTruncated": self.guardian_stderr_bytes > len(self.guardian_stderr),
            "stderrReadError": self.guardian_stderr_error,
        }

    async def read_guard(self):
        try:
            while True:
                line = await self.control_reader.readline()
                if not line:
                    break
                value = json.loads(line)
                if value.get("ready") and not self.ready.done():
                    self.ready.set_result(value)
                elif "cleaned" in value:
                    if not self.cleaned.done():
                        self.cleaned.set_result(bool(value["cleaned"]))
                elif "id" in value:
                    future = self.guard_pending.get(value["id"])
                    if future and not future.done():
                        future.set_result(value)
                elif value.get("event") == "runTimeout":
                    self.event("runTimeout", {})
                elif "error" in value:
                    self.event("failed", {"code": "DEBUG_GUARDIAN_FAILED"})
        finally:
            if not self.ready.done():
                self.ready.set_exception(RuntimeError("Guardian startup failed"))
            for future in list(self.guard_pending.values()):
                if not future.done():
                    future.set_exception(EOFError("Guardian disconnected"))
            self.event("guardianLost", {})

    async def read_adapter(self):
        try:
            while True:
                line = await self.process.stdout.readline()
                if not line:
                    break
                value = json.loads(line)
                if "id" in value:
                    future = self.pending.get(value["id"])
                    if future and not future.done():
                        if value.get("ok"):
                            future.set_result(value.get("body", {}))
                        else:
                            future.set_exception(
                                DebugError("DEBUG_ADAPTER_REQUEST_FAILED")
                            )
                elif value.get("event") in (
                    "stopped",
                    "running",
                    "terminated",
                    "output",
                    "compiled",
                    "compileError",
                    "failed",
                ):
                    self.event(value["event"], value.get("body", {}))
        except (ValueError, asyncio.LimitOverrunError):
            self.event("failed", {"code": "DEBUG_ADAPTER_PROTOCOL_FAILED"})
        finally:
            for future in list(self.pending.values()):
                if not future.done():
                    future.set_exception(EOFError("Adapter disconnected"))
            self.event("terminated", {})

    async def guard(self, op, **arguments):
        async with self.guard_lock:
            self.seq += 1
            seq = self.seq
            future = asyncio.get_running_loop().create_future()
            self.guard_pending[seq] = future
            self.control_writer.write(
                json.dumps({"id": seq, "op": op, **arguments}).encode() + b"\n"
            )
            await self.control_writer.drain()
            try:
                return await asyncio.wait_for(future, 2)
            finally:
                self.guard_pending.pop(seq, None)

    async def request(self, operation, arguments):
        self.seq += 1
        seq = self.seq
        future = asyncio.get_running_loop().create_future()
        self.pending[seq] = future
        self.process.stdin.write(
            json.dumps(
                {"id": seq, "operation": operation, "arguments": arguments}
            ).encode()
            + b"\n"
        )
        await self.process.stdin.drain()
        try:
            return await asyncio.wait_for(future, self.policy.operation)
        finally:
            self.pending.pop(seq, None)

    async def close(self):
        if not hasattr(self, "close_task"):
            self.close_task = asyncio.create_task(self._close())
        return await asyncio.shield(self.close_task)

    async def _close(self):
        self.closed = True
        # Closing control is unconditionally interpreted as whole-tree death.
        if hasattr(self, "control_writer"):
            self.control_writer.close()
            try:
                await self.control_writer.wait_closed()
            except OSError:
                pass
        if not hasattr(self, "process"):
            if hasattr(self, "trusted"):
                await asyncio.to_thread(self.trusted.remove)
            shutil.rmtree(self.directory, ignore_errors=True)
            return True

        async def exited():
            # Process.wait may wait for inherited stdout EOF even after the
            # guardian is dead, while its frozen descendants hold that pipe.
            # Observe exit status first so emergency cleanup can kill them.
            while self.process.returncode is None:
                await asyncio.sleep(0.01)

        try:
            await asyncio.wait_for(exited(), 5)
        except asyncio.TimeoutError:
            # Never release budget based only on a timed out kill.
            return False
        # The last ack can be lost when our own pipe closes. Exit 0 alone is not
        # proof: independently check all delegated group directories are gone.
        if self.process.returncode != 0:
            # Guardian may have been OOM-killed. The agent is outside the global
            # student/guardian parent and can still perform a whole-group kill.
            try:
                groups = Cgroups(
                    delegated_paths(self.policy, self.id), self.policy.cgroup_version
                )
                existing = {k: v for k, v in groups.paths.items() if v.exists()}
                if existing:
                    if len(existing) != len(groups.paths):
                        return False
                    await asyncio.to_thread(groups.remove)
            except Exception:
                return False
        await asyncio.wait_for(self.process.wait(), 2)
        clean = all(
            not Path(p).exists()
            for p in set(delegated_paths(self.policy, self.id).values())
        )
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if clean:
            for path in set(
                delegated_paths(self.policy, "guardian-" + self.id).values()
            ):
                target = Path(path)
                if target.exists():
                    if (target / "cgroup.procs").read_text().strip():
                        return False
                    target.rmdir()
            shutil.rmtree(self.directory, ignore_errors=True)
        return clean
