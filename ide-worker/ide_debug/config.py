"""Fail-closed, deployment-owned debugger policy (one runtime agent per node)."""

from dataclasses import dataclass
import os
from pathlib import Path

MiB = 1024 * 1024
GiB = 1024 * MiB
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")


@dataclass(frozen=True)
class Policy:
    enabled: bool = False
    resident: int = 1024
    active: int = 32
    queue: int = 1024
    idle: float = 300
    lifetime: float = 1800
    wait: float = 120
    operation: float = 15
    run_slice: float = 2
    budget: int = 56 * GiB
    hard: int = 64 * GiB
    reserve: int = 2 * GiB
    host_floor: int = 8 * GiB
    pid_budget: int = 65536
    guardian_memory: int = 16 * MiB
    node: str = "debug-1"
    state_dir: str = "/run/sduoj-debug"
    manifest: str = ""
    nsjail: str = "/usr/local/bin/nsjail"
    bootstrap: str = "/usr/local/libexec/sduoj-debug-bootstrap"
    # Every controller path is explicitly delegated to this service, never its root.
    cgroup_root: str = "/sys/fs/cgroup"
    cgroup_parent: str = "sduoj-debug"
    cgroup_version: int = 1
    # Explicit operator-approved subordinate identities, never inferred from the
    # browser, a template, or an arbitrary free host UID. Zero disables launch.
    subuid: int = 0
    subgid: int = 0

    def __post_init__(self):
        if not (0 < self.resident <= 1024 and 0 < self.active <= 32 and 0 < self.queue <= 1024):
            raise ValueError("Invalid debug concurrency policy")
        if not (0 < self.idle <= 300 and 0 < self.lifetime <= 1800 and 0 < self.wait <= 120):
            raise ValueError("Invalid debug deadline policy")
        if not (0 < self.reserve < self.budget < self.hard and self.host_floor >= 0):
            raise ValueError("Invalid debug memory policy")
        if not (0 < self.operation <= 60 and 0 < self.run_slice <= 10 and self.pid_budget > 0):
            raise ValueError("Invalid debug execution policy")
        if not 16 * MiB <= self.guardian_memory <= 128 * MiB or self.guardian_memory % PAGE_SIZE:
            raise ValueError("Invalid guardian memory reservation")
        if self.cgroup_version not in (1, 2) or not self.cgroup_parent.replace("-", "").isalnum():
            raise ValueError("Invalid delegated cgroup configuration")
        if (
            not self.state_dir.startswith(("/run/", "/dev/shm/"))
            or ".." in Path(self.state_dir).parts
        ):
            raise ValueError("Debug state must use a private runtime/tmpfs directory")
        if not self.node.replace("-", "").isalnum():
            raise ValueError("Invalid debug node name")
        if any(type(value) is not int or value != 0 and not 65536 <= value < 2**32 - 1
               for value in (self.subuid, self.subgid)):
            raise ValueError("Invalid approved debugger subordinate identity")

    @classmethod
    def environment(cls):
        env = {"enabled": os.getenv("AUTOLAB_DEBUG_ENABLED") == "1"}
        for field in cls.__dataclass_fields__:
            if field == "enabled":
                continue
            raw = os.getenv("AUTOLAB_DEBUG_" + field.upper())
            if raw is not None:
                default = getattr(cls(), field)
                env[field] = type(default)(raw)
        return cls(**env)


def host_available():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("MemAvailable is required")
