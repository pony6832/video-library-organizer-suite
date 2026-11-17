"""Named Windows mutexes: one desktop window, and a marker the installer waits on.

``RUNNING_MUTEX`` is held by every process of the application (window, catalog
and analysis workers). The installer's ``AppMutex`` names it, so Setup asks the
user to close the program instead of failing on files that are in use.
``WINDOW_MUTEX`` is held by the desktop window only and keeps a second window
from opening on the same account.
"""
from __future__ import annotations

import sys

RUNNING_MUTEX = "VideoLibraryOrganizer-Running-02E5D05F-9218-4CC5-B41E-66A759599ADD"
WINDOW_MUTEX = "VideoLibraryOrganizer-Window-02E5D05F-9218-4CC5-B41E-66A759599ADD"

_ERROR_ALREADY_EXISTS = 183
# Handles stay open for the life of the process; Windows releases them on exit.
_held: list[int] = []


def hold(name: str) -> bool:
    """Create or open the mutex and keep it; False when it already existed."""
    if sys.platform != "win32":
        return True
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        # Never block startup because the marker could not be created.
        return True
    already_existed = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    _held.append(handle)
    return not already_existed
