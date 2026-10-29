"""Linux resource controls. All synchronous writes run in the external guardian.

v1 controller mounts can be named differently; the delegator supplies their
absolute paths via a mapping, including co-mounted cpu,cpuacct. No implicit v2
fallback. A freezer timeout never counts as a frozen instance.
"""

import os
import ctypes
from pathlib import Path
import pwd
import re
import signal
import stat
import struct
import time
from .process_identity import open_pidfd, send_pidfd


def process_uids(pid):
    """Read the host-visible identities, not the process's namespaced getuid()."""
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("Uid:"):
            values = tuple(int(value) for value in line.split()[1:])
            if len(values) == 4:
                return values
    raise RuntimeError("Cannot verify sandbox process identities")


def namespace_init(pid, service_uid, subuid=None):
    status = dict(line.split(":", 1) for line in Path(f"/proc/{pid}/status").read_text().splitlines() if ":" in line)
    chain = [int(n) for n in status.get("NSpid", "").split()]
    mappings = [tuple(int(n) for n in row.split())
                for row in Path(f"/proc/{pid}/uid_map").read_text().splitlines()]
    return (len(chain) > 1 and chain[-1] == 1 and (0, service_uid, 1) in mappings and
            (subuid is None or (65534, subuid, 1) in mappings))


def kill_member(pid, paths, *, subuid=None):
    # Bind the signal to a process identity, then confirm group membership.
    # A rapidly exiting/forking target must not turn a stale PID into a signal
    # for an unrelated service after the kernel recycles the numeric PID.
    try:
        descriptor = open_pidfd(pid)
    except ProcessLookupError:
        return
    try:
        if any(str(pid) in (Path(path) / "cgroup.procs").read_text().split() for path in paths):
            # The namespace-root supervisor maps to our host UID and remains
            # alive until teardown. Killing that precise PID1 makes the kernel
            # terminate all subordinate-UID descendants in its PID namespace.
            # The non-root guardian cannot signal those descendants itself.
            if (process_uids(pid) != (os.getuid(),) * 4 or
                    not namespace_init(pid, os.getuid(), subuid)):
                return False
            try:
                send_pidfd(descriptor, signal.SIGKILL)
                return True
            except ProcessLookupError:
                pass
    except FileNotFoundError:
        # The pidfd remains bound to the exited identity; never retry a signal
        # against a new process that happens to reuse the numeric PID.
        return False
    finally:
        os.close(descriptor)


