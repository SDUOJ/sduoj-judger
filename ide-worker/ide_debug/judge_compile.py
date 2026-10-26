"""The native judge compiler contract, without a host-shell fallback.

Limits and argument units match IOSubmissionHandler.compile. This module runs
inside the private jail; /usr/bin/sandbox drops its compiler child to nobody.
The surrounding cgroup still bounds the complete compiler process tree.
"""

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import signal
import sys


SANDBOX = "/usr/bin/sandbox"
OUTPUT_BYTES = 20 * 1024 * 1024
PUBLIC_BYTES = 65536
COMPILE_CODES = frozenset({
    "DEBUG_COMPILE_FAILED", "DEBUG_COMPILE_TIMEOUT",
    "DEBUG_COMPILE_MEMORY_LIMIT", "DEBUG_COMPILE_OUTPUT_LIMIT",
    "DEBUG_COMPILE_SANDBOX_FAILED",
})


@dataclass(frozen=True)
class CompileLimits:
    cpu_ms: int
    real_ms: int
    memory_bytes: int

    def __post_init__(self):
        if (type(self.cpu_ms) is not int or not 0 < self.cpu_ms <= 60000
                or type(self.real_ms) is not int or not 0 < self.real_ms <= 60000
                or type(self.memory_bytes) is not int
                or not 0 <= self.memory_bytes <= 8 * 1024**3):
            raise ValueError("Invalid judge compile limits")

    @classmethod
    def template(cls, template):
        config = json.loads(template["shellScript"])["user"]["compile"]
        values = [config[key] for key in ("maxCpuTime", "maxRealTime", "maxMemory")]
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("Invalid judge compile limits")
        if not 0 < values[0] <= 60000 or not 0 < values[1] <= 60000:
            raise ValueError("Debug requires bounded judge compile deadlines")
        if values[2] > 8 * 1024 * 1024:
            raise ValueError("Invalid judge compile memory")
        # Judge templates use KiB, whereas the native sandbox consumes bytes.
        # Java's zero retains the judge meaning; the outer cgroup remains finite.
        return cls(values[0], values[1], values[2] * 1024)

    def argv(self, command, path_env):
        if (not isinstance(command, list) or not command
                or any(not isinstance(arg, str) or "\x00" in arg for arg in command)
                or not command[0].startswith("/") or len(command) > 256
                or not isinstance(path_env, str) or not path_env
                or any(c in path_env for c in ("\x00", "\n", "\r"))):
            raise ValueError("Invalid approved compile command")
        return [
            SANDBOX,
            f"--max_cpu_time={self.cpu_ms}",
            f"--max_real_time={self.real_ms}",
            f"--max_memory={self.memory_bytes}",
            "--max_stack=134217728",
            f"--max_output_size={OUTPUT_BYTES}",
            f"--exe_path={command[0]}",
            *[f"--exe_args={arg}" for arg in command[1:]],
            f"--exe_envs=PATH={path_env}",
            "--input_path=/dev/null",
            "--output_path=compiler.out",
        ]


def classify(result):
    """A malformed/infrastructure result must never look like compilation success."""
    names = ("result", "error", "exit_code", "signal", "cpu_time", "real_time", "memory")
    if (not isinstance(result, dict)
            or any(type(result.get(k)) is not int or result[k] < 0 for k in names)):
        return "DEBUG_COMPILE_SANDBOX_FAILED"
    if result["error"] or result["result"] == 5:
        return "DEBUG_COMPILE_SANDBOX_FAILED"
    if result["result"] in (1, 2):
        return "DEBUG_COMPILE_TIMEOUT"
    if result["result"] == 3:
        return "DEBUG_COMPILE_MEMORY_LIMIT"
    if result["result"] == 6 or result["signal"] == signal.SIGXFSZ:
        return "DEBUG_COMPILE_OUTPUT_LIMIT"
    if result["result"] not in (0, 4):
        return "DEBUG_COMPILE_SANDBOX_FAILED"
    if result["result"] or result["exit_code"] or result["signal"]:
        return "DEBUG_COMPILE_FAILED"
    return None


