"""S01 STG-B10Q: READ-ONLY verification of real recovery target and S3 archive.

This file is the only executable alongside probe.py in the separate Q
preflight image. It NEVER calls pg_restore with a database destination, never
runs SQL DML/DDL, and never makes S3 writes. Any exception stops the job.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import probe

ENDPOINT = "https://t3.storageapi.dev"
REGION = "auto"
BUCKET = "s01-lab-recovery-20261014-ehk810"
KEY = "s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom"
EXPECTED_SHA256 = "1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab"
MAX_BYTES = 50 * 1024 * 1024
SOURCE_CLUSTER = probe.ORIGINAL_CLUSTER
TARGET_CLUSTER = probe.EXPECTED_TARGET_CLUSTER
REQUIRED_SECRETS = ("RESTORE_ACCESS_KEY_ID", "RESTORE_SECRET_ACCESS_KEY")


class AuditDenied(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_env(env: dict[str, str]) -> dict[str, str]:
    try:
        pg_env = probe.validate_environment(env)
    except probe.ProbeDenied as exc:
        raise AuditDenied("TARGET_" + exc.reason) from None
    for name, value in (
        ("RESTORE_ENDPOINT", ENDPOINT),
        ("RESTORE_BUCKET", BUCKET),
        ("RESTORE_REGION", REGION),
    ):
        if env.get(name) != value:
            raise AuditDenied("STORAGE_REFERENCE_" + name)
    for name in REQUIRED_SECRETS:
        if not env.get(name):
            raise AuditDenied("STORAGE_CREDENTIAL_" + name)
    return pg_env


def new_s3_client(env: dict[str, str]):
    # Boto3 only after all identity checks. No logging client exceptions.
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=ENDPOINT, region_name=REGION,
        aws_access_key_id=env["RESTORE_ACCESS_KEY_ID"],
        aws_secret_access_key=env["RESTORE_SECRET_ACCESS_KEY"],
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 1},
            connect_timeout=5,
            read_timeout=20,
            s3={"addressing_style": "virtual"},
        ),
    )


def assert_head(client) -> int:
    try:
        head = client.head_object(Bucket=BUCKET, Key=KEY)
    except Exception:
        raise AuditDenied("ARCHIVE_HEAD_FAILED") from None
    size = head.get("ContentLength")
    if type(size) is not int or not (5 <= size <= MAX_BYTES):
        raise AuditDenied("ARCHIVE_SIZE")
    metadata = head.get("Metadata") or {}
    if (
        metadata.get("sha256") != EXPECTED_SHA256
        or metadata.get("cluster") != SOURCE_CLUSTER
        or metadata.get("database") != "railway"
        or metadata.get("pgmajor") != "18"
    ):
        raise AuditDenied("ARCHIVE_METADATA")
    return size


def download_and_verify(client, path: Path, expected_size: int):
    try:
        data = client.get_object(Bucket=BUCKET, Key=KEY)
    except Exception:
        raise AuditDenied("ARCHIVE_GET_FAILED") from None
    if data.get("ContentLength") != expected_size:
        raise AuditDenied("ARCHIVE_LENGTH")
    length = 0
    sha = hashlib.sha256()
    body = data["Body"]
    try:
        with path.open("xb") as dest:
            while True:
                chunk = body.read(1024 * 1024)
                if not chunk:
                    break
                length += len(chunk)
                if length > expected_size or length > MAX_BYTES:
                    raise AuditDenied("ARCHIVE_LENGTH")
                sha.update(chunk)
                dest.write(chunk)
    except AuditDenied:
        raise
    except Exception:
        raise AuditDenied("ARCHIVE_STREAM_FAILED") from None
    finally:
        body.close()
    if length != expected_size or sha.hexdigest() != EXPECTED_SHA256:
        raise AuditDenied("ARCHIVE_SHA256")
    with path.open("rb") as handle:
        if handle.read(5) != b"PGDMP":
            raise AuditDenied("ARCHIVE_MAGIC")
    return sha.hexdigest()


def assert_archive_readable(path: Path, pg_env: dict[str, str], runner=subprocess.run):
    # A list-only operation has no --dbname, --host or SQL execution.
    args = ["pg_restore", "--list", str(path)]
    try:
        result = runner(
            args, env=pg_env, timeout=20, capture_output=True,
            text=True, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise AuditDenied("PG_RESTORE_LIST_FAILED") from None
    if result.returncode or not result.stdout.startswith(";"):
        raise AuditDenied("PG_RESTORE_LIST_FAILED")


def inspect(env: dict[str, str], *, client=None, probe_fn=probe.probe,
            list_runner=subprocess.run) -> str:
    pg_env = validate_env(env)
    try:
        actual = probe_fn(env)
    except probe.ProbeDenied as exc:
        raise AuditDenied("FIRST_PROBE_" + exc.reason) from None
    if actual != TARGET_CLUSTER or actual == SOURCE_CLUSTER:
        raise AuditDenied("FIRST_PROBE_WRONG_CLUSTER")
    if client is None:
        client = new_s3_client(env)
    size = assert_head(client)
    with tempfile.TemporaryDirectory(prefix="s01-readonly-archive-") as directory:
        path = Path(directory) / "real-backup.pgcustom"
        digest = download_and_verify(client, path, size)
        assert_archive_readable(path, pg_env, runner=list_runner)
        try:
            actual_2 = probe_fn(env)
        except probe.ProbeDenied as exc:
            raise AuditDenied("SECOND_PROBE_" + exc.reason) from None
        if actual_2 != TARGET_CLUSTER:
            raise AuditDenied("SECOND_PROBE_WRONG_CLUSTER")
    return digest


def main():
    try:
        digest = inspect(dict(os.environ))
    except AuditDenied as exc:
        print("S01 STG-B10Q: NO-GO (" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        # SDK/driver exceptions can embed endpoints and credentials.
        print("S01 STG-B10Q: NO-GO (REDACTED_FAILURE)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print(
        "S01 STG-B10Q: PASS (READ ONLY; target cluster=" + TARGET_CLUSTER
        + "; source archive SHA256=" + digest
        + "; pg_restore LIST checked; no SQL writes)", flush=True,
    )


if __name__ == "__main__":
    main()
