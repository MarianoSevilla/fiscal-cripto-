"""S01-LAB-LOCK: deny-by-default Railway lab guard, inert outside the lab.

Security contract:
- The lab project/environment are real, separate Railway IDs.
- There is NO lab web service yet. Until its real service ID and approved HTTPS
  origin are pinned in reviewed code, lab Flask startup MUST fail closed.
- No database, HTTP or provider I/O happens in this module.
- A generic env switch (LAB_MODE etc.) cannot lift the guard.
- STG-LOCK-001 is independently enforced for the original staging environment.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from staging_isolation import (
    DISABLED_STAGING_CREDENTIALS,
    RAILWAY_HEALTHCHECK_HOST,
)


@dataclass(frozen=True)
class LabIdentity:
    project_id: str
    environment_id: str
    # A web service has NOT been created/authorized. Do not guess the ID.
    web_service_id: str | None
    # No public or internal approved HTTPS origin has been authorized.
    base_url: str | None
    # Expected project-private PostgreSQL host. Verify the actual reference
    # independently before any deployment, even though the PG endpoint is "postgres".
    db_hostname: str


LAB_IDENTITY = LabIdentity(
    project_id="5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e",
    environment_id="3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8",
    web_service_id=None,  # STG-B04 deliberate NO-GO until a new scoped approval
    base_url=None,  # STG-B04 deliberate NO-GO until reviewed host/Origin
    db_hostname="postgres.railway.internal",
)

# Any credential in a lab service is a misconfiguration, even a provider "test"
# key. Some flags are permitted only if explicitly disabled.
LAB_FORBIDDEN_CREDENTIALS = DISABLED_STAGING_CREDENTIALS + (
    "TURNSTILE_SECRET_KEY", "TURNSTILE_SITE_KEY", "STRIPE_PUBLISHABLE_KEY",
)
LAB_DISABLED_FEATURE_FLAGS = (
    "ENABLE_ADVISORY_STATUS_EMAILS",
    "ENABLE_ADVISORY_UPLOADS",
    "PROCESSING_ERROR_EMAILS_ENABLED",
)


def is_lab_candidate(env: Mapping[str, str], *, identity: LabIdentity | None = None) -> bool:
    """Detect any lab marker, including deliberate mode/project mismatches."""
    pins = LAB_IDENTITY if identity is None else identity
    return (
        env.get("RAILWAY_PROJECT_ID") == pins.project_id
        or env.get("RAILWAY_ENVIRONMENT_ID") == pins.environment_id
        or str(env.get("RAILWAY_ENVIRONMENT_NAME", "")).strip().lower() == "lab"
        or (
            bool(pins.web_service_id)
            and env.get("RAILWAY_SERVICE_ID") == pins.web_service_id
        )
    )


def validate_lab_isolation(
    env: Mapping[str, str], *, identity: LabIdentity | None = None
) -> bool:
    """Fail BEFORE db.init_app, Alembic and any web route for unsafe lab.

    A caller may supply an identity only in synthetic unit/integration tests.
    Production entrypoint uses the hardcoded LAB_IDENTITY (still intentionally
    missing the future web service ID and approved origin).
    """
    pins = LAB_IDENTITY if identity is None else identity
    if not is_lab_candidate(env, identity=pins):
        return False

    if not pins.web_service_id or not pins.base_url:
        raise RuntimeError("S01 lab isolation: web identity and origin not pinned")

    expected = {
        "RAILWAY_PROJECT_ID": pins.project_id,
        "RAILWAY_ENVIRONMENT_ID": pins.environment_id,
        "RAILWAY_SERVICE_ID": pins.web_service_id,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "FLASK_ENV": "staging",
        "APP_BASE_URL": pins.base_url,
        "PAYPAL_ENVIRONMENT": "sandbox",
    }
    for name, value in expected.items():
        if env.get(name) != value:
            raise RuntimeError("S01 lab isolation: invalid environment identity: " + name)

    approved = urlsplit(pins.base_url)
    if (
        approved.scheme != "https"
        or not approved.hostname
        or approved.path not in ("", "/")
        or approved.query or approved.fragment
        or approved.username or approved.password
    ):
        raise RuntimeError("S01 lab isolation: invalid approved HTTPS origin")

    try:
        url = urlsplit(env.get("DATABASE_URL", ""))
        db_ok = (
            url.scheme == "postgresql+psycopg2"
            and url.hostname == pins.db_hostname
            and url.port == 5432
            and url.path == "/railway"
            and bool(url.username)
            and bool(url.password)
            and not url.query
            and not url.fragment
        )
    except (TypeError, ValueError):
        db_ok = False
    if not db_ok:
        raise RuntimeError("S01 lab isolation: DATABASE_URL must target dedicated lab PostgreSQL")

    for key in LAB_FORBIDDEN_CREDENTIALS:
        if (env.get(key) or "").strip():
            raise RuntimeError("S01 lab isolation: disabled external credential present: " + key)
    for key in LAB_DISABLED_FEATURE_FLAGS:
        if (env.get(key) or "").strip().lower() not in ("", "false", "0", "off", "no"):
            raise RuntimeError("S01 lab isolation: forbidden active feature: " + key)
    return True


def lab_request_denial(
    *, host: str, path: str, method: str, origin: str | None = None,
    identity: LabIdentity | None = None,
) -> tuple[int, str] | None:
    """Preflight phase is healthcheck-only. All APIs/auth/payments stay 503.

    Do not add synthetic login or payment routes until an independent lab-only
    authorization/test phase has been developed and approved.
    """
    pins = LAB_IDENTITY if identity is None else identity
    if not pins.web_service_id or not pins.base_url:
        return 503, "S01 lab not enabled"
    if host.lower() == RAILWAY_HEALTHCHECK_HOST:
        if path == "/healthz" and method.upper() in ("GET", "HEAD") and origin is None:
            return None
        return 421, "S01 lab host not authorized"
    trusted = urlsplit(pins.base_url).netloc.lower()
    if not trusted or host.lower() != trusted:
        return 421, "S01 lab host not authorized"
    if origin and origin != pins.base_url:
        return 403, "S01 lab origin not authorized"
    if path == "/healthz" and method.upper() in ("GET", "HEAD"):
        return None
    return 503, "S01 lab route not explicitly permitted"


def install_lab_email_barrier(resend_module) -> None:
    """Refuse all Resend calls, including background tasks, regardless of key."""
    def refuse(*_args, **_kwargs):
        raise RuntimeError("S01 lab isolation: outbound email disabled")
    resend_module.Emails.send = refuse
