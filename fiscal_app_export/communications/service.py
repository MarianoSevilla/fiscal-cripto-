"""
Business logic for the communications module.
Pure functions — no direct Flask app object dependency.
Imports db models and uses the SQLAlchemy session within the active app context.
"""
import os
import uuid
import threading
import time
import logging
from datetime import datetime
from typing import Optional

import resend

from models import db, User, CommunicationCampaign, CommunicationDelivery
from .email_sender import render_campaign_html, render_campaign_text

logger = logging.getLogger(__name__)

_RESEND_FROM  = os.environ.get("RESEND_FROM_EMAIL", "noreply@marianosevilla.com")
_APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://www.marianosevilla.com")

# Ensure the From field includes a human display name.
# Resend (and SMTP) accept "Display Name <email@domain.com>" format.
_RESEND_FROM_DISPLAY = (
    _RESEND_FROM if "<" in _RESEND_FROM
    else f"Mariano Sevilla <{_RESEND_FROM}>"
)

# Mirrors ADMIN_EMAILS from app.py — evaluated once at import time.
# If the env var changes at runtime (rare), restart the process.
_ADMIN_EMAILS = frozenset(
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
)

# Excluded roles — never receive campaigns
_EXCLUDED_ROLES = {"admin", "fiscal_advisor"}

# Valid recipient segments
VALID_SEGMENTS = frozenset({"all", "verified", "unverified"})

# ── SEND RATE LIMITING ────────────────────────────────────────────────────────
# Resend free/paid limit: 5 req/sec.  We target ≤4 to stay comfortably under.
# Override with CAMPAIGN_SEND_DELAY_MS env var (e.g. "250" for 4/sec).
# sleep(_SEND_DELAY_S) is called AFTER every individual send, so the effective
# rate is 1 / (_SEND_DELAY_S + api_call_latency) — always ≤ 1/_SEND_DELAY_S.
_SEND_DELAY_S: float = float(os.environ.get("CAMPAIGN_SEND_DELAY_MS", "250")) / 1000.0

# Keywords that identify a Resend 429 / rate-limit error in the exception string
_RATE_LIMIT_SIGNALS = ("429", "too many requests", "rate limit", "rate_limit")


# ── HELPERS ──────────────────────────────────────────────────────────────────

def _ensure_unsub_token(user: User) -> str:
    """Lazily assigns an unsubscribe token if the user doesn't have one."""
    if not user.comms_unsubscribe_token:
        user.comms_unsubscribe_token = uuid.uuid4().hex
        db.session.add(user)
        db.session.flush()
    return user.comms_unsubscribe_token


# ── QUERIES ──────────────────────────────────────────────────────────────────

def _base_recipients_query():
    """
    Base query: active users, not opted-out, not admin/advisor roles,
    not in ADMIN_EMAILS env var.
    Does NOT filter by email_verified_at — callers apply that via segment.
    """
    q = User.query.filter(
        User.is_active.is_(True),
        User.comms_opted_out.is_(False),
        User.role.notin_(list(_EXCLUDED_ROLES)),
    )
    if _ADMIN_EMAILS:
        q = q.filter(~User.email.in_(list(_ADMIN_EMAILS)))
    return q


def get_eligible_recipients_query(segment: str = "all"):
    """
    Returns a query for campaign-eligible users filtered by segment.

    Segments:
      "all"        — active + not opted-out (verified and unverified)
      "verified"   — only email-confirmed users (email_verified_at IS NOT NULL)
      "unverified" — only users who haven't confirmed their email yet
    All segments exclude: inactive, opted-out, admin/advisor roles, ADMIN_EMAILS.
    """
    q = _base_recipients_query()
    if segment == "verified":
        q = q.filter(User.email_verified_at.isnot(None))
    elif segment == "unverified":
        q = q.filter(User.email_verified_at.is_(None))
    # "all" — no additional verification filter
    return q


def count_eligible_recipients(segment: str = "all") -> int:
    return get_eligible_recipients_query(segment).count()


def count_eligible_recipients_all_segments() -> dict:
    """Returns recipient counts for all three segments in a single call."""
    return {
        "all":        count_eligible_recipients("all"),
        "verified":   count_eligible_recipients("verified"),
        "unverified": count_eligible_recipients("unverified"),
    }


