#!/usr/bin/env python3
"""Inventory build-stage runtime bytes without following image-absolute links."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


def inventory(root):
    root = Path(root)
    records = []
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = Path(directory) / name
            info = path.lstat()
            item = {'path': path.relative_to(root).as_posix(),
                    'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
            if stat.S_ISLNK(info.st_mode):
                item.update(kind='symlink', target=os.readlink(path))
            elif stat.S_ISDIR(info.st_mode):
                item['kind'] = 'directory'
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for data in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(data)
                item.update(kind='file', size=info.st_size, sha256=digest.hexdigest())
            else:
                raise ValueError('Runtime inventory cannot contain special files')
            records.append(item)
    return {'schemaVersion': 1, 'scope': 'build-stage-runtime-inventory-not-image-digest',
            'files': sorted(records, key=lambda item: item['path'])}


if __name__ == '__main__':
    print(json.dumps(inventory(sys.argv[1]), sort_keys=True, separators=(',', ':')))
