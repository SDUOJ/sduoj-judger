"""Business invariants with a deterministic sandbox double (not isolation proof)."""

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import time
import pytest

from ide_debug.config import Policy, MiB, GiB
from ide_debug.models import Create, Command
from ide_debug.profiles import DebugError, Profile, debug_compile
from ide_debug.profiles import phase_startup_budget
from ide_debug.judge_compile import CompileLimits
from ide_debug.runtime import Runtime

TEMPLATES = json.loads(
    (Path(__file__).parent / "fixtures/ide_public_templates_20261023.json").read_text()
)
ROW = next(r for r in TEMPLATES if r["id"] == "19")


def manifest(row=ROW, language="c"):
    profile, _ = debug_compile(row, language)
    return {
        row["id"]: {
            "templateHash": profile["templateHash"],
            "templateVersion": row["version"],
            "verified": True,
            "language": language,
            "rootfs": "/rootfs",
            "artifact_digest": "sha256:" + "a" * 64,
            "runner": "/opt/sduoj-debug/runner.py",
            "python": "/usr/bin/python3",
            "debugger": ["/usr/bin/gdb"],
            "hard": 128 * MiB,
            "startup": phase_startup_budget(256 * MiB, CompileLimits.template(row).memory_bytes),
            "runtime_startup": 256 * MiB,
            "artifact_max_bytes": 64 * MiB,
            "compile_setup_bytes": 64 * MiB,
            "compile_seccomp": "/etc/compile.policy",
            "compile_policy_sha256": "c" * 64,
            "floor": 32 * MiB,
            "margin": 8 * MiB,
            "pids": 64,
            "cpu_seconds": 30,
            "compile_seconds": 10,
            "compile_sandbox_sha256": "b" * 64,
            "compile_path_env": "/usr/bin:/bin",
            "active": 2,
            "starting": 1,
            "seccomp": "/etc/debug.policy",
            "tmpfs": 64 * MiB,
            "java_options": [],
        }
    }


def body(user=7, **overrides):
    return Create(
        **dict(
            {
                "commandId": f"create-{user:020d}",
                "language": "c",
                "judgeTemplateId": "19",
                "problemCode": "P1",
                "context": {"type": 0, "problemCode": "P1"},
                "code": "int main(){return 0;}",
                "breakpoints": [1],
            },
            **overrides,
        )
    )


class Store:
    def __init__(self):
        self.users = {}
        self.saved = {}
        self.specs = {}
        self.receipts = {}
        self.node = None

    async def open_receipt(self, user, command):
        return self.receipts.get((user, command))

    async def save_open_receipt(self, user, command, fingerprint, session):
        self.receipts[user, command] = {"hash": fingerprint, "sessionId": session}

    async def claim_node(self, value):
        if self.node:
            return False
        self.node = value
        return True

    async def renew_node(self, value):
        return self.node == value

    async def release_node(self, value):
        self.node = None

    async def claim_user(self, user, session, ttl):
        if user in self.users:
            return self.users[user]
        self.users[user] = session

    async def release_user(self, user, session):
        if self.users.get(user) == session:
            self.users.pop(user)

    async def save(self, session):
        self.saved[session.id] = session.snapshot()

    async def save_spec(self, session, spec):
        self.specs[session.id] = spec.copy()

    async def terminal(self, session):
        await self.save(session)
        self.specs.pop(session.id, None)
        await self.release_user(session.user, session.id)

    async def get(self, session_id, user):
        value = self.saved[session_id]
        if value["userId"] != user:
            raise DebugError("DEBUG_SESSION_NOT_FOUND", 404)
        return value


