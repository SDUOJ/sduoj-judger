#!/usr/bin/env python3
"""Offline image derivation. Profiles remain disabled pending explicit acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, '/opt/sduoj-ide')
from ide_debug.profiles import sandbox_binary, phase_startup_budget
from ide_debug.judge_compile import CompileLimits
from ide_intelligence.toolchain import parse_template


def artifact_digest(judge_image, overlay, sandbox_sha):
    return 'sha256:' + hashlib.sha256(json.dumps({
        'judgeImage': judge_image, 'overlay': overlay, 'sandboxSha256': sandbox_sha,
    }, sort_keys=True).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--judge-image')
    identity.add_argument('--runtime-inventory')
    args = parser.parse_args()
    if args.runtime_inventory:
        raw_inventory = Path(args.runtime_inventory).read_bytes()
        inventory = json.loads(raw_inventory)
        if (inventory.get('schemaVersion') != 1 or
                inventory.get('scope') != 'build-stage-runtime-inventory-not-image-digest' or
                not inventory.get('files')):
            raise ValueError('Build-stage runtime inventory required')
        runtime_identity = 'sha256:' + hashlib.sha256(raw_inventory).hexdigest()
    elif not (args.judge_image.startswith('sha256:') or '@sha256:' in args.judge_image):
        raise ValueError('Immutable Judger image is required')
    else:
        runtime_identity = args.judge_image
    root = Path('/opt/judge-rootfs')
    # Image layers omit Docker's runtime-only /work mount point. NsJail must
    # find it before mounting the per-session tmpfs over a read-only rootfs.
    (root / 'work').mkdir(mode=0o755, exist_ok=True)
    sandbox = sandbox_binary(root)
    sandbox_sha = hashlib.sha256(sandbox.read_bytes()).hexdigest()
    overlay = root / 'opt/sduoj-debug'
    files = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(overlay.rglob('*')) if path.is_file() and path.suffix in ('.py', '.class')}
    # A native supervisor overlay must change the artifact identity even when
    # compiler versions, template hashes and Python adapters stay identical.
    artifact = artifact_digest(runtime_identity, files, sandbox_sha)
    compile_path = '/opt/java/openjdk17/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    compile_policy = Path('/opt/sduoj-ide/compile.policy')
    compile_policy_sha = hashlib.sha256(compile_policy.read_bytes()).hexdigest()
    profiles, identities = {}, {}
    rows = json.loads(Path('/opt/sduoj-ide/toolchain-templates.json').read_text())
    for template_id, language in [('19', 'c'), ('32', 'cpp'), ('38', 'python'), ('51', 'java')]:
        row = next(row for row in rows if row['id'] == template_id)
        analysis = parse_template(row, language, template_id)
        runtime_startup = (1024 if language == 'java' else 384) * 1024**2
        artifact_max_bytes = compile_setup_bytes = 64 * 1024**2
        startup = phase_startup_budget(runtime_startup, CompileLimits.template(row).memory_bytes,
                                       artifact_max_bytes=artifact_max_bytes,
                                       compile_setup_bytes=compile_setup_bytes)
        identities[template_id] = {'templateVersion': row['version'], 'templateHash': analysis['templateHash'],
                                   'compilePathEnv': compile_path}
        profiles[template_id] = dict(identities[template_id], language=language, verified=False,
            rootfs=str(root), artifact_digest=artifact, runner='/opt/sduoj-debug/ide_debug/runner.py',
            python='/opt/python/3.11/bin/python',
            debugger=([analysis['javaHome'] + '/bin/java', '-Xms16m', '-Xmx64m',
                       '-XX:ReservedCodeCacheSize=32m', '-XX:CompressedClassSpaceSize=32m',
                       '-cp', '/opt/sduoj-debug/bridge', 'DebugBridge'] if language == 'java' else
                      ['/opt/python/3.11/bin/python'] if language == 'python' else
                      ['/usr/bin/env', 'PYTHONHOME=/opt/sduoj-debug/gdb-runtime/usr',
                       '/opt/sduoj-debug/gdb-runtime/lib/ld-linux-aarch64.so.1', '--library-path',
                       '/opt/sduoj-debug/gdb-runtime/lib', '/opt/sduoj-debug/gdb-runtime/gdb',
                       '--data-directory=/opt/sduoj-debug/gdb-runtime/share/gdb']),
            hard=(768 if language == 'java' else 256) * 1024**2,
            startup=startup, runtime_startup=runtime_startup,
            artifact_max_bytes=artifact_max_bytes, compile_setup_bytes=compile_setup_bytes,
            compile_seccomp=str(compile_policy), compile_policy_sha256=compile_policy_sha,
            floor=(128 if language == 'java' else 64) * 1024**2,
            margin=16 * 1024**2, pids=192 if language == 'java' else 64,
            cpu_seconds=30, compile_seconds=30, active=1, starting=1,
            seccomp='/opt/sduoj-ide/debug.policy', tmpfs=64 * 1024**2,
            java_options=['-Xms16m', '-Xmx128m', '-XX:ReservedCodeCacheSize=32m', '-XX:CompressedClassSpaceSize=32m'],
            compile_sandbox_sha256=sandbox_sha, compile_path_env=compile_path)
        profiles[template_id].pop('compilePathEnv')
    inventory = json.dumps(files, sort_keys=True).encode()
    inventory_path = '/opt/sduoj-ide/debug-overlay-inventory.json'
    Path(inventory_path).write_bytes(inventory)
    stamp = dict(artifactDigest=artifact, sandboxSha256=sandbox_sha,
                 compilePolicySha256=compile_policy_sha, templates=identities,
                 overlayManifest=inventory_path,
                 overlaySha256=hashlib.sha256(inventory).hexdigest(), acceptance='pending')
    if args.runtime_inventory:
        stamp.update(runtimeInventory=args.runtime_inventory,
                     runtimeInventorySha256=runtime_identity.removeprefix('sha256:'))
    else:
        stamp['judgeImage'] = args.judge_image
    source = Path('/opt/sduoj-ide/compile-sandbox-source.json')
    if source.exists():
        stamp['sandboxSourceManifestSha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
        stamp['sandboxScope'] = 'debug-compile-supervisor-overlay'
    (root / '.sduoj-debug-toolchain.json').write_text(json.dumps(stamp, sort_keys=True))
    Path('/opt/sduoj-ide/debug-profiles.json').write_text(json.dumps(profiles, sort_keys=True))


if __name__ == '__main__':
    main()
