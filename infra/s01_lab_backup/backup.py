"""STG-B10L — one-shot private logical backup from verified S01 LAB PG18.

Produces exactly one encrypted-in-transit, private S3 object with an embedded
SHA256 metadata digest, verifies round-trip bytes, then exits. NO SQL DDL/DML,
no Flask, providers, HTTP listener, shared volume, or automatic retry.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROJECT = "5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e"
ENVIRONMENT = "3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8"
SERVICE = "2b2b54f8-3010-4d08-ada4-f2df73f4be2d"
CLUSTER = "7696213098351943739"
PRIVATE_DOMAIN = "s01-lab-backup-reader.railway.internal"
S3_ENDPOINT = "https://t3.storageapi.dev"
S3_BUCKET = "s01-lab-recovery-20261014-ehk810"
S3_REGION = "auto"
S3_KEY = "s01-lab/pg18/prebootstrap/cluster-7696213098351943739.pgcustom"
MAX_BYTES = 50 * 1024 * 1024
PUBLIC_MARKERS = ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL", "APP_BASE_URL")
UNSAFE_PROVIDER_MARKERS = (
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "PAYPAL_CLIENT_SECRET",
    "RESEND_API_KEY", "GOOGLE_CLIENT_SECRET", "SENTRY_DSN", "SECRET_KEY",
)
# This query is only issued with default_transaction_read_only=on; all objects
# in public, custom schemas and nonstandard extensions must be absent.
CHECK_SQL = """
SELECT
 current_database(),
 current_setting('server_version_num'),
 current_setting('transaction_read_only'),
 (pg_catalog.pg_control_system()).system_identifier::text,
 (SELECT count(*) FROM pg_class c JOIN pg_namespace n
   ON n.oid=c.relnamespace WHERE n.nspname='public')::text,
 (SELECT count(*) FROM pg_proc p JOIN pg_namespace n
   ON n.oid=p.pronamespace WHERE n.nspname='public')::text,
 (SELECT count(*) FROM pg_type t JOIN pg_namespace n
   ON n.oid=t.typnamespace WHERE n.nspname='public')::text,
 (SELECT count(*) FROM pg_namespace WHERE nspname NOT IN
   ('public','information_schema','pg_catalog') AND nspname NOT LIKE 'pg_toast%'
   AND nspname NOT LIKE 'pg_temp_%')::text,
 (SELECT count(*) FROM pg_extension WHERE extname <> 'plpgsql')::text,
 (SELECT count(*) FROM pg_event_trigger)::text;