class Sandbox:
    instances = []

    def __init__(self, sid, profile, policy, emit):
        self.emit = emit
        self.calls = []
        self.cap = profile.startup
        self.frozen = False
        self.killed = False
        self.usage = 24 * MiB
        self.instances.append(self)

    async def start(self, spec):
        self.emit("stopped", {"threadId": 1, "reason": "entry"})

    async def guard(self, op, **arguments):
        self.calls.append((op, arguments))
        if op == "freeze":
            self.frozen = True
        if op == "thaw":
            self.frozen = False
        if op == "limit":
            self.cap = arguments["value"]
        return {"memory": self.usage, "cpuSeconds": 0, "pids": 3}

    async def request(self, op, args):
        self.calls.append((op, args))
        if op in ("continue", "next", "stepIn", "stepOut"):
            self.emit("running", {})
            self.emit("stopped", {"threadId": 1, "reason": "step"})
        if op == "stackTrace":
            return {
                "stackFrames": [
                    {"id": 0, "name": "main", "line": 3, "source": "/work/main.c"}
                ]
            }
        return {
            "variables": [{"name": "value", "value": "42", "variablesReference": 0}]
        }

    async def close(self):
        self.killed = True
        return True


async def wait_for(predicate, timeout=1):
    async def run():
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(run(), timeout)


def policy(**overrides):
    return replace(
        Policy(cgroup_version=2), budget=GiB, hard=2 * GiB, reserve=32 * MiB, host_floor=0, **overrides
    )


def command(session, number=1, operation="next", **overrides):
    value = {
        "commandId": f"command-{number:020d}",
        "sessionEpoch": session.epoch,
        "expectedStateVersion": session.version,
        "stopId": session.stop,
        "operation": operation,
        "arguments": {"threadId": 1} if operation == "next" else {},
    }
    value.update(overrides)
    return Command(**value)


def test_real_templates_debug_overrides_preserve_semantics_and_linking():
    for row in TEMPLATES:
        lang = (
            "c"
            if row["id"] == "19"
            else (
                "cpp"
                if row["id"] in ("6", "32", "50")
                else "java" if row["id"] in ("14", "37", "51") else "python"
            )
        )
        profile, args = debug_compile(row, lang)
        if lang in ("c", "cpp"):
            assert "-O0" in args and "-g" in args and "-s" not in args
            assert "-static" in args and "--define-macro=ONLINE_JUDGE" in args
            assert "--optimize=2" not in args
            if row["id"] == "19":
                assert "-lm" in args and "-fno-asm" in args
            if row["id"] == "50":
                assert "-Wl,/opt/gcc/13.2.0/lib64" in args
        elif lang == "java":
            assert "-g" in args
    changed = dict(ROW, version=ROW["version"] + 1)
    with pytest.raises(DebugError, match="NOT_VERIFIED"):
        Profile.resolve(manifest(), changed, "c")


def test_single_user_idempotency_heap_survives_and_stale_handles_rejected():
    async def run():
        store = Store()
        runtime = Runtime(policy(), store, manifest(), Sandbox, lambda: 100 * GiB)
        await runtime.start()
        try:
            first = await runtime.create(7, body(), ROW)
            session = runtime.sessions[first["sessionId"]]
            await wait_for(lambda: session.frozen and not session.actor.locked())
            again = await runtime.create(7, body(), ROW)
            assert again["sessionId"] == first["sessionId"]
            with pytest.raises(DebugError, match="COMMAND_ID_CONFLICT"):
                await runtime.create(7, body(code="different"), ROW)
            before = session.stop
            req = command(session)
            await runtime.command(session.id, 7, req)
            await wait_for(
                lambda: session.commands[req.commandId]["status"] == "completed"
            )
            duplicate = await runtime.command(session.id, 7, req)
            assert duplicate["sessionId"] == session.id and session.stop != before
            assert sum(op == "next" for op, _ in session.sandbox.calls) == 1
            with pytest.raises(DebugError, match="STALE_STOP"):
                await runtime.command(session.id, 7, command(session, 2, stopId=before))
            with pytest.raises(DebugError, match="NOT_FOUND"):
                await runtime.lookup(session.id, 8)
            assert session.grant == 32 * MiB and len(runtime.sessions) == 1
            assert [op for op, _ in session.sandbox.calls].index("limit") > [
                op for op, _ in session.sandbox.calls
            ].index("freeze")
        finally:
            await runtime.close()
        assert not store.users and not store.specs and session.sandbox.killed

    asyncio.run(run())


