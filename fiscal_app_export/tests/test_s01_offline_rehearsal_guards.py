"""Fail-closed tests for S01 offline production-backup rehearsal (no real data)."""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools" / "s01_rehearse_restored_backup.py"
)
spec = importlib.util.spec_from_file_location("s01_rehearsal", MODULE_PATH)
rehearsal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


def test_private_custom_archive_and_sha256(tmp_path):
    backup = tmp_path / "synthetic.dump"
    backup.write_bytes(b"PGDMP" + b"CI fake content only")
    backup.chmod(0o600)
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    rehearsal.checked_archive(backup, digest)


@pytest.mark.parametrize("contents", [
    b"not a postgres archive",
    b"AGE-ENCRYPTED-FILE",
])
def test_invalid_archive_magic_denied(tmp_path, contents):
    backup = tmp_path / "bad.dump"
    backup.write_bytes(contents)
    backup.chmod(0o600)
    with pytest.raises(rehearsal.RehearsalError, match="pg_dump custom"):
        rehearsal.checked_archive(
            backup, hashlib.sha256(contents).hexdigest()
        )


def test_modified_archive_denied(tmp_path):
    backup = tmp_path / "synthetic.dump"
    backup.write_bytes(b"PGDMPoriginal")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    backup.write_bytes(b"PGDMPtampered")
    backup.chmod(0o600)
    with pytest.raises(rehearsal.RehearsalError, match="SHA-256 incorrecto"):
        rehearsal.checked_archive(backup, digest)


def test_permissive_file_denied(tmp_path):
    backup = tmp_path / "synthetic.dump"
    backup.write_bytes(b"PGDMParchive")
    backup.chmod(0o644)
    with pytest.raises(rehearsal.RehearsalError, match="chmod 600"):
        rehearsal.checked_archive(
            backup, hashlib.sha256(backup.read_bytes()).hexdigest()
        )


def test_backup_symlink_denied(tmp_path):
    original = tmp_path / "original"
    original.write_bytes(b"PGDMParchive")
    original.chmod(0o600)
    link = tmp_path / "alias"
    link.symlink_to(original)
    with pytest.raises(rehearsal.RehearsalError, match="enlaces simbólicos"):
        rehearsal.checked_archive(
            link, hashlib.sha256(original.read_bytes()).hexdigest()
        )


def test_checksum_sidecar_binds_filename(tmp_path):
    backup = tmp_path / "original.dump"
    digest = "b" * 64
    sidecar = tmp_path / "original.sha256"
    sidecar.write_text(f"{digest}  original.dump\n", encoding="ascii")
    assert rehearsal.expected_digest(backup, sidecar) == digest
    sidecar.write_text(f"{digest}  some_other.dump\n", encoding="ascii")
    with pytest.raises(rehearsal.RehearsalError, match="otro nombre"):
        rehearsal.expected_digest(backup, sidecar)


def test_checksum_symlink_denied(tmp_path):
    backup = tmp_path / "original.dump"
    original = tmp_path / "hash"
    original.write_text("a" * 64 + "\n")
    link = tmp_path / "symlink"
    link.symlink_to(original)
    with pytest.raises(rehearsal.RehearsalError, match="symlink"):
        rehearsal.expected_digest(backup, link)


def test_environment_strips_external_services(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://production.invalid/railway")
    monkeypatch.setenv("PGHOST", "postgres-prod.example.invalid")
    monkeypatch.setenv("PGPASSWORD", "never-use-production")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_should_not_inherit")
    monkeypatch.setenv("RESEND_API_KEY", "real-mail-key")
    monkeypatch.setenv("HTTPS_PROXY", "https://external.invalid")
    assert all(
        key not in rehearsal.clean_environment()
        for key in ("DATABASE_URL", "PGHOST", "PGPASSWORD",
                    "STRIPE_SECRET_KEY", "RESEND_API_KEY", "HTTPS_PROXY")
    )
    isolated = rehearsal.pg_environment(tmp_path / "socket", tmp_path, app=True)
    assert isolated["PGHOST"] == str(tmp_path / "socket")
    assert isolated["PGDATABASE"] == "s01_local_rehearsal"
    assert isolated["PGSSLMODE"] == "disable"
    assert "production.invalid" not in isolated["DATABASE_URL"]
    assert isolated["FLASK_ENV"] == "testing"
    assert isolated["STRIPE_SECRET_KEY"] == ""
    assert isolated["RESEND_API_KEY"] == ""
    assert isolated["PYTHONPATH"].endswith("python_guard")


def test_no_network_guard_does_not_depend_on_prod_secrets(tmp_path):
    rehearsal.deny_tcp_python_network(tmp_path)
    source = (tmp_path / "python_guard" / "sitecustomize.py").read_text()
    assert "socket.AF_UNIX" in source
    assert "blocks all IP networking" in source
    assert "blocks DNS" in source
    assert "class _LocalSocket(_orig_socket)" in source


def test_restricted_socket_imports_asyncio_ssl_in_fresh_python(tmp_path):
    """Regression: Python 3.13 SSL subclasses socket.socket on import."""
    rehearsal.deny_tcp_python_network(tmp_path)
    guard = tmp_path / "python_guard" / "sitecustomize.py"
    probe = """
import runpy, sys
runpy.run_path(sys.argv[1])
import asyncio
import ssl
import socket
assert isinstance(socket.socket, type)
try:
    socket.socket(socket.AF_INET, socket.SOCK_STREAM)
except OSError as exc:
    assert 'blocks all IP networking' in str(exc)
else:
    raise AssertionError('IP socket was permitted')
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM):
    pass
try:
    socket.getaddrinfo('example.invalid', 443)
except OSError as exc:
    assert 'blocks DNS' in str(exc)
else:
    raise AssertionError('DNS lookup was permitted')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", probe, str(guard)],
        env=rehearsal.clean_environment(),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-1200:]


def test_restricted_socket_allows_sqlalchemy_import(tmp_path):
    """The precise import path previously raised TypeError in SQLAlchemy 2.1."""
    rehearsal.deny_tcp_python_network(tmp_path)
    guard = tmp_path / "python_guard" / "sitecustomize.py"
    probe = """
import runpy, sys
runpy.run_path(sys.argv[1])
from sqlalchemy import inspect, text
from flask_migrate import upgrade
import asyncio, ssl, socket
assert isinstance(socket.socket, type)
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(guard)],
        env=rehearsal.clean_environment(),
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-1200:]


def test_main_refuses_execution_in_ci(tmp_path, monkeypatch):
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"PGDMPfixture")
    backup.chmod(0o600)
    sidecar = tmp_path / "backup.sha256"
    sidecar.write_text(hashlib.sha256(backup.read_bytes()).hexdigest())
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(os, "geteuid", lambda: 1234)
    monkeypatch.setattr(
        "sys.argv",
        ["cmd", "--backup", str(backup), "--sha-file", str(sidecar),
         "--pg-bin", str(tmp_path)],
    )
    with pytest.raises(rehearsal.RehearsalError, match="infraestructura CI"):
        rehearsal.main()