"""


class StopBackup(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def checked_environment(env):
    if not (
        env.get("RAILWAY_PROJECT_ID") == PROJECT
        and env.get("RAILWAY_ENVIRONMENT_ID") == ENVIRONMENT
        and env.get("RAILWAY_ENVIRONMENT_NAME") == "lab"
        and env.get("RAILWAY_SERVICE_ID") == SERVICE
        and env.get("RAILWAY_PRIVATE_DOMAIN") == PRIVATE_DOMAIN
    ):
        raise StopBackup("WRONG_LAB_IDENTITY")
    if any((env.get(x) or "").strip() for x in PUBLIC_MARKERS):
        raise StopBackup("PUBLIC_EXPOSURE_MARKER")
    if any((env.get(x) or "").strip() for x in UNSAFE_PROVIDER_MARKERS):
        raise StopBackup("PROVIDER_SECRET_IN_BACKUP_SERVICE")
    port = env.get("PORT", "")
    if port and (not port.isascii() or not port.isdecimal()
                 or len(port) > 5 or not 1 <= int(port) <= 65535):
        raise StopBackup("INVALID_PORT")
    dsn = env.get("DATABASE_URL", "")
    try:
        url = urlsplit(dsn)
        if (url.scheme != "postgresql"
            or url.hostname != "postgres.railway.internal"
            or url.port != 5432
            or url.path != "/railway"
            or url.query or url.fragment
            or not url.username or not url.password):
            raise ValueError("unapproved DSN")
    except (ValueError, TypeError):
        raise StopBackup("WRONG_DATABASE_DESTINATION") from None
    if (
        env.get("BACKUP_ENDPOINT") != S3_ENDPOINT
        or env.get("BACKUP_BUCKET") != S3_BUCKET
        or env.get("BACKUP_REGION") != S3_REGION
        or not env.get("BACKUP_ACCESS_KEY_ID")
        or not env.get("BACKUP_SECRET_ACCESS_KEY")
    ):
        raise StopBackup("WRONG_BUCKET_DESTINATION")
    # Only PG* vars are passed to subprocesses. Never place DSNs/passwords on
    # command line or log their values. decode username/pass safely.
    return {
        "PGHOST": url.hostname, "PGPORT": "5432", "PGDATABASE": "railway",
        "PGUSER": unquote(url.username), "PGPASSWORD": unquote(url.password),
        "PGSSLMODE": "require",
        "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=30000",
        "PATH": env.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": "/tmp",
    }


def run_pg(command, pg_env, timeout=45):
    # Enforce executable argv allowlist; stdout/stderr are never printed.
    if command[0] not in ("psql", "pg_dump"):
        raise StopBackup("COMMAND_DENIED")
    result = subprocess.run(
        command, env=pg_env, capture_output=True, text=True,
        timeout=timeout, check=False,
    )
    if result.returncode != 0:
        raise StopBackup("PG_COMMAND_FAILED")
    return result.stdout.strip()


def assert_pristine_database(pg_env):
    output = run_pg(["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                     "-c", CHECK_SQL], pg_env)
    rows = output.splitlines()
    if len(rows) != 1:
        raise StopBackup("CATALOG_IDENTITY")
    parts = rows[0].split("|")
    if len(parts) != 10:
        raise StopBackup("CATALOG_IDENTITY")
    if (parts[0] != "railway" or not parts[1].isdigit()
        or int(parts[1]) // 10000 != 18 or parts[2] != "on"
        or parts[3] != CLUSTER):
        raise StopBackup("CLUSTER_MISMATCH")
    if any(x != "0" for x in parts[4:]):
        raise StopBackup("DB_NOT_PRISTINE")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def s3_client(env):
    # boto3 is imported only AFTER offline environment validation.
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", endpoint_url=S3_ENDPOINT, region_name=S3_REGION,
        aws_access_key_id=env["BACKUP_ACCESS_KEY_ID"],
        aws_secret_access_key=env["BACKUP_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", retries={"max_attempts": 1},
                      s3={"addressing_style": "virtual"}),
    )


def assert_no_prior_object(client):
    from botocore.exceptions import ClientError
    try:
        client.head_object(Bucket=S3_BUCKET, Key=S3_KEY)
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status == 404:
            return
        raise StopBackup("BUCKET_HEAD_FAILED") from None
    raise StopBackup("BACKUP_ALREADY_EXISTS")


def create_backup(env):
    pg_env = checked_environment(env)
    assert_pristine_database(pg_env)
    client = s3_client(env)
    assert_no_prior_object(client)
    with tempfile.TemporaryDirectory(prefix="s01-backup-") as tmp:
        archive = Path(tmp) / "lab.pgcustom"
        run_pg(["pg_dump", "--format=custom", "--no-owner", "--no-acl",
                "--file", str(archive)], pg_env, timeout=90)
        if not archive.is_file() or not (1 <= archive.stat().st_size <= MAX_BYTES):
            raise StopBackup("BACKUP_SIZE")
        assert_pristine_database(pg_env)
        digest = sha256_file(archive)
        with archive.open("rb") as f:
            client.put_object(
                Bucket=S3_BUCKET, Key=S3_KEY, Body=f,
                ContentLength=archive.stat().st_size,
                ContentType="application/octet-stream",
                IfNoneMatch="*",   # Atomic create-or-reject; never overwrite
                Metadata={"sha256": digest, "cluster": CLUSTER,
                          "database": "railway", "pgmajor": "18"},
            )
        meta = client.head_object(Bucket=S3_BUCKET, Key=S3_KEY)
        if (meta.get("ContentLength") != archive.stat().st_size
            or (meta.get("Metadata") or {}).get("sha256") != digest):
            raise StopBackup("REMOTE_METADATA_MISMATCH")
        # Verify the actual stored bytes, not merely the upload response.
        restored = Path(tmp) / "reloaded.pgcustom"
        with restored.open("wb") as out:
            body = client.get_object(Bucket=S3_BUCKET, Key=S3_KEY)["Body"]
            while block := body.read(1024 * 1024):
                out.write(block)
        if sha256_file(restored) != digest:
            raise StopBackup("REMOTE_CONTENT_MISMATCH")
    return digest


def main():
    try:
        # No deployment permission is conferred by this script on any other
        # service, or any restore/bootstrap operation.
        digest = create_backup(dict(os.environ))
    except StopBackup as exc:
        print("S01 STG-B10L: NO-GO (" + exc.reason + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        # No stack traces/driver exceptions/URLs/S3 credentials in logs.
        print("S01 STG-B10L: NO-GO (UNEXPECTED_ERROR; details redacted)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 STG-B10L: PASS (private lab backup, remote SHA256=" +
          digest + ", source cluster=" + CLUSTER + ", source pristine)",
          flush=True)


if __name__ == "__main__":
    main()