def test_joint_admission_wait_timeout_preserves_existing_scene_and_no_late_execution():
    async def run():
        runtime = Runtime(
            policy(active=1, wait=0.05), Store(), manifest(), Sandbox, lambda: 100 * GiB
        )
        await runtime.start()
        try:
            first = await runtime.create(7, body(), ROW)
            s = runtime.sessions[first["sessionId"]]
            await wait_for(lambda: s.frozen and not s.actor.locked())
            # Shrink frees most of its startup cap; then force growth shortage.
            runtime.policy = replace(runtime.policy, budget=96 * MiB, reserve=32 * MiB)
            req = command(s)
            await runtime.command(s.id, 7, req)
            assert s.ticket and s.frozen
            assert runtime.active["c"] == 0
            await asyncio.sleep(0.07)
            runtime.wake.set()
            await wait_for(lambda: s.ticket is None)
            assert s.commands[req.commandId]["error"] == "DEBUG_RESOURCE_WAIT_TIMEOUT"
            assert s.frozen and not s.sandbox.killed
            runtime.policy = replace(runtime.policy, budget=GiB)
            runtime.wake.set()
            await asyncio.sleep(0.02)
            assert not any(op == "next" for op, _ in s.sandbox.calls)
        finally:
            await runtime.close()

    asyncio.run(run())


def test_immutable_30_minute_deadline_counts_queue_and_poll_does_not_touch_ttl():
    async def run():
        runtime = Runtime(
            policy(lifetime=0.18, idle=0.15),
            Store(),
            manifest(),
            Sandbox,
            lambda: 100 * GiB,
        )
        await runtime.start()
        try:
            result = await runtime.create(7, body(), ROW)
            s = runtime.sessions[result["sessionId"]]
            await wait_for(lambda: s.frozen and not s.actor.locked())
            hard, started = s.hard_at, s.started
            idle = s.idle_at
            await runtime.poll(s.id, 7, 0, 0)
            assert s.idle_at == idle
            await runtime.command(s.id, 7, command(s))
            await wait_for(lambda: s.frozen and not s.actor.locked())
            assert s.started == started and s.hard_at == hard and s.idle_at <= hard
            # Maintenance interval is intentionally centralized, not per-ticket.
            await wait_for(lambda: s.state == "terminated", timeout=1)
            assert s.sandbox.killed and s.grant == 0
        finally:
            await runtime.close()

    asyncio.run(run())


def test_owner_lease_and_cleanup_failure_fail_closed():
    class Unclean(Sandbox):
        async def close(self):
            return False

    async def run():
        store = Store()
        one = Runtime(policy(), store, manifest(), Unclean, lambda: 100 * GiB)
        two = Runtime(policy(), store, manifest(), Sandbox, lambda: 100 * GiB)
        await one.start()
        with pytest.raises(RuntimeError, match="one debug runtime"):
            await two.start()
        result = await one.create(7, body(), ROW)
        s = one.sessions[result["sessionId"]]
        await wait_for(lambda: s.frozen and not s.actor.locked())
        await one.terminate(s, "test")
        assert (
            s.state == "lost"
            and s.grant
            and not one.admitting
            and store.users[7] == s.id
        )
        await one.close()
        assert store.node is not None

    asyncio.run(run())


@pytest.mark.parametrize(
    "op,args",
    [
        ("next", {"threadId": "1\n-exec-run"}),
        ("variables", {"variablesReference": 1, "count": 101}),
        ("setBreakpoints", {"lines": [True]}),
        ("scopes", {"frameId": 1, "evaluate": "system()"}),
        ("stdin", {"text": "\x00"}),
    ],
)
def test_no_raw_dap_or_shell_argument_injection(op, args):
    from ide_debug.runtime import validate_arguments

    with pytest.raises(DebugError):
        validate_arguments(op, args)


def test_queue_cancellation_preserves_frozen_scene_and_releases_no_live_grant():
    async def run():
        runtime = Runtime(policy(), Store(), manifest(), Sandbox, lambda: 100 * GiB)
        await runtime.start()
        try:
            value = await runtime.create(7, body(), ROW)
            session = runtime.sessions[value["sessionId"]]
            await wait_for(lambda: session.frozen and not session.actor.locked())
            runtime.available = lambda: 0
            req = command(session)
            await runtime.command(session.id, 7, req)
            ticket = session.ticket
            grant = session.grant
            await runtime.cancel(session.id, 7, session.epoch, ticket.id)
            assert session.ticket is None and session.frozen and session.grant == grant
            assert session.commands[req.commandId]["error"] == "DEBUG_CANCELLED"
            runtime.available = lambda: 100 * GiB
            runtime.wake.set()
            await asyncio.sleep(0.01)
            assert not any(op == "next" for op, _ in session.sandbox.calls)
        finally:
            await runtime.close()

    asyncio.run(run())


