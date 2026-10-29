"""Materialize verified artifacts in the fresh runtime jail's executable tmpfs.

The source remains a read-only, noexec bind. No mount flag is relaxed. Invoke
only in the trusted namespace supervisor, before dropping adapter identity.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat


def materialize(source, destination, *, manifest_sha256, source_sha256,
                template_sha256, native_sha256):
    source, destination = Path(source), Path(destination)
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    root = os.open(source, flags | os.O_DIRECTORY)
    output = os.open(destination, flags | os.O_DIRECTORY)
    try:
        target_stat = os.fstat(output)
        if target_stat.st_uid != os.geteuid() or os.listdir(output):
            raise ValueError('Fresh owned runtime workspace required')
        descriptor = os.open('manifest.json', flags | os.O_NONBLOCK, dir_fd=root)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 131072:
                raise ValueError('Invalid runtime artifact manifest')
            raw = stream.read(131073)
        if hashlib.sha256(raw).hexdigest() != manifest_sha256:
            raise ValueError('Runtime artifact manifest changed')
        manifest = json.loads(raw)
        if (manifest.get('version') != 1 or manifest.get('sourceSha256') != source_sha256 or
                manifest.get('templateSha256') != template_sha256 or
                manifest.get('nativeSha256') != native_sha256):
            raise ValueError('Runtime artifact identity mismatch')
        rows = manifest['files']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
            raise ValueError('Invalid runtime artifact count')
        seen, directories, total = set(), set(), len(raw)
        for row in rows:
            relative = PurePosixPath(row['path'])
            if (not row['path'] or relative.is_absolute() or '..' in relative.parts or
                    relative.as_posix() != row['path'] or len(relative.parts) > 8 or
                    any(len(part.encode()) > 255 for part in relative.parts) or row['path'] in seen or
                    row['mode'] not in (0o444, 0o555) or type(row['size']) is not int or
                    not 0 <= row['size'] <= 20 * 1024**2):
                raise ValueError('Invalid runtime artifact entry')
            total += row['size']
            if total > 64 * 1024**2:
                raise ValueError('Runtime artifacts exceed workspace budget')
            seen.add(row['path'])
            current = os.dup(root)
            target_parent = os.dup(output)
            try:
                for index, part in enumerate(relative.parts[:-1]):
                    child = os.open(part, flags | os.O_DIRECTORY, dir_fd=current)
                    os.close(current)
                    current = child
                    try:
                        os.mkdir(part, 0o755, dir_fd=target_parent)
                    except FileExistsError:
                        pass
                    child = os.open(part, flags | os.O_DIRECTORY, dir_fd=target_parent)
                    os.close(target_parent)
                    target_parent = child
                    directories.add('/'.join(relative.parts[:index + 1]))
                descriptor = os.open(relative.name, flags | os.O_NONBLOCK, dir_fd=current)
                with os.fdopen(descriptor, 'rb') as incoming:
                    info = os.fstat(incoming.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                            info.st_size != row['size'] or stat.S_IMODE(info.st_mode) != row['mode']):
                        raise ValueError('Runtime artifact file changed')
                    copied = os.open(relative.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                     os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=target_parent)
                    with os.fdopen(copied, 'wb') as outgoing:
                        digest, size = hashlib.sha256(), 0
                        for block in iter(lambda: incoming.read(65536), b''):
                            size += len(block)
                            if size > row['size']:
                                raise ValueError('Runtime artifact grew')
                            digest.update(block)
                            outgoing.write(block)
                        if size != row['size'] or digest.hexdigest() != row['sha256']:
                            raise ValueError('Runtime artifact digest mismatch')
                        outgoing.flush()
                        os.fchmod(outgoing.fileno(), row['mode'])
                check = os.open(relative.name, flags | os.O_NONBLOCK, dir_fd=target_parent)
                with os.fdopen(check, 'rb') as installed:
                    info = os.fstat(installed.fileno())
                    digest = hashlib.sha256()
                    for block in iter(lambda: installed.read(65536), b''):
                        digest.update(block)
                    if (info.st_uid != os.geteuid() or info.st_nlink != 1 or
                            info.st_size != row['size'] or stat.S_IMODE(info.st_mode) != row['mode'] or
                            digest.hexdigest() != row['sha256']):
                        raise ValueError('Materialized runtime artifact changed')
            finally:
                os.close(current)
                os.close(target_parent)
        # Before the adapter is created, its nobody identity must be unable to
        # replace even read-only files by renaming through a writable directory.
        for name in sorted(directories, reverse=True):
            os.chmod(destination / name, 0o555)
        os.fchmod(output, 0o555)
        return manifest
    finally:
        os.close(output)
        os.close(root)
