"""
CSV processing error tracking and auto-email.

Best-effort only: record_processing_error_safe() NEVER raises.
All DB and email failures are logged and swallowed internally.

Feature flag: PROCESSING_ERROR_EMAILS_ENABLED=true/false (default false)
Rate limit:   PROCESSING_ERROR_MAX_EMAILS_PER_HOUR (default 100)
"""
import os
import re
import hashlib
import logging
import traceback as tb
import concurrent.futures
from datetime import datetime, timedelta
from email_helpers import SUPPORT_FOOTER_TEXT

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LEN    = 500
_MAX_TRACEBACK_LEN  = 1500
_MAX_EMAILS_PER_HOUR = int(os.environ.get("PROCESSING_ERROR_MAX_EMAILS_PER_HOUR", "100"))


# ── SANITIZATION ──────────────────────────────────────────────────────────────

_REDACT_PATTERNS = [
    # Email addresses
    (re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), '[EMAIL]'),
    # Long hex strings (API keys, secrets, UUIDs without dashes)
    (re.compile(r'\b[a-fA-F0-9]{32,}\b'), '[TOKEN]'),
    # Long base64-ish strings
    (re.compile(r'[A-Za-z0-9+/]{40,}={0,2}'), '[TOKEN]'),
    # key=value / key: value for sensitive param names
    (re.compile(
        r'(?i)(bearer|token|api[-_]?key|apikey|secret|password|passwd|pwd)\s*[=:]\s*\S+'
    ), r'\1=[REDACTED]'),
]


def _sanitize(text: str, max_len: int) -> str:
    if not text:
        return ""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    if len(text) > max_len:
        text = text[:max_len] + "…[trunc]"
    return text


def _extract_traceback_short(exc: Exception) -> str:
    try:
        raw = "".join(tb.format_exception(type(exc), exc, exc.__traceback__))
        return _sanitize(raw, _MAX_TRACEBACK_LEN)
    except Exception:
        return ""


# ── FINGERPRINTING ────────────────────────────────────────────────────────────

