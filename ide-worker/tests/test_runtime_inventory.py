import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    'runtime_inventory', Path(__file__).resolve().parents[1] / 'scripts/inventory_debug_rootfs.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_inventory_tracks_runtime_bytes_but_not_timestamps(tmp_path):
    header = tmp_path / 'header.h'
    header.write_text('first')
    before = module.inventory(tmp_path)
    header.touch()
    assert module.inventory(tmp_path) == before
    header.write_text('other')
    assert module.inventory(tmp_path) != before


def test_image_absolute_symlink_never_reads_host_target(tmp_path):
    link = tmp_path / 'sandbox'
    link.symlink_to('/not-a-host-input/native/sandbox')
    assert module.inventory(tmp_path)['files'][0]['target'] == '/not-a-host-input/native/sandbox'
    link.unlink()
    link.symlink_to('/another/image/path')
    assert module.inventory(tmp_path)['files'][0]['target'] == '/another/image/path'


def test_inventory_rejects_runtime_fifo(tmp_path):
    import os
    os.mkfifo(tmp_path / 'ipc')
    with pytest.raises(ValueError, match='special files'):
        module.inventory(tmp_path)
