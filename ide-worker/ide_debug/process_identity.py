"""Linux pidfds, including interpreters built against pre-pidfd libc headers.

Only known native Linux syscall tables are allowed. A missing syscall or denied
operation fails closed; numeric-PID signalling is never a fallback.
"""
import ctypes
from functools import lru_cache
import os
import signal


@lru_cache(maxsize=1)
def _syscall():
    system = os.uname()
    if system.sysname != "Linux" or system.machine not in {"aarch64", "x86_64"}:
        raise RuntimeError("No verified pidfd syscall mapping for this platform")
    library = ctypes.CDLL(None, use_errno=True)
    call = library.syscall
    call.argtypes = [ctypes.c_long]  # Remaining arguments are explicitly typed varargs.
    call.restype = ctypes.c_long
    return call


def _checked(number, *arguments):
    result = _syscall()(ctypes.c_long(number), *arguments)
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return result


def open_pidfd(pid):
    native = getattr(os, "pidfd_open", None)
    if native is not None:
        return native(pid)
    return _checked(434, ctypes.c_int(pid), ctypes.c_uint(0))


def send_pidfd(descriptor, signum):
    native = getattr(signal, "pidfd_send_signal", None)
    if native is not None:
        return native(descriptor, signum)
    _checked(424, ctypes.c_int(descriptor), ctypes.c_int(signum),
             ctypes.c_void_p(), ctypes.c_uint(0))
