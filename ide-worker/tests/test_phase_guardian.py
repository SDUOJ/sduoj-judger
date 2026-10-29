"""Phase ownership failures; these doubles do not qualify native isolation."""
import hashlib
import json
import os
from pathlib import Path
import signal
from types import SimpleNamespace

import pytest

from ide_debug import phase_guardian as phases
from ide_debug.launcher import compile_config, nsjail_config, Sandbox
from ide_debug.config import Policy


def artifact(tmp_path, **changes):
    directory = tmp_path / 'artifacts'
    directory.mkdir()
    wire = dict(code='int main(void){return 0;}', language='c', templateSha256='a' * 64,
                compileSandboxSha256='b' * 64)
    manifest = dict(sourceSha256=hashlib.sha256(wire['code'].encode()).hexdigest(),
                    templateSha256=wire['templateSha256'], nativeSha256=wire['compileSandboxSha256'],
                    language='c', version=1, files=[])
    manifest.update(changes)
    raw = json.dumps(manifest).encode()
    (directory / 'manifest.json').write_bytes(raw)
    return {'export': str(tmp_path), 'wire': wire}, hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('field', ['sourceSha256', 'templateSha256', 'nativeSha256', 'language'])
def test_handoff_rejects_cross_source_template_binary_or_language(tmp_path, field):
    spec, digest = artifact(tmp_path, **{field: 'changed'})
    with pytest.raises(ValueError, match='identity'):
        phases.prepared_wire(spec, digest)


