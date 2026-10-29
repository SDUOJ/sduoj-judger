"""Freeze a quiescent compiler tree; no process launch or runtime integration.

Only a trusted controller may construct ArtifactContract and supply
confirm_drained. That callback must verify reaped compiler/namespace processes,
empty owned cgroups and closed control FDs, or raise. A browser boolean is not
an acceptable substitute. Candidate limits require profile/business review.
"""

import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
import re
import secrets
import stat
import sys


class ArtifactError(ValueError):
    pass


@dataclass(frozen=True)
class Limits:
    max_depth: int = 8
    max_files: int = 256
    max_bytes: int = 64 * 1024**2
    max_file_bytes: int = 20 * 1024**2

    def __post_init__(self):
        for value, ceiling in ((self.max_depth, 8), (self.max_files, 256),
                               (self.max_bytes, 64 * 1024**2),
                               (self.max_file_bytes, 20 * 1024**2)):
            if type(value) is not int or not 0 < value <= ceiling:
                raise ArtifactError("Invalid artifact limit")


@dataclass(frozen=True)
class ArtifactContract:
    language: str
    source_name: str
    source_sha256: str
    template_sha256: str
    native_sha256: str
    source_device: int
    source_inode: int
    compiler_uid: int
    python_cache_tag: str = ""
    limits: Limits = Limits()

    def __post_init__(self):
        extensions = {"c": ".c", "cpp": (".cc", ".cpp", ".cxx"),
                      "java": ".java", "python": ".py"}
        if (self.language not in extensions or
                not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.(?:c|cc|cpp|cxx|java|py)", self.source_name) or
                not self.source_name.endswith(extensions[self.language])):
            raise ArtifactError("Invalid trusted source identity")
        for digest in (self.source_sha256, self.template_sha256, self.native_sha256):
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise ArtifactError("Invalid trusted digest")
        if (any(type(v) is not int or v < 0 for v in
                (self.source_device, self.source_inode, self.compiler_uid)) or
                self.source_inode == 0 or not isinstance(self.limits, Limits)):
            raise ArtifactError("Invalid trusted filesystem identity")
        if self.language == "python" and not re.fullmatch(r"(?:cpython-[0-9]{2,3}|pypy[0-9]{2,3})", self.python_cache_tag):
            raise ArtifactError("Target Python cache tag required")
        if self.language != "python" and self.python_cache_tag:
            raise ArtifactError("Unexpected Python cache tag")


@dataclass(frozen=True)
class FrozenArtifacts:
    name: str
    manifest_json: bytes
    controller_receipt: tuple

    @property
    def manifest_sha256(self):
        return hashlib.sha256(self.manifest_json).hexdigest()


_LIBC = ctypes.CDLL(None, use_errno=True)
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def _xattrs(fd):
    """Use the descriptor even on macOS Python builds without os.listxattr."""
    function = _LIBC.flistxattr
    args = (fd, None, 0, 0) if sys.platform == "darwin" else (fd, None, 0)
    function.restype = ctypes.c_ssize_t
    length = function(*args)
    if length < 0:
        raise OSError(ctypes.get_errno(), "Cannot inspect descriptor xattrs")
    if length > 65536:
        raise ArtifactError("Oversized xattr list")
    if not length:
        return ()
    buffer = ctypes.create_string_buffer(length)
    args = (fd, buffer, length, 0) if sys.platform == "darwin" else (fd, buffer, length)
    actual = function(*args)
    if actual < 0 or actual > length:
        raise ArtifactError("Changed xattr list")
    return buffer.raw[:actual].split(b"\0")


def _fingerprint(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_nlink, st.st_uid,
            st.st_gid, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _safe_name(name):
    if (not isinstance(name, str) or name in ("", ".", "..") or
            "/" in name or "\0" in name or len(name.encode()) > 255):
        raise ArtifactError("Single relative component required")


def _parent(fd):
    st = os.fstat(fd)
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid() or
            stat.S_IMODE(st.st_mode) != 0o700):
        raise ArtifactError("Parent must be a worker-owned 0700 directory")


