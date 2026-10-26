"""Last-resort node cleanup, also usable as systemd ExecStopPost.

No Redis reservation is silently taken over. After success an operator can
reconcile metadata and explicitly release the previous owner reservation.
"""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import time
from .config import Policy
from .cgroups import delegated_paths, kill_member
from .node_lock import node_lock

NAME = re.compile(r"^(?:guardian-)?[a-f0-9]{32}$")


def cleanup(policy, timeout=5):
    with node_lock(policy.state_dir):
        return _cleanup(policy, timeout)


def _cleanup(policy, timeout):
    parents = {key: Path(value).parent for key, value in delegated_paths(policy, "probe").items()}
    names = set()
    for parent in set(parents.values()):
        if (parent / "cgroup.procs").read_text().split():
            raise RuntimeError("Debugger parent contains unexpected direct processes")
        for child in parent.iterdir():
            if child.is_dir():
                if not NAME.fullmatch(child.name):
                    raise RuntimeError("Unknown subgroup; refusing automatic recovery")
                names.add(child.name)
    pending = {
        parent / name
        for parent in set(parents.values())
        for name in names
        if (parent / name).is_dir()
    }
    end = time.monotonic() + timeout
    while pending:
        members = set()
        for path in pending:
            members.update(int(pid) for pid in (path / "cgroup.procs").read_text().split())
        if os.getpid() in members:
            raise RuntimeError("Recovery process is inside the sandbox parent")
        for pid in members:
            kill_member(pid, pending)
        # A pending SIGKILL must be allowed to run even if the student tree was
        # frozen when both its API and its individual guardian disappeared.
        controller = "freezer.state" if policy.cgroup_version == 1 else "cgroup.freeze"
        freeze_parents = (
            {parents["freezer"]} if policy.cgroup_version == 1 else set(parents.values())
        )
        for path in pending:
            if path.parent in freeze_parents and (path / controller).exists():
                (path / controller).write_text("THAWED" if policy.cgroup_version == 1 else "0")
        for path in list(pending):
            if not (path / "cgroup.procs").read_text().strip():
                try:
                    path.rmdir()
                    pending.remove(path)
                except OSError:
                    pass
        if not pending:
            break
        if time.monotonic() >= end:
            raise RuntimeError("Recovery could not confirm complete cleanup")
        time.sleep(0.02)
    state = Path(policy.state_dir)
    if state.exists():
        for path in state.iterdir():
            if path.name == ".agent.lock":
                continue
            if (
                not re.fullmatch(r"[a-f0-9]{32}", path.name)
                or not path.is_dir()
                or path.is_symlink()
            ):
                raise RuntimeError("Unknown state entry; refusing removal")
            shutil.rmtree(path)
    return {"cleaned": True, "groups": len(names), "redisReservationReleased": False}


def main():
    parser = argparse.ArgumentParser(
        description="Inspect or explicitly clean owned debugger groups"
    )
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()
    policy = Policy.environment()
    if not args.cleanup:
        print(
            json.dumps(
                {
                    "stateDir": policy.state_dir,
                    "parents": delegated_paths(policy, "<session>"),
                    "action": "read-only; --cleanup required",
                }
            )
        )
        return
    print(json.dumps(cleanup(policy)))


if __name__ == "__main__":
    main()