def test_handoff_binds_exact_manifest_before_runtime(tmp_path):
    spec, digest = artifact(tmp_path)
    value = phases.prepared_wire(spec, digest)
    assert value['preparedArtifactSha256'] == digest
    (tmp_path / 'artifacts/manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='changed'):
        phases.prepared_wire(spec, digest)


def test_runtime_is_not_started_on_compile_failure_or_missing_handoff():
    guardian = phases.Guardian.__new__(phases.Guardian)
    guardian.phase, guardian.prepared, guardian.output_eof = 'compile', None, True
    for status in (0, 256):
        with pytest.raises(RuntimeError, match='did not complete'):
            guardian.transition(status)


def test_native_leaf_remaining_blocks_handoff_before_any_migration(tmp_path, monkeypatch):
    guardian = phases.Guardian.__new__(phases.Guardian)
    root = tmp_path / 'session'
    guardian.phase = 'compile'
    guardian.child, guardian.pinned = 1234, {1234: 9876}
    signals = []
    monkeypatch.setattr(phases, 'send_pidfd', lambda fd, sig: signals.append((fd, sig)))
    monkeypatch.setattr(phases.os, 'waitpid', lambda pid, flags:
                        (pid, (int(signal.SIGSTOP) << 8) | 0x7f))
    guardian.domain = SimpleNamespace(root=root, nodes=lambda branch:
        [root / 'compile', root / 'compile/control', root / 'compile/sduoj-2-123'])
    with pytest.raises(RuntimeError, match='has not been removed'):
        guardian.handoff()
    assert signals == [(9876, signal.SIGSTOP)]


def test_unowned_supervisor_is_never_pinned_or_signalled(tmp_path, monkeypatch):
    guardian = phases.Guardian.__new__(phases.Guardian)
    root = tmp_path / 'session'
    control = root / 'compile/control'
    control.mkdir(parents=True)
    (control / 'cgroup.procs').write_text('1234\n5678\n')
    guardian.phase = 'compile'
    guardian.child, guardian.pinned = 1234, {1234: 9876}
    guardian.domain = SimpleNamespace(root=root, nodes=lambda branch: [root / 'compile', control])
    guardian.owns_supervisor = lambda pid, group: False
    signals = []
    monkeypatch.setattr(phases, 'send_pidfd', lambda fd, sig: signals.append((fd, sig)))
    monkeypatch.setattr(phases.os, 'waitpid', lambda pid, flags:
                        (pid, (int(signal.SIGSTOP) << 8) | 0x7f))
    monkeypatch.setattr(phases, 'open_pidfd', lambda pid: pytest.fail('Unowned supervisor must not be pinned'))
    with pytest.raises(RuntimeError, match='Unexpected compile phase processes'):
        guardian.handoff()
    assert signals == [(9876, signal.SIGSTOP)]


def test_cleanup_kills_exact_launcher_even_if_namespace_was_never_created(monkeypatch):
    guardian = phases.Guardian.__new__(phases.Guardian)
    guardian.child, guardian.pinned = 1234, {1234: 9876}
    guardian.input_fd = guardian.output_fd = None
    calls = []
    guardian.domain = SimpleNamespace(root=SimpleNamespace(exists=lambda: True),
                                      remove=lambda: calls.append('domain-drained'))
    monkeypatch.setattr(phases, 'send_pidfd', lambda fd, sig: calls.append((fd, sig)))
    monkeypatch.setattr(phases.os, 'waitpid', lambda pid, flags: calls.append(('reap', pid)))
    monkeypatch.setattr(phases.os, 'close', lambda fd: calls.append(('close', fd)))
    guardian.cleanup()
    assert calls == [(9876, signal.SIGKILL), 'domain-drained', ('reap', 1234), ('close', 9876)]


def test_unconfirmed_pidfd_cannot_report_cleanup_success():
    guardian = phases.Guardian.__new__(phases.Guardian)
    guardian.child, guardian.pinned = 1234, {}
    with pytest.raises(RuntimeError, match='pidfd acquisition'):
        guardian.cleanup()


def test_cleanup_removes_frozen_tree_without_following_foreign_symlink(tmp_path):
    session = tmp_path / 'session'
    frozen = session / 'export/artifacts'
    frozen.mkdir(parents=True)
    (frozen / 'main').write_bytes(b'frozen artifact')
    (frozen / 'main').chmod(0o444)
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    (foreign / 'keep').write_text('not part of the session')
    (session / 'alias').symlink_to(foreign, target_is_directory=True)
    frozen.chmod(0o555)
    sandbox = Sandbox.__new__(Sandbox)
    sandbox.directory = session
    assert sandbox.remove_directory()
    assert not session.exists() and (foreign / 'keep').read_text() == 'not part of the session'


def test_compile_and_runtime_setup_keep_distinct_mounts_policies_and_capabilities(monkeypatch):
    for name in ('getuid', 'geteuid', 'getgid', 'getegid'):
        monkeypatch.setattr('ide_debug.launcher.os.' + name, lambda: 10001)
    profile = SimpleNamespace(rootfs='/rootfs', tmpfs=64 * 1024**2,
        artifact_max_bytes=64 * 1024**2, compile_seconds=20,
        compile_seccomp='/compile.policy', seccomp='/runtime.policy',
        python='/python', runner='/opt/sduoj-debug/ide_debug/runner.py')
    policy = Policy(cgroup_version=2, subuid=100000, subgid=100000)
    compile = compile_config(profile, policy, '/private/session/export', '/cgroup/session/compile')
    runtime = nsjail_config(profile, policy, '/private/session/export/artifacts')
    assert 'CAP_SYS_ADMIN' in compile and 'CAP_SYS_ADMIN' not in runtime
    assert 'disable_no_new_privs: true' in compile
    assert 'seccomp_policy_file: "/compile.policy"' in compile
    assert 'ide_debug.compile_phase' in compile
    assert 'dst: "/compile-cgroup"' in compile and 'dst: "/compile-cgroup"' not in runtime
    assert 'seccomp_policy_file: "/runtime.policy"' in runtime
    assert 'arg: "--prepared-artifacts"' in runtime
    assert 'dst: "/artifacts" is_bind: true rw: false nosuid: true nodev: true noexec: true' in runtime