def compiler_output(work):
    """Only compiler diagnostics are public, never sandbox.log or launcher stderr."""
    path = Path(work) / "compiler.out"
    try:
        # Compiler-owned files cannot redirect the trusted reader to another path.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            import stat
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Invalid compiler output")
            data = stream.read(PUBLIC_BYTES + 1)
        return {
            "output": data[:PUBLIC_BYTES].decode(errors="replace"),
            "truncated": len(data) > PUBLIC_BYTES,
        }
    except FileNotFoundError:
        return {"output": "", "truncated": False}


async def compile_source(spec, work="/work"):
    """Return a public failure event or None. Never execute the compiler directly."""
    failure = {"code": "DEBUG_COMPILE_SANDBOX_FAILED", "output": ""}
    try:
        if os.getuid() != 0 or os.geteuid() != 0:
            return failure
        expected = spec["compileSandboxSha256"]
        if hashlib.sha256(Path(SANDBOX).read_bytes()).hexdigest() != expected:
            return failure
        limits = CompileLimits(**spec["compileLimits"])
        argv = limits.argv(spec["compile"], spec["compilePathEnv"])
        print(json.dumps({"stage": "compile-start", "sandboxSha256": expected,
                          "compiler": spec["compile"][0], "cpuMs": limits.cpu_ms,
                          "realMs": limits.real_ms, "memoryBytes": limits.memory_bytes}),
              file=sys.stderr, flush=True)
        process = await asyncio.create_subprocess_exec(
            *argv, cwd=work, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            start_new_session=True, limit=16384,
        )

        async def private_stderr():
            tail = bytearray()
            while True:
                chunk = await process.stderr.read(4096)
                if not chunk:
                    return bytes(tail).decode(errors='replace')
                tail.extend(chunk)
                del tail[:-8192]

        stderr_task = asyncio.create_task(private_stderr())

        async def read_result():
            data = bytearray()
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > 16384:
                    raise ValueError("Unbounded sandbox result")
            await process.wait()
            if process.returncode:
                # Only the private guardian diagnostics receive this bounded
                # native-launcher stream. It never enters IDE output/events.
                print(json.dumps({'stage': 'compile-launcher',
                    'returnCode': process.returncode, 'stderr': await stderr_task}),
                    file=sys.stderr, flush=True)
                raise ValueError("Sandbox launcher failed")
            return json.loads(data)

        timeout_source = None
        try:
            # Native timeout rounds to the next second; allow only a bounded
            # control margin. On expiry, outer guardian cleanup kills descendants.
            result = await asyncio.wait_for(read_result(), limits.real_ms / 1000 + 3)
            code = classify(result)
            if code == "DEBUG_COMPILE_TIMEOUT":
                timeout_source = "sandbox"
        except asyncio.TimeoutError:
            code, result = "DEBUG_COMPILE_TIMEOUT", {}
            timeout_source = "control-watchdog"
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), 1)
                except asyncio.TimeoutError:
                    # Report the compile failure now. Exiting the namespace
                    # supervisor plus guardian teardown owns whole-tree cleanup;
                    # an unconfirmed cgroup never releases its reservation.
                    pass
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
        print(json.dumps({"stage": "compile-result", "code": code or "COMPILED",
                          "timeoutSource": timeout_source,
                          "result": {key: result[key] for key in (
                              "result", "error", "exit_code", "signal", "cpu_time", "real_time", "memory")
                                     if type(result.get(key)) is int}}), file=sys.stderr, flush=True)
        if code:
            return dict(compiler_output(work), code=code,
                        exitCode=result.get("exit_code"), signal=result.get("signal"),
                        timeoutSource=timeout_source)
        return None
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"stage": "compile-infrastructure", "exception": type(error).__name__}),
              file=sys.stderr, flush=True)
        return failure
