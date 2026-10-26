import json
import time
import pytest
from sduoj_ide_worker.protocol import Job


def payload(**changes):
    value = dict(schemaVersion=1, requestId='request-1234567890', replyTo='gateway-1234567890',
                 sessionId='session-1234567890', sessionEpoch='epoch-1234567890',
                 ownerId='9007199254740993', role='lsp', deadlineAt=int(time.time()*1000)+1000)
    value.update(changes)
    return json.dumps(value)


def test_owner_identity_is_lossless_string():
    assert Job.parse(payload()).value['ownerId'] == '9007199254740993'
    with pytest.raises(ValueError):
        Job.parse(payload(ownerId=9007199254740993))


@pytest.mark.parametrize('field,value', [('sessionId', '../other'), ('replyTo', 'other:channel'),
    ('sessionEpoch', ''), ('schemaVersion', 2), ('role', 'shell')])
def test_reject_invalid_envelopes(field, value):
    with pytest.raises(ValueError):
        Job.parse(payload(**{field:value}))


def test_expired_jobs_are_not_executable():
    assert Job.parse(payload(deadlineAt=0)).expired
