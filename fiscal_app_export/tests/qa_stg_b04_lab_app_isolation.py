"""STG-B06 synthetic Railway lab import and private-only Flask firewall test.

GitHub Actions only. Fake env metadata uses real pinned IDs but no Railway
runtime, network, database or external providers. Test sockets are disabled.
No real Railway project is connected or modified.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LAB_ORIGIN = "http://s01-lab-web.railway.internal:8080"

NO_NETWORK = r'''
import socket

def refuse(*_args, **_kwargs):
    raise AssertionError("S01 lab CI must not connect to any network or DB")

socket.socket.connect = refuse
import psycopg2
psycopg2.connect = refuse
import requests
requests.sessions.Session.request = refuse
'''

FLASK_SMOKE = NO_NETWORK + r'''
import os
from app import app, _LAB_ISOLATED, _STAGING_ISOLATED, _PAYPAL_ENABLED
from lab_isolation import LAB_IDENTITY

assert _LAB_ISOLATED is True
assert _STAGING_ISOLATED is False
assert _PAYPAL_ENABLED is False
assert LAB_IDENTITY.web_service_id == os.environ["RAILWAY_SERVICE_ID"]
assert app.config["SESSION_COOKIE_SECURE"] is True
assert app.config["SQLALCHEMY_DATABASE_URI"].endswith("@postgres-im3h.railway.internal:5432/railway")
assert "bootstrap_db.py" not in open("Procfile", encoding="utf-8").read()

cli = app.test_client()

def check(method, path, expected, base="http://s01-lab-web.railway.internal:8080", headers=None):
    response = cli.open(path, method=method, base_url=base, headers=headers or {})
    assert response.status_code == expected, (
        method, path, response.status_code, expected
    )
    return response

assert check("GET", "/healthz", 200).get_json()["ok"]
check("HEAD", "/healthz", 200, "https://healthcheck.railway.app")
check("GET", "/healthz", 200, "https://healthcheck.railway.app")

for method, path in (
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
    ("GET", "/api/admin/comunicaciones/campaigns"),
    ("POST", "/api/contacto"),
    ("POST", "/signup/"),
    ("GET", "/admin"),
    ("POST", "/healthz"),
):
    result = check(method, path, 503)
    assert result.headers["Cache-Control"] == "no-store"
    assert result.headers["Retry-After"] == "300"

check("GET", "/healthz", 421, "https://www.marianosevilla.com")
check("GET", "/api/me", 421, "https://healthcheck.railway.app")
check("GET", "/healthz", 421, "https://healthcheck.railway.app",
      {"Origin": "http://s01-lab-web.railway.internal:8080"})
check("GET", "/healthz", 403,
      "http://s01-lab-web.railway.internal:8080",
      {"Origin": "https://www.marianosevilla.com"})
check("GET", "/healthz", 421, "http://s01-lab-web.railway.internal")
check("GET", "/healthz", 421, "http://s01-lab-web.railway.internal:8081")

assert os.environ["S01_LAB_MODE"] == "true"  # Ignored; no bypass
check("POST", "/api/webhooks/stripe", 503)
print("STG-B06 Flask PASS: pinned Railway identity, private HTTP origin, "
      "20 sensitive routes 503, strict hosts/origins, no DB/network/providers")
'''


def main() -> None:
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("CI") == "true"
    assert os.environ.get("FLASK_ENV") == "testing"

    root = os.environ.copy()
    for key in tuple(root):
        if key.startswith("RAILWAY_") or key in (
            "DATABASE_URL", "SECRET_KEY", "FLASK_ENV", "APP_BASE_URL",
            "ADMIN_EMAILS", "FISCAL_ADVISOR_EMAILS", "PAYPAL_ENVIRONMENT",
            "S01_LAB_MODE", "S01_SYNTHETIC_LAB_MODE",
            "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID",
            "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "RESEND_API_KEY",
            "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PORT",
            "TURNSTILE_SECRET_KEY", "TURNSTILE_SITE_KEY",
            "STRIPE_PUBLISHABLE_KEY", "ENABLE_ADVISORY_STATUS_EMAILS",
            "ENABLE_ADVISORY_UPLOADS", "PROCESSING_ERROR_EMAILS_ENABLED",
        ):
            root.pop(key)

    env = root.copy()
    env.update({
        "FLASK_ENV": "staging",
        "SECRET_KEY": "CI-INERT-LAB-SESSION-NOT-REAL",
        "RAILWAY_PROJECT_ID": "5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e",
        "RAILWAY_ENVIRONMENT_ID": "3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8",
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": "212f4f52-b349-4387-a046-9f6b08237d2e",
        "RAILWAY_PRIVATE_DOMAIN": "s01-lab-web.railway.internal",
        "PORT": "8080",
        "APP_BASE_URL": LAB_ORIGIN,
        "PAYPAL_ENVIRONMENT": "sandbox",
        # Representative of the template's reference syntax at runtime.
        "DATABASE_URL": "postgresql://ci:ci-only@postgres-im3h.railway.internal:5432/railway",
        "S01_LAB_MODE": "true",
    })

    bad_settings = (
        ("FLASK_ENV", "production"),
        ("RAILWAY_PROJECT_ID", "e04f04a8-3aae-4aed-9073-638601f8ca30"),
        ("RAILWAY_SERVICE_ID", "3eecda71-9f53-4b33-a308-887d835b7fce"),
        ("RAILWAY_PRIVATE_DOMAIN", "www.marianosevilla.com"),
        ("PORT", "8081"),
        ("APP_BASE_URL", "https://www.marianosevilla.com"),
        ("RAILWAY_PUBLIC_DOMAIN", "lab.up.railway.app"),
        ("DATABASE_URL", "postgresql://ci:ci@postgres-zzky.railway.internal:5432/railway"),
        ("DATABASE_URL", "postgresql://ci:ci@postgres.railway.internal:5432/railway"),
        ("STRIPE_SECRET_KEY", "ci-fake-not-a-real-secret"),
    )
    for variable, bad_value in bad_settings:
        unsafe = env.copy()
        unsafe[variable] = bad_value
        checked = subprocess.run(
            [sys.executable, "-c", NO_NETWORK + "\nimport app"],
            cwd=ROOT, env=unsafe, capture_output=True, text=True, timeout=60,
        )
        assert checked.returncode != 0, ("bad lab identity unexpectedly booted", variable)
        assert "S01 lab isolation:" in checked.stderr, ("missing guard", variable)
        assert "ci-fake-not-a-real-secret" not in checked.stderr

    subprocess.run(
        [sys.executable, "-c", FLASK_SMOKE],
        cwd=ROOT, env=env, check=True, text=True, timeout=60,
    )
    print("STG-B06 PASS: private-only lab identity pinned in code; "
          "staging lock independent; no Railway actions")


if __name__ == "__main__":
    main()