def _check_fd(fd, contract, directory):
    st = os.fstat(fd)
    if (st.st_dev != contract.source_device or
            st.st_uid not in (os.geteuid(), contract.compiler_uid) or
            st.st_mode & (stat.S_ISUID | stat.S_ISGID)):
        raise ArtifactError("Unapproved filesystem identity or mode")
    if (not (stat.S_ISDIR(st.st_mode) if directory else stat.S_ISREG(st.st_mode)) or
            not directory and st.st_nlink != 1):
        raise ArtifactError("Only directories and singly linked regular files allowed")
    if b"security.capability" in _xattrs(fd):
        raise ArtifactError("File capabilities forbidden")
    return st


def _allowed(path, contract, directory=False):
    if path == contract.source_name:
        return not directory
    parts = path.split("/")
    stem = contract.source_name.rsplit(".", 1)[0]
    if contract.language in ("c", "cpp"):
        return not directory and path == "main"
    if contract.language == "java":
        identifier = r"[A-Za-z_$][A-Za-z0-9_$]*"
        return (all(re.fullmatch(identifier, p) for p in parts) if directory else
                all(re.fullmatch(identifier, p) for p in parts[:-1]) and
                re.fullmatch(identifier + r"\.class", parts[-1]) is not None)
    if directory:
        return path == "__pycache__"
    return re.fullmatch(r"__pycache__/" + re.escape(stem + "." + contract.python_cache_tag) +
                        r"(?:\.opt-[012])?\.pyc", path) is not None


def _scan(fd, contract):
    result = {}
    files = total = entries = 0

    def visit(current, prefix, depth):
        nonlocal files, total, entries
        before = _fingerprint(_check_fd(current, contract, True))
        with os.scandir(current) as iterator:
            for entry in iterator:
                entries += 1
                if entries > contract.limits.max_files * (contract.limits.max_depth + 1):
                    raise ArtifactError("Too many tree entries")
                _safe_name(entry.name)
                path = prefix + entry.name
                observed = os.stat(entry.name, dir_fd=current, follow_symlinks=False)
                directory = stat.S_ISDIR(observed.st_mode)
                if (not directory and not stat.S_ISREG(observed.st_mode) or
                        not _allowed(path, contract, directory)):
                    raise ArtifactError("Unexpected artifact entry: " + path)
                if depth + 1 > contract.limits.max_depth:
                    raise ArtifactError("Artifact depth exceeded")
                child = os.open(entry.name, _DIRECTORY if directory else _FILE, dir_fd=current)
                try:
                    st = _check_fd(child, contract, directory)
                    if _fingerprint(st) != _fingerprint(observed):
                        raise ArtifactError("Artifact replaced during traversal")
                    result[path] = (directory, _fingerprint(st))
                    if directory:
                        visit(child, path + "/", depth + 1)
                    else:
                        files += 1
                        total += st.st_size
                        if (contract.language in ("c", "cpp") and path == "main" and
                                not st.st_mode & 0o111):
                            raise ArtifactError("Native entry must be executable")
                        if (files > contract.limits.max_files or st.st_size > contract.limits.max_file_bytes or
                                total > contract.limits.max_bytes):
                            raise ArtifactError("Artifact size or count exceeded")
                finally:
                    os.close(child)
        if _fingerprint(_check_fd(current, contract, True)) != before:
            raise ArtifactError("Directory changed during traversal")

    visit(fd, "", 0)
    if contract.source_name not in result:
        raise ArtifactError("Authorized source missing")
    required = ("main" if contract.language in ("c", "cpp") else
                contract.source_name[:-5] + ".class" if contract.language == "java" else None)
    if required and required not in result:
        raise ArtifactError("Entry artifact missing")
    return result


def _open_relative(root, path, *, directory=False):
    current = os.dup(root)
    try:
        parts = path.split("/")
        for part in parts[:-1]:
            child = os.open(part, _DIRECTORY, dir_fd=current)
            os.close(current)
            current = child
        return os.open(parts[-1], _DIRECTORY if directory else _FILE, dir_fd=current)
    finally:
        os.close(current)


