import json

import pytest

from sduoj_ide_worker.worker import Worker
from sduoj_ide_worker.protocol import encode
from ide_intelligence.shared_pool import SharedLanguagePool
from ide_intelligence.config import load_config


@pytest.mark.parametrize('language', ['c', 'cpp', 'python', 'java'])
def test_single_language_pool_registration(language):
    worker = Worker('lsp', language, redis=object())
    worker.pool = SharedLanguagePool(load_config())
    worker.pool.processes = {language: 1}
    worker.pool.max_processes = 1
    registration = json.loads(encode(worker.registration()))
    assert list(registration['metrics']['languages']) == [language]
    assert registration['metrics']['maxProcesses'] == 1
