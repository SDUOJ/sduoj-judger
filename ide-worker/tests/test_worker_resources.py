import json
from pathlib import Path

import pytest

from ide_intelligence.languages import command
from sduoj_ide_worker.nacos import settings
from ide_intelligence.resource_settings import integer, validate


def test_resource_settings_cannot_inject_arguments_or_exceed_bounds():
    for value in ('0', '9', '-1', '2 --help', '2.0', 'nan'):
        with pytest.raises(ValueError):
            validate({'SDUOJ_IDE_CLANGD_JOBS': value})
    for value in ('0', '257'):
        with pytest.raises(ValueError):
            validate({'SDUOJ_IDE_CPP_MAX_DOCUMENTS': value})


def test_nacos_validates_resource_ranges_before_startup():
    environment = {'SDUOJ_IDE_REDIS_URL': 'redis://localhost/14',
                   'SDUOJ_IDE_PREFIX': 'resource-test:', 'AUTOLAB_DEBUG_ENABLED': '1',
                   'SDUOJ_IDE_CPP_MAX_DOCUMENTS': 48, 'SDUOJ_IDE_JAVA_PROCESSORS': 2}
    assert settings(json.dumps({'schemaVersion': 1, 'environment': environment}))[
        'SDUOJ_IDE_CPP_MAX_DOCUMENTS'] == '48'
    environment['SDUOJ_IDE_JAVA_PROCESSORS'] = 0
    with pytest.raises(ValueError):
        settings(json.dumps({'schemaVersion': 1, 'environment': environment}))


def test_language_limits_preserve_global_fallback_and_isolate_java_options(monkeypatch):
    monkeypatch.setenv('SDUOJ_IDE_CLANGD_JOBS', '1')
    monkeypatch.setenv('SDUOJ_IDE_CPP_MAX_DOCUMENTS', '48')
    monkeypatch.setenv('SDUOJ_IDE_JAVA_PROCESSORS', '2')
    monkeypatch.setenv('SDUOJ_IDE_JAVA_HEAP_MB', '384')
    monkeypatch.setenv('AUTOLAB_IDE_JDTLS_COMMAND', 'jdtls --jvm-arg=-Xmx256m')
    assert '-j=1' in command('cpp', Path('/tmp/ide'), shared=True)
    java = command('java', Path('/tmp/ide'), shared=True)
    assert '--jvm-arg=-XX:ActiveProcessorCount=2' in java
    assert java.index('--jvm-arg=-Xmx384m') > java.index('--jvm-arg=-Xmx256m')
    assert all('ActiveProcessorCount' not in arg for arg in command('java', Path('/tmp/ide')))
    assert integer('SDUOJ_IDE_CPP_MAX_DOCUMENTS', 32) == 48
    assert integer('SDUOJ_IDE_C_MAX_DOCUMENTS', 32) == 32
