"""Each CLI startup fetches Nacos before preparation or component creation."""
import os
import sys
from unittest.mock import AsyncMock

import pytest

from sduoj_ide_worker.__main__ import main


@pytest.mark.parametrize('inherited_hash', ['', 'stale-parent-hash'])
def test_main_bootstraps_once_before_preparation_and_service(monkeypatch, inherited_hash):
    events = []
    monkeypatch.setattr(sys, 'argv', ['worker', '--role', 'all'])
    monkeypatch.setenv('SDUOJ_IDE_NACOS_HASH', inherited_hash)
    async def fetch():
        events.append('fetch')
        monkeypatch.setenv('SDUOJ_IDE_NACOS_HASH', 'fresh-config')
    bootstrap = AsyncMock(side_effect=fetch)
    monkeypatch.setattr('sduoj_ide_worker.nacos.bootstrap', bootstrap)
    def prepare():
        assert os.environ['SDUOJ_IDE_NACOS_HASH'] == 'fresh-config'
        events.append('prepare')
    class Service:
        def __init__(self):
            events.append('construct')
        async def run(self):
            events.append('run')
    monkeypatch.setattr('sduoj_ide_worker.service.Service', Service)
    main(prepare=prepare)
    assert events == ['fetch', 'prepare', 'construct', 'run']
    bootstrap.assert_awaited_once()


@pytest.mark.parametrize('error', [RuntimeError('unavailable'), ValueError('invalid config')])
def test_inherited_hash_cannot_bypass_failed_configuration(monkeypatch, error):
    monkeypatch.setattr(sys, 'argv', ['worker', '--role', 'all'])
    monkeypatch.setenv('SDUOJ_IDE_NACOS_HASH', 'inherited-valid-looking-hash')
    bootstrap = AsyncMock(side_effect=error)
    monkeypatch.setattr('sduoj_ide_worker.nacos.bootstrap', bootstrap)
    service = AsyncMock()
    monkeypatch.setattr('sduoj_ide_worker.service.Service', service)
    prepared = []
    with pytest.raises(type(error)):
        main(prepare=lambda: prepared.append(True))
    bootstrap.assert_awaited_once()
    service.assert_not_called()
    assert prepared == []
