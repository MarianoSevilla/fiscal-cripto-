"""STG-LOCK-001: deliberately inert outside the designated Railway staging service.

This is a *preflight lockdown*, not an implementation of payment sandboxes.
It must execute before Flask touches a database or performs bootstrap DDL.
Never include secret values in errors, logs, or responses.
"""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit


STAGING_BASE_URL = "https://fiscal-cripto-staging-staging.up.railway.app"
STAGING_HOST = "fiscal-cripto-staging-staging.up.railway.app"
STAGING_DB_HOST = "postgres-zzky.railway.internal"
STAGING_PROJECT_ID = "e04f04a8-3aae-4aed-9073-638601f8ca30"
STAGING_ENVIRONMENT_ID = "b2937140-78f7-4347-a9bc-c96333e03b9b"
STAGING_SERVICE_ID = "3eecda71-9f53-4b33-a308-887d835b7fce"

# Until the S00/S01 reconciliation contract has been independently approved,
# never allow staging to call a real provider or send email.
DISABLED_STAGING_CREDENTIALS = (
    "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID",
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "RESEND_API_KEY",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
)


def is_staging_candidate(env: Mapping[str, str]) -> bool:
    """Fail closed if *any* staging identity appears, including a wrong FLASK_ENV."""
    return (
        str(env.get("FLASK_ENV", "")).strip().lower() == "staging"
        or str(env.get("RAILWAY_ENVIRONMENT_NAME", "")).strip().lower() == "staging"
        or env.get("RAILWAY_ENVIRONMENT_ID") == STAGING_ENVIRONMENT_ID
        or env.get("RAILWAY_SERVICE_ID") == STAGING_SERVICE_ID
    )


def validate_staging_isolation(env: Mapping[str, str]) -> bool:
    """Return True only for explicitly verified staging. No DB or network I/O.

    Production passes through untouched. A mislabeled staging runtime aborts
    *before* db.create_all() / bootstrap_db.py can operate on its DATABASE_URL.
    """
    if not is_staging_candidate(env):
        return False

    identity = {
        "FLASK_ENV": "staging",
        "RAILWAY_ENVIRONMENT_NAME": "staging",
        "RAILWAY_ENVIRONMENT_ID": STAGING_ENVIRONMENT_ID,
        "RAILWAY_SERVICE_ID": STAGING_SERVICE_ID,
        "RAILWAY_PROJECT_ID": STAGING_PROJECT_ID,
        "APP_BASE_URL": STAGING_BASE_URL,
        "PAYPAL_ENVIRONMENT": "sandbox",
    }
    for name, expected in identity.items():
        if env.get(name) != expected:
            raise RuntimeError("Staging isolation: required environment identity mismatch: " + name)

    try:
        url = urlsplit(env.get("DATABASE_URL", ""))
        db_ok = (
            url.scheme == "postgresql+psycopg2"
            and url.hostname == STAGING_DB_HOST
            and url.port == 5432
            and url.path == "/railway"
            and url.username is not None
            and bool(url.password)
            and not url.query
            and not url.fragment
        )
    except (TypeError, ValueError):
        db_ok = False
    if not db_ok:
        raise RuntimeError("Staging isolation: DATABASE_URL must reference dedicated staging PostgreSQL")

    for name in DISABLED_STAGING_CREDENTIALS:
        if (env.get(name) or "").strip():
            raise RuntimeError("Staging isolation: external credential must remain disabled: " + name)
    return True


def staging_request_denial(*, host: str, path: str, method: str, origin: str | None = None) -> tuple[int, str] | None:
    """Restrict the preflight runtime before any endpoint or provider is reached.

    All state-changing requests are disabled until staging data is certified.
    No PayPal return URL (GET) or signed webhook is processed in this phase.
    """
    if host.lower().split(":", 1)[0] != STAGING_HOST:
        return 421, "Staging host not authorized"
    if origin and origin != STAGING_BASE_URL:
        return 403, "Staging origin not authorized"
    if method.upper() not in ("GET", "HEAD", "OPTIONS"):
        return 503, "Staging changes temporarily disabled"
    # Read-only API paths may still disclose data, consume single-use tokens,
    # call third parties or change DB state. Dataset provenance is not yet
    # certified: only public static pages and /healthz stay reachable.
    if (path.startswith(("/api/", "/admin/", "/auth/google", "/pagar/", "/mis-solicitudes-fiscales"))
            or path in ("/api", "/admin", "/pagar", "/static/pagar.html")):
        return 503, "Staging API or sensitive route disabled"
    return None


def install_staging_email_barrier(resend_module) -> None:
    """Additional process-wide belt-and-braces block, including threads.

    This does not replace fail-fast rejection of RESEND_API_KEY above.
    """
    def refuse_staging_email(*_args, **_kwargs):
        raise RuntimeError("Staging isolation: outbound email disabled")

    resend_module.Emails.send = refuse_staging_email