def _remove_private(parent, name):
    fd = os.open(name, _DIRECTORY, dir_fd=parent)
    try:
        os.fchmod(fd, 0o700)
        for child in os.listdir(fd):
            st = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(st.st_mode):
                _remove_private(fd, child)
            else:
                os.unlink(child, dir_fd=fd)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent)


def _publish(parent, staging, destination):
    if sys.platform == "linux":
        function = getattr(_LIBC, "renameat2", None)
        flag = 1  # RENAME_NOREPLACE
        if function is None:
            # Original Ubuntu18 libc predates the wrapper. Keep the identical
            # kernel operation/flag; never fall back to replacing rename().
            number = {"aarch64": 276, "x86_64": 316}.get(os.uname().machine)
            if number is None:
                raise ArtifactError("Unreviewed renameat2 syscall architecture")
            result = _LIBC.syscall(ctypes.c_long(number), ctypes.c_int(parent),
                                   ctypes.c_char_p(os.fsencode(staging)), ctypes.c_int(parent),
                                   ctypes.c_char_p(os.fsencode(destination)), ctypes.c_uint(flag))
            if result != 0:
                raise OSError(ctypes.get_errno(), "Exclusive artifact publication failed")
            return
    elif sys.platform == "darwin":
        function = getattr(_LIBC, "renameatx_np", None)
        flag = 4  # RENAME_EXCL, sys/stdio.h
    else:
        function = None
    if function is None:
        raise ArtifactError("Exclusive atomic rename unavailable")
    if function(parent, os.fsencode(staging), parent, os.fsencode(destination), flag) != 0:
        raise OSError(ctypes.get_errno(), "Exclusive artifact publication failed")


def _verify_copy(root, records):
    for row in records:
        fd = _open_relative(root, row["path"])
        try:
            st = os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
                    st.st_uid != os.geteuid() or stat.S_IMODE(st.st_mode) != row["mode"] or
                    st.st_size != row["size"] or b"security.capability" in _xattrs(fd)):
                raise ArtifactError("Copied artifact identity changed")
            digest = hashlib.sha256()
            size = 0
            while True:
                data = os.read(fd, 65536)
                if not data:
                    break
                size += len(data)
                if size > row["size"]:
                    raise ArtifactError("Copied artifact grew")
                digest.update(data)
            if (size != row["size"] or digest.hexdigest() != row["sha256"] or
                    _fingerprint(os.fstat(fd)) != _fingerprint(st)):
                raise ArtifactError("Copied artifact digest changed")
        finally:
            os.close(fd)


