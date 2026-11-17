from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

# The UI polls, the worker writes and the heartbeat thread writes concurrently.
# Wait instead of failing fast with "database is locked".
BUSY_TIMEOUT_SECONDS = 30.0


class ClosingConnection(sqlite3.Connection):
    """``with connect(...)`` commits or rolls back *and* closes the handle.

    The stock ``sqlite3.Connection`` context manager only ends the transaction,
    so every ``with`` block used to leak an open file handle until GC.
    """

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


_DRIVE_FIXED = 3
# Folders a sync client watches; it would upload the -wal/-shm side files on
# every write and can hold them open while the worker needs them.
_SYNC_ROOT_VARIABLES = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
_journal_checked: set[str] = set()


def wal_is_safe(path: Path | str) -> bool:
    """True only for a database on a local fixed disk outside a synced folder.

    Write-ahead logging lets the status window read while the worker writes,
    but it relies on shared memory, which network shares (a NAS) do not
    provide reliably. Anywhere else the default rollback journal stays.
    """
    if sys.platform != "win32":
        return False
    resolved = os.path.abspath(str(path))
    drive = os.path.splitdrive(resolved)[0]
    if not drive or drive.startswith("\\\\"):
        return False
    import ctypes

    if ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") != _DRIVE_FIXED:
        return False
    folded = os.path.normcase(resolved)
    for variable in _SYNC_ROOT_VARIABLES:
        root = os.environ.get(variable)
        if root and folded.startswith(os.path.normcase(os.path.abspath(root)) + os.sep):
            return False
    return True


def _use_write_ahead_log(connection: sqlite3.Connection, path: Path | str) -> None:
    key = os.path.normcase(os.path.abspath(str(path)))
    if key in _journal_checked:
        return
    _journal_checked.add(key)
    if not wal_is_safe(path):
        return
    try:
        # Stored in the database file, so one switch covers every later
        # connection (the worker, the window and the media library panel).
        connection.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        # Another process holds the file right now; the old mode still works.
        _journal_checked.discard(key)


def connect(path: Path | str, *, timeout: float = BUSY_TIMEOUT_SECONDS) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=timeout, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    _use_write_ahead_log(connection, path)
    return connection
