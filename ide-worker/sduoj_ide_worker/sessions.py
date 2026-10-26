"""Read-only execution view of Gateway-owned source/session snapshots."""
import json
import time
import os
from pathlib import Path
from ide_intelligence.session_store import Session, SessionMissing
from ide_intelligence.toolchain import parse_template, require_runtime
from .protocol import key


class ExecutionSessions:
    def __init__(self, redis):
        self.client = redis

    async def redis(self):
        return self.client

    @staticmethod
    def session_key(session_id):
        return key('session', session_id)

    async def metadata(self, session_id, owner_id, epoch=None):
        raw = await self.client.get(self.session_key(session_id))
        if not raw:
            raise SessionMissing()
        value = json.loads(raw)
        if value.get('ownerId') != str(owner_id) or (epoch and value.get('sessionEpoch') != epoch):
            raise SessionMissing()
        return value

    async def get(self, session_id, owner_id, refresh=False):
        value = await self.metadata(session_id, owner_id)
        template = value.get('template')
        profile = parse_template(template, value['language'], str(template['id'])) if template else None
        if profile and profile['language'] in {'c', 'cpp'}:
            root = Path(os.environ.get('SDUOJ_JUDGE_ROOTFS', '/opt/judge-rootfs'))
            if root.is_dir():
                # clangd reads Judger's standard headers; it never executes the driver.
                flags = list(profile['analysisFlags'])
                flags += ['--sysroot=' + str(root)]
                compiler = root / profile['compiler'].lstrip('/')
                target = os.readlink(compiler) if compiler.is_symlink() else compiler.name
                major = target.rsplit('-', 1)[-1]
                if major.isdigit():
                    candidates = list(root.glob('usr/lib/gcc/*/' + major + '/include'))
                    if profile['language'] == 'cpp':
                        candidates = [root / 'usr/include/c++' / major,
                                      *root.glob('usr/include/*/c++/' + major), *candidates]
                    for directory in candidates:
                        if directory.is_dir():
                            flags += ['-isystem', str(directory)]
                profile['analysisFlags'] = flags
        require_runtime(profile)
        ttl = await self.client.ttl(self.session_key(session_id))
        if ttl <= 0:
            raise SessionMissing()
        return Session(session_id, int(owner_id), value.get('clientHash', ''), value['language'],
                       value.get('contextHash', ''), value['documentName'], value['documentUri'],
                       value['revision'], value['code'], int(time.time() * 1000) + ttl * 1000, profile)
