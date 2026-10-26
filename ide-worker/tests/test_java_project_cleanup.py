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
        with pytest.raises(LspUnavailable, match='cleanup unconfirmed'):
            await p.close_document('owned')
        assert p.closed and not p._documents
        assert len(deletes) == 4
    asyncio.run(run())
