"""SEC5-PRIV: durable-file mechanics with a separately pinned expected head.

Pure synthetic filesystem tests. No database, Railway or customer information.
"""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sec5_priv_recovery_evidence import (  # noqa: E402
    RecoveryEvidenceError, persist_immutable, read_pinned,
)


def test_immutable_evidence_fsynced_and_pinned(tmp_path):
    path = tmp_path / "synthetic-journal.json"
    content = {"version": 1, "events": [{"seq": 1, "id": 123}]}
    pin = persist_immutable(path, content)
    assert pin == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(pin) == 64
    assert read_pinned(path, trusted_head=pin) == content
    assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(RecoveryEvidenceError):
        persist_immutable(path, {"version": 1, "events": []})
    assert read_pinned(path, trusted_head=pin) == content


@pytest.mark.parametrize("untrusted_head", [None, "", "not-hex", "0" * 64, "A" * 64])
def test_missing_or_stale_trusted_head_fails(tmp_path, untrusted_head):
    path = tmp_path / "evidence.json"
    persist_immutable(path, {"version": 1})
    with pytest.raises(RecoveryEvidenceError):
        read_pinned(path, trusted_head=untrusted_head)


def test_missing_corrupt_or_oversized_journal_fails(tmp_path):
    path = tmp_path / "evidence.json"
    pin = persist_immutable(path, {"version": 1, "events": []})
    path.write_bytes(path.read_bytes() + b"corrupt")
    with pytest.raises(RecoveryEvidenceError):
        read_pinned(path, trusted_head=pin)
    path.unlink()
    with pytest.raises(RecoveryEvidenceError):
        read_pinned(path, trusted_head=pin)
    path.write_bytes(b"x" * 65537)
    with pytest.raises(RecoveryEvidenceError):
        read_pinned(path, trusted_head=hashlib.sha256(path.read_bytes()).hexdigest())


def test_symlink_and_unsafe_permissions_fails(tmp_path):
    target = tmp_path / "target"
    pin = persist_immutable(target, {"version": 1})
    symlink = tmp_path / "symlink"
    symlink.symlink_to(target)
    with pytest.raises(RecoveryEvidenceError):
        read_pinned(symlink, trusted_head=pin)
    with pytest.raises(RecoveryEvidenceError):
        persist_immutable(symlink, {"version": 2})
    target.chmod(0o644)
    with pytest.raises(RecoveryEvidenceError):
        read_pinned(target, trusted_head=pin)


def test_duplicate_fields_and_noncanonical_json_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    raw = b'{"version":1,"version":1}'
    path.write_bytes(raw)
    path.chmod(0o600)
    with pytest.raises(RecoveryEvidenceError):
        read_pinned(path, trusted_head=hashlib.sha256(raw).hexdigest())

    raw = json.dumps({"version": 1}, indent=2).encode()
    path.write_bytes(raw)
    with pytest.raises(RecoveryEvidenceError):
        read_pinned(path, trusted_head=hashlib.sha256(raw).hexdigest())


def test_no_invalid_or_oversized_persistent_content(tmp_path):
    path = tmp_path / "invalid.json"
    for bad in (None, [], {"nonfinite": float("nan")},
                {"large": "a" * 65537}):
        with pytest.raises(RecoveryEvidenceError):
            persist_immutable(path, bad)
        assert not path.exists()