class Cgroups:
    def __init__(self, paths, version=1):
        self.paths = {k: Path(v) for k, v in paths.items()}
        self.version = version

    def file(self, controller, name):
        return self.paths[controller] / name

    def read(self, controller, name):
        return self.file(controller, name).read_text().strip()

    def write(self, controller, name, value):
        self.file(controller, name).write_text(str(value))

    def create(self, memory, pids, cpu_us=100000):
        created = []
        try:
            for path in set(self.paths.values()):
                path.mkdir(mode=0o700)
                created.append(path)
            self.limit(memory)
            if self.version == 1:
                self.write("pids", "pids.max", pids)
                self.write("cpu", "cpu.cfs_period_us", 100000)
                self.write("cpu", "cpu.cfs_quota_us", cpu_us)
                if self.read("memory", "memory.use_hierarchy") != "1":
                    raise RuntimeError("Hierarchical memory accounting required")
            else:
                self.write("memory", "pids.max", pids)
                self.write("memory", "cpu.max", f"{cpu_us} 100000")
                self.write("memory", "memory.oom.group", 1)
        except BaseException:
            for path in reversed(created):
                path.rmdir()
            raise

    def attach(self, pid):
        # Child is stopped BEFORE exec. All controllers must confirm membership.
        for path in set(self.paths.values()):
            (path / "cgroup.procs").write_text(str(pid))
            if pid not in {int(v) for v in (path / "cgroup.procs").read_text().split()}:
                raise RuntimeError("Incomplete cgroup membership")

    def limit(self, value):
        name = "memory.limit_in_bytes" if self.version == 1 else "memory.max"
        self.write("memory", name, value)
        actual = int(self.read("memory", name))
        # Linux rounds up to a page; the ledger must reserve this rounded value.
        if actual != value:
            raise RuntimeError("Cgroup limit readback mismatch")
        return actual

    def usage(self):
        mem = "memory.usage_in_bytes" if self.version == 1 else "memory.current"
        cpu = (
            int(self.read("cpu", "cpuacct.usage")) / 1e9
            if self.version == 1
            else int(
                dict(line.split() for line in self.read("memory", "cpu.stat").splitlines())[
                    "usage_usec"
                ]
            )
            / 1e6
        )
        return {
            "memory": int(self.read("memory", mem)),
            "cpuSeconds": cpu,
            "pids": int(self.read("pids" if self.version == 1 else "memory", "pids.current")),
        }

    def freeze(self, frozen=True, deadline=1.0):
        if self.version == 1:
            self.write("freezer", "freezer.state", "FROZEN" if frozen else "THAWED")
            check = lambda: self.read("freezer", "freezer.state") == (
                "FROZEN" if frozen else "THAWED"
            )
        else:
            self.write("memory", "cgroup.freeze", int(frozen))
            check = lambda: dict(
                line.split() for line in self.read("memory", "cgroup.events").splitlines()
            ).get("frozen") == str(int(frozen))
        end = time.monotonic() + deadline
        while not check():
            if time.monotonic() >= end:
                raise RuntimeError("Freezer acknowledgement timeout")
            time.sleep(0.01)

    def kill(self):
        # Kill only verified service-UID members (including namespace PID1), then
        # wait for kernel teardown of subordinate-UID members. A remaining member
        # or EPERM is not success: preserve the cgroup and reservation for recovery.
        end = time.monotonic() + 3
        while True:
            members = set()
            for path in set(self.paths.values()):
                members.update(int(pid) for pid in (path / "cgroup.procs").read_text().split())
            if not members:
                return
            for pid in members:
                kill_member(pid, set(self.paths.values()))
            # Thaw after the kill is pending so frozen tasks can leave the group.
            self.freeze(False)
            if time.monotonic() >= end:
                raise RuntimeError("Sandbox cleanup not confirmed")
            time.sleep(0.02)

    def remove(self):
        self.kill()
        for path in set(self.paths.values()):
            path.rmdir()


