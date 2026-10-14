"""S01 STG-B10O: candidate restore logic; deliberately NOT executable live.

This module is NOT copied by infra/s01_lab_restore/Dockerfile. Its main()
always exits NO-GO, and its worker must not be wired to Railway until an
independent, specific authorization to write to the recovery DB.

The only DB target is Postgres-Im3h; source Postgres is never a configured
endpoint or credential. Download is from one private object with pinned SHA256.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import probe

S3_ENDPOINT = "https://t3.storageapi.dev"
S3_REGION = "auto"
S3_BUCKET = "s01-lab-recovery-20261014-ehk810"
ARCHIVE_KEY = "s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom"
EXPECTED_SHA256 = "1af6ba229c781a7cc0b357610119d546c4a47bcce5a2b19442a11501ea3afdab"
RESTORE_INTENT_KEY = "s01-lab/pg18/restore-intent/target-7696517018472497211.lock"
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
REQUIRED_S3 = (
    "RESTORE_ENDPOINT", "RESTORE_BUCKET", "RESTORE_REGION",
    "RESTORE_ACCESS_KEY_ID", "RESTORE_SECRET_ACCESS_KEY",
)


class RestoreDenied(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def validate_configuration(env: dict[str, str]) -> dict[str, str]:
    """Call before importing S3 client, opening a DB socket or fetching data."""
    try:
        pg_env = probe.validate_environment(env)
    except probe.ProbeDenied as exc:
        raise RestoreDenied("TARGET_" + exc.reason) from None
    expected = (
        ("RESTORE_ENDPOINT", S3_ENDPOINT),
        ("RESTORE_BUCKET", S3_BUCKET),
        ("RESTORE_REGION", S3_REGION),
    )
    mismatched = [key for key, value in expected if env.get(key) != value]
    mismatched.extend(
        key for key in REQUIRED_S3[3:]
        if not env.get(key)
    )
    if mismatched:
        # Names ONLY; never credentials or S3 URL values in shared logs.
        raise RestoreDenied("STORAGE_REFERENCE:" + ",".join(mismatched))
    return pg_env


def s3_client(env):
    # Imported only after configuration guard; no Railway secrets in tests.
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=S3_ENDPOINT, region_name=S3_REGION,
        aws_access_key_id=env["RESTORE_ACCESS_KEY_ID"],
        aws_secret_access_key=env["RESTORE_SECRET_ACCESS_KEY"],
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 1},
            s3={"addressing_style": "virtual"},
        ),
    )


def require_archive_metadata(client) -> int:
    head = client.head_object(Bucket=S3_BUCKET, Key=ARCHIVE_KEY)
    metadata = head.get("Metadata") or {}
    size = head.get("ContentLength")
    if type(size) is not int or not (5 <= size <= MAX_ARCHIVE_BYTES):
        raise RestoreDenied("ARCHIVE_SIZE")
    if (
        metadata.get("sha256") != EXPECTED_SHA256
        or metadata.get("cluster") != probe.ORIGINAL_CLUSTER
        or metadata.get("database") != "railway"
        or metadata.get("pgmajor") != "18"
    ):
        raise RestoreDenied("ARCHIVE_METADATA")
    return size


def read_verified_archive(client, output: Path, size: int) -> None:
    """Download exactly the approved object's bytes without printing rows."""
    response = client.get_object(Bucket=S3_BUCKET, Key=ARCHIVE_KEY)
    if response.get("ContentLength") != size:
        raise RestoreDenied("ARCHIVE_LENGTH")
    digest = hashlib.sha256()
    total = 0
    stream = response["Body"]
    try:
        with output.open("xb") as archive:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES or total > size:
                    raise RestoreDenied("ARCHIVE_LENGTH")
                digest.update(chunk)
                archive.write(chunk)
    finally:
        stream.close()
    if total != size or digest.hexdigest() != EXPECTED_SHA256:
        raise RestoreDenied("ARCHIVE_SHA256")
    with output.open("rb") as archive:
        if archive.read(5) != b"PGDMP":
            raise RestoreDenied("ARCHIVE_FORMAT")


