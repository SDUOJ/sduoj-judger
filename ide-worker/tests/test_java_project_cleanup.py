"""JDT unmanaged-project deletion is exact, acknowledged and bounded."""
import asyncio

import pytest

from ide_intelligence.lsp_process import LspProcess, LspUnavailable


def fixture(tmp_path):
    root = tmp_path / 'workspace'
    data = tmp_path / 'workspace-jdtls-data'
    process = LspProcess(['jdtls', '-data', str(data)], root, None, 'java')
    directory = tmp_path / 'documents' / ('owned-r1-' + 'a' * 32)
    directory.mkdir(parents=True)
    process._immutable_directories.add(directory)
    return process, directory, data


def test_removes_only_exact_old_revision_and_confirms_job_before_return(tmp_path):
    async def run():
        p, old, data = fixture(tmp_path)
        own = (data / (old.name + '_1234abcd')).as_uri()
        current = (data / ('owned-r2-' + 'b' * 32 + '_abcd')).as_uri()
        other = (data / ('other-r1-' + 'c' * 32 + '_abcd')).as_uri()
        outside = (tmp_path / (old.name + '_1234abcd')).as_uri()
        projects = [own, old.as_uri(), current, other, outside]
        seen = []
        delayed = 0

        async def request(method, params, timeout):
            nonlocal delayed, projects
            seen.append(params)
            if params['command'] == 'java.project.changeImportedProjects':
                assert params['arguments'] == [[], [], [own, old.as_uri()]]
                if not delayed:
                    delayed = 2
                return None
            if delayed:
                delayed -= 1
                if not delayed:
                    projects = [current, other, outside]
            return projects

        p.request = request
        await p._remove_java_revision_projects(old)
        assert old.exists()
        assert projects == [current, other, outside]
        assert 1 <= sum(x['command'] == 'java.project.changeImportedProjects' for x in seen) <= 4
    asyncio.run(run())


@pytest.mark.parametrize('malformed', [None, {}, [1]])
def test_invalid_server_project_list_fails_closed(tmp_path, malformed):
    async def run():
        p, old, _ = fixture(tmp_path)
        async def request(*args, **kwargs):
            return malformed
        p.request = request
        with pytest.raises(LspUnavailable, match='cleanup unconfirmed'):
            await p._remove_java_revision_projects(old)
        assert old.exists()
    asyncio.run(run())


def test_command_error_preserves_source_and_propagates_failure(tmp_path):
    async def run():
        p, old, data = fixture(tmp_path)
        async def request(method, params, timeout):
            if params['command'] == 'java.project.getAll':
                return [(data / (old.name + '_abcd')).as_uri()]
            raise LspUnavailable('server rejected command')
        p.request = request
        with pytest.raises(LspUnavailable, match='cleanup unconfirmed'):
            await p._remove_java_revision_projects(old)
        assert old.exists()
    asyncio.run(run())


def test_unknown_source_or_data_root_never_sends_delete(tmp_path):
    async def run():
        p, old, _ = fixture(tmp_path)
        async def request(*args, **kwargs):
            raise AssertionError('must reject before server request')
        p.request = request
        with pytest.raises(LspUnavailable, match='ownership mismatch'):
            await p._remove_java_revision_projects(tmp_path / 'foreign')
        p.command = ['jdtls', '-data', str(tmp_path / 'foreign-data')]
        with pytest.raises(LspUnavailable, match='data ownership mismatch'):
            await p._remove_java_revision_projects(old)
    asyncio.run(run())


def test_unconfirmed_cleanup_retires_process_instead_of_reusing_project(tmp_path):
    async def run():
        p, old, data = fixture(tmp_path)
        p.java_immutable_uri = True
        path = old / 'src' / 'Main.java'
        path.parent.mkdir()
        path.write_text('class Main {}')
        p._documents['owned'] = {'path': path}
        deletes = []
        async def request(method, params, timeout):
            if params['command'] == 'java.project.getAll':
                return [(data / (old.name + '_abcd')).as_uri()]
            deletes.append(params)
            return None
        p.request = request
        with pytest.raises(LspUnavailable, match='cleanup failed'):
            await p.close_document('owned')
        assert p.closed and not p._documents
        assert 1 <= len(deletes) <= 4
    asyncio.run(run())