def owned_cgroup(path):
    """Verify the actual mount type and inode, not controller-looking files."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path.resolve() != path:
        raise RuntimeError("Canonical owned cgroup path required")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise RuntimeError("Unowned cgroup directory")
        if os.uname().sysname != "Linux":
            raise RuntimeError("cgroup2 requires Linux")
        buffer = ctypes.create_string_buffer(256)
        library = ctypes.CDLL(None, use_errno=True)
        if library.fstatfs(fd, buffer) != 0:
            raise OSError(ctypes.get_errno(), "Cannot inspect cgroup filesystem")
        if ctypes.c_long.from_buffer(buffer).value != 0x63677270:
            raise RuntimeError("Actual cgroup2 filesystem required")
        return info.st_dev, info.st_ino
    finally:
        os.close(fd)


class SessionDomain(Cgroups):
    """Single v2 accounting domain across compile, handoff and runtime.

    Empty process lists at the domain root do not prove cleanup: native leaves
    and populated flags are checked recursively. Only mapped namespace PID1
    members are signalled here. A guardian separately owns exact launcher
    pidfds from its stopped fork handshake.
    """
    def __init__(self, paths, version=2, *, subuid=None):
        if version != 2 or set(paths) != {"memory"}:
            raise RuntimeError("Compile phases require one explicit cgroup-v2 domain")
        super().__init__(paths, version)
        self.root = self.paths["memory"]
        self.subuid = subuid
        self.identity = None

    def create(self, memory, pids, cpu_us=100000):
        owned_cgroup(self.root.parent)
        super().create(memory, pids, cpu_us)
        self.identity = owned_cgroup(self.root)
        if (self.root / "cgroup.procs").read_text().split():
            raise RuntimeError("Session accounting root must stay process-free")
        controllers = (self.root / "cgroup.controllers").read_text().split()
        if not {"cpu", "memory", "pids"} <= set(controllers):
            raise RuntimeError("Owned cpu/memory/pids delegation required")
        (self.root / "cgroup.subtree_control").write_text("+cpu +memory +pids")

    def branch(self, name, memory, pids):
        if name not in ("compile", "handoff", "runtime"):
            raise RuntimeError("Unapproved session phase")
        self._root()
        group = Cgroups({"memory": str(self.root / name)}, 2)
        group.create(memory, pids)
        owned_cgroup(self.root / name)
        if name == "compile":
            (self.root / name / "cgroup.subtree_control").write_text("+cpu +memory +pids")
            control = Cgroups({"memory": str(self.root / name / "control")}, 2)
            control.create(memory, pids)
        return group

    def _root(self):
        current = owned_cgroup(self.root)
        if self.identity is None:
            self.identity = current
        if current != self.identity:
            raise RuntimeError("Session cgroup identity changed")

    def nodes(self, branch=None):
        self._root()
        selected = self.root if branch is None else self.root / branch
        if branch not in (None, "compile", "handoff", "runtime"):
            raise RuntimeError("Unapproved cleanup branch")
        if not selected.exists():
            return []
        result = []
        def walk(path, depth):
            owned_cgroup(path)
            if depth > 2:
                raise RuntimeError("Unexpected cgroup hierarchy")
            result.append(path)
            for child in path.iterdir():
                info = child.lstat()
                if stat.S_ISLNK(info.st_mode):
                    raise RuntimeError("Symlink in owned cgroup hierarchy")
                if not stat.S_ISDIR(info.st_mode):
                    continue
                if path == self.root:
                    allowed = child.name in ("compile", "handoff", "runtime")
                elif path == self.root / "compile":
                    allowed = child.name == "control" or re.fullmatch(r"sduoj-[1-9][0-9]*-[0-9]+", child.name)
                else:
                    allowed = False
                if not allowed:
                    raise RuntimeError("Unrecognized child in owned cgroup")
                walk(child, depth + 1)
        walk(selected, 0 if branch is None else 1)
        return result

    def drained(self, branch=None):
        for path in self.nodes(branch):
            if (path / "cgroup.procs").read_text().split():
                return False
            events = dict(line.split() for line in (path / "cgroup.events").read_text().splitlines())
            if events.get("populated") != "0":
                return False
        return True

    def remove_branch(self, branch, *, timeout=3):
        end = time.monotonic() + timeout
        while not self.drained(branch):
            paths = self.nodes(branch)
            members = {int(pid) for path in paths for pid in (path / "cgroup.procs").read_text().split()}
            for pid in members:
                kill_member(pid, paths, subuid=self.subuid)
            self.freeze(False)
            if time.monotonic() >= end:
                raise RuntimeError("Hierarchical phase cleanup unconfirmed")
            time.sleep(0.02)
        for path in reversed(self.nodes(branch)):
            if not self.drained(branch):
                raise RuntimeError("Cgroup repopulated during cleanup")
            path.rmdir()

    def remove(self):
        if not self.root.exists():
            return
        self._root()
        for name in ("compile", "handoff", "runtime"):
            self.remove_branch(name)
        if not self.drained():
            raise RuntimeError("Session domain is not drained")
        self.root.rmdir()


def delegated_paths(policy, session_id):
    root, parent = Path(policy.cgroup_root), policy.cgroup_parent
    if policy.cgroup_version == 2:
        return {"memory": str(root / parent / session_id)}
    names = {"memory": "memory", "cpu": "cpu,cpuacct", "pids": "pids", "freezer": "freezer"}
    return {key: str(root / name / parent / session_id) for key, name in names.items()}


def exact_identity_filecap(raw, capability):
    """Accept only revision-2 effective, one permitted bit, no inheritable bits."""
    return raw == struct.pack('<IIIII', 0x02000001, 1 << capability, 0, 0, 0)


def identity_helper_preflight(helper, capability):
    info = helper.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0
            or info.st_mode & (0o022 | stat.S_ISGID) or not os.access(helper, os.X_OK)):
        raise RuntimeError('Untrusted identity helper: ' + str(helper))
    try:
        raw = os.getxattr(helper, 'security.capability')
    except OSError as error:
        import errno
        if error.errno not in (errno.ENODATA, errno.ENOTSUP):
            raise
        raw = b''
    if info.st_mode & stat.S_ISUID:
        if raw:
            raise RuntimeError('Mixed setuid and filecap helper route is forbidden')
        return 'setuid'
    if not exact_identity_filecap(raw, capability):
        raise RuntimeError('Exact single-capability identity helper required: ' + str(helper))
    return 'filecap'


def namespace_preflight(policy):
    """Require the exact operator-authorized rootless mapping and helper route.

    This checks prerequisites only. A real namespace/sandbox/drop/cleanup probe
    remains a release gate, including on each supported cgroup/kernel version.
    """
    uid, gid = os.getuid(), os.getgid()
    if (uid == 0 or os.geteuid() != uid or os.getegid() != gid
            or not policy.subuid or not policy.subgid
            or policy.subuid == uid or policy.subgid == gid):
        raise RuntimeError("Approved rootless debugger identities are required")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines()
                  if ":" in line)
    if status.get("NoNewPrivs", "").strip() != "0":
        raise RuntimeError("newidmap helpers require an approved NoNewPrivileges=0 launch route")
    username = pwd.getpwuid(uid).pw_name
    for name, value in (("subuid", policy.subuid), ("subgid", policy.subgid)):
        path = Path("/etc") / name
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError("Untrusted subordinate identity allocation: " + str(path))
        allowed = False
        for line in path.read_text().splitlines():
            fields = line.strip().split(":")
            if len(fields) != 3 or fields[0] not in (username, str(uid)):
                continue
            try:
                begin, count = int(fields[1]), int(fields[2])
            except ValueError:
                continue
            allowed |= begin <= value < begin + count and count > 0
        if not allowed:
            raise RuntimeError("Debugger subordinate identity is not allocated in " + str(path))
    for name, capability in (("newuidmap", 7), ("newgidmap", 6)):
        helper = Path("/usr/bin") / name
        identity_helper_preflight(helper, capability)


def preflight(policy):
    if os.uname().sysname != "Linux":
        raise RuntimeError("Debugger sandbox requires Linux")
    # Python may expose the API while the target kernel/seccomp policy rejects
    # the syscall. Probe only ourselves, with signal 0; never use a numeric-PID
    # fallback for sandbox cleanup.
    descriptor = None
    try:
        descriptor = open_pidfd(os.getpid())
        send_pidfd(descriptor, 0)
    except OSError as error:
        raise RuntimeError("Working pidfd process identity support is required") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    paths = delegated_paths(policy, "preflight")
    for path in set(Path(p).parent for p in paths.values()):
        if not path.is_dir() or not os.access(path, os.W_OK):
            raise RuntimeError("Missing delegated cgroup: " + str(path))
    for parent in set(Path(p).parent for p in paths.values()):
        if any(item.is_dir() for item in parent.iterdir()):
            raise RuntimeError("Delegated debugger parent needs orphan recovery")
        if (parent / "cgroup.procs").read_text().split():
            raise RuntimeError("Delegated debugger parent must contain no processes")
    memory_parent = Path(paths["memory"]).parent
    limit = memory_parent / (
        "memory.limit_in_bytes" if policy.cgroup_version == 1 else "memory.max"
    )
    parent_limit = int(limit.read_text().strip())
    if not policy.budget <= parent_limit <= policy.hard:
        # The admission ledger must fit under the kernel's actual ceiling.
        # Otherwise paused sessions could be OOM-killed before the ledger
        # notices pressure, even though its own reservations still fit.
        raise RuntimeError("Student parent memory limit must cover the admission budget without exceeding the hard limit")
    namespace_preflight(policy)
    for executable in (policy.nsjail, policy.bootstrap):
        if not Path(executable).is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError("Missing trusted sandbox executable: " + executable)
    # Create/remove an empty group to verify permissions and every controller.
    probe = Cgroups(paths, policy.cgroup_version)
    probe.create(32 * 1024 * 1024, 32)
    try:
        probe.freeze(True)
        probe.freeze(False)
        probe.usage()
    finally:
        probe.remove()