def test_python_target_and_java_jvm_flags_come_from_the_authorized_template():
    python_row = next(row for row in TEMPLATES if row["id"] == "38")
    config = manifest(python_row, "python")
    selected = Profile.resolve(config, python_row, "python")
    assert selected.python == "/usr/bin/python3"
    assert selected.target_python == "/opt/python/3.11/bin/python"
    java_row = next(row for row in TEMPLATES if row["id"] == "51")
    config = manifest(java_row, "java")
    config["51"]["debugger"] = [
        "/opt/java/openjdk21/bin/java",
        "-cp",
        "/bridge",
        "DebugBridge",
    ]
    with pytest.raises(DebugError, match="UNRESOLVED"):
        Profile.resolve(config, java_row, "java")
    selected = Profile.resolve(config, java_row, "java", {"problemMemoryLimit": 262144})
    assert "-XX:MaxRAM=262144k" in selected.java_options
    assert "-Dfile.encoding=UTF-8" in selected.java_options
    assert "-Djava.awt.headless=true" in selected.java_options
    config["51"]["debugger"][0] = "/opt/java/openjdk17/bin/java"
    with pytest.raises(DebugError):
        Profile.resolve(config, java_row, "java", {"problemMemoryLimit": 262144})


def test_disconnect_cannot_cancel_stop_cleanup_or_release_a_live_memory_grant():
    async def run():
        entered = asyncio.Event()
        finish = asyncio.Event()

        class SlowClose(Sandbox):
            async def close(self):
                entered.set()
                await finish.wait()
                return True

        runtime = Runtime(policy(), Store(), manifest(), SlowClose, lambda: 100 * GiB)
        await runtime.start()
        try:
            value = await runtime.create(7, body(), ROW)
            session = runtime.sessions[value["sessionId"]]
            await wait_for(lambda: session.frozen and not session.actor.locked())
            stop = asyncio.create_task(
                runtime.control(session.id, 7, session.epoch, "stop")
            )
            await entered.wait()
            stop.cancel()
            with pytest.raises(asyncio.CancelledError):
                await stop
            assert session.grant and runtime.users[7] == session.id
            finish.set()
            await wait_for(lambda: session.state == "terminated" and not session.grant)
            assert 7 not in runtime.users and not runtime.store.users
        finally:
            finish.set()
            await runtime.close()

    asyncio.run(run())


def test_normal_stop_ignores_late_guardian_and_adapter_terminal_callbacks():
    async def run():
        class ClosingCallbacks(Sandbox):
            async def close(self):
                self.emit("guardianLost", {})
                self.emit("terminated", {})
                self.emit("failed", {"code": "DEBUG_GUARDIAN_FAILED"})
                self.killed = True
                return True

        runtime = Runtime(policy(), Store(), manifest(), ClosingCallbacks, lambda: 100 * GiB)
        await runtime.start()
        try:
            value = await runtime.create(7, body(), ROW)
            session = runtime.sessions[value["sessionId"]]
            await wait_for(lambda: session.frozen and not session.actor.locked())
            await runtime.control(session.id, 7, session.epoch, "stop")
            assert session.state == "terminated"
            assert session.reason == "DEBUG_USER_STOP"
            terminal = [event for event in session.events if event["type"] in
                        {"terminated", "guardianLost", "failed", "lost"}]
            assert terminal == [{"cursor": terminal[0]["cursor"],
                                 "type": "terminated",
                                 "data": {"reason": "DEBUG_USER_STOP"}}]
            assert runtime.metrics["terminated_total"] == 1
            assert session.grant == 0
            assert 7 not in runtime.users and not runtime.store.users
        finally:
            await runtime.close()
    asyncio.run(run())