def test_retirement_is_independent_of_cancelled_caller_and_close_drains(tmp_path):
    async def run():
        p, old, _ = fixture(tmp_path)
        entered, finish = asyncio.Event(), asyncio.Event()
        async def remove(directory):
            assert directory == old
            entered.set()
            await finish.wait()
        p._remove_java_revision_projects = remove
        await p._queue_java_retirement('owned', old)
        await entered.wait()
        job = p._java_retirements[old][1]
        async def waiter():
            await asyncio.shield(job)
        caller = asyncio.create_task(waiter())
        await asyncio.sleep(0)
        caller.cancel()
        await asyncio.gather(caller, return_exceptions=True)
        assert not job.cancelled() and old.exists()
        finish.set()
        await job
        assert not old.exists() and not p._java_retirements
        assert p._java_retirement_error is None
    asyncio.run(run())


def test_retirement_refuses_active_current_revision(tmp_path):
    async def run():
        p, old, _ = fixture(tmp_path)
        p._documents['owned'] = {'path': old / 'src' / 'Main.java'}
        await p._queue_java_retirement('owned', old)
        job = p._java_retirements[old][1]
        with pytest.raises(LspUnavailable, match='cleanup failed'):
            await job
        assert p._java_retirement_error is not None
        await asyncio.sleep(0)
    asyncio.run(run())


def test_next_workspace_transition_waits_for_pending_retirement(tmp_path):
    async def run():
        p, old, _ = fixture(tmp_path)
        entered, finish, switched = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def remove(directory):
            entered.set()
            await finish.wait()
        p._remove_java_revision_projects = remove
        await p._queue_java_retirement('owned', old)
        await entered.wait()
        async def next_transition():
            async with p._immutable_transition():
                assert not p._java_retirements and not old.exists()
                switched.set()
        task = asyncio.create_task(next_transition())
        await asyncio.sleep(0)
        assert not switched.is_set()
        finish.set()
        await task
        assert switched.is_set()
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['hold', 'release'])
@pytest.mark.parametrize('operation', ['completion', 'diagnostics'])
def test_pool_waits_for_native_retirements_before_every_analysis_mode(mode, operation):
    from ide_intelligence.config import load_config
    from ide_intelligence.shared_pool import SharedLanguagePool
    from tests.test_ide_pool import Store, session
    from tests.test_ide_shared_pool import SharedProcess

    class Guarded(SharedProcess):
        retired = False

        async def finish_java_retirements(self):
            await asyncio.sleep(.001)
            self.retired = True

        async def completion_for(self, *args):
            assert self.retired
            return await super().completion_for(*args)

        async def diagnostics_for(self, *args):
            assert self.retired
            return []

    async def run():
        pool = SharedLanguagePool(load_config(), process_factory=Guarded, diagnostics_mode=mode)
        try:
            result = await pool.execute(Store(), session(), operation, {'line': 1, 'column': 1}, 1000)
            assert result['status'] == 'ready'
        finally:
            await pool.close()
    asyncio.run(run())


def test_cleanup_evidence_retains_stages_without_server_messages_or_paths(tmp_path):
    import json

    async def run():
        p, old, data = fixture(tmp_path)
        secret = 'tenant-source-private-secret'

        async def request(method, params, timeout):
            if params['command'] == 'java.project.getAll':
                return [(data / (old.name + '_abcd')).as_uri()]
            raise LspUnavailable(secret)

        p.request = request
        with pytest.raises(LspUnavailable):
            await p._remove_java_revision_projects(old)
        evidence = p.java_cleanup_failure
        assert evidence['trace']['stage'] == 'delete-start'
        assert evidence['exceptionClasses'] == ['LspUnavailable']
        stages = [event['stage'] for event in evidence['trace']['events']]
        assert stages == ['ownership-check', 'getAll-start', 'getAll-return',
                          'getAll-matched', 'delete-start']
        encoded = json.dumps(evidence)
        assert secret not in encoded and str(tmp_path) not in encoded and old.name not in encoded
        p._record_java_cleanup_failure(ValueError('later failure'))
        assert p.java_cleanup_failure is evidence
    asyncio.run(run())


def test_private_failure_log_is_bounded_private_and_survives_slot_removal(tmp_path, monkeypatch):
    import shutil
    from ide_intelligence import lsp_process
    output = tmp_path / 'private-evidence'
    monkeypatch.setattr(lsp_process, '_JAVA_FAILURE_LOG_DIRECTORY', output)
    p, old, data = fixture(tmp_path / 'slot')
    log = data / '.metadata' / '.log'
    log.parent.mkdir(parents=True)
    log.write_bytes(b'x' * 200000)
    p._record_java_cleanup_failure(TimeoutError())
    saved = p.java_cleanup_failure['privateLog']
    assert saved['status'] == 'saved' and saved['bytes'] == 131072 and saved['truncated']
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output / saved['file']).stat().st_mode & 0o777 == 0o600
    shutil.rmtree(tmp_path / 'slot')
    assert (output / saved['file']).exists()
    for number in range(7):
        (output / str(number)).touch()
    assert p._preserve_java_failure_log()['status'] == 'retention-limit'