# ── CAMPAIGN CRUD ─────────────────────────────────────────────────────────────

def delete_campaign(campaign_id: int) -> tuple[bool, str]:
    """
    Hard-delete a campaign and its deliveries.

    Returns (True, "") on success, (False, error_message) on refusal.

    Blocked:
    - status 'sending' or 'queued'  → in-flight, cannot interrupt.
    - status 'sent' with ≥1 delivery.status='sent' → real emails sent,
      keep for traceability.
    Allowed:
    - draft, failed, cancelled        → always.
    - sent with zero real deliveries  → test/empty run, safe to drop.
    """
    campaign = CommunicationCampaign.query.get(campaign_id)
    if not campaign:
        return False, "Campaña no encontrada."

    if campaign.status in ("sending", "queued"):
        return False, (
            f"No se puede eliminar una campaña en estado '{campaign.status}'. "
            "Espera a que el envío termine."
        )

    if campaign.status == "sent":
        real_sent = (
            CommunicationDelivery.query
            .filter_by(campaign_id=campaign_id, status="sent")
            .count()
        )
        if real_sent > 0:
            return False, (
                "No se puede eliminar una campaña enviada con entregas registradas. "
                "Se conserva por trazabilidad."
            )

    # Safe to delete — remove child rows first (FK constraint), then parent
    CommunicationDelivery.query.filter_by(campaign_id=campaign_id).delete()
    db.session.delete(campaign)
    db.session.commit()
    logger.info("Campaign %s deleted (was status=%s)", campaign_id, campaign.status)
    return True, ""


def create_campaign_draft(
    subject: str,
    body: str,
    preview_text: str,
    admin_user_id: int,
    recipient_segment: str = "all",
) -> CommunicationCampaign:
    seg = recipient_segment if recipient_segment in VALID_SEGMENTS else "all"
    campaign = CommunicationCampaign(
        subject=subject.strip(),
        body=body.strip(),
        preview_text=(preview_text or "").strip()[:200],
        status="draft",
        created_by_id=admin_user_id,
        idempotency_key=uuid.uuid4().hex,
        recipient_segment=seg,
    )
    db.session.add(campaign)
    db.session.commit()
    return campaign


def update_campaign_draft(
    campaign: CommunicationCampaign,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    preview_text: Optional[str] = None,
    recipient_segment: Optional[str] = None,
) -> CommunicationCampaign:
    if subject is not None:
        campaign.subject = subject.strip()[:500]
    if body is not None:
        campaign.body = body.strip()
    if preview_text is not None:
        campaign.preview_text = preview_text.strip()[:200]
    if recipient_segment is not None and recipient_segment in VALID_SEGMENTS:
        campaign.recipient_segment = recipient_segment
    db.session.commit()
    return campaign


# ── EMAIL SEND ────────────────────────────────────────────────────────────────

def send_test_email(campaign: CommunicationCampaign, to_email: str) -> dict:
    """Sends a single test email to the admin. Not logged as a delivery."""
    if not resend.api_key:
        return {"ok": False, "error": "RESEND_API_KEY no configurada."}

    html = render_campaign_html(campaign, unsubscribe_url="#test-no-action")
    text = render_campaign_text(campaign)

    try:
        result = resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [to_email],
            "subject": f"[TEST] {campaign.subject}",
            "html":    html,
            "text":    text,
        })
        provider_id = result.get("id", "") if isinstance(result, dict) else ""
        return {"ok": True, "provider_id": provider_id}
    except Exception as exc:
        logger.error("Test email failed to %s: %s", to_email, exc)
        return {"ok": False, "error": str(exc)}


def dispatch_campaign(campaign_id: int, app_context) -> None:
    """
    Launches campaign dispatch in a background daemon thread.
    The Flask app_context is passed so the thread can push it.
    Status transitions handled inside _execute_campaign.
    """
    def _run():
        with app_context:
            _execute_campaign(campaign_id)

    thread = threading.Thread(
        target=_run,
        name=f"campaign-send-{campaign_id}",
        daemon=True,
    )
    thread.start()
    logger.info("Campaign %s dispatch thread started", campaign_id)


def _is_rate_limit_error(exc: Exception) -> bool:
    """Returns True if the exception looks like a Resend 429 rate-limit error."""
    msg = str(exc).lower()
    return any(sig in msg for sig in _RATE_LIMIT_SIGNALS)