def test_recovery_replace_dedup_and_foreign_owner():
    async def run():
        runtime = Runtime(policy(), Store(), manifest(), Sandbox, lambda: 100 * GiB)
        await runtime.start()
        try:
            first = await runtime.create(7, body(), ROW)
            old = runtime.sessions[first["sessionId"]]
            await wait_for(lambda: old.frozen and not old.actor.locked())
            restored = await runtime.create(
                7,
                body(
                    commandId="restore-00000000000001",
                    restoreOnly=True,
                    resumeSessionId=old.id,
                    resumeSessionEpoch=old.epoch,
                ),
                ROW,
            )
            assert restored["sessionId"] == old.id
            with pytest.raises(DebugError, match="NOT_FOUND"):
                await runtime.create(
                    8,
                    body(
                        commandId="restore-00000000000002",
                        restoreOnly=True,
                        resumeSessionId=old.id,
                        resumeSessionEpoch=old.epoch,
                    ),
                    ROW,
                )
            with pytest.raises(DebugError, match="RESUME_UNAVAILABLE"):
                await runtime.create(
                    7,
                    body(
                        commandId="restore-00000000000003",
                        restoreOnly=True,
                        resumeSessionId=old.id,
                        resumeSessionEpoch=old.epoch,
                        code="changed",
                    ),
                    ROW,
                )
            fresh = body(commandId="replace-00000000000001", replaceExisting=True)
            replies = await asyncio.gather(
                *[runtime.create(7, fresh, ROW) for _ in range(4)]
            )
            assert (
                len({r["sessionId"] for r in replies}) == 1
                and replies[0]["sessionId"] != old.id
            )
            assert old.sandbox.killed and old.grant == 0
            assert runtime.users[7] == replies[0]["sessionId"]
        finally:
            await runtime.close()

    asyncio.run(run())


def test_profile_trusted_wall_limit_and_safe_watch_paths():
    from ide_debug.runtime import validate_arguments

    row = dict(ROW)
    config = json.loads(row["shellScript"])
    config["user"]["run"]["maxRealTimeFactor"] = 3
    row["shellScript"] = json.dumps(config)
    profile = Profile.resolve(manifest(row), row, "c", {"problemTimeLimit": 1000})
    assert profile.run_seconds == 6
    for expression in ("value", "user.name", "arr[0]", "arr[0].value"):
        assert validate_arguments("watch", {"frameId": 0, "expressions": [expression]})
    for expression in (
        "value()",
        "arr[-1]",
        "x + 1",
        "x.__class__()",
        "arr[100000]",
        "x;quit",
    ):
        with pytest.raises(DebugError):
            validate_arguments("watch", {"frameId": 0, "expressions": [expression]})


def test_running_input_does_not_wait_for_execution_actor_or_reset_deadline():
    class Waiting(Sandbox):
        async def request(self, op, args):
            if op in ("continue", "next", "stepIn", "stepOut"):
                self.emit("running", {})
                return {}
            if op == "stdin":
                self.calls.append((op, args))
                return {"acceptedBytes": len(args["text"].encode())}
            return await super().request(op, args)

    async def run():
        runtime = Runtime(policy(), Store(), manifest(), Waiting, lambda: 100 * GiB)
        await runtime.start()
        try:
            first = await runtime.create(7, body(), ROW)
            session = runtime.sessions[first["sessionId"]]
            await wait_for(lambda: session.frozen and not session.actor.locked())
            await runtime.command(session.id, 7, command(session, operation="continue"))
            await wait_for(
                lambda: session.state == "running" and session.actor.locked()
            )
            deadline = session.run_until
            request = command(
                session, 9, operation="stdin", arguments={"text": "hello\n"}
            )
            await runtime.command(session.id, 7, request)
            await runtime.command(session.id, 7, request)
            await wait_for(
                lambda: session.commands[request.commandId]["status"] == "completed"
            )
            assert session.run_until == deadline
            assert [op for op, _ in session.sandbox.calls].count("stdin") == 1
        finally:
            await runtime.close()

    asyncio.run(run())


