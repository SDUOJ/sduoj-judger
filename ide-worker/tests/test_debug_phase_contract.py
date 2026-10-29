"""Admission and file identity contracts; no native isolation credit."""
import asyncio
from dataclasses import replace
import hashlib
import json
import os

import pytest

from ide_debug.profiles import DebugError, load_manifest, verify_compile_policy
from tests.test_debug_runtime import Runtime, Store, Sandbox, policy, manifest, ROW, body, GiB, MiB


@pytest.mark.parametrize('mode', ['v1', 'budget', 'hard'])
def test_invalid_phase_budget_rejects_before_claim_or_spawn(mode):
    async def check():
        config = policy()
        if mode == 'v1':
            config = replace(config, cgroup_version=1)
        elif mode == 'budget':
            config = replace(config, budget=512 * MiB)
        else:
            config = replace(config, budget=512 * MiB, hard=560 * MiB)
        store = Store()
        class ForbiddenSandbox(Sandbox):
            def __init__(self, *args):
                pytest.fail('Invalid grant must not start a sandbox')
        runtime = Runtime(config, store, manifest(), ForbiddenSandbox, lambda: 100 * GiB)
        await runtime.start()
        try:
            with pytest.raises(DebugError, match='PHASE_BUDGET_INVALID'):
                await runtime.create(7, body(), ROW)
            assert not store.users and not store.specs and not runtime.sessions
        finally:
            await runtime.close()
    asyncio.run(check())


def installed_manifest(tmp_path):
    root = tmp_path / 'rootfs'
    (root / 'usr/bin').mkdir(parents=True)
    sandbox = root / 'usr/bin/sandbox'
    sandbox.write_bytes(b'fixture native identity; never executed')
    native_hash = hashlib.sha256(sandbox.read_bytes()).hexdigest()
    setup, runtime = tmp_path / 'compile.policy', tmp_path / 'runtime.policy'
    setup.write_text('fixture compile policy; never installed')
    runtime.write_text('fixture runtime policy; never installed')
    setup_hash = hashlib.sha256(setup.read_bytes()).hexdigest()
    entry = manifest()['19']
    entry.update(rootfs=str(root), seccomp=str(runtime), compile_seccomp=str(setup),
                 compile_policy_sha256=setup_hash, compile_sandbox_sha256=native_hash)
    identity = {'artifactDigest': entry['artifact_digest'], 'sandboxSha256': native_hash,
                'compilePolicySha256': setup_hash, 'templates': {'19': {
                    'templateVersion': entry['templateVersion'], 'templateHash': entry['templateHash'],
                    'compilePathEnv': entry['compile_path_env']}}}
    (root / '.sduoj-debug-toolchain.json').write_text(json.dumps(identity))
    filename = tmp_path / 'profiles.json'
    filename.write_text(json.dumps({'19': entry}))
    return filename, setup


def test_load_manifest_binds_actual_compile_policy_and_stamp(tmp_path):
    filename, setup = installed_manifest(tmp_path)
    assert load_manifest(filename)['19']['verified']
    setup.write_text('changed permissions contract')
    with pytest.raises(DebugError, match='POLICY_NOT_VERIFIED'):
        load_manifest(filename)
    data = json.loads(filename.read_text())
    data['19']['compile_policy_sha256'] = hashlib.sha256(setup.read_bytes()).hexdigest()
    filename.write_text(json.dumps(data))
    with pytest.raises(DebugError, match='ARTIFACT_IDENTITY'):
        load_manifest(filename)


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'writable', 'oversized'])
def test_policy_rejects_unsafe_files_without_blocking(tmp_path, kind):
    target = tmp_path / 'compile.policy'
    digest = hashlib.sha256(b'policy').hexdigest()
    if kind == 'symlink':
        other = tmp_path / 'other'
        other.write_bytes(b'policy')
        target.symlink_to(other)
    elif kind == 'fifo':
        os.mkfifo(target)
    else:
        target.write_bytes(b'x' * 65537 if kind == 'oversized' else b'policy')
        if kind == 'writable':
            target.chmod(0o666)
    with pytest.raises(DebugError, match='POLICY_NOT_VERIFIED'):
        verify_compile_policy(target, digest)
