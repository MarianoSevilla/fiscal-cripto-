"""SEC5-PRIV: immutable, locally fsynced evidence snapshots outside a DB dump.

Library ONLY: this is not a production event store, a startup gate or a legal
retention decision. The independently trusted SHA-256 head MUST be obtained
from outside the snapshot location, and freshness must be guaranteed externally.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat


MAX_BYTES = 65536
HEAD_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class RecoveryEvidenceError(ValueError):
    pass


def _object_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecoveryEvidenceError("Duplicate recovery evidence field")
        result[key] = value
    return result


def _canonical_json(payload):
    if not isinstance(payload, dict):
        raise RecoveryEvidenceError("Recovery evidence must be a JSON object")
    try:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RecoveryEvidenceError("Invalid recovery evidence format") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise RecoveryEvidenceError("Recovery evidence exceeds size limit")
    return raw


def persist_immutable(path: Path, payload: dict) -> str:
    """Create a single restricted, fsynced file, never replace an existing one.

    Caller must choose a genuinely durable location independent of the backup.
    The returned digest MUST be pinned outside this location by an operator.
    """
    path = Path(path)
    raw = _canonical_json(payload)
    # No mkdir, no implicit destination, no overwrite, no symlink following.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise RecoveryEvidenceError("Cannot create immutable recovery evidence") from exc
    try:
        with os.fdopen(fd, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except Exception as exc:
        # Never allow an incomplete file to look like a valid written result.
        try:
            path.unlink()
        except OSError:
            pass
        raise RecoveryEvidenceError("Recovery evidence could not be persisted") from exc
    return hashlib.sha256(raw).hexdigest()


def read_pinned(path: Path, *, trusted_head: str) -> dict:
    """Reject absent, truncated, untrusted, stale or noncanonical evidence.

    The digest alone detects changes relative to a TRUSTED and current head; it
    does not prove that the operator supplied the latest head.
    """
    if not isinstance(trusted_head, str) or not HEAD_PATTERN.fullmatch(trusted_head):
        raise RecoveryEvidenceError("Trusted external head is missing or invalid")
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RecoveryEvidenceError("Recovery journal unavailable") from exc
    with os.fdopen(fd, "rb", closefd=True) as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) & 0o077
                or not 0 < info.st_size <= MAX_BYTES):
            raise RecoveryEvidenceError("Unsafe recovery evidence file")
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != trusted_head:
        raise RecoveryEvidenceError("Recovery evidence differs from trusted head")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_no_duplicates,
                             parse_constant=lambda _: (_ for _ in ()).throw(
                                 RecoveryEvidenceError("Non-finite JSON value")))
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RecoveryEvidenceError("Malformed recovery evidence") from exc
    if _canonical_json(payload) != raw:
        raise RecoveryEvidenceError("Noncanonical recovery evidence")
    return payload
