"""Host-local ownership survives Redis eviction; recovery cannot race a live API."""

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path


@contextmanager
def node_lock(state_dir):
    directory = Path(state_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise RuntimeError("Debug runtime directory must be private")
    descriptor = os.open(
        str(directory / ".agent.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Debug runtime or recovery already owns this node") from error
        yield
    finally:
        os.close(descriptor)
