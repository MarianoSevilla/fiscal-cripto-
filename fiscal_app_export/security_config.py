"""Fail-closed session configuration, without app imports or database access.

FLASK_ENV is an application setting here (Flask 3 no longer interprets it).
Only explicit local development/tests may use HTTP cookies or a fallback key.
"""
from collections.abc import Mapping
import warnings


DEVELOPMENT_SECRET = "dev-only-insecure-key-change-me"
_LOCAL_MODES = {"development", "testing"}
_SECURE_MODES = {"production", "staging"}
_DEPLOYMENT_MARKERS = (
    "RAILWAY_ENVIRONMENT_ID", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID", "RAILWAY_DEPLOYMENT_ID", "RAILWAY_PUBLIC_DOMAIN",
    "RAILWAY_PRIVATE_DOMAIN", "PORT", "SERVER_SOFTWARE",
)


def build_security_config(env: Mapping[str, str]) -> dict:
    """Validate before DB initialization; errors never include supplied values.

    An absent/blank mode selects production policy, including off Railway.
    Presence (even empty) of deployment markers disallows local exceptions.
    Preserve a supplied key byte-for-byte so existing signatures remain valid.
    DEBUG/TESTING stay disabled as before; isolated fixtures opt in themselves.
    """
    mode = env.get("FLASK_ENV", "").strip().lower() or "production"
    if mode not in _LOCAL_MODES | _SECURE_MODES:
        raise RuntimeError("Unsupported FLASK_ENV; startup refused.")

    deployed = any(name in env for name in _DEPLOYMENT_MARKERS)
    local = mode in _LOCAL_MODES
    if local and deployed:
        raise RuntimeError("Local development/testing mode is forbidden in a deployed service.")

    # Match Flask CLI's false values; 'off' or whitespace are NOT false there.
    if not local and env.get("FLASK_DEBUG", "").lower() not in {"", "0", "false", "no"}:
        raise RuntimeError("FLASK_DEBUG must be disabled in a deployed/secure environment.")

    secret = env.get("SECRET_KEY")
    if secret is None or not secret.strip():
        if not local:
            raise RuntimeError("SECRET_KEY is missing or blank; startup refused.")
        warnings.warn(
            "Using the development session key in explicit local development/testing only.",
            stacklevel=2,
        )
        secret = DEVELOPMENT_SECRET
    elif not local and secret.strip() == DEVELOPMENT_SECRET:
        raise RuntimeError("Development SECRET_KEY is forbidden in a deployed/secure environment.")

    return {
        "RUNTIME_MODE": mode,
        "SECRET_KEY": secret,
        "DEBUG": False,
        "TESTING": False,
        "SESSION_COOKIE_SECURE": not local,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "REMEMBER_COOKIE_SECURE": not local,
        "REMEMBER_COOKIE_HTTPONLY": True,
        "REMEMBER_COOKIE_SAMESITE": "Lax",
    }