def _execute_campaign(campaign_id: int) -> None:
    """
    Core send loop. Runs in a background thread with app context.

    Rate limiting:  sleeps _SEND_DELAY_S after every individual send so the
                    effective rate is ≤ 1/_SEND_DELAY_S req/sec (default 4/sec),
                    safely under Resend's 5 req/sec limit.

    Final statuses:
      sent             — all recipients received the email.
      partial_success  — some sent, some failed.
      failed           — all failed (or loop-level exception).
    """
    campaign = CommunicationCampaign.query.get(campaign_id)
    if not campaign:
        logger.error("Campaign %s not found in _execute_campaign", campaign_id)
        return
    if campaign.status != "queued":
        logger.warning(
            "Campaign %s expected 'queued', got '%s' — aborting",
            campaign_id, campaign.status,
        )
        return

    try:
        campaign.status  = "sending"
        campaign.sent_at = datetime.utcnow()
        db.session.commit()

        seg        = campaign.recipient_segment or "all"
        recipients = get_eligible_recipients_query(seg).all()
        total      = len(recipients)
        sent_ok    = 0

        logger.info(
            "Campaign %s: starting send to %d recipients "
            "(rate limit: %.0fms delay / send)",
            campaign_id, total, _SEND_DELAY_S * 1000,
        )

        for user in recipients:
            token     = _ensure_unsub_token(user)
            unsub_url = f"{_APP_BASE_URL}/unsubscribe?token={token}"
            html      = render_campaign_html(campaign, unsubscribe_url=unsub_url)
            text      = render_campaign_text(campaign, unsubscribe_url=unsub_url)

            delivery = CommunicationDelivery(
                campaign_id=campaign_id,
                user_id=user.id,
                email=user.email,
                status="pending",
            )
            db.session.add(delivery)
            db.session.flush()

            try:
                result = resend.Emails.send({
                    "from":    _RESEND_FROM_DISPLAY,
                    "to":      [user.email],
                    "subject": campaign.subject,
                    "html":    html,
                    "text":    text,
                    "headers": {
                        # RFC 8058 one-click unsubscribe
                        "List-Unsubscribe":      f"<{unsub_url}>",
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                    },
                })
                delivery.status      = "sent"
                delivery.provider_id = (result.get("id", "") if isinstance(result, dict) else "")
                delivery.sent_at     = datetime.utcnow()
                sent_ok += 1

            except Exception as exc:
                err_str = str(exc)[:500]
                delivery.status = "failed"
                delivery.error  = err_str

                if _is_rate_limit_error(exc):
                    logger.error(
                        "[CAMPAIGN %s] RATE LIMIT (429) sending to %s — "
                        "increase CAMPAIGN_SEND_DELAY_MS (current: %.0fms)",
                        campaign_id, user.email, _SEND_DELAY_S * 1000,
                    )
                else:
                    logger.warning(
                        "[CAMPAIGN %s] Delivery failed for %s: %s",
                        campaign_id, user.email, err_str,
                    )

            db.session.commit()

            # ── Rate limit: sleep after every send ───────────────────────────
            # Ensures effective rate ≤ 1/_SEND_DELAY_S req/sec.
            # Default 250ms → ≤4 req/sec (Resend limit: 5/sec).
            time.sleep(_SEND_DELAY_S)

        # ── Final campaign status ─────────────────────────────────────────────
        failed_count = total - sent_ok
        if sent_ok == 0:
            final_status = "failed"
        elif failed_count > 0:
            final_status = "partial_success"
        else:
            final_status = "sent"

        campaign.status           = final_status
        campaign.recipients_count = sent_ok
        db.session.commit()
        logger.info(
            "Campaign %s done: %d/%d sent, %d failed → status=%s",
            campaign_id, sent_ok, total, failed_count, final_status,
        )

    except Exception as exc:
        logger.error("Campaign %s dispatch error: %s", campaign_id, exc, exc_info=True)
        try:
            campaign = CommunicationCampaign.query.get(campaign_id)
            if campaign:
                campaign.status        = "failed"
                campaign.error_message = str(exc)[:500]
                db.session.commit()
        except Exception as inner:
            logger.error("Could not update campaign %s to failed: %s", campaign_id, inner)
