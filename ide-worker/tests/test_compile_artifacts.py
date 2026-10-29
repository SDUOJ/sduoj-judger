"""Filesystem handoff tests only; no compiler, namespace or business credit."""

import ctypes
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys

import pytest

from ide_debug import compile_artifacts as artifacts


@pytest.fixture
def tree(tmp_path):
    source_parent = tmp_path / "compiler-private"
    destination_parent = tmp_path / "worker-private"
    source_parent.mkdir(mode=0o700)
    destination_parent.mkdir(mode=0o700)
    source = source_parent / "compile"
    source.mkdir(mode=0o700)
    (source / "main.c").write_bytes(b"int main(void){return 0;}\n")
    (source / "main").write_bytes(b"executable fixture, not run")
    (source / "main").chmod(0o755)
    parent_fd = os.open(source_parent, artifacts._DIRECTORY)
    destination_fd = os.open(destination_parent, artifacts._DIRECTORY)
    st = source.stat()
    contract = artifacts.ArtifactContract("c", "main.c", hashlib.sha256((source / "main.c").read_bytes()).hexdigest(),
                                          "a" * 64, "b" * 64, st.st_dev, st.st_ino, os.geteuid())
    try:
        yield source, destination_parent, parent_fd, destination_fd, contract
    finally:
        os.close(parent_fd)
        os.close(destination_fd)


def freeze(tree, **updates):
    source, _, parent, destination, contract = tree
    return artifacts.freeze_artifacts(parent, "compile", destination, "frozen",
                                      contract=replace(contract, **updates), confirm_drained=lambda: None)


def assert_unpublished(tree):
    assert list(tree[1].iterdir()) == []


def test_cpp_artifacts_are_fresh_readonly_and_manifest_binds_identities(tree):
    source, parent, _, _, contract = tree
    confirmations = []
    result = artifacts.freeze_artifacts(tree[2], "compile", tree[3], "frozen", contract=contract,
                                        confirm_drained=lambda: confirmations.append("checked"))
    destination = parent / result.name
    manifest = json.loads(result.manifest_json)
    assert confirmations == ["checked", "checked"]
    assert manifest["sourceSha256"] == contract.source_sha256
    assert manifest["templateSha256"] == contract.template_sha256
    assert manifest["nativeSha256"] == contract.native_sha256
    assert str(source) not in result.manifest_json.decode()
    assert "uid" not in result.manifest_json.decode()
    assert (destination / "manifest.json").read_bytes() == result.manifest_json
    assert stat.S_IMODE(destination.stat().st_mode) == 0o555
    for row in manifest["files"]:
        output = destination / row["path"]
        assert output.read_bytes() == (source / row["path"]).read_bytes()
        assert output.stat().st_ino != (source / row["path"]).stat().st_ino
        assert stat.S_IMODE(output.stat().st_mode) == (0o555 if row["path"] == "main" else 0o444)
        assert hashlib.sha256(output.read_bytes()).hexdigest() == row["sha256"]
    (source / "main").write_bytes(b"post-freeze mutation")
    assert (destination / "main").read_bytes() != (source / "main").read_bytes()


def test_java_trusted_entry_name_inner_classes_and_package_tree(tree):
    source = tree[0]
    (source / "main").unlink()
    (source / "main.c").unlink()
    (source / "Solution.java").write_bytes(b"class Solution {}")
    (source / "Solution.class").write_bytes(b"class bytes")
    (source / "Solution$1.class").write_bytes(b"inner bytes")
    (source / "pkg").mkdir()
    (source / "pkg/Helper.class").write_bytes(b"nested bytes")
    result = freeze(tree, language="java", source_name="Solution.java",
                    source_sha256=hashlib.sha256((source / "Solution.java").read_bytes()).hexdigest())
    assert {row["path"] for row in json.loads(result.manifest_json)["files"]} == {
        "Solution.java", "Solution.class", "Solution$1.class", "pkg/Helper.class"}
    assert stat.S_IMODE((tree[1] / "frozen/pkg").stat().st_mode) == 0o555


