"""Independent fail-stop guardian; never executes user code in its own process.

The control fd is NOT inherited by nsjail. Parent loss / stale heartbeat / hard
age kills the entire cgroup. Started-at is recorded before the first fork and
can never be extended by a control message. Only fixed control verbs exist.
"""

import json
import math
import os
from pathlib import Path
import select
import signal
import socket
import sys
import time
from .cgroups import Cgroups


def main():
    spec = json.loads(Path(sys.argv[1]).read_text())
    control = socket.socket(fileno=int(sys.argv[2]))
    control.setblocking(False)
    cg = Cgroups(spec["cgroups"], spec["version"])
    trusted = Cgroups(spec["trustedCgroups"], spec["version"])
    child = None
    start = time.monotonic()
    hard = start + spec["lifetime"]
    idle = start + spec["idle"]
    run_deadline = math.inf
    run_generation = 0
    heartbeat = start
    buffer = b""

    def reply(value):
        control.sendall(json.dumps(value, separators=(",", ":")).encode() + b"\n")

    try:
        # Bootstrap attached us before exec, so Python's pages are charged.
        for path in set(trusted.paths.values()):
            if str(os.getpid()) not in (path / "cgroup.procs").read_text().split():
                raise RuntimeError("Guardian is outside its reserved cgroup")
        cg.create(spec["memory"], spec["pids"])
        child = os.fork()
        if child == 0:
            control.close()
            # Do not leak environment, root paths, credentials, or control fds.
            os.kill(os.getpid(), signal.SIGSTOP)
            os.execve(
                spec["nsjail"],
                [spec["nsjail"], "--config", spec["config"]],
                {"PATH": "/usr/bin:/bin"},
            )
        _, status = os.waitpid(child, os.WUNTRACED)
        if not os.WIFSTOPPED(status):
            raise RuntimeError("Launcher handshake failed")
        cg.attach(child)
        os.kill(child, signal.SIGCONT)
        reply(
            {
                "ready": True,
                "startedAt": time.time(),
                "hardSeconds": max(0, hard - time.monotonic()),
            }
        )
        while True:
            now = time.monotonic()
            if now >= run_deadline:
                reply({"event": "runTimeout"})
                break
            if now >= min(hard, idle) or now - heartbeat > 12:
                break
            if os.waitpid(child, os.WNOHANG)[0]:
                child = None
                break
            if cg.usage()["cpuSeconds"] >= spec["cpuSeconds"]:
                break
            readable, _, _ = select.select(
                [control],
                [],
                [],
                max(0, min(0.5, hard - now, idle - now, run_deadline - now)),
            )
            if not readable:
                continue
            data = control.recv(8192)
            if not data:
                break
            buffer += data
            if len(buffer) > 16384:
                raise RuntimeError("Invalid guardian control message")
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                req = json.loads(line)
                op = req["op"]
                if op == "heartbeat":
                    heartbeat = time.monotonic()
                elif op == "touch":
                    idle = min(hard, time.monotonic() + spec["idle"])
                elif op == "run":
                    seconds, generation = req["seconds"], req["generation"]
                    if (
                        type(seconds) not in (int, float)
                        or not math.isfinite(seconds)
                        or seconds <= 0
                        or type(generation) is not int
                        or generation <= 0
                    ):
                        raise RuntimeError("Invalid run deadline")
                    if generation > run_generation:
                        run_generation = generation
                        run_deadline = min(hard, time.monotonic() + seconds)
                elif op == "run-end":
                    if req["generation"] == run_generation:
                        run_deadline = math.inf
                elif op == "freeze":
                    cg.freeze(True)
                elif op == "thaw":
                    cg.freeze(False)
                elif op == "limit":
                    value = req["value"]
                    if (
                        not isinstance(value, int)
                        or value <= 0
                        or value > spec["memory"]
                        or value % os.sysconf("SC_PAGE_SIZE")
                    ):
                        raise RuntimeError("Invalid memory grant")
                    cg.limit(value)
                elif op == "kill":
                    raise EOFError()
                elif op != "stats":
                    raise RuntimeError("Invalid guardian operation")
                reply({"id": req["id"], "ok": True, **cg.usage()})
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as error:
        # Do not copy student source, output or command arguments to host logs.
        try:
            reply({"error": type(error).__name__})
        except OSError:
            pass
    finally:
        try:
            cg.remove()
            if child:
                os.waitpid(child, 0)
            try:
                reply({"cleaned": True})
            except OSError:
                pass
        except BaseException as error:
            # Leave the directory/ledger quarantined; caller must not free its
            # grant if death is not confirmed. Parent hard cap remains in force.
            print(json.dumps({'stage': 'guardian-cleanup',
                              'exception': type(error).__name__,
                              'errno': getattr(error, 'errno', None)}),
                  file=sys.stderr, flush=True)
            try:
                reply({"cleaned": False})
            except OSError:
                pass
            sys.exit(2)


if __name__ == "__main__":
    main()
