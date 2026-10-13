"""S01 C2-R01: fail-closed guard for non-financial internal status changes.

No provider access, external I/O, emails, migrations or customer communications.
The production handler must acquire the advisory row lock before this check.
"""
from datetime import datetime
from models import (
    db, FiscalAdvisoryRequest, FiscalAdvisoryStatusHistory,
    AdvisoryAuditLog, S01StripeCheckoutAttempt,
)

# Previous legacy workflow statuses may be reviewed, but no transition may
# newly assert that the user was contacted or that payments were initiated.
C2_SOURCE_STATES = frozenset({
    "submitted", "under_review", "pendiente_info", "waiting_user_info",
})
C2_TARGET_STATES = frozenset({"submitted", "under_review"})

_C2_EVIDENCE_COLUMNS = (
    "quoted_amount", "rafa_fee_cents", "commission_cents",
    "commission_rate_bps", "quoted_by_user_id", "quote_message",
    "quote_sent_at", "quote_expires_at", "payment_link_token",
    "quote_accepted_at", "quote_acceptance_ip", "quote_acceptance_user_agent",
    "paypal_order_id", "paypal_capture_id", "payment_provider",
    "stripe_checkout_session_id", "stripe_payment_intent_id",
    "amount_paid", "paid_at",
)
_C2_FINANCIAL_AUDIT_ACTIONS = frozenset({
    AdvisoryAuditLog.ACTION_QUOTE_SENT,
    AdvisoryAuditLog.ACTION_COMPLETED,
    AdvisoryAuditLog.ACTION_CANCELLED,
    AdvisoryAuditLog.ACTION_DELETED,
})


class C2ProtectedState(Exception):
    """Request has financial or inconsistent historical evidence."""


def c2_can_change_state(advisory: FiscalAdvisoryRequest) -> bool:
    """Fail closed on any recorded quote, consent, payment, or legacy trace.

    Pure internal status changes and the initial 'submitted' history are
    permitted. Caller must lock the advisory row for write transactions.
    """
    if advisory.status not in C2_SOURCE_STATES:
        return False
    if any(getattr(advisory, field, None) is not None
           for field in _C2_EVIDENCE_COLUMNS):
        return False
    if S01StripeCheckoutAttempt.query.filter_by(
            advisory_id=advisory.id).first() is not None:
        return False
    if FiscalAdvisoryStatusHistory.query.filter(
        FiscalAdvisoryStatusHistory.request_id == advisory.id,
        ~FiscalAdvisoryStatusHistory.status.in_(C2_SOURCE_STATES),
    ).first() is not None:
        return False
    if AdvisoryAuditLog.query.filter(
        AdvisoryAuditLog.request_id == advisory.id,
        AdvisoryAuditLog.action.in_(_C2_FINANCIAL_AUDIT_ACTIONS),
    ).first() is not None:
        return False
    return True


def c2_change_internal_state(*, request_id: int, new_status: str,
                             actor_id: int, note: str = "") -> tuple[str, bool]:
    """Serializable per-row decision, with no external communication.

    Returns (status, unchanged); raises C2ProtectedState without writing.
    """
    if new_status not in C2_TARGET_STATES:
        raise C2ProtectedState("target not allowed")
    advisory = (
        FiscalAdvisoryRequest.query.filter_by(id=request_id)
        .with_for_update().first_or_404()
    )
    if not c2_can_change_state(advisory):
        db.session.rollback()
        raise C2ProtectedState("historical evidence or unsafe source state")
    if advisory.status == new_status:
        db.session.rollback()
        return new_status, True
    previous = advisory.status
    advisory.status = new_status
    db.session.add(FiscalAdvisoryStatusHistory(
        request_id=advisory.id, status=new_status,
        changed_by=actor_id, note=note or None,
    ))
    db.session.add(AdvisoryAuditLog(
        request_id=advisory.id, admin_id=actor_id,
        action=AdvisoryAuditLog.ACTION_STATUS_CHANGED,
        detail=f"C2: {previous} → {new_status}" + (f" · {note}" if note else ""),
    ))
    db.session.commit()
    return new_status, False
