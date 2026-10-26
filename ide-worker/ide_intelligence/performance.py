"""Bounded stage timings; callbacks are scoped to one HTTP request context."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import os
from pathlib import Path
import time


observer = ContextVar('ide_performance_observer', default=None)


@contextmanager
def measure(name, language='all'):
    callback = observer.get()
    if callback is None:
        yield
        return
    started = time.monotonic()
    try:
        yield
    finally:
        callback((name, language), time.monotonic() - started)


def measured(name):
    def decorate(function):
        @wraps(function)
        async def call(*args, **kwargs):
            with measure(name):
                return await function(*args, **kwargs)
        return call
    return decorate


def process_sample(pid, role, language=None):
    try:
        text = Path(f'/proc/{pid}/stat').read_text()
        fields = text[text.rfind(')') + 2:].split()
        return {'pid': pid, 'role': role, 'language': language,
                'parentPid': int(fields[1]),
                'comm': text[text.find('(') + 1:text.rfind(')')],
                'cpuSeconds': (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'),
                'threads': int(fields[17]),
                'rssBytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE')}
    except (OSError, ValueError, IndexError):
        return None


def process_tree_samples(pid, language):
    pending, seen, rows = [pid], set(), []
    while pending and len(seen) < 64:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        row = process_sample(current, 'lsp', language)
        if row is None:
            continue
        rows.append(row)
        try:
            children = Path(f'/proc/{current}/task/{current}/children').read_text().split()
            pending.extend(int(child) for child in children)
        except (OSError, ValueError):
            pass
    return rows


def cgroup_cpu_sample(root=Path('/sys/fs/cgroup')):
    """cgroup-v2 counters distinguish a CPU quota ceiling from API-only work."""
    try:
        quota, period = (root / 'cpu.max').read_text().split()
        fields = dict(line.split() for line in (root / 'cpu.stat').read_text().splitlines())
        return {'version': 2, 'quotaCores': None if quota == 'max' else int(quota) / int(period),
                **{name: int(fields[name]) for name in
                   ('usage_usec', 'nr_periods', 'nr_throttled', 'throttled_usec') if name in fields}}
    except (OSError, ValueError, ZeroDivisionError):
        return {}