@pytest.mark.parametrize("cached", [False, True])
def test_python_only_authorized_source_and_target_cache_tag(tree, cached):
    source = tree[0]
    (source / "main").unlink()
    (source / "main.c").unlink()
    (source / "main.py").write_bytes(b"print(1)\n")
    if cached:
        (source / "__pycache__").mkdir()
        (source / "__pycache__/main.cpython-311.pyc").write_bytes(b"cache bytes")
    result = freeze(tree, language="python", source_name="main.py", python_cache_tag="cpython-311",
                    source_sha256=hashlib.sha256((source / "main.py").read_bytes()).hexdigest())
    assert len(json.loads(result.manifest_json)["files"]) == (2 if cached else 1)


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo", "socket", "suid", "sgid", "unknown"])
def test_special_links_modes_and_unknown_files_are_rejected(tree, kind):
    source = tree[0]
    if kind in ("suid", "sgid"):
        (source / "main").chmod(0o4755 if kind == "suid" else 0o2755)
    else:
        (source / "main").unlink()
        if kind == "symlink":
            (source / "main").symlink_to(source / "main.c")
        elif kind == "hardlink":
            os.link(source / "main.c", source / "main")
        elif kind == "fifo":
            os.mkfifo(source / "main")
        elif kind == "socket":
            channel = socket.socket(socket.AF_UNIX)
            previous = os.open(".", artifacts._DIRECTORY)
            try:
                os.chdir(source)
                channel.bind("main")
            finally:
                os.fchdir(previous)
                os.close(previous)
                channel.close()
        else:
            (source / "main").write_bytes(b"exe")
            (source / "secret.txt").write_bytes(b"secret")
    with pytest.raises((artifacts.ArtifactError, OSError)):
        freeze(tree)
    assert_unpublished(tree)


def test_actual_security_capability_xattr_is_rejected(tree):
    fd = os.open(tree[0] / "main", os.O_RDWR)
    capability = struct.pack("<IIIII", 0x02000001, 1, 0, 0, 0)
    data = ctypes.create_string_buffer(capability)
    function = ctypes.CDLL(None, use_errno=True).fsetxattr
    args = (fd, b"security.capability", data, len(capability), 0, 0) if sys.platform == "darwin" else (
        fd, b"security.capability", data, len(capability), 0)
    try:
        assert function(*args) == 0, os.strerror(ctypes.get_errno())
        assert b"security.capability" in artifacts._xattrs(fd)
    finally:
        os.close(fd)
    with pytest.raises(artifacts.ArtifactError, match="capabilities"):
        freeze(tree)
    assert_unpublished(tree)


@pytest.mark.skipif(sys.platform != "linux" or os.geteuid() != 0,
                    reason="Actual device node test requires disposable Linux root with only MKNOD capability")
def test_actual_device_node_is_rejected(tree):
    (tree[0] / "main").unlink()
    os.mknod(tree[0] / "main", stat.S_IFCHR | 0o600, os.makedev(1, 3))
    with pytest.raises(artifacts.ArtifactError, match="Unexpected"):
        freeze(tree)
    assert_unpublished(tree)


def test_native_entry_without_execute_permission_is_rejected(tree):
    (tree[0] / "main").chmod(0o644)
    with pytest.raises(artifacts.ArtifactError, match="executable"):
        freeze(tree)
    assert_unpublished(tree)


def test_nested_symlink_is_never_traversed(tree):
    source = tree[0]
    (source / "main").unlink()
    (source / "main.c").unlink()
    (source / "Main.java").write_text("class Main {}")
    (source / "Main.class").write_bytes(b"class")
    (source / "pkg").symlink_to(tree[1], target_is_directory=True)
    with pytest.raises(artifacts.ArtifactError):
        freeze(tree, language="java", source_name="Main.java",
               source_sha256=hashlib.sha256((source / "Main.java").read_bytes()).hexdigest())
    assert_unpublished(tree)


@pytest.mark.parametrize("limit", ["file", "total", "count", "depth"])
def test_bounded_file_total_count_and_depth(tree, limit):
    limits = artifacts.Limits(max_file_bytes=2) if limit == "file" else (
        artifacts.Limits(max_bytes=20) if limit == "total" else artifacts.Limits(max_files=1))
    if limit == "depth":
        source = tree[0]
        (source / "main").unlink()
        (source / "main.c").unlink()
        (source / "Main.java").write_bytes(b"class Main {}")
        (source / "Main.class").write_bytes(b"class")
        nested = source.joinpath(*("p" for _ in range(8)))
        nested.mkdir(parents=True)
        (nested / "X.class").write_bytes(b"class")
        kwargs = dict(language="java", source_name="Main.java",
                      source_sha256=hashlib.sha256((source / "Main.java").read_bytes()).hexdigest())
    else:
        kwargs = {"limits": limits}
    with pytest.raises(artifacts.ArtifactError):
        freeze(tree, **kwargs)
    assert_unpublished(tree)


@pytest.mark.parametrize("update", [{"source_sha256": "c" * 64}, {"source_inode": 1},
                                    {"compiler_uid": True}, {"source_name": "../main.c"}])
def test_trusted_identity_mismatch_is_not_accepted(tree, update):
    with pytest.raises(artifacts.ArtifactError):
        freeze(tree, **update)
    assert_unpublished(tree)


def test_parent_requires_owned_private_directory(tree):
    tree[1].chmod(0o755)
    with pytest.raises(artifacts.ArtifactError, match="Parent"):
        freeze(tree)
    assert_unpublished(tree)