def test_private_failure_log_refuses_symlink_metadata(tmp_path, monkeypatch):
    from ide_intelligence import lsp_process
    monkeypatch.setattr(lsp_process, '_JAVA_FAILURE_LOG_DIRECTORY', tmp_path / 'private-evidence')
    p, old, data = fixture(tmp_path / 'slot')
    data.mkdir()
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    (foreign / '.log').write_text('private source')
    (data / '.metadata').symlink_to(foreign, target_is_directory=True)
    assert p._preserve_java_failure_log()['status'] == 'ownership-rejected'


def test_cleanup_evidence_has_bounded_ring_and_records_deleted_ack(tmp_path):
    async def run():
        p, old, data = fixture(tmp_path)
        projects = [(data / (old.name + '_abcd')).as_uri()]

        async def request(method, params, timeout):
            if params['command'] == 'java.project.getAll':
                return list(projects)
            await p._server_message({'method': 'language/eventNotification',
                'params': {'eventType': 210, 'data': list(projects)}})
            projects.clear()

        p.request = request
        await p._remove_java_revision_projects(old)
        assert any(row['stage'] == 'ProjectsDeleted-matched' for row in p._java_cleanup_trace['events'])
        for _ in range(1000):
            p._java_cleanup_event('synthetic-count', ownedCount=0)
        p._record_java_cleanup_failure(RuntimeError('private detail'))
        assert len(p.java_cleanup_failure['trace']['events']) == 64
        assert p.java_cleanup_failure['trace']['eventCount'] > 1000
    asyncio.run(run())


def test_pool_keeps_first_failure_after_workspace_disposal_and_replacement():
    from ide_intelligence.config import load_config
    from ide_intelligence.shared_pool import SharedLanguagePool
    from tests.test_ide_shared_pool import SharedProcess

    async def run():
        pool = SharedLanguagePool(load_config(), process_factory=SharedProcess)
        slot = pool._new_slot('java', 0)
        await slot.startup
        slot.process.java_cleanup_failure = {'exceptionClasses': ['TimeoutError'],
                                            'trace': {'stage': 'getAll-start'}}
        original = slot.root.name
        await pool._dispose(slot)
        assert not __import__('pathlib').Path(original).exists()
        pool.slots.pop(('java', 0))
        snapshot = pool.metrics_snapshot()['javaCleanupFailures']
        assert snapshot[0]['evidence']['trace']['stage'] == 'getAll-start'
        snapshot[0]['evidence']['trace']['stage'] = 'mutated'
        replacement = pool._new_slot('java', 0)
        await replacement.startup
        replacement.process.java_cleanup_failure = {'exceptionClasses': ['ValueError']}
        await pool._dispose(replacement)
        assert pool.metrics_snapshot()['javaCleanupFailures'][0]['evidence']['exceptionClasses'] == ['TimeoutError']
        await pool.close()
    asyncio.run(run())


@pytest.mark.parametrize('stalled,expected', [
    ('getAll', 'getAll-start'), ('delete', 'delete-start'), ('confirmation', 'getAll-start')])
def test_cleanup_failure_distinguishes_rpc_stage_and_preserves_timeout_chain(tmp_path, stalled, expected):
    async def run():
        p, old, data = fixture(tmp_path)
        get_count = 0

        async def request(method, params, timeout):
            nonlocal get_count
            get_all = params['command'] == 'java.project.getAll'
            if get_all:
                get_count += 1
            if (stalled == 'getAll' or stalled == 'delete' and not get_all
                    or stalled == 'confirmation' and get_count > 1):
                await asyncio.Event().wait()
            return [(data / (old.name + '_abcd')).as_uri()] if get_all else None

        p.request = request
        with pytest.raises(LspUnavailable):
            await p._remove_java_revision_projects(old)
        evidence = p.java_cleanup_failure
        assert evidence['trace']['stage'] == expected
        assert evidence['exceptionClasses'] == ['TimeoutError', 'CancelledError']
        stages = [row['stage'] for row in evidence['trace']['events']]
        assert ('delete-return' in stages) is (stalled == 'confirmation')
        assert evidence['trace']['seconds'] < 2.3
    asyncio.run(run())