def freeze_artifacts(source_parent_fd, source_name, destination_parent_fd, destination_name,
                     *, contract, confirm_drained):
    """Return only after complete atomic publication; failures leave no final tree.

    The final 0555 directory is staging for a read-only/noexec /artifacts bind;
    mode 0555 does not imply its host filesystem permits execution. Trusted
    runtime PID 1 must verify the manifest and copy into its bounded existing
    exec tmpfs /work, freeze that tree, then drop the adapter identity. Its host
    parent remains worker-owned 0700. Scratch must be a separate mount; the
    current runner must not write source/compile again.
    Compiler diagnostics must remain outside this strictly allowlisted tree.
    """
    _safe_name(source_name)
    _safe_name(destination_name)
    _parent(source_parent_fd)
    _parent(destination_parent_fd)
    if not isinstance(contract, ArtifactContract) or not callable(confirm_drained):
        raise ArtifactError("Trusted contract and drain verifier required")
    if confirm_drained() is not None:
        raise ArtifactError("Drain verifier must raise on failure, not accept a flag")
    root = os.open(source_name, _DIRECTORY, dir_fd=source_parent_fd)
    staging = None
    target = None
    try:
        st = _check_fd(root, contract, True)
        if (st.st_dev, st.st_ino) != (contract.source_device, contract.source_inode):
            raise ArtifactError("Source root identity changed")
        if _fingerprint(os.stat(source_name, dir_fd=source_parent_fd, follow_symlinks=False)) != _fingerprint(st):
            raise ArtifactError("Source root replaced")
        tree = _scan(root, contract)
        staging = ".compile-artifacts-" + secrets.token_hex(16)
        os.mkdir(staging, 0o700, dir_fd=destination_parent_fd)
        target = os.open(staging, _DIRECTORY, dir_fd=destination_parent_fd)
        records = []
        for path, (directory, expected) in sorted(tree.items()):
            if directory:
                os.mkdir(path, 0o700, dir_fd=target)
                continue
            source = _open_relative(root, path)
            destination = None
            try:
                if _fingerprint(_check_fd(source, contract, False)) != expected:
                    raise ArtifactError("Artifact changed before copy")
                destination = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                      0o600, dir_fd=target)
                digest = hashlib.sha256()
                size = 0
                while True:
                    data = os.read(source, 65536)
                    if not data:
                        break
                    size += len(data)
                    if size > expected[6] or size > contract.limits.max_file_bytes:
                        raise ArtifactError("Artifact grew during copy")
                    digest.update(data)
                    view = memoryview(data)
                    while view:
                        written = os.write(destination, view)
                        if written <= 0:
                            raise ArtifactError("Short artifact write")
                        view = view[written:]
                if size != expected[6] or _fingerprint(_check_fd(source, contract, False)) != expected:
                    raise ArtifactError("Artifact changed during copy")
                if path == contract.source_name and digest.hexdigest() != contract.source_sha256:
                    raise ArtifactError("Authorized source hash mismatch")
                mode = 0o555 if contract.language in ("c", "cpp") and path == "main" else 0o444
                os.fchmod(destination, mode)
                os.fsync(destination)
                records.append({"path": path, "size": size, "sha256": digest.hexdigest(), "mode": mode})
            finally:
                os.close(source)
                if destination is not None:
                    os.close(destination)
        if _scan(root, contract) != tree:
            raise ArtifactError("Compiler tree changed after copy")
        if confirm_drained() is not None:
            raise ArtifactError("Drain verifier must raise on failure")
        if _scan(root, contract) != tree:
            raise ArtifactError("Compiler tree changed at post-drain boundary")
        final_root = os.stat(source_name, dir_fd=source_parent_fd, follow_symlinks=False)
        if (final_root.st_dev, final_root.st_ino) != (contract.source_device, contract.source_inode):
            raise ArtifactError("Source root replaced after copy")
        manifest = json.dumps({"version": 1, "language": contract.language,
                               "sourceSha256": contract.source_sha256,
                               "templateSha256": contract.template_sha256,
                               "nativeSha256": contract.native_sha256, "files": records},
                              sort_keys=True, separators=(",", ":")).encode()
        if sum(row["size"] for row in records) + len(manifest) > contract.limits.max_bytes:
            raise ArtifactError("Manifest and artifacts exceed byte budget")
        fd = os.open("manifest.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=target)
        try:
            view = memoryview(manifest)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise ArtifactError("Short manifest write")
                view = view[written:]
            os.fchmod(fd, 0o444)
            os.fsync(fd)
        finally:
            os.close(fd)
        for path, (directory, _) in sorted(tree.items(), reverse=True):
            if directory:
                directory_fd = _open_relative(target, path, directory=True)
                try:
                    os.fchmod(directory_fd, 0o555)
                finally:
                    os.close(directory_fd)
        os.fchmod(target, 0o555)
        os.fsync(target)
        _verify_copy(target, records + [{"path": "manifest.json", "size": len(manifest),
                                        "sha256": hashlib.sha256(manifest).hexdigest(), "mode": 0o444}])
        _parent(destination_parent_fd)
        _publish(destination_parent_fd, staging, destination_name)
        staging = None
        return FrozenArtifacts(destination_name, manifest,
                               (contract.source_device, contract.source_inode, contract.compiler_uid))
    finally:
        os.close(root)
        if target is not None:
            os.close(target)
        if staging is not None:
            _remove_private(destination_parent_fd, staging)
