"""S01 B10N: isolated, one-shot, read-only target identity probe.

No restore code, S3 client, migration engine, web server, or writable SQL.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from urllib.parse import urlsplit, unquote

PROJECT = "5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e"
ENVIRONMENT = "3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8"
RUNNER_SERVICE = "dc26ad37-ca87-4813-b85f-7a6f23d60527"
RUNNER_DOMAIN = "s01-lab-restore-one-shot.railway.internal"
TARGET_HOST = "postgres-im3h.railway.internal"
ORIGINAL_CLUSTER = "7696213098351943739"
EXPECTED_TARGET_CLUSTER = "7696517018472497211"
BLOCKED_PUBLIC = ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL", "APP_BASE_URL")
BLOCKED_PROVIDERS = (
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "PAYPAL_CLIENT_SECRET",
    "RESEND_API_KEY", "GOOGLE_CLIENT_SECRET", "SECRET_KEY", "SENTRY_DSN",
)
SQL = """
SELECT current_database(),current_setting('server_version_num'),
 current_setting('transaction_read_only'),
 (pg_catalog.pg_control_system()).system_identifier::text,
 (SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n
   ON n.oid=c.relnamespace WHERE n.nspname='public'),
 (SELECT count(*) FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n
   ON n.oid=p.pronamespace WHERE n.nspname='public'),
 (SELECT count(*) FROM pg_catalog.pg_type t JOIN pg_catalog.pg_namespace n
   ON n.oid=t.typnamespace WHERE n.nspname='public'),
 (SELECT count(*) FROM pg_catalog.pg_namespace
   WHERE nspname NOT IN ('public','information_schema','pg_catalog')
   AND nspname NOT LIKE 'pg_toast%' AND nspname NOT LIKE 'pg_temp_%'),
 (SELECT count(*) FROM pg_catalog.pg_extension WHERE extname <> 'plpgsql'),
 (SELECT count(*) FROM pg_catalog.pg_event_trigger);
"""


class ProbeDenied(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_environment(env: dict[str, str]) -> dict[str, str]:
    expected = (
        ("RAILWAY_PROJECT_ID", PROJECT),
        ("RAILWAY_ENVIRONMENT_ID", ENVIRONMENT),
        ("RAILWAY_ENVIRONMENT_NAME", "lab"),
        ("RAILWAY_SERVICE_ID", RUNNER_SERVICE),
        ("RAILWAY_PRIVATE_DOMAIN", RUNNER_DOMAIN),
    )
    if any(env.get(k) != v for k, v in expected):
        raise ProbeDenied("WRONG_RAILWAY_IDENTITY")
    if any((env.get(k) or "").strip() for k in BLOCKED_PUBLIC):
        raise ProbeDenied("PUBLIC_MARKER")
    if any((env.get(k) or "").strip() for k in BLOCKED_PROVIDERS):
        raise ProbeDenied("PROVIDER_SECRET")
    if any((env.get(k) or "").strip() for k in (
        "DATABASE_URL", "SOURCE_DATABASE_URL", "PGPASSWORD", "PGHOST",
        "PGSERVICE", "PGPASSFILE",
    )):
        raise ProbeDenied("UNEXPECTED_DATABASE_SOURCE")
    port = env.get("PORT", "")
    if port and (not port.isascii() or not port.isdecimal()
                 or len(port) > 5 or not 1 <= int(port) <= 65535):
        raise ProbeDenied("INVALID_RUNTIME_PORT")
    try:
        parsed = urlsplit(env.get("TARGET_DATABASE_URL", ""))
        if not (parsed.scheme == "postgresql" and parsed.hostname == TARGET_HOST
                and parsed.port == 5432 and parsed.path == "/railway"
                and not parsed.query and not parsed.fragment
                and parsed.username and parsed.password):
            raise ValueError("bad connection target")
    except (ValueError, TypeError):
        raise ProbeDenied("WRONG_TARGET_DATABASE") from None
    return {
        "PGHOST": TARGET_HOST, "PGPORT": "5432", "PGDATABASE": "railway",
        "PGUSER": unquote(parsed.username), "PGPASSWORD": unquote(parsed.password),
        "PGSSLMODE": "require",
        "PGOPTIONS": "-c default_transaction_read_only=on -c statement_timeout=10000",
        "PATH": env.get("PATH", "/usr/bin:/bin"), "HOME": "/tmp",
    }


def validate_catalog(raw: str) -> str:
    lines = raw.strip().splitlines()
    if len(lines) != 1:
        raise ProbeDenied("INVALID_CATALOG_SHAPE")
    cols = lines[0].split("|")
    if len(cols) != 10 or cols[:3] != ["railway", "180006", "on"]:
        raise ProbeDenied("VERSION_DB_OR_READONLY_MISMATCH")
    fingerprint = cols[3]
    if not re.fullmatch(r"[0-9]{16,20}", fingerprint):
        raise ProbeDenied("INVALID_TARGET_FINGERPRINT")
    if fingerprint == ORIGINAL_CLUSTER:
        raise ProbeDenied("SOURCE_CLUSTER_AS_TARGET")
    if fingerprint != EXPECTED_TARGET_CLUSTER:
        raise ProbeDenied("UNEXPECTED_TARGET_CLUSTER")
    if cols[4:] != ["0"] * 6:
        raise ProbeDenied("TARGET_NOT_PRISTINE")
    return fingerprint


def probe(environ: dict[str, str], runner=subprocess.run) -> str:
    pg_env = validate_environment(environ)
    argv = ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", SQL]
    try:
        result = runner(argv, env=pg_env, text=True, capture_output=True,
                        check=False, timeout=20)
    except (OSError, subprocess.SubprocessError):
        raise ProbeDenied("READONLY_QUERY_FAILED") from None
    if result.returncode:
        raise ProbeDenied("READONLY_QUERY_FAILED")
    return validate_catalog(result.stdout)


def main() -> None:
    try:
        cluster = probe(dict(os.environ))
    except ProbeDenied as exc:
        print("S01 STG-B10N: NO-GO (" + exc.reason + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except Exception:
        print("S01 STG-B10N: NO-GO (REDACTED)",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 STG-B10N PROBE PASS: target PG18.6, pristine, cluster="
          + cluster + ", different from original", flush=True)


if __name__ == "__main__":
    main()
