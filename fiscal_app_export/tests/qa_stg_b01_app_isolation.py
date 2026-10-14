"""STG-B01: integration of preserved STG-LOCK into S01 candidate.

CI ONLY. A *fake* staging environment is injected into a subprocess to
verify the security firewall before opening sockets or touching PostgreSQL.
The synthetic functional lab runs ONLY in the existing FLASK_ENV=testing E2E,
using a temporary SQLite database and .invalid accounts.

No Railway variable values, credentials, real customer rows or endpoints.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

FAKE_STAGE = r'''
import socket

def no_network(*args, **kwargs):
    raise AssertionError("STG-B01 test forbids all network/DB connections")

socket.socket.connect = no_network
import psycopg2
psycopg2.connect = no_network
import requests
requests.sessions.Session.request = no_network

from app import app, _STAGING_ISOLATED, _PAYPAL_ENABLED
from staging_isolation import STAGING_BASE_URL, STAGING_HOST, RAILWAY_HEALTHCHECK_HOST

assert _STAGING_ISOLATED is True
assert _PAYPAL_ENABLED is False
assert app.config["SESSION_COOKIE_SECURE"] is True
assert app.config["SQLALCHEMY_DATABASE_URI"].endswith("@postgres-zzky.railway.internal:5432/railway")
assert "bootstrap_db.py" not in open("Procfile", encoding="utf-8").read()

cli = app.test_client()
def check(method, path, expected, host=STAGING_BASE_URL, headers=None):
    reply = cli.open(path, method=method, base_url=host, headers=headers or {})
    assert reply.status_code == expected, (method, path, reply.status_code, expected)
    return reply

assert check("GET", "/healthz", 200).get_json()["ok"]
assert check("HEAD", "/healthz", 200, "https://" + RAILWAY_HEALTHCHECK_HOST)
assert check("GET", "/healthz", 200, "https://" + RAILWAY_HEALTHCHECK_HOST)
check("GET", "/", 200)
for method, path in (
    ("POST", "/"),
    ("POST", "/healthz"),
    ("GET", "/login/"),
    ("GET", "/dashboard"),
    ("GET", "/api/me"),
    ("GET", "/api/asesoramiento/mis-solicitudes"),
    ("POST", "/api/asesoramiento/solicitar"),
    ("POST", "/api/admin/asesoramiento/solicitudes/6/nota"),
    ("POST", "/api/pago/iniciar/synthetic"),
    ("GET", "/api/pago/info/synthetic"),
    ("GET", "/api/pago/paypal/capture"),
    ("POST", "/api/webhooks/paypal"),
    ("POST", "/api/webhooks/stripe"),
    ("GET", "/verify-email"),
    ("GET", "/static/pagar.html"),
):
    resp = check(method, path, 503)
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Retry-After"] == "300"

check("GET", "/api/me", 421, "https://www.marianosevilla.com")
check("GET", "/api/me", 421, "https://" + RAILWAY_HEALTHCHECK_HOST)
check("GET", "/healthz", 421, "https://" + RAILWAY_HEALTHCHECK_HOST,
      {"Origin": STAGING_BASE_URL})
check("GET", "/", 403, STAGING_BASE_URL,
      {"Origin": "https://www.marianosevilla.com"})

# A hypothetical env switch must not ever bypass STG-LOCK.
assert "S01_SYNTHETIC_LAB_MODE" in __import__("os").environ
check("POST", "/api/asesoramiento/solicitar", 503)
print("STG-B01 fake staging Flask: exact Railway identity PASS; 15 blocked routes PASS; "
      "healthcheck exception PASS; no network/DB/provider PASS")
'''

FAKE_LAB = r'''
import os
assert os.environ["FLASK_ENV"] == "testing"
assert os.environ["DATABASE_URL"].startswith("sqlite:////")
from app import app, _STAGING_ISOLATED
assert _STAGING_ISOLATED is False
assert app.config["SESSION_COOKIE_SECURE"] is False
assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:////")
assert app.test_client().get("/healthz").status_code == 200
print("STG-B01 synthetic CI lab: staging firewall inert in isolated testing PASS")
'''


def main() -> None:
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("CI") == "true"
    assert os.environ.get("FLASK_ENV") == "testing"
    # Only local test values; do not inherit any Railway environment ID or URL.
    root_env = os.environ.copy()
    for key in tuple(root_env):
        if key.startswith("RAILWAY_") or key in (
            "DATABASE_URL", "SECRET_KEY", "FLASK_ENV", "APP_BASE_URL",
            "ADMIN_EMAILS", "FISCAL_ADVISOR_EMAILS",
            "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID",
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "RESEND_API_KEY",
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
            "PAYPAL_ENVIRONMENT", "S01_SYNTHETIC_LAB_MODE",
        ):
            root_env.pop(key)

    env = root_env.copy()
    env.update({
        "FLASK_ENV": "staging",
        "SECRET_KEY": "CI-INERT-FAKE-STAGING-KEY-NOT-A-PRODUCTION-SECRET",
        "RAILWAY_PROJECT_ID": "e04f04a8-3aae-4aed-9073-638601f8ca30",
        "RAILWAY_ENVIRONMENT_ID": "b2937140-78f7-4347-a9bc-c96333e03b9b",
        "RAILWAY_ENVIRONMENT_NAME": "staging",
        "RAILWAY_SERVICE_ID": "3eecda71-9f53-4b33-a308-887d835b7fce",
        "APP_BASE_URL": "https://fiscal-cripto-staging-staging.up.railway.app",
        "PAYPAL_ENVIRONMENT": "sandbox",
        "DATABASE_URL": (
            "postgresql+psycopg2://ci:ci-inert-password"
            "@postgres-zzky.railway.internal:5432/railway"
        ),
        "S01_SYNTHETIC_LAB_MODE": "true",
    })
    subprocess.run(
        [sys.executable, "-c", FAKE_STAGE], cwd=ROOT, env=env,
        check=True, text=True, timeout=60,
    )

    # Verify that the real Flask import fails before DB/HTTP can initialize
    # when the staging runtime points at production, has provider keys or
    # falsely labels itself as production. Do not echo any variable values.
    for variable, bad_value in (
        ("DATABASE_URL", "postgresql+psycopg2://ci:invalid@postgres.railway.internal:5432/railway"),
        ("STRIPE_SECRET_KEY", "ci-only-inert-stripe-secret"),
        ("FLASK_ENV", "production"),
    ):
        invalid = env.copy()
        invalid[variable] = bad_value
        failed = subprocess.run(
            [sys.executable, "-c", "import app"], cwd=ROOT, env=invalid,
            capture_output=True, text=True, timeout=60,
        )
        assert failed.returncode != 0, ("invalid staging identity unexpectedly launched", variable)
        assert ("Staging isolation:" in failed.stderr
                and variable in failed.stderr), ("missing fail-closed evidence", variable)

    import tempfile
    with tempfile.TemporaryDirectory(prefix="s01-stg-b01-fixtures-") as directory:
        lab_env = root_env.copy()
        lab_env.update({
            "FLASK_ENV": "testing",
            "SECRET_KEY": "CI-INERT-LAB-KEY-ONLY",
            "DATABASE_URL": "sqlite:///" + str(Path(directory) / "lab.sqlite"),
            "S01_SYNTHETIC_LAB_MODE": "true",
        })
        subprocess.run(
            [sys.executable, "-c", FAKE_LAB], cwd=ROOT, env=lab_env,
            check=True, text=True, timeout=60,
        )
    print("STG-B01 integration PASS: staging lockdown preserved; "
          "synthetic CI mode separate; no Railway effects")


if __name__ == "__main__":
    main()
