"""Formal compiler contract tests; mocks do not count as kernel/toolchain proof."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal

import pytest

from ide_debug import judge_compile as compile
from ide_debug.profiles import Profile, DebugError, sandbox_binary
from tests.test_debug_runtime import TEMPLATES, ROW, manifest, policy, Store, Sandbox, body, wait_for
from ide_debug.runtime import Runtime


def receipt(**updates):
    return dict(result=0, error=0, exit_code=0, signal=0,
                cpu_time=10, real_time=12, memory=1024, **updates)


@pytest.mark.parametrize("row", TEMPLATES, ids=lambda row: row["id"])
def test_exact_template_units_and_formal_sandbox_arguments(row):
    source = json.loads(row["shellScript"])["user"]["compile"]
    limits = compile.CompileLimits.template(row)
    argv = limits.argv(["/usr/bin/compiler", "--output=main", "main.c"], "/usr/bin:/bin",
                       cgroup_root="/compile-cgroup", pids=64)
    assert argv[0] == "/usr/bin/sandbox"
    assert f'--max_cpu_time={source["maxCpuTime"]}' in argv
    assert f'--max_real_time={source["maxRealTime"]}' in argv
    assert f'--max_memory={source["maxMemory"] * 1024 or 1024**3}' in argv
    assert "--max_stack=134217728" in argv
    assert "--max_output_size=20971520" in argv
    assert "--exe_args=--output=main" in argv
    assert "--input_path=/dev/null" in argv and "--output_path=/control/compiler.out" in argv
    assert "--exe_envs=PATH=/usr/bin:/bin" in argv
    assert "--max_process_number=64" in argv and "--cgroup_root=/compile-cgroup" in argv
    assert "--io_mode=memfd" in argv and "--isolate_fs=1" in argv
    assert not any(arg.startswith(("--uid=", "--gid=", "--seccomp_rules=")) for arg in argv)


@pytest.mark.parametrize("updates,code", [
    ({"result": 1}, "DEBUG_COMPILE_TIMEOUT"),
    ({"result": 2}, "DEBUG_COMPILE_TIMEOUT"),
    ({"result": 3}, "DEBUG_COMPILE_MEMORY_LIMIT"),
    ({"result": 4, "exit_code": 1}, "DEBUG_COMPILE_FAILED"),
    ({"result": 5, "error": 6}, "DEBUG_COMPILE_SANDBOX_FAILED"),
    ({"result": 6}, "DEBUG_COMPILE_OUTPUT_LIMIT"),
    ({"result": 4, "signal": int(signal.SIGXFSZ)}, "DEBUG_COMPILE_OUTPUT_LIMIT"),
    ({"result": 7}, "DEBUG_COMPILE_SANDBOX_FAILED"),
    ({"result": True}, "DEBUG_COMPILE_SANDBOX_FAILED"),
])
def test_classifies_formal_sandbox_results(updates, code):
    value = receipt()
    value.update(updates)
    assert compile.classify(value) == code
    assert compile.classify(receipt()) is None
    assert compile.classify({"result": 0}) == "DEBUG_COMPILE_SANDBOX_FAILED"


def test_missing_approved_digest_and_unbounded_template_fail_closed():
    config = manifest()
    del config["19"]["compile_sandbox_sha256"]
    with pytest.raises(DebugError, match="PROFILE_INVALID"):
        Profile.resolve(config, ROW, "c")
    changed = dict(ROW)
    spec = json.loads(changed["shellScript"])
    spec["user"]["compile"]["maxRealTime"] = 0
    changed["shellScript"] = json.dumps(spec)
    with pytest.raises(ValueError, match="bounded"):
        compile.CompileLimits.template(changed)


def test_output_is_bounded_and_cannot_follow_symlinks_or_fifos(tmp_path):
    (tmp_path / "compiler.out").write_bytes(b"a" * (compile.PUBLIC_BYTES + 100))
    assert compile.compiler_output(tmp_path) == {"output": "a" * compile.PUBLIC_BYTES, "truncated": True}
    (tmp_path / "compiler.out").unlink()
    (tmp_path / "private.log").write_text("private host stderr")
    (tmp_path / "compiler.out").symlink_to(tmp_path / "private.log")
    with pytest.raises(OSError):
        compile.compiler_output(tmp_path)


def test_compiler_stderr_is_public_but_infrastructure_logs_are_private(tmp_path):
    (tmp_path / "compiler.err").write_text("main.c:3: error: expected expression\n")
    (tmp_path / "compiler.out").write_text("compiler progress\n")
    (tmp_path / "sandbox.log").write_text("PRIVATE host path and native setup log")
    result = compile.compiler_output(tmp_path)
    assert result["output"] == "main.c:3: error: expected expression\ncompiler progress\n"
    assert not result["truncated"] and "PRIVATE" not in result["output"]
    (tmp_path / "compiler.err").write_bytes(b"e" * compile.PUBLIC_BYTES)
    result = compile.compiler_output(tmp_path)
    assert result == {"output": "e" * compile.PUBLIC_BYTES, "truncated": True}
    (tmp_path / "compiler.out").unlink()
    os.mkfifo(tmp_path / "compiler.out")
    with pytest.raises(ValueError, match="output"):
        compile.compiler_output(tmp_path)


def test_formal_sandbox_absolute_symlink_is_resolved_inside_rootfs(tmp_path):
    target = tmp_path / "opt/sduoj-sandbox/bin/sandbox"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"verified judge binary")
    link = tmp_path / "usr/bin/sandbox"
    link.parent.mkdir(parents=True)
    link.symlink_to("/opt/sduoj-sandbox/bin/sandbox")
    assert sandbox_binary(tmp_path) == target
    link.unlink()
    link.symlink_to("../../../../host-private-binary")
    with pytest.raises(DebugError, match="NOT_VERIFIED"):
        sandbox_binary(tmp_path)
    link.unlink()
    link.symlink_to("/usr/bin/sandbox")
    with pytest.raises(DebugError, match="NOT_VERIFIED"):
        sandbox_binary(tmp_path)


def test_non_namespace_root_never_spawns_direct_compiler(monkeypatch):
    monkeypatch.setattr(compile.os, "getuid", lambda: 1000)
    async def forbidden(*args, **kwargs):
        pytest.fail("Unprivileged mode must not launch any compiler")
    monkeypatch.setattr(compile.asyncio, "create_subprocess_exec", forbidden)
    result = asyncio.run(compile.compile_source({"compile": ["/usr/bin/gcc"]}))
    assert result["code"] == "DEBUG_COMPILE_SANDBOX_FAILED"


@pytest.mark.parametrize("outcome,expected", [
    ("success", None), ("compiler-error", "DEBUG_COMPILE_FAILED"),
    ("malformed", "DEBUG_COMPILE_SANDBOX_FAILED"),
    ("timeout", "DEBUG_COMPILE_TIMEOUT"),
])
def test_sandbox_protocol_and_watchdog_reap_control_process(tmp_path, monkeypatch, capsys, outcome, expected):
    sandbox = tmp_path / "sandbox"
    sandbox.write_bytes(b"approved binary placeholder, never executed")
    monkeypatch.setattr(compile, "SANDBOX", str(sandbox))
    monkeypatch.setattr(compile.os, "getuid", lambda: 0)
    monkeypatch.setattr(compile.os, "geteuid", lambda: 0)
    (tmp_path / "compiler.err").write_text("source.c:1: error: expected expression\n")
    read_output = compile.compiler_output
    monkeypatch.setattr(compile, "compiler_output", lambda path: read_output(tmp_path))
    calls, killed = [], []

    class Process:
        pid, returncode = 987654321, None
        read_count = 0
        @property
        def stderr(self):
            stream = asyncio.StreamReader()
            stream.feed_eof()
            return stream
        @property
        def stdout(self):
            return self
        async def read(self, size):
            if outcome == "timeout":
                await asyncio.Event().wait()
            self.read_count += 1
            if self.read_count > 2:
                return b""
            value = receipt()
            if outcome == "compiler-error":
                value.update(result=4, exit_code=1)
            data = b"invalid JSON" if outcome == "malformed" else json.dumps(value).encode()
            return data[:3] if self.read_count == 1 else data[3:]
        async def wait(self):
            if self.returncode is None:
                self.returncode = 0
            return self.returncode
    process = Process()
    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return process
    def killpg(pid, sig):
        killed.append((pid, sig))
        process.returncode = -9
    monkeypatch.setattr(compile.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(compile.os, "killpg", killpg)
    original_wait_for = asyncio.wait_for
    async def short_watchdog(awaitable, timeout):
        assert timeout in (1, 8)
        return await original_wait_for(awaitable, 0.01 if outcome == "timeout" and timeout == 8 else timeout)
    monkeypatch.setattr(compile.asyncio, "wait_for", short_watchdog)
    spec = {
        "compileSandboxSha256": hashlib.sha256(sandbox.read_bytes()).hexdigest(),
        "compileLimits": {"cpu_ms": 3000, "real_ms": 5000, "memory_bytes": 512 * 1024**2},
        "compile": ["/usr/bin/gcc", "main.c", "-g", "-O0"],
        "compilePathEnv": "/usr/bin:/bin",
        "compileMode": "official-v2-separate",
        "compileCgroupRoot": "/compile-cgroup",
        "compilePids": 64,
    }
    result = asyncio.run(compile.compile_source(spec, str(tmp_path)))
    if expected is None:
        assert result is None
    else:
        assert result["code"] == expected
        if outcome in ("compiler-error", "timeout"):
            assert "expected expression" in result["output"]
    assert len(calls) == 1 and calls[0][0][0] == str(sandbox)
    assert "--exe_path=/usr/bin/gcc" in calls[0][0]
    assert calls[0][1]["start_new_session"] is True
    assert process.returncode is not None
    assert bool(killed) == (outcome == "timeout")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert '"stage": "compile-start"' in captured.err
    assert "source.c:1: error" not in captured.err
    if outcome == "timeout":
        assert result["timeoutSource"] == "control-watchdog"


@pytest.mark.parametrize("code", sorted(compile.COMPILE_CODES))
def test_compile_failure_survives_terminal_snapshot_and_late_callbacks(code):
    class CompileFailure(Sandbox):
        async def start(self, spec):
            self.emit("compileError", {"code": code, "output": "source diagnostic", "truncated": True})
            self.emit("terminated", {})
            self.emit("guardianLost", {})
    async def run():
        runtime = Runtime(policy(), Store(), manifest(), CompileFailure, lambda: 100 * 1024**3)
        await runtime.start()
        try:
            value = await runtime.create(7, body(), ROW)
            session = runtime.sessions[value["sessionId"]]
            await wait_for(lambda: session.state in ("terminated", "failed"))
            assert session.snapshot()["reason"] == code
            errors = [event for event in session.events if event["type"] == "compileError"]
            assert len(errors) == 1 and errors[0]["data"]["output"] == "source diagnostic"
            assert session.grant == 0
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize('event', ['failed', 'guardianLost', 'terminated'])
def test_exit_before_compiled_is_a_visible_compile_stage_failure(event):
    class BeforeCompile(Sandbox):
        async def start(self, spec):
            self.emit(event, {})
    async def run():
        runtime = Runtime(policy(), Store(), manifest(), BeforeCompile, lambda: 100 * 1024**3)
        await runtime.start()
        try:
            value = await runtime.create(7, body(), ROW)
            session = runtime.sessions[value['sessionId']]
            await wait_for(lambda: session.state == 'terminated')
            assert session.reason == 'DEBUG_COMPILE_SANDBOX_FAILED'
            assert any(item['type'] == 'compileError' and item['data']['code'] == session.reason
                       for item in session.events)
        finally:
            await runtime.close()
    asyncio.run(run())
