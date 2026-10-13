"""STG-B04 CI-only imported Flask lab firewall and negative startup verification.

Runs in GitHub Actions only, no network, PostgreSQL, Railway or provider access.
The real lab web service is NOT pinned; startup must fail until later approval.
A simulated approved identity is injected in a separate subprocess for HTTP tests.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

FAKE_LAB = r'''
import os
import socket
def fail(*_args, **_kwargs):
    raise AssertionError("STG-B04 forbids any network/DB/provider I/O")
socket.socket.connect = fail
import psycopg2
psycopg2.connect = fail
import requests
requests.sessions.Session.request = fail

import lab_isolation
from dataclasses import replace
lab_isolation.LAB_IDENTITY = replace(
    lab_isolation.LAB_IDENTITY,
    web_service_id="ci-only-fictional-web-service",
    base_url="https://s01-lab-ci.invalid",
)
from app import app, _LAB_ISOLATED, _STAGING_ISOLATED, _PAYPAL_ENABLED

assert _LAB_ISOLATED is True
assert _STAGING_ISOLATED is False
assert _PAYPAL_ENABLED is False
assert app.config["SESSION_COOKIE_SECURE"] is True
assert app.config["SQLALCHEMY_DATABASE_URI"].endswith("@postgres.railway.internal:5432/railway")
assert "bootstrap_db.py" not in open("Procfile", encoding="utf-8").read()

client = app.test_client()
def check(method, path, status, base="https://s01-lab-ci.invalid", headers=None):
    result = client.open(path, method=method, base_url=base, headers=headers or {})
    assert result.status_code == status, (method, path, result.status_code, status)
    return result

assert check("GET", "/healthz", 200).get_json()["ok"]
check("HEAD", "/healthz", 200, "https://healthcheck.railway.app")
check("GET", "/healthz", 200, "https://healthcheck.railway.app")
for method, path in [
    ("GET", "/"), ("POST", "/"), ("GET", "/login/"),
    ("GET", "/dashboard"), ("GET", "/api/me"),
    ("GET", "/api/asesoramiento/mis-solicitudes"),
    ("POST", "/api/asesoramiento/solicitar"),
    ("POST", "/api/admin/asesoramiento/solicitudes/6/nota"),
    ("POST", "/api/pago/iniciar/fake"),
    ("GET", "/api/pago/info/fake"),
    ("GET", "/api/pago/paypal/capture"),
    ("POST", "/api/webhooks/paypal"),
    ("POST", "/api/webhooks/stripe"),
    ("GET", "/verify-email"),
    ("GET", "/static/pagar.html"),
    ("POST", "/healthz"),
]:
    resp = check(method, path, 503)
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Retry-After"] == "300"

check("GET", "/healthz", 421, "https://www.marianosevilla.com")
check("GET", "/api/me", 421, "https://healthcheck.railway.app")
check("GET", "/healthz", 421, "https://healthcheck.railway.app",
      {"Origin": "https://s01-lab-ci.invalid"})
check("GET", "/healthz", 403, "https://s01-lab-ci.invalid",
      {"Origin": "https://www.marianosevilla.com"})
assert os.environ.get("S01_LAB_MODE") == "true"
check("POST", "/api/webhooks/stripe", 503)
print("STG-B04 fake Flask lab: private ID guard PASS; healthcheck-only PASS; 16 blocked routes PASS; no network/provider PASS")
'''


def main() -> None:
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("CI") == "true"
    assert os.environ.get("FLASK_ENV") == "testing"

    root = os.environ.copy()
    for k in tuple(root):
        if k.startswith("RAILWAY_") or k in (
            "DATABASE_URL", "SECRET_KEY", "FLASK_ENV", "APP_BASE_URL",
            "ADMIN_EMAILS", "FISCAL_ADVISOR_EMAILS", "PAYPAL_ENVIRONMENT",
            "S01_LAB_MODE", "S01_SYNTHETIC_LAB_MODE",
            "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID",
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "RESEND_API_KEY",
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
        ):
            root.pop(k)

    env = root.copy()
    env.update({
        "FLASK_ENV": "staging",
        "SECRET_KEY": "CI-INERT-LAB-SESSION-KEY-NOT-A-REAL-SECRET",
        "RAILWAY_PROJECT_ID": "5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e",
        "RAILWAY_ENVIRONMENT_ID": "3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8",
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": "ci-only-fictional-web-service",
        "APP_BASE_URL": "https://s01-lab-ci.invalid",
        "PAYPAL_ENVIRONMENT": "sandbox",
        "DATABASE_URL": "postgresql+psycopg2://ci:inert-ci-only@postgres.railway.internal:5432/railway",
        "S01_LAB_MODE": "true",
    })

    # Actual release remains unpinned; no Flask application may start on lab.
    denied = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert denied.returncode != 0
    assert "S01 lab isolation: web identity and origin not pinned" in denied.stderr
    assert "inert-ci-only" not in denied.stderr

    # Negative startup before DB I/O; fake pinned identity used only in process.
    for variable, value in (
        ("FLASK_ENV", "production"),
        ("RAILWAY_PROJECT_ID", "e04f04a8-3aae-4aed-9073-638601f8ca30"),
        ("RAILWAY_SERVICE_ID", "3eecda71-9f53-4b33-a308-887d835b7fce"),
        ("DATABASE_URL", "postgresql+psycopg2://ci:ci@postgres-zzky.railway.internal:5432/railway"),
        ("STRIPE_SECRET_KEY", "ci-inert-not-a-real-secret"),
    ):
        test_env = env.copy()
        test_env[variable] = value
        preamble = """from dataclasses import replace
import lab_isolation
lab_isolation.LAB_IDENTITY = replace(
 lab_isolation.LAB_IDENTITY, web_service_id='ci-only-fictional-web-service',
 base_url='https://s01-lab-ci.invalid')
import app
"""
        blocked = subprocess.run(
            [sys.executable, "-c", preamble], cwd=ROOT, env=test_env,
            capture_output=True, text=True, timeout=60,
        )
        assert blocked.returncode != 0, ("unsafe lab booted", variable)
        assert "S01 lab isolation:" in blocked.stderr, ("missing guard", variable)
        assert "ci-inert-not-a-real-secret" not in blocked.stderr

    subprocess.run(
        [sys.executable, "-c", FAKE_LAB],
        cwd=ROOT, env=env, check=True, text=True, timeout=60,
    )
    print("STG-B04 PASS: lab runtime deliberately unpinned; fake identity safe; original staging regression in separate B01 suite")


if __name__ == "__main__":
    main()
