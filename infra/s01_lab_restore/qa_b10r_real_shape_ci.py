"""STG-B10R: invoke the actual restore_once function on disposable PG18 CI.

Two genuine PG18 servers on 127.0.0.1; fake S3 bytes and intent marker.
No Railway credentials, volumes, production data or networks.
"""
from __future__ import annotations
import hashlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import probe
import restore_candidate as candidate

PASSWORD = "ci-only-test-password"

def cli(port, database, statement):
    p = subprocess.run(
        ["docker", "run", "--rm", "--network", "host",
         "-e", "PGPASSWORD=" + PASSWORD, "postgres:18",
         "psql", "-h", "127.0.0.1", "-p", str(port), "-U", "postgres",
         "-d", database, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
         "-c", statement],
        text=True, capture_output=True, timeout=30,
    )
    if p.returncode:
        raise RuntimeError("SYNTHETIC_SQL_FAILURE")
    return p.stdout.strip()

class FakeS3:
    def __init__(self, archive):
        self.archive = archive
        self.digest = hashlib.sha256(archive).hexdigest()
        self.claimed = False
        self.events = []
    def head_object(self, **kwargs):
        self.events.append("HEAD")
        return {"ContentLength": len(self.archive), "Metadata": {
            "sha256": self.digest, "cluster": probe.ORIGINAL_CLUSTER,
            "database": "railway", "pgmajor": "18"}}
    def get_object(self, **kwargs):
        self.events.append("GET")
        return {"ContentLength": len(self.archive), "Body": io.BytesIO(self.archive)}
    def put_object(self, **kwargs):
        self.events.append("CLAIM")
        if self.claimed or kwargs.get("IfNoneMatch") != "*":
            raise RuntimeError("CI_ALREADY_CLAIMED")
        self.claimed = True
        return {"ETag": '"synthetic"'}

def preflight(_env):
    row = cli(55433, "railway",
        "SELECT current_database(),current_setting('server_version_num'),"
        "(pg_control_system()).system_identifier::text,"
        "(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public');")
    fields = row.split("|")
    if (len(fields) != 4 or fields[0] != "railway"
        or not fields[1].startswith("18")
        or fields[2] in (probe.ORIGINAL_CLUSTER, probe.EXPECTED_TARGET_CLUSTER)
        or fields[3] != "0"):
        raise probe.ProbeDenied("CI_DESTINATION_CHANGED")
    return probe.EXPECTED_TARGET_CLUSTER

def restore_cli(args, **kwargs):
    f = Path(args[-1])
    if args[0] != "pg_restore" or not f.is_file():
        raise RuntimeError("UNEXPECTED_CI_CLI")
    if "--dbname=railway" in args:
        if "--single-transaction" not in args or "--exit-on-error" not in args:
            raise RuntimeError("UNSAFE_RESTORE_OPTIONS")
    elif "--list" not in args:
        raise RuntimeError("UNEXPECTED_ARCHIVE_COMMAND")
    vars_ = dict(kwargs["env"])
    vars_.update({"PGHOST": "127.0.0.1", "PGPORT": "55433",
                  "PGDATABASE": "railway", "PGUSER": "postgres",
                  "PGPASSWORD": PASSWORD, "PGSSLMODE": "prefer"})
    command = ["docker", "run", "--rm", "--network", "host"]
    command += [v for name in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER",
                  "PGPASSWORD", "PGOPTIONS", "PGSSLMODE") for v in ("-e", name)]
    command += ["-v", str(f.parent) + ":/archive:ro",
                "postgres:18", *args[:-1], "/archive/" + f.name]
    return subprocess.run(command, env=vars_, **kwargs)

def main():
    if (os.getenv("GITHUB_ACTIONS") != "true" or os.getenv("CI") != "true"
        or any(x.startswith("RAILWAY_") for x in os.environ)
        or any(x in os.environ for x in ("DATABASE_URL", "TARGET_DATABASE_URL"))):
        raise RuntimeError("CI_ONLY")
    for port in (5432, 55433):
        cli(port, "postgres", "CREATE DATABASE railway")
    origin = cli(5432, "railway", "SELECT (pg_control_system()).system_identifier")
    dest = cli(55433, "railway", "SELECT (pg_control_system()).system_identifier")
    if origin == dest or origin in (probe.ORIGINAL_CLUSTER, probe.EXPECTED_TARGET_CLUSTER) or dest in (probe.ORIGINAL_CLUSTER, probe.EXPECTED_TARGET_CLUSTER):
        raise RuntimeError("SYNTHETIC_CLUSTER_COLLISION")
    with tempfile.TemporaryDirectory(prefix="b10r-only-ci-") as folder:
        archive_path = Path(folder) / "ci.pgcustom"
        proc = subprocess.run(
            ["docker", "run", "--rm", "--network", "host",
             "-e", "PGPASSWORD=" + PASSWORD,
             "-v", folder + ":/archive", "postgres:18", "pg_dump",
             "-h", "127.0.0.1", "-p", "5432", "-U", "postgres",
             "-d", "railway", "-Fc", "--no-owner", "--no-acl",
             "-f", "/archive/ci.pgcustom"], capture_output=True, timeout=45)
        if proc.returncode or not archive_path.is_file():
            raise RuntimeError("CI_DUMP_FAILED")
        data = archive_path.read_bytes()
        bucket = FakeS3(data)
        pg_env = {"PGHOST": "127.0.0.1", "PGPORT": "55433",
                  "PGDATABASE": "railway", "PGUSER": "postgres",
                  "PGPASSWORD": PASSWORD, "PGSSLMODE": "prefer",
                  "PGOPTIONS": "-c default_transaction_read_only=on",
                  "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"}
        with patch.object(candidate, "EXPECTED_SHA256", bucket.digest), patch.object(candidate, "validate_configuration", return_value=pg_env):
            result = candidate.restore_once({"synthetic": "true"},
                       client=bucket, probe_fn=preflight, cli_runner=restore_cli)
            if result != "RESTORE_VERIFIED_INDEPENDENT_RECOVERY_CLUSTER":
                raise RuntimeError("CI_RESTORE_STATUS")
            if bucket.events != ["HEAD", "GET", "CLAIM"]:
                raise RuntimeError("CI_EVENT_ORDER")
            try:
                candidate.restore_once({"synthetic": "true"},
                       client=bucket, probe_fn=preflight, cli_runner=restore_cli)
            except candidate.RestoreDenied as exc:
                if exc.code != "RESTORE_INTENT_ALREADY_EXISTS_OR_FAILED":
                    raise
            else:
                raise RuntimeError("CI_REPLAY_NOT_DENIED")
    print("B10R CI PASS: real PG18 restore_once flow on two disposable clusters, authentic pg_dump, mock S3 marker, postflight empty, replay denied; zero Railway access")

if __name__ == "__main__":
    main()