def test_stop_joins_dispatched_start_before_releasing_owner_or_grant():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        class Delayed(Sandbox):
            async def start(self, spec):
                entered.set()
                await release.wait()
                self.emit("stopped", {"threadId": 1})

        runtime = Runtime(policy(), Store(), manifest(), Delayed, lambda: 100 * GiB)
        await runtime.start()
        try:
            first = await runtime.create(7, body(), ROW)
            session = runtime.sessions[first["sessionId"]]
            await asyncio.wait_for(entered.wait(), 1)
            stopping = asyncio.create_task(
                runtime.control(session.id, 7, session.epoch, "stop")
            )
            await wait_for(lambda: session.closing)
            assert (
                runtime.users[7] == session.id
                and session.grant > 0
                and not stopping.done()
            )
            release.set()
            await asyncio.wait_for(stopping, 1)
            assert (
                session.sandbox.killed and session.grant == 0 and 7 not in runtime.users
            )
        finally:
            release.set()
            await runtime.close()

    asyncio.run(run())


def test_run_segment_deadline_terminates_instead_of_auto_pausing():
    class Forever(Sandbox):
        async def request(self, op, args):
            if op == "continue":
                self.emit("running", {})
                return {}
            return await super().request(op, args)

    async def run():
        runtime = Runtime(policy(), Store(), manifest(), Forever, lambda: 100 * GiB)
        await runtime.start()
        try:
            first = await runtime.create(
                7, body(), ROW, parameters={"problemTimeLimit": 20}
            )
            session = runtime.sessions[first["sessionId"]]
            await wait_for(lambda: session.frozen and not session.actor.locked())
            await runtime.command(session.id, 7, command(session, operation="continue"))
            await wait_for(lambda: session.state == "terminated")
            assert (
                session.reason == "DEBUG_RUN_TIMEOUT"
                and session.sandbox.killed
                and session.grant == 0
            )
            assert not any(op == "pause" for op, _ in session.sandbox.calls)
        finally:
            await runtime.close()

    asyncio.run(run())


def test_equal_source_new_command_cannot_return_old_allocation():
    async def run():
        runtime = Runtime(policy(), Store(), manifest(), Sandbox, lambda: 100 * GiB)
        await runtime.start()
        try:
            first = await runtime.create(7, body(), ROW)
            with pytest.raises(DebugError, match='DEBUG_USER_ALREADY_HAS_SESSION'):
                await runtime.create(7, body(commandId='another-create-command-00001'), ROW)
            assert list(runtime.sessions) == [first['sessionId']]
        finally:
            await runtime.close()
    asyncio.run(run())


def test_failed_initial_persistence_never_dispatches_or_loses_live_sandbox():
    class FailedStore(Store):
        async def save(self, session):
            await asyncio.sleep(.02)
            raise RuntimeError('unavailable')
    async def run():
        store = FailedStore()
        runtime = Runtime(policy(), store, manifest(), Sandbox, lambda: 100 * GiB)
        await runtime.start()
        try:
            with pytest.raises(RuntimeError, match='unavailable'):
                await runtime.create(7, body(), ROW)
            assert not runtime.sessions and not runtime.queue and not runtime.running
            assert not store.users
            assert runtime.metrics['dispatched_total'] == 0
        finally:
            await runtime.close()
    asyncio.run(run())


def test_cancelled_stdin_records_interruption_without_name_error():
    class BlockingInput(Sandbox):
        async def request(self, op, args):
            if op == 'stdin':
                await asyncio.Event().wait()
            return await super().request(op, args)
    async def run():
        runtime = Runtime(policy(), Store(), manifest(), BlockingInput, lambda: 100 * GiB)
        await runtime.start()
        try:
            first = await runtime.create(7, body(), ROW)
            session = runtime.sessions[first['sessionId']]
            await wait_for(lambda: session.frozen and not session.actor.locked())
            session.commands['input-1'] = {'status': 'dispatched'}
            task = asyncio.create_task(runtime.live_input(session, 'input-1', {'text': 'hello'}))
            await asyncio.sleep(.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert session.commands['input-1']['error'] == 'DEBUG_COMMAND_INTERRUPTED'
        finally:
            await runtime.close()
    asyncio.run(run())