def test_root_substitution_is_rejected(tree):
    source = tree[0]
    source.rename(source.with_name("old"))
    source.mkdir()
    with pytest.raises(artifacts.ArtifactError, match="root identity"):
        freeze(tree)
    assert_unpublished(tree)


def test_real_symlink_substitution_between_scan_and_copy_is_rejected(tree, monkeypatch):
    original = artifacts._open_relative
    source = tree[0]

    def substitute(root, path):
        if path == "main":
            (source / "main").unlink()
            (source / "main").symlink_to(source / "main.c")
        return original(root, path)

    monkeypatch.setattr(artifacts, "_open_relative", substitute)
    with pytest.raises((artifacts.ArtifactError, OSError)):
        freeze(tree)
    assert_unpublished(tree)


def test_in_place_mutation_while_reading_is_rejected(tree, monkeypatch):
    read = artifacts.os.read
    changed = False

    def mutate(fd, size):
        nonlocal changed
        data = read(fd, size)
        if data and not changed:
            changed = True
            with (tree[0] / "main").open("ab") as stream:
                stream.write(b"mutation")
        return data

    monkeypatch.setattr(artifacts.os, "read", mutate)
    with pytest.raises(artifacts.ArtifactError):
        freeze(tree)
    assert_unpublished(tree)


def test_post_copy_tree_addition_is_rejected(tree, monkeypatch):
    scan = artifacts._scan
    calls = 0

    def changed(root, contract):
        nonlocal calls
        calls += 1
        if calls == 2:
            (tree[0] / "unexpected").write_bytes(b"late")
        return scan(root, contract)

    monkeypatch.setattr(artifacts, "_scan", changed)
    with pytest.raises(artifacts.ArtifactError):
        freeze(tree)
    assert_unpublished(tree)


def test_drain_failure_after_copy_keeps_destination_unpublished(tree):
    calls = []

    def drained():
        calls.append(None)
        if len(calls) == 2:
            raise artifacts.ArtifactError("Compiler not drained")

    with pytest.raises(artifacts.ArtifactError, match="not drained"):
        artifacts.freeze_artifacts(tree[2], "compile", tree[3], "frozen", contract=tree[4],
                                   confirm_drained=drained)
    assert_unpublished(tree)


def test_drain_callback_cannot_mutate_tree_after_source_validation(tree):
    confirmations = 0

    def drained():
        nonlocal confirmations
        confirmations += 1
        if confirmations == 2:
            (tree[0] / "main").write_bytes(b"changed at drain boundary")

    with pytest.raises(artifacts.ArtifactError, match="post-drain"):
        artifacts.freeze_artifacts(tree[2], "compile", tree[3], "frozen", contract=tree[4],
                                   confirm_drained=drained)
    assert_unpublished(tree)


def test_browser_boolean_and_success_flag_are_rejected(tree):
    for verifier in (True, lambda: True):
        with pytest.raises(artifacts.ArtifactError):
            artifacts.freeze_artifacts(tree[2], "compile", tree[3], "frozen", contract=tree[4],
                                       confirm_drained=verifier)
    assert_unpublished(tree)


@pytest.mark.parametrize("empty", [False, True])
def test_existing_destination_is_never_overwritten(tree, empty):
    existing = tree[1] / "frozen"
    existing.mkdir()
    inode = existing.stat().st_ino
    if not empty:
        (existing / "owner.txt").write_text("retain")
    with pytest.raises(FileExistsError):
        freeze(tree)
    assert existing.stat().st_ino == inode
    if not empty:
        assert (existing / "owner.txt").read_text() == "retain"
    assert [p.name for p in tree[1].iterdir()] == ["frozen"]


def test_write_failure_never_exposes_partial_destination(tree, monkeypatch):
    def failed(*args):
        raise OSError("injected storage failure")

    monkeypatch.setattr(artifacts.os, "write", failed)
    with pytest.raises(OSError):
        freeze(tree)
    assert_unpublished(tree)


def test_copied_bytes_are_rehashed_before_publication(tree, monkeypatch):
    write = artifacts.os.write
    corrupt = True

    def changed(fd, data):
        nonlocal corrupt
        if corrupt:
            corrupt = False
            return write(fd, b"x" * len(data))
        return write(fd, data)

    monkeypatch.setattr(artifacts.os, "write", changed)
    with pytest.raises(artifacts.ArtifactError, match="digest changed"):
        freeze(tree)
    assert_unpublished(tree)


def test_limits_cannot_be_unbounded_or_exceed_profile_ceiling():
    for kwargs in ({"max_file_bytes": 20 * 1024**2 + 1}, {"max_bytes": 0},
                   {"max_files": 257}, {"max_depth": 9}):
        with pytest.raises(artifacts.ArtifactError):
            artifacts.Limits(**kwargs)
