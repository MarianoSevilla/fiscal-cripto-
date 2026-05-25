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

# Mirrors ADMIN_EMAILS from app.py — evaluated once at import time.
# If the env var changes at runtime (rare), restart the process.
_ADMIN_EMAILS = frozenset(
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
)

# Excluded roles — never receive campaigns
_EXCLUDED_ROLES = {"admin", "fiscal_advisor"}


# ── HELPERS ──────────────────────────────────────────────────────────────────

def _ensure_unsub_token(user: User) -> str:
    """Lazily assigns an unsubscribe token if the user doesn't have one."""
    if not user.comms_unsubscribe_token:
        user.comms_unsubscribe_token = uuid.uuid4().hex
        db.session.add(user)
        db.session.flush()
    return user.comms_unsubscribe_token


# ── QUERIES ──────────────────────────────────────────────────────────────────

def get_eligible_recipients_query():
    """
    Base query for campaign-eligible users.
    Excludes: unverified, inactive, opted-out, admins, fiscal advisors,
              and any email in ADMIN_EMAILS env var.
    """
    q = User.query.filter(
        User.email_verified_at.isnot(None),
        User.is_active.is_(True),
        User.comms_opted_out.is_(False),
        User.role.notin_(list(_EXCLUDED_ROLES)),
    )
    if _ADMIN_EMAILS:
        q = q.filter(~User.email.in_(list(_ADMIN_EMAILS)))
    return q


def count_eligible_recipients() -> int:
    return get_eligible_recipients_query().count()


# ── CAMPAIGN CRUD ─────────────────────────────────────────────────────────────

def create_campaign_draft(
    subject: str,
    body: str,
    preview_text: str,
    admin_user_id: int,
) -> CommunicationCampaign:
    campaign = CommunicationCampaign(
        subject=subject.strip(),
        body=body.strip(),
        preview_text=(preview_text or "").strip()[:200],
        status="draft",
        created_by_id=admin_user_id,
        idempotency_key=uuid.uuid4().hex,
    )
    db.session.add(campaign)
    db.session.commit()
    return campaign


def update_campaign_draft(
    campaign: CommunicationCampaign,
    subject: Optional[str] = None,
    body: Optional[str] = None,
    preview_text: Optional[str] = None,
) -> CommunicationCampaign:
    if subject is not None:
        campaign.subject = subject.strip()[:500]
    if body is not None:
        campaign.body = body.strip()
    if preview_text is not None:
        campaign.preview_text = preview_text.strip()[:200]
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
            "from":    _RESEND_FROM,
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


def _execute_campaign(campaign_id: int) -> None:
    """
    Core send loop. Runs in a background thread with app context.
    - Processes recipients one by one with a small delay (~20 emails/sec)
    - Writes a CommunicationDelivery row per recipient
    - Updates campaign status from queued → sending → sent / failed
    """
    campaign = CommunicationCampaign.query.get(campaign_id)
    if not campaign:
        logger.error("Campaign %s not found in _execute_campaign", campaign_id)
        return
    if campaign.status != "queued":
        logger.warning("Campaign %s expected 'queued', got '%s' — aborting", campaign_id, campaign.status)
        return

    try:
        campaign.status = "sending"
        campaign.sent_at = datetime.utcnow()
        db.session.commit()

        recipients = get_eligible_recipients_query().all()
        total      = len(recipients)
        sent_ok    = 0

        logger.info("Campaign %s: starting send to %d recipients", campaign_id, total)

        for user in recipients:
            token      = _ensure_unsub_token(user)
            unsub_url  = f"{_APP_BASE_URL}/unsubscribe?token={token}"
            html       = render_campaign_html(campaign, unsubscribe_url=unsub_url)
            text       = render_campaign_text(campaign, unsubscribe_url=unsub_url)

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
                    "from":    _RESEND_FROM,
                    "to":      [user.email],
                    "subject": campaign.subject,
                    "html":    html,
                    "text":    text,
                })
                delivery.status      = "sent"
                delivery.provider_id = (result.get("id", "") if isinstance(result, dict) else "")
                delivery.sent_at     = datetime.utcnow()
                sent_ok += 1
            except Exception as exc:
                delivery.status = "failed"
                delivery.error  = str(exc)[:500]
                logger.warning("Delivery failed for %s (campaign %s): %s", user.email, campaign_id, exc)

            db.session.commit()
            time.sleep(0.05)  # ~20 req/sec — comfortably under Resend limits

        campaign.status          = "sent"
        campaign.recipients_count = sent_ok
        db.session.commit()
        logger.info("Campaign %s done: %d/%d sent", campaign_id, sent_ok, total)

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
