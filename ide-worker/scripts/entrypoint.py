#!/usr/bin/env python3
"""Normal workers are unprivileged. Explicit dev lab bootstrap stays container-local."""
import json
import os
from pathlib import Path


def dev_debug_lab():
    if os.getuid() != 0 or os.getenv('SDUOJ_IDE_DEV_DEBUG_LAB') != '1':
        raise RuntimeError('Explicit container-only debug lab bootstrap required')
    root = Path('/sys/fs/cgroup')
    if not (root / 'cgroup.controllers').exists():
        raise RuntimeError('The local Docker lab requires cgroup v2')
    supervisor = root / 'ide-supervisor'
    supervisor.mkdir(exist_ok=True)
    for pid in (root / 'cgroup.procs').read_text().split():
        try:
            (supervisor / 'cgroup.procs').write_text(pid)
        except ProcessLookupError:
            pass
    (root / 'cgroup.subtree_control').write_text('+memory +cpu +pids')
    # v2 migration checks write permission on the common ancestor as well as
    # the destination. This is the private container cgroup namespace root;
    # never delegate the host root this way in a production deployment.
    os.chown(root / 'cgroup.procs', 10001, 10001)
    parent = root / os.environ['AUTOLAB_DEBUG_CGROUP_PARENT']
    parent.mkdir(exist_ok=True)
    (parent / 'memory.max').write_text(os.environ['AUTOLAB_DEBUG_HARD'])
    (parent / 'cpu.max').write_text('100000 100000')
    (parent / 'pids.max').write_text('512')
    (parent / 'cgroup.subtree_control').write_text('+memory +cpu +pids')
    os.chown(parent, 10001, 10001)
    for name in ('cgroup.procs', 'cgroup.threads', 'cgroup.subtree_control'):
        path = parent / name
        if path.exists():
            os.chown(path, 10001, 10001)
    state = Path(os.environ['AUTOLAB_DEBUG_STATE_DIR'])
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chown(state, 10001, 10001)
    path = Path('/opt/sduoj-ide/debug-profiles.json')
    profiles = json.loads(path.read_text())
    for profile in profiles.values():
        profile['verified'] = True
        profile['acceptanceScope'] = 'local-dev-correctness-only'
    # Rootfs/image remain read-only in normal deployment. Only this explicit
    # throwaway dev profile writes a local acceptance copy on tmpfs.
    accepted = Path('/run/ide-dev-profiles.json')
    accepted.write_text(json.dumps(profiles))
    accepted.chmod(0o644)
    os.environ['AUTOLAB_DEBUG_MANIFEST'] = str(accepted)
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)


if __name__ == '__main__':
    from sduoj_ide_worker.__main__ import main
    # Fetch config once per process, before dev setup consumes its quotas and
    # before Worker modules capture Redis prefixes or construct clients.
    main(prepare=dev_debug_lab if os.getenv('SDUOJ_IDE_DEV_DEBUG_LAB') == '1' else None)
