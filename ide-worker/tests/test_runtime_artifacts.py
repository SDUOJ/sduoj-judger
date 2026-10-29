import hashlib
import json
import os
from pathlib import Path

import pytest

from ide_debug.runtime_artifacts import materialize


def fixture(tmp_path, rows=None):
    source, output = tmp_path / 'artifacts', tmp_path / 'work'
    source.mkdir()
    output.mkdir()
    data = b'compiled bytes'
    (source / 'main').write_bytes(data)
    (source / 'main').chmod(0o555)
    manifest = {'version': 1, 'sourceSha256': 'a' * 64, 'templateSha256': 'b' * 64,
                'nativeSha256': 'c' * 64, 'files': rows or [
                    {'path': 'main', 'size': len(data), 'mode': 0o555,
                     'sha256': hashlib.sha256(data).hexdigest()}]}
    raw = json.dumps(manifest).encode()
    (source / 'manifest.json').write_bytes(raw)
    kwargs = dict(manifest_sha256=hashlib.sha256(raw).hexdigest(), source_sha256='a' * 64,
                  template_sha256='b' * 64, native_sha256='c' * 64)
    return source, output, kwargs


def test_copies_into_fresh_workspace_and_closes_directory_write_access(tmp_path):
    source, output, kwargs = fixture(tmp_path)
    result = materialize(source, output, **kwargs)
    assert (output / 'main').read_bytes() == (source / 'main').read_bytes()
    assert (output / 'main').stat().st_ino != (source / 'main').stat().st_ino
    assert output.stat().st_mode & 0o777 == 0o555
    assert (output / 'main').stat().st_mode & 0o777 == 0o555
    assert result['sourceSha256'] == kwargs['source_sha256']
    output.chmod(0o700)


@pytest.mark.parametrize('field', ['manifest_sha256', 'source_sha256', 'template_sha256', 'native_sha256'])
def test_rejects_mismatched_authorized_identity(tmp_path, field):
    source, output, kwargs = fixture(tmp_path)
    kwargs[field] = 'd' * 64
    with pytest.raises(ValueError):
        materialize(source, output, **kwargs)
    assert not list(output.iterdir())


def test_rejects_modified_compiler_artifact(tmp_path):
    source, output, kwargs = fixture(tmp_path)
    (source / 'main').chmod(0o755)
    (source / 'main').write_bytes(b'tampered bytes')
    (source / 'main').chmod(0o555)
    with pytest.raises(ValueError):
        materialize(source, output, **kwargs)


def test_rejects_source_symlink(tmp_path):
    source, output, kwargs = fixture(tmp_path)
    (source / 'main').unlink()
    (source / 'main').symlink_to('/etc/passwd')
    with pytest.raises(OSError):
        materialize(source, output, **kwargs)


def test_rejects_hard_link(tmp_path):
    source, output, kwargs = fixture(tmp_path)
    os.link(source / 'main', tmp_path / 'alias')
    with pytest.raises(ValueError):
        materialize(source, output, **kwargs)


def test_rejects_escape_before_creating_file(tmp_path):
    source, output, kwargs = fixture(tmp_path, [
        {'path': '../escape', 'size': 0, 'mode': 0o444, 'sha256': 'a' * 64}])
    with pytest.raises(ValueError):
        materialize(source, output, **kwargs)
    assert not (tmp_path / 'escape').exists()


def test_requires_empty_workspace(tmp_path):
    source, output, kwargs = fixture(tmp_path)
    (output / 'owned').write_text('keep')
    with pytest.raises(ValueError):
        materialize(source, output, **kwargs)
    assert (output / 'owned').read_text() == 'keep'
