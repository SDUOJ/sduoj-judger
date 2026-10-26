import errno
from pathlib import Path
from types import SimpleNamespace
import stat
import struct
import pytest
from ide_debug.cgroups import exact_identity_filecap, identity_helper_preflight


def caps(bit):
    return struct.pack('<IIIII', 0x02000001, 1 << bit, 0, 0, 0)


@pytest.mark.parametrize('bit', [6, 7])
def test_only_exact_filecap_contract(bit):
    assert exact_identity_filecap(caps(bit), bit)
    for raw in (b'', caps(21), caps(bit) + b'\0' * 4,
                struct.pack('<IIIII', 0x02000001, (1 << bit) | 2, 0, 0, 0),
                struct.pack('<IIIII', 0x02000001, 1 << bit, 1, 0, 0)):
        assert not exact_identity_filecap(raw, bit)


@pytest.mark.parametrize('mode,owner,raw,expected', [
    (0o100755, 0, caps(6), 'filecap'),
    (0o104755, 0, b'', 'setuid'),
    (0o100775, 0, caps(6), None),
    (0o100755, 10001, caps(6), None),
    (0o120777, 0, caps(6), None),
    (0o104755, 0, caps(6), None),
    (0o100755, 0, caps(7), None),
    (0o100755, 0, b'', None),
])
def test_helper_routes_fail_closed(monkeypatch, mode, owner, raw, expected):
    monkeypatch.setattr(Path, 'lstat', lambda self: SimpleNamespace(st_mode=mode, st_uid=owner))
    monkeypatch.setattr('os.access', lambda *args: True)
    monkeypatch.setattr('os.getxattr', lambda *args: raw, raising=False)
    if expected:
        assert identity_helper_preflight(Path('/trusted-helper'), 6) == expected
    else:
        with pytest.raises(RuntimeError):
            identity_helper_preflight(Path('/trusted-helper'), 6)