def run_pgrestore(argv, pg_env, *, runner=subprocess.run, timeout=90):
    if not argv or argv[0] != "pg_restore":
        raise RestoreDenied("INVALID_COMMAND")
    try:
        result = runner(
            argv, env=pg_env, capture_output=True,
            text=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        raise RestoreDenied("RESTORE_CLI_FAILED") from None
    if result.returncode != 0:
        # NEVER log pg_restore stdout/stderr (may contain DB details).
        raise RestoreDenied("RESTORE_CLI_FAILED")
    return result.stdout


def check_archive_toc(archive_path, pg_env, runner=subprocess.run):
    result = run_pgrestore(
        ["pg_restore", "--list", str(archive_path)],
        pg_env, runner=runner, timeout=15,
    )
    # Pinned SHA256 is the primary content identity. No need to print TOC.
    if not result.startswith(";"):
        raise RestoreDenied("ARCHIVE_TOC")
    return True


def claim_restore_intent(client) -> None:
    """Permanent one-shot claim. Even failure leaves marker: no silent retry.

    This is a write to the backup bucket, NOT to any DB. S3 create-if-absent
    semantics reject redeploys, concurrent attempts and replayed jobs.
    """
    try:
        client.put_object(
            Bucket=S3_BUCKET,
            Key=RESTORE_INTENT_KEY,
            Body=b"S01 RECOVERY ATTEMPT; manual review required for any retry",
            ContentType="text/plain",
            IfNoneMatch="*",
            Metadata={
                "sourcearchive": EXPECTED_SHA256,
                "targetcluster": probe.EXPECTED_TARGET_CLUSTER,
            },
        )
    except Exception:
        raise RestoreDenied("RESTORE_INTENT_ALREADY_EXISTS_OR_FAILED") from None


def restore_once(env, *, client=None, probe_fn=probe.probe,
                 cli_runner=subprocess.run) -> str:
    """Candidate for a future specifically approved executor, NOT main()."""
    pg_env = validate_configuration(env)

    # Real network preflight must originate from this exact private runner.
    try:
        first = probe_fn(env)
    except probe.ProbeDenied as exc:
        raise RestoreDenied("PRECHECK_" + exc.reason) from None
    if first != probe.EXPECTED_TARGET_CLUSTER:
        raise RestoreDenied("PRECHECK_TARGET_MISMATCH")

    if client is None:
        client = s3_client(env)
    size = require_archive_metadata(client)
    with tempfile.TemporaryDirectory(prefix="s01-restore-") as tmp:
        archive = Path(tmp) / "verified.pgcustom"
        read_verified_archive(client, archive, size)
        check_archive_toc(archive, pg_env, runner=cli_runner)

        # Re-verify target immediately before claiming permanent intent.
        try:
            if probe_fn(env) != probe.EXPECTED_TARGET_CLUSTER:
                raise RestoreDenied("SECOND_PRECHECK_TARGET_MISMATCH")
        except probe.ProbeDenied as exc:
            raise RestoreDenied("SECOND_PRECHECK_" + exc.reason) from None

        # Must be final pre-write step; no automatic cleanup on failures.
        claim_restore_intent(client)

        # The preflight was read-only. ONLY this command may write, to the
        # pinned recovery DB: never --create, --clean, --if-exists or DROP.
        # A PostgreSQL single transaction rolls back SQL on restore failure.
        write_env = dict(pg_env)
        write_env["PGOPTIONS"] = (
            "-c statement_timeout=30000 -c lock_timeout=5000"
        )
        run_pgrestore(
            ["pg_restore", "--exit-on-error", "--single-transaction",
             "--no-owner", "--no-acl", "--dbname=railway",
             str(archive)],
            write_env, runner=cli_runner, timeout=90,
        )
        # An initially pristine backup MUST leave user catalogs pristine.
        # If this check fails, DO NOT rollback/drop the recovery DB.
        try:
            if probe_fn(env) != probe.EXPECTED_TARGET_CLUSTER:
                raise RestoreDenied("POSTCHECK_TARGET_MISMATCH")
        except probe.ProbeDenied as exc:
            raise RestoreDenied("POSTCHECK_" + exc.reason) from None
    return "RESTORE_VERIFIED_INDEPENDENT_RECOVERY_CLUSTER"


def main() -> None:
    # No CLI route to restore_once in B10O. A future explicitly authorized
    # commit must introduce a separate entrypoint and pass independent gates.
    print("S01 STG-B10O: NO-GO (LIVE_RESTORE_NOT_AUTHORIZED)",
          file=sys.stderr, flush=True)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