def build_processing_error_fingerprint(
    exchange: str,
    stage: str,
    error_type: str,
    message_short: str,
) -> str:
    """
    Build a stable 16-char fingerprint for deduplication.

    Deliberately excludes: timestamps, user IDs, filenames, paths, line numbers.
    Same underlying bug → same fingerprint regardless of who triggered it.
    """
    msg = (message_short or "").lower().strip()
    msg = re.sub(r'\d+', 'N', msg)                    # line numbers, row counts → N
    msg = re.sub(r'(/[^/ \t\n]+)+', '/PATH', msg)     # filesystem paths
    msg = msg[:100]

    key = "|".join([
        (exchange   or "").lower().strip(),
        (stage      or "").lower().strip(),
        (error_type or "").lower().strip(),
        msg,
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ── CLASSIFICATION ────────────────────────────────────────────────────────────

_NON_ACTIONABLE_TYPES = frozenset({
    # SQLAlchemy / DB infra
    "OperationalError", "InterfaceError", "InternalError",
    "DatabaseError", "ProgrammingError",
    # Network / IO
    "TimeoutError", "ConnectionError", "ConnectionResetError",
    "ConnectionAbortedError", "ConnectionRefusedError",
    "BrokenPipeError", "OSError", "IOError",
    # Resource limits (already shown to user)
    "MemoryError",
    # Auth / permissions
    "PermissionError",
    # PDF / report generation — internal rendering problem, not user CSV
    "LayoutError",
    # Python internals — never user-triggered
    "SystemExit", "KeyboardInterrupt", "GeneratorExit",
})

_NON_ACTIONABLE_MSG_FRAGMENTS = (
    "timeout", "timed out",
    "rate limit", "too many requests",
    "network", "connection reset", "broken pipe", "refused",
    "railway", "fly.io", "heroku",
    "401", "403", "unauthorized", "forbidden",
    "login required", "session expired",
    "demasiadas filas", "too many rows",
    # PDF / reportlab internal errors — not caused by user CSV
    "flowable",     # reportlab LayoutError body ("Flowable with cell...")
    "reportlab",    # any direct reportlab reference
    "platypus",     # reportlab.platypus subpackage
    "frame too small",
)

_ACTIONABLE_TYPES = frozenset({
    # CSV format / parsing problems — directly user-fixable
    "KeyError", "ValueError",
    "UnicodeDecodeError", "UnicodeError",
    "AttributeError", "IndexError", "TypeError",
    "ParserError", "EmptyDataError",    # pandas
    "NotImplementedError", "StopIteration",
    "AssertionError",
})


def is_actionable_processing_error(
    error_type: str,
    stage: str,
    message_short: str,
) -> bool:
    """
    Returns True if this error is worth sending an automated support email.

    Actionable  = CSV format problem, unsupported column layout, encoding issue, edge case.
    Not actionable = transient infra errors, auth errors, resource limits.
    """
    if (error_type or "") in _NON_ACTIONABLE_TYPES:
        return False

    msg_lower = (message_short or "").lower()
    for fragment in _NON_ACTIONABLE_MSG_FRAGMENTS:
        if fragment in msg_lower:
            return False

    if (error_type or "") in _ACTIONABLE_TYPES:
        return True

    # Unknown type with no non-actionable signals → assume actionable
    return True


# ── USER-FRIENDLY MESSAGES ────────────────────────────────────────────────────

def make_user_friendly_message(
    error_type: str,
    stage: str,
    message_short: str,
) -> str:
    """
    Return a plain-language description of the error for the support email.
    No Python exception names, no tracebacks, no internal details.
    Checked in order — first match wins.
    """
    et  = (error_type    or "").strip()
    msg = (message_short or "").lower()

    # Date / time format problems (Binance "%y-%m-%d %H:%M:%S" etc.)
    if "time data" in msg or "does not match format" in msg or "strptime" in msg:
        return (
            "Hemos detectado un formato de fecha en el CSV que no hemos podido "
            "interpretar correctamente."
        )

    # Encoding / character set issues
    if et in ("UnicodeDecodeError", "UnicodeError") or "codec" in msg or "encoding" in msg:
        return (
            "El archivo CSV tiene una codificación que no hemos podido leer. "
            "Intenta descargarlo de nuevo desde tu exchange sin abrirlo con Excel."
        )

    # Empty or trivially broken file
    if et == "EmptyDataError" or "no columns" in msg or ("empty" in msg and "data" in msg):
        return "El archivo CSV parece estar vacío o no contiene datos válidos."

    # CSV structure / separator problems (ParserError, "Expected N fields")
    if et == "ParserError" or ("expected" in msg and "field" in msg) or "tokenize" in msg:
        return (
            "El CSV tiene un formato de separación de columnas que no hemos podido "
            "interpretar. Intenta descargarlo directamente desde tu exchange."
        )

    # Missing or renamed columns (KeyError on column name)
    if et == "KeyError" or ("column" in msg and ("not found" in msg or "missing" in msg)):
        return (
            "El CSV no contiene las columnas que esperábamos. "
            "Es posible que el formato de exportación de tu exchange haya cambiado."
        )

    # Generic fallback — keeps the email non-alarming
    return "Hemos detectado un formato de CSV que no hemos podido interpretar correctamente."


# ── DEDUPLICATION & RATE LIMITING ─────────────────────────────────────────────

def _should_send_email(session, user_id, exchange: str, fingerprint: str) -> bool:
    """
    Returns True only if:
    1. No email was sent for this user+exchange+fingerprint in the last 24h.
    2. Global hourly cap (_MAX_EMAILS_PER_HOUR) is not exceeded.
    """
    from models import ProcessingError
    from sqlalchemy import func

    now        = datetime.utcnow()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_1h  = now - timedelta(hours=1)

    # Per-user+exchange+fingerprint deduplication
    already_sent = (
        session.query(ProcessingError)
        .filter(
            ProcessingError.auto_email_sent.is_(True),
            ProcessingError.fingerprint == fingerprint,
            ProcessingError.user_id    == user_id,
            ProcessingError.exchange   == exchange,
            ProcessingError.auto_email_sent_at >= cutoff_24h,
        )
        .first()
    )
    if already_sent:
        return False

    # Global hourly cap
    recent_sent = (
        session.query(func.count(ProcessingError.id))
        .filter(
            ProcessingError.auto_email_sent.is_(True),
            ProcessingError.auto_email_sent_at >= cutoff_1h,
        )
        .scalar()
    ) or 0

    if recent_sent >= _MAX_EMAILS_PER_HOUR:
        logger.warning(
            "[ERROR_TRACKING] global email rate limit reached (%d/h), skipping auto-email",
            recent_sent,
        )
        return False

    return True


# ── EMAIL SENDING ─────────────────────────────────────────────────────────────

def send_processing_error_email(
    user_email: str,
    exchange: str,
    error_id: int,
    user_friendly_msg: str,
) -> bool:
    """
    Send auto-support email via Resend with a hard 5s timeout.
    user_friendly_msg must be a plain-language sentence (no tech details).
    Returns True if sent successfully. Raises on failure (caller handles).
    """
    import resend as _resend
    from email_templates import processing_error_email

    api_key    = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("RESEND_FROM_EMAIL", "noreply@marianosevilla.com")
    from_display = (
        from_email if "<" in from_email else f"Mariano Sevilla <{from_email}>"
    )

    if not api_key:
        logger.warning("[ERROR_TRACKING] RESEND_API_KEY not configured, skipping auto-email")
        return False

    exchange_display = (exchange or "tu exchange").capitalize()
    context_line     = user_friendly_msg or ""
    html, text       = processing_error_email(exchange_display, context_line)

    payload = {
        "from":    from_display,
        "to":      [user_email],
        "subject": f"Problema al procesar tu archivo de {exchange_display}",
        "html":    html,
        "text":    text,
    }

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_resend.Emails.send, payload)
        try:
            future.result(timeout=5.0)
        except concurrent.futures.TimeoutError:
            logger.error(
                "[ERROR_TRACKING] auto-email timed out after 5s error_id=%s", error_id
            )
            return False

    return True


# ── INTERNAL IMPLEMENTATION ───────────────────────────────────────────────────

def _do_record(
    *,
    user_id,
    email,
    exchange,
    stage,
    exc: Exception,
    csv_filename,
    csv_size,
    parser,
) -> None:
    from models import db, ProcessingError

    error_type      = type(exc).__name__
    message_short   = _sanitize(str(exc), _MAX_MESSAGE_LEN)
    traceback_short = _extract_traceback_short(exc)
    fingerprint     = build_processing_error_fingerprint(exchange, stage, error_type, message_short)
    safe_filename   = (os.path.basename(csv_filename)[:255] if csv_filename else None)

    record = ProcessingError(
        user_id         = user_id,
        email           = email,
        exchange        = exchange,
        parser          = parser,
        stage           = stage,
        error_type      = error_type,
        message_short   = message_short,
        traceback_short = traceback_short,
        fingerprint     = fingerprint,
        csv_filename    = safe_filename,
        csv_size        = csv_size,
        auto_email_sent = False,
    )

    try:
        db.session.add(record)
        db.session.commit()
        logger.info(
            "[ERROR_TRACKING] saved processing error id=%s fingerprint=%s",
            record.id, fingerprint,
        )
    except Exception as db_exc:
        db.session.rollback()
        logger.error("[ERROR_TRACKING] DB save failed: %s", db_exc)
        return  # Can't save → don't attempt email

    # ── Feature flag check ────────────────────────────────────────────────────
    if os.environ.get("PROCESSING_ERROR_EMAILS_ENABLED", "false").lower() != "true":
        return

    if not email:
        return

    if not is_actionable_processing_error(error_type, stage, message_short):
        logger.info(
            "[ERROR_TRACKING] auto-email skipped (non-actionable) error_type=%s stage=%s",
            error_type, stage,
        )
        return

    if not _should_send_email(db.session, user_id, exchange, fingerprint):
        logger.info(
            "[ERROR_TRACKING] auto-email skipped (deduplicated) fp=%s user_id=%s",
            fingerprint, user_id,
        )
        return

    user_friendly_msg = make_user_friendly_message(error_type, stage, message_short)

    try:
        sent = send_processing_error_email(email, exchange, record.id, user_friendly_msg)
        if sent:
            record.auto_email_sent    = True
            record.auto_email_sent_at = datetime.utcnow()
            try:
                db.session.commit()
                logger.info(
                    "[ERROR_TRACKING] auto-email sent error_id=%s to=%s",
                    record.id, email,
                )
            except Exception:
                db.session.rollback()
        else:
            logger.warning(
                "[ERROR_TRACKING] auto-email failed (send returned False) error_id=%s",
                record.id,
            )
    except Exception as email_exc:
        err_str = str(email_exc)[:500]
        logger.error(
            "[ERROR_TRACKING] auto-email failed error_id=%s: %s", record.id, err_str
        )
        try:
            record.email_send_error = err_str
            db.session.commit()
        except Exception:
            db.session.rollback()


# ── PUBLIC API ────────────────────────────────────────────────────────────────

def record_processing_error_safe(
    *,
    user_id=None,
    email=None,
    exchange=None,
    stage=None,
    exc: Exception,
    csv_filename=None,
    csv_size=None,
    parser=None,
) -> None:
    """
    Record a CSV processing error in the DB and optionally send an auto-email.

    NEVER raises. All DB and email failures are logged and discarded.
    Safe to call from /api/analizar's except block without any risk.
    """
    try:
        _do_record(
            user_id=user_id,
            email=email,
            exchange=exchange,
            stage=stage,
            exc=exc,
            csv_filename=csv_filename,
            csv_size=csv_size,
            parser=parser,
        )
    except Exception:
        logger.exception("[ERROR_TRACKING] unexpected failure in record_processing_error_safe — ignoring")
