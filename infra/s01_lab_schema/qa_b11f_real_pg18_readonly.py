"""STG-B11F: run B11B's ACTUAL catalog SELECT on disposable PG18 CI.

Railway's B11B repository attachment was blocked. This test MUST NOT attach
a source to Railway or probe the real lab; it tests only SQL/catalog behavior.

Synthetic runner redirects PostgreSQL traffic to Docker-local 127.0.0.1:5432
AFTER B11B's production identity guard has built its private PGHOST.
This is a CI-only test seam and MUST NOT be packaged into the B11B image.
"""
from __future__ import annotations

import os
from subprocess import CompletedProcess
import subprocess
from unittest.mock import patch

import preflight

CI_PASSWORD = "ci-only-test-password"
CI_CLIENT_IMAGE = "postgres:18"
FORBIDDEN_CLUSTER_IDS = frozenset((
    preflight.TARGET_CLUSTER,
    preflight.FORBIDDEN_ORIGINAL_CLUSTER,
))


class CiDenied(RuntimeError):
    pass


def require_disposable_ci(env: dict[str, str]) -> None:
    if not (
        env.get("GITHUB_ACTIONS") == "true"
        and env.get("CI") == "true"
        and env.get("RUNNER_OS") == "Linux"
    ):
        raise CiDenied("NOT_GITHUB_CI")
    if any(key.startswith("RAILWAY_") for key in env):
        raise CiDenied("RAILWAY_ENVIRONMENT_PRESENT")
    if any(env.get(key) for key in (
        "DATABASE_URL", "SOURCE_DATABASE_URL", "TARGET_DATABASE_URL",
        "PGHOST", "PGPASSWORD", "PGSERVICE", "PGPASSFILE",
        "S01_SCHEMA_BOOTSTRAP_APPROVAL",
    )):
        raise CiDenied("EXTERNAL_DATABASE_CREDENTIAL_PRESENT")


def fake_identity() -> dict[str, str]:
    """Pure synthetic mapping that must never be forwarded to other hosts."""
    return {
        "RAILWAY_PROJECT_ID": preflight.PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": preflight.ENVIRONMENT_ID,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": preflight.SERVICE_ID,
        "RAILWAY_PRIVATE_DOMAIN": preflight.SERVICE_PRIVATE_DOMAIN,
        "TARGET_DATABASE_URL": (
            "postgresql://postgres:" + CI_PASSWORD
            + "@postgres-im3h.railway.internal:5432/railway"
        ),
    }


def disposable_psql(statement: str, *, readonly: bool) -> str:
    # docker --network host maps ONLY to the GitHub Actions postgres:18
    # disposable service, not any Railway private/public DNS.
    argv = [
        "docker", "run", "--rm", "--network", "host",
        "-e", "PGPASSWORD=" + CI_PASSWORD,
    ]
    if readonly:
        argv += ["-e", "PGOPTIONS=-c default_transaction_read_only=on"]
    argv += [
        CI_CLIENT_IMAGE,
        "psql", "-h", "127.0.0.1", "-p", "5432", "-U", "postgres",
        "-d", "railway", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
        "-c", statement,
    ]
    result = subprocess.run(
        argv, capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode:
        raise CiDenied("SYNTHETIC_POSTGRES_SQL_FAILED")
    return result.stdout.strip()


def readonly_runner(argv, *, env, text, capture_output, check, timeout):
    """Test seam: accept only the exact B11B readonly query and private pins.

    NEVER run any psql args or connection params supplied by external input.
    """
    expected = [
        "psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
        "-c", preflight.SQL,
    ]
    if argv != expected:
        raise CiDenied("UNAPPROVED_SQL_QUERY")
    if env.get("PGHOST") != preflight.TARGET_HOST:
        raise CiDenied("PROBE_DID_NOT_PIN_TARGET_HOST")
    if env.get("PGSSLMODE") != "require":
        raise CiDenied("PROBE_DID_NOT_REQUIRE_SSL")
    if "default_transaction_read_only=on" not in env.get("PGOPTIONS", ""):
        raise CiDenied("PROBE_DID_NOT_REQUIRE_READONLY")
    if not (text and capture_output and not check and timeout <= 20):
        raise CiDenied("BAD_PROCESS_OPTIONS")
    return CompletedProcess(
        args=argv, returncode=0,
        stdout=disposable_psql(preflight.SQL, readonly=True) + "\n",
        stderr="",
    )


def run():
    require_disposable_ci(dict(os.environ))
    version_and_cluster = disposable_psql(
        "SELECT current_setting('server_version_num'),"
        "(pg_catalog.pg_control_system()).system_identifier::text",
        readonly=True,
    ).split("|")
    if len(version_and_cluster) != 2:
        raise CiDenied("BAD_SYNTHETIC_CLUSTER_REPORT")
    version, cluster = version_and_cluster
    if not version.startswith("18") or not cluster.isdecimal():
        raise CiDenied("CI_REQUIRES_POSTGRES18")
    if cluster in FORBIDDEN_CLUSTER_IDS:
        raise CiDenied("REAL_CLUSTER_ID_FORBIDDEN")

    # Pin the version and cluster to the new disposable container only.
    # B11B source constants remain pinned to real PG18.6 for Railway.
    with patch.object(preflight, "TARGET_PG_VERSION", version), patch.object(
        preflight, "TARGET_CLUSTER", cluster
    ):
        verified = preflight.preflight(fake_identity(), runner=readonly_runner)
        if verified != cluster:
            raise CiDenied("PRISTINE_CATALOG_UNEXPECTED")
        print("B11F CI PASS: genuine PG18 catalog query pristine + read-only")

        # Only in ephemeral GitHub CI create an unexpected table + row.
        disposable_psql(
            "CREATE TABLE public.b11f_synthetic_probe (n integer PRIMARY KEY);"
            " INSERT INTO public.b11f_synthetic_probe VALUES (42);",
            readonly=False,
        )
        try:
            preflight.preflight(fake_identity(), runner=readonly_runner)
        except preflight.SchemaPreflightDenied as exc:
            if exc.code != "SCHEMA_NOT_PRISTINE":
                raise CiDenied("WRONG_DIRTY_DENIAL") from None
        else:
            raise CiDenied("NONEMPTY_DATABASE_ACCEPTED")

        rows = disposable_psql(
            "SELECT count(*) FROM public.b11f_synthetic_probe",
            readonly=True,
        )
        if rows != "1":
            raise CiDenied("PREFLIGHT_MODIFIED_SYNTHETIC_DATA")
        print(
            "B11F CI PASS: dirty PG18 catalog rejected; row preserved;"
            " no schema writes by preflight; no Railway access"
        )


if __name__ == "__main__":
    run()
