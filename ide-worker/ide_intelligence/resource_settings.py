"""Bounded operator settings for shared LSP resource controls."""
import os
import re


LIMITS = {
    'SDUOJ_IDE_CLANGD_JOBS': (1, 8),
    'SDUOJ_IDE_JAVA_PROCESSORS': (1, 8),
    'SDUOJ_IDE_JAVA_HEAP_MB': (128, 2048),
    **{'SDUOJ_IDE_' + language + '_MAX_DOCUMENTS': (1, 256)
       for language in ('C', 'CPP', 'JAVA', 'PYTHON')},
}


def validate(values):
    for name, (minimum, maximum) in LIMITS.items():
        if name in values:
            raw = str(values[name])
            if not re.fullmatch(r'[0-9]+', raw) or not minimum <= int(raw) <= maximum:
                raise ValueError('Invalid IDE resource setting: ' + name)


def integer(name, default=None):
    value = os.getenv(name)
    if value is None:
        return default
    validate({name: value})
    return int(value)
