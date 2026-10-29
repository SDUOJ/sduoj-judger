import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ide_debug.launcher import nsjail_config
from ide_debug.config import Policy
from sduoj_ide_worker.worker import Worker
from sduoj_ide_worker.protocol import Job
from sduoj_ide_worker.debug import DebugExecution


def test_debug_replicas_have_distinct_stable_resource_reservation_identities(monkeypatch):
    monkeypatch.delenv('AUTOLAB_DEBUG_NODE', raising=False)
    first = DebugExecution(SimpleNamespace(id='replica_first'))
    second = DebugExecution(SimpleNamespace(id='replica_second'))
    assert first.policy.node != second.policy.node
    assert first.policy.node == DebugExecution(SimpleNamespace(id='replica_first')).policy.node


def test_process_cap_is_per_cgroup_not_shared_uid_rlimit(monkeypatch):
    monkeypatch.setattr('ide_debug.launcher.os.getuid', lambda: 10001)
    monkeypatch.setattr('ide_debug.launcher.os.getgid', lambda: 10001)
    monkeypatch.setattr('ide_debug.launcher.os.geteuid', lambda: 10001)
    monkeypatch.setattr('ide_debug.launcher.os.getegid', lambda: 10001)
    profile = SimpleNamespace(pids=64, rootfs='/rootfs', tmpfs=67108864,
        seccomp='/policy', python='/python', runner='/runner.py')
    config = nsjail_config(profile, Policy(subuid=100000, subgid=100000))
    assert 'rlimit_nproc_type: INF' in config
    assert 'rlimit_nproc: 64' not in config
    assert 'rlimit_nofile: 256' in config
    assert 'rlimit_stack_type: VALUE' in config
    # Launcher.start still passes profile.pids to the independent guardian's
    # cgroup creation; this change does not remove the per-sandbox PID cap.


def test_expired_debug_task_is_explicitly_not_executed():
    async def check():
        value = dict(schemaVersion=1, requestId='request-1234567890', replyTo='gateway-1234567890',
            sessionId='session-1234567890', sessionEpoch='epoch-1234567890', ownerId='7',
            role='debug', operation='create', body={}, deadlineAt=1)
        redis = SimpleNamespace(get=AsyncMock(return_value=json.dumps(value)))
        worker = Worker('debug', redis=redis)
        worker.debug = SimpleNamespace(reject_unstarted=AsyncMock(), execute=AsyncMock())
        worker.reply = AsyncMock()
        await worker.process(value['requestId'])
        worker.debug.execute.assert_not_called()
        worker.debug.reject_unstarted.assert_awaited_once()
        assert worker.reply.await_args.kwargs == dict(status=504, error='DEBUG_TASK_EXPIRED')
    asyncio.run(check())


def test_confirmed_program_exit_completes_resume_instead_of_marking_interrupted():
    from tests.test_debug_runtime import Runtime, Store, Sandbox, policy, manifest, ROW, body, command, wait_for, GiB

    class ExitingSandbox(Sandbox):
        async def command(self, operation, arguments):
            if operation == 'continue':
                self.emit('terminated', {'reason': 'exited-normally'})
            return {}

        async def request(self, operation, arguments):
            return await self.command(operation, arguments)

    async def check():
        runtime = Runtime(policy(), Store(), manifest(), ExitingSandbox, lambda: 100 * GiB)
        await runtime.start()
        try:
            created = await runtime.create(7, body(), ROW)
            session = runtime.sessions[created['sessionId']]
            await wait_for(lambda: session.frozen and not session.actor.locked())
            session.compiled = True
            request = command(session, operation='continue')
            await runtime.command(session.id, 7, request)
            await wait_for(lambda: session.state == 'terminated')
            assert session.reason == 'DEBUG_TERMINATED'
            assert session.commands[request.commandId]['status'] == 'completed'
        finally:
            await runtime.close()
    asyncio.run(check())
