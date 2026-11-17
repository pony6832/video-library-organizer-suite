from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .models import MediaRecord
from .process_utils import CREDENTIAL_ENVIRONMENT_KEYS


_SECRET_KEYS = CREDENTIAL_ENVIRONMENT_KEYS


class SourceIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    path: Path
    size: int
    mtime_ns: int
    sha256: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def capture_source(
    path: Path, *, known: tuple[int | None, int | None, str] | None = None
) -> SourceSnapshot:
    """Snapshot a source file.

    ``known`` is a (size, mtime_ns, sha256) triple recorded earlier for this
    path. When size and modification time still match, its fingerprint is
    reused instead of reading the whole file again - the same rule the scanner
    applies on a rescan. Reading a multi-gigabyte video several times per
    analysis used to cost more than the analysis on slow disks.
    """
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    stat_result = resolved.stat()
    if (
        known is not None
        and known[0] == stat_result.st_size
        and known[1] == stat_result.st_mtime_ns
    ):
        fingerprint = known[2]
    else:
        fingerprint = sha256_file(resolved)
    return SourceSnapshot(
        path=resolved,
        size=stat_result.st_size,
        mtime_ns=stat_result.st_mtime_ns,
        sha256=fingerprint,
    )


def check_snapshot_matches_record(
    record: MediaRecord, snapshot: SourceSnapshot
) -> None:
    """The snapshot just taken belongs to this record's path and content."""
    if record.path.resolve() != snapshot.path:
        raise SourceIntegrityError(f"來源路徑已變更：{record.path}")
    if snapshot.sha256 != record.fingerprint:
        raise SourceIntegrityError(f"來源指紋與清冊不符：{record.path}")


def verify_source_unchanged(
    record: MediaRecord, snapshot: SourceSnapshot
) -> SourceSnapshot:
    """The file still has the snapshot's size and modification time.

    The cheap counterpart of ``verify_record_source`` for the check after an
    analysis: the tools only read the source, so a changed size or timestamp
    is what a real modification looks like.
    """
    try:
        current = capture_source(
            record.path,
            known=(snapshot.size, snapshot.mtime_ns, snapshot.sha256),
        )
    except (FileNotFoundError, NotADirectoryError) as error:
        raise SourceIntegrityError(
            f"找不到來源媒體：{record.path}"
        ) from error
    if current.path != snapshot.path:
        raise SourceIntegrityError(f"來源路徑已變更：{record.path}")
    if current.size != snapshot.size:
        raise SourceIntegrityError(f"來源大小已變更：{record.path}")
    if current.mtime_ns != snapshot.mtime_ns:
        raise SourceIntegrityError(f"來源修改時間已變更：{record.path}")
    return current


def verify_record_source(
    record: MediaRecord, snapshot: SourceSnapshot
) -> SourceSnapshot:
    try:
        current = capture_source(record.path)
    except (FileNotFoundError, NotADirectoryError) as error:
        raise SourceIntegrityError(
            f"找不到來源媒體：{record.path}"
        ) from error

    if record.path.resolve() != snapshot.path or current.path != snapshot.path:
        raise SourceIntegrityError(f"來源路徑已變更：{record.path}")
    if snapshot.sha256 != record.fingerprint:
        raise SourceIntegrityError(f"來源指紋與清冊不符：{record.path}")
    if current.size != snapshot.size:
        raise SourceIntegrityError(f"來源大小已變更：{record.path}")
    if current.mtime_ns != snapshot.mtime_ns:
        raise SourceIntegrityError(f"來源修改時間已變更：{record.path}")
    if current.sha256 != snapshot.sha256:
        raise SourceIntegrityError(f"來源指紋已變更：{record.path}")
    return current


def sanitize_error(
    message: str,
    environment: Mapping[str, str] | None = None,
) -> str:
    safe = str(message)
    source_environment = os.environ if environment is None else environment
    for key in _SECRET_KEYS:
        value = source_environment.get(key)
        if value:
            safe = safe.replace(value, "[redacted]")
    safe = "".join(
        character
        if character == "\t" or ord(character) >= 32
        else " "
        for character in safe
    )
    return safe[:1000]
