"""Runs INSIDE the jail. Compilers, adapters and target share its resource cap.

The outer agent only supplies a previously authorized profile and frozen source.
Target stdout never shares this JSON control pipe. No shell commands are used.
"""

import asyncio
import json
import os
from pathlib import Path
import signal
import sys

# Rootfs publishes this package under /opt/sduoj-debug.
sys.path.insert(0, "/opt/sduoj-debug")
from ide_debug.watch import inspect_paths
from ide_debug.adapters.native import Native
from ide_debug.adapters.python import Python
from ide_debug.adapters.java import Java
from ide_debug.judge_compile import compile_source

OUTPUT_LIMIT = 196608
output_bytes = 0


def emit(kind, body):
    global output_bytes
    if kind == "output":
        data = body.get("output", "")
        encoded = data.encode()
        remaining = max(0, OUTPUT_LIMIT - output_bytes)
        output_bytes += len(encoded)
        if not remaining:
            return
        body = dict(body, output=encoded[:remaining].decode(errors="replace"))
        if output_bytes > OUTPUT_LIMIT:
            body["truncated"] = True
    wire = json.dumps({"event": kind, "body": body}, ensure_ascii=True)
    if len(wire) <= 262144:
        print(wire, flush=True)


def bounded(value, depth=0):
    if depth > 12:
        return "<truncated>"
    if isinstance(value, str):
        return value[:1024]
    if isinstance(value, list):
        return [bounded(item, depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        return {
            str(k)[:128]: bounded(v, depth + 1) for k, v in list(value.items())[:32]
        }
    return value


def namespace_identity():
    """The trusted PID-1 supervisor may be root only inside this private userns."""
    if os.getuid() != 0 or os.geteuid() != 0 or os.getpid() != 1:
        raise RuntimeError("Private namespace supervisor required")
    for name in ("uid_map", "gid_map"):
        rows = [tuple(map(int, line.split()))
                for line in Path("/proc/self/" + name).read_text().splitlines()]
        if (len(rows) != 2 or {row[0] for row in rows} != {0, 65534}
                or any(row[1] <= 0 or row[2] != 1 for row in rows)
                or len({row[1] for row in rows}) != 2):
            raise RuntimeError("Approved isolated identity mapping required")
    if Path("/proc/self/setgroups").read_text().strip() != "allow":
        raise RuntimeError("Judge sandbox requires permitted setgroups")


def drop_adapter_identity():
    """The debugger and student program never retain supervisor capabilities."""
    os.setgroups([65534])
    os.setresgid(65534, 65534, 65534)
    os.setresuid(65534, 65534, 65534)
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines()
                  if ":" in line)
    if (os.getresuid() != (65534,) * 3 or os.getresgid() != (65534,) * 3
            or os.getgroups() != [65534]
            or any(int(status.get(name, "1").strip(), 16)
                   for name in ("CapEff", "CapPrm", "CapAmb"))
            or status.get("NoNewPrivs", "0").strip() != "1"):
        raise RuntimeError("Adapter privilege drop failed")


async def supervise_adapter(spec, reader):
    """Keep trusted userns PID 1 alive so v1 cleanup can reap all descendants."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, __file__, "--adapter-only", cwd="/work",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True, limit=262144,
    )

    async def input_pipe():
        process.stdin.write(json.dumps({"spec": spec}).encode() + b"\n")
        await process.stdin.drain()
        while True:
            line = await reader.readline()
            if not line:
                return
            process.stdin.write(line)
            await process.stdin.drain()

    async def output_pipe():
        while True:
            line = await process.stdout.readline()
            if not line:
                return
            # A malformed adapter line is private infrastructure failure.
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("Invalid adapter response")
            print(json.dumps(value, ensure_ascii=True), flush=True)

    async def private_pipe():
        used = 0
        while True:
            chunk = await process.stderr.read(4096)
            if not chunk:
                return
            # Continue draining after the budget; a private warning must not
            # block adapter teardown or enter the JSON response stream.
            kept = chunk[:max(0, 8192 - used)]
            used += len(chunk)
            if kept:
                sys.stderr.write(kept.decode(errors="replace"))
                sys.stderr.flush()

    tasks = [asyncio.create_task(input_pipe()), asyncio.create_task(output_pipe()),
             asyncio.create_task(process.wait())]
    private = asyncio.create_task(private_pipe())
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if tasks[1] in done and tasks[2] not in done:
            await asyncio.wait_for(asyncio.shield(tasks[2]), 1)
        if tasks[2] in done and tasks[1] not in done:
            # Preserve final diagnostics already buffered when the child exits.
            await asyncio.wait_for(asyncio.shield(tasks[1]), 1)
        if tasks[1] in done or tasks[2] in done:
            await asyncio.wait_for(asyncio.shield(private), 1)
    finally:
        for task in tasks:
            task.cancel()
        private.cancel()
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(private, return_exceptions=True)
        await process.wait()


async def main():
    reader = asyncio.StreamReader(limit=1048576)
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)
    init = json.loads(await reader.readline())
    spec = init["spec"]
    if sys.argv[1:] != ["--adapter-only"]:
        try:
            namespace_identity()
            source = Path("/work/" + spec["source"])
            source.write_text(spec["code"])
            # The service's private umask is 0077; only this source must be
            # readable by the compiler's separate nobody identity.
            source.chmod(0o644)
            failure = await compile_source(spec)
        except (OSError, ValueError, RuntimeError):
            failure = {"code": "DEBUG_COMPILE_SANDBOX_FAILED", "output": ""}
        if failure:
            emit("compileError", failure)
            return
        emit("compiled", {})
        await supervise_adapter(spec, reader)
        return
    drop_adapter_identity()
    adapter = {"c": Native, "cpp": Native, "python": Python, "java": Java}[
        spec["language"]
    ](emit)
    await adapter.start(spec)
    while True:
        line = await reader.readline()
        if not line:
            return
        request = json.loads(line)
        try:
            body = (
                await inspect_paths(adapter, request["arguments"])
                if request["operation"] == "watch"
                else await adapter.command(request["operation"], request["arguments"])
            )
            print(
                json.dumps({"id": request["id"], "ok": True, "body": bounded(body)}),
                flush=True,
            )
        except Exception:
            print(
                json.dumps(
                    {
                        "id": request["id"],
                        "ok": False,
                        "error": "DEBUG_ADAPTER_REQUEST_FAILED",
                    }
                ),
                flush=True,
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(json.dumps({"stage": "adapter-runner", "exception": type(error).__name__,
                          "message": str(error)[:1024]}), file=sys.stderr, flush=True)
        emit("failed", {"code": "DEBUG_ADAPTER_FAILED"})
        sys.exit(1)
