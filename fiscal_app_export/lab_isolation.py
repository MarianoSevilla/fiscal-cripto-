"""S01-LAB-LOCK: separate Railway S01 laboratory private-only preflight.

No database, HTTP, provider or other I/O occurs in this module. ID pins came
from read-only Railway service inventory, NOT from user-provided environment
flags. For lab: do not attach public domains, do not enable payment/email,
and do not bypass the early guard. Origin uses HTTP over Railway's encrypted
project/environment-scoped WireGuard private network, NOT the public edge.

Pinning IDs in GitHub does NOT authorize Railway variables, migrations or deploy.
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
    web_service_id: str
    base_url: str
    db_hostname: str


LAB_IDENTITY = LabIdentity(
    project_id="5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e",
    environment_id="3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8",
    web_service_id="212f4f52-b349-4387-a046-9f6b08237d2e",
    base_url="http://s01-lab-web.railway.internal:8080",
    db_hostname="postgres-im3h.railway.internal",
)

LAB_FORBIDDEN_CREDENTIALS = DISABLED_STAGING_CREDENTIALS + (
    "TURNSTILE_SECRET_KEY", "TURNSTILE_SITE_KEY", "STRIPE_PUBLISHABLE_KEY",
)
LAB_DISABLED_FEATURE_FLAGS = (
    "ENABLE_ADVISORY_STATUS_EMAILS",
    "ENABLE_ADVISORY_UPLOADS",
    "PROCESSING_ERROR_EMAILS_ENABLED",
)


def is_lab_candidate(env: Mapping[str, str], *, identity: LabIdentity | None = None) -> bool:
    """Any one lab runtime marker forces a full fail-closed identity check."""
    pins = LAB_IDENTITY if identity is None else identity
    return (
        env.get("RAILWAY_PROJECT_ID") == pins.project_id
        or env.get("RAILWAY_ENVIRONMENT_ID") == pins.environment_id
        or env.get("RAILWAY_SERVICE_ID") == pins.web_service_id
        or str(env.get("RAILWAY_ENVIRONMENT_NAME", "")).strip().lower() == "lab"
        or env.get("APP_BASE_URL") == pins.base_url
    )


def validate_lab_isolation(
    env: Mapping[str, str], *, identity: LabIdentity | None = None
) -> bool:
    """Validate before any SQLAlchemy initialization or provider interaction.

    The explicit identity parameter is for synthetic unit tests ONLY; the
    Flask app imports and uses LAB_IDENTITY without external overrides.
    """
    pins = LAB_IDENTITY if identity is None else identity
    if not is_lab_candidate(env, identity=pins):
        return False

    try:
        approved = urlsplit(pins.base_url)
        origin_ok = (
            approved.scheme == "http"
            and bool(approved.hostname)
            and approved.hostname.endswith(".railway.internal")
            and approved.port == 8080
            and approved.netloc == f"{approved.hostname}:8080"
            and not approved.path and not approved.query and not approved.fragment
            and not approved.username and not approved.password
        )
    except (ValueError, TypeError):
        origin_ok = False
    if not origin_ok or not pins.web_service_id:
        raise RuntimeError("S01 lab isolation: private web origin or identity invalid")

    expected = {
        "RAILWAY_PROJECT_ID": pins.project_id,
        "RAILWAY_ENVIRONMENT_ID": pins.environment_id,
        "RAILWAY_SERVICE_ID": pins.web_service_id,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "FLASK_ENV": "staging",
        "RAILWAY_PRIVATE_DOMAIN": approved.hostname,
        "PORT": "8080",
        "APP_BASE_URL": pins.base_url,
        "PAYPAL_ENVIRONMENT": "sandbox",
    }
    for name, value in expected.items():
        if env.get(name) != value:
            raise RuntimeError("S01 lab isolation: invalid environment identity: " + name)

    # This is a configuration tripwire, NOT proof of the service's live
    # Railway network settings. Independently verify no public domains/TCP.
    for name in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL"):
        if (env.get(name) or "").strip():
            raise RuntimeError("S01 lab isolation: public exposure marker present: " + name)

    try:
        url = urlsplit(env.get("DATABASE_URL", ""))
        db_ok = (
            url.scheme in ("postgresql", "postgresql+psycopg2")
            and url.hostname == pins.db_hostname
            and url.port == 5432
            and url.path == "/railway"
            and bool(url.username)
            and bool(url.password)
            and not url.query and not url.fragment
        )
    except (TypeError, ValueError):
        db_ok = False
    if not db_ok:
        raise RuntimeError("S01 lab isolation: DATABASE_URL must target private lab PostgreSQL")

    for name in LAB_FORBIDDEN_CREDENTIALS:
        if (env.get(name) or "").strip():
            raise RuntimeError("S01 lab isolation: disabled external credential present: " + name)

    for name in LAB_DISABLED_FEATURE_FLAGS:
        if (env.get(name) or "").strip().lower() not in ("", "false", "0", "no", "off"):
            raise RuntimeError("S01 lab isolation: forbidden active feature: " + name)
    return True


def lab_request_denial(
    *, host: str, path: str, method: str, origin: str | None = None,
    identity: LabIdentity | None = None,
) -> tuple[int, str] | None:
    """Only the health endpoint is available, everything else denies."""
    pins = LAB_IDENTITY if identity is None else identity
    trusted = urlsplit(pins.base_url).netloc.lower()
    if host.lower() == RAILWAY_HEALTHCHECK_HOST:
        if path == "/healthz" and method.upper() in ("GET", "HEAD") and origin is None:
            return None
        return 421, "S01 lab host not authorized"
    if host.lower() != trusted:
        return 421, "S01 lab host not authorized"
    if origin and origin != pins.base_url:
        return 403, "S01 lab origin not authorized"
    if path == "/healthz" and method.upper() in ("GET", "HEAD"):
        return None
    return 503, "S01 lab route not explicitly permitted"


def install_lab_email_barrier(resend_module) -> None:
    """Process-wide refusal, including background-thread Resend calls."""
    def refuse(*_args, **_kwargs):
        raise RuntimeError("S01 lab isolation: outbound email disabled")
    resend_module.Emails.send = refuse
