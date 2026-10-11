"""U04 financial records. No cascade or historical reconstruction."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from models import db

STATES = (
    "ORDER_CREATING", "ORDER_CREATED", "READY_TO_CAPTURE", "CAPTURE_STARTED",
    "UNCERTAIN", "PROVIDER_PENDING", "RECONCILED", "CLOSED_NO_CHARGE", "REVIEW_REQUIRED",
)
NOTICE_STATES = ("UNCLAIMED", "CLAIMED", "ACKNOWLEDGED", "UNKNOWN", "SKIPPED")
def now():
    return datetime.now(timezone.utc)
def uid():
    return str(uuid4())


class PayPalPaymentAttempt(db.Model):
    __tablename__ = "paypal_payment_attempt"
    id = db.Column(db.Uuid(as_uuid=False), primary_key=True, default=uid)
    advisory_id = db.Column(db.Integer, db.ForeignKey("fiscal_advisory_requests.id", ondelete="RESTRICT"), nullable=False)
    origin = db.Column(db.String(20), nullable=False, default="managed")
    quote_generation = db.Column(db.Uuid(as_uuid=False))
    quote_evidence_ref = db.Column(db.String(100))
    quoted_amount_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="EUR")
    quote_sent_at = db.Column(db.DateTime(timezone=True))
    quote_expires_at = db.Column(db.DateTime(timezone=True))
    expected_custom_id = db.Column(db.String(100), nullable=False)
    provider_account_scope = db.Column(db.String(64), nullable=False)
    environment = db.Column(db.String(8), nullable=False)
    create_request_id = db.Column(db.Uuid(as_uuid=False), nullable=False, default=uid)
    capture_request_id = db.Column(db.Uuid(as_uuid=False))
    paypal_order_id = db.Column(db.String(36))
    paypal_capture_id = db.Column(db.String(64))
    state = db.Column(db.String(24), nullable=False)
    uncertainty_phase = db.Column(db.String(7))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    order_created_at = db.Column(db.DateTime(timezone=True))
    approval_verified_at = db.Column(db.DateTime(timezone=True))
    capture_started_at = db.Column(db.DateTime(timezone=True))
    uncertain_at = db.Column(db.DateTime(timezone=True))
    last_observed_at = db.Column(db.DateTime(timezone=True))
    resolved_at = db.Column(db.DateTime(timezone=True))
    claim_id = db.Column(db.Uuid(as_uuid=False))
    version = db.Column(db.Integer, nullable=False, default=1)
    request_contract_hash = db.Column(db.String(64), nullable=False)
    resolution_reason = db.Column(db.String(40))
    resolution_event_id = db.Column(db.Uuid(as_uuid=False), db.ForeignKey(
        "paypal_payment_event.id", name="fk_paypal_resolution_event",
        ondelete="RESTRICT", use_alter=True, deferrable=True, initially="DEFERRED"))
    customer_notification_state = db.Column(db.String(16), nullable=False, default="UNCLAIMED")
    owner_notification_state = db.Column(db.String(16), nullable=False, default="UNCLAIMED")
    customer_notification_claimed_at = db.Column(db.DateTime(timezone=True))
    owner_notification_claimed_at = db.Column(db.DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("quoted_amount_cents > 0 AND currency = 'EUR'", name="ck_paypal_money"),
        CheckConstraint("environment IN ('live', 'sandbox')", name="ck_paypal_environment"),
        CheckConstraint("state IN (" + ",".join(repr(s) for s in STATES) + ")", name="ck_paypal_state"),
        CheckConstraint("version > 0", name="ck_paypal_version"),
        CheckConstraint("(origin = 'managed' AND quote_generation IS NOT NULL) OR (origin = 'legacy_verified' AND quote_evidence_ref IS NOT NULL)", name="ck_paypal_origin"),
        CheckConstraint("capture_request_id IS NULL OR capture_request_id <> create_request_id", name="ck_paypal_request_keys"),
        CheckConstraint("(capture_request_id IS NULL AND capture_started_at IS NULL AND claim_id IS NULL) OR (capture_request_id IS NOT NULL AND capture_started_at IS NOT NULL AND claim_id IS NOT NULL)", name="ck_paypal_capture_reservation"),
        CheckConstraint("state NOT IN ('CAPTURE_STARTED', 'PROVIDER_PENDING') OR (capture_request_id IS NOT NULL AND paypal_order_id IS NOT NULL)", name="ck_paypal_capture_state"),
        CheckConstraint("state <> 'UNCERTAIN' OR (uncertainty_phase IN ('CREATE', 'CAPTURE') AND uncertain_at IS NOT NULL)", name="ck_paypal_uncertain"),
        CheckConstraint("state <> 'UNCERTAIN' OR (uncertainty_phase='CREATE' AND capture_started_at IS NULL) OR (uncertainty_phase='CAPTURE' AND capture_started_at IS NOT NULL)", name="ck_paypal_uncertain_phase"),
        CheckConstraint("state NOT IN ('ORDER_CREATED', 'READY_TO_CAPTURE') OR paypal_order_id IS NOT NULL", name="ck_paypal_order_state"),
        CheckConstraint("state NOT IN ('RECONCILED', 'CLOSED_NO_CHARGE') OR (resolved_at IS NOT NULL AND resolution_reason IS NOT NULL AND resolution_event_id IS NOT NULL)", name="ck_paypal_resolution"),
        CheckConstraint("state <> 'RECONCILED' OR (paypal_order_id IS NOT NULL AND paypal_capture_id IS NOT NULL)", name="ck_paypal_reconciled"),
        CheckConstraint("state <> 'PROVIDER_PENDING' OR paypal_capture_id IS NOT NULL", name="ck_paypal_pending"),
        CheckConstraint("customer_notification_state IN (" + ",".join(repr(s) for s in NOTICE_STATES) + ") AND owner_notification_state IN (" + ",".join(repr(s) for s in NOTICE_STATES) + ")", name="ck_paypal_notices"),
        CheckConstraint("customer_notification_state NOT IN ('CLAIMED','ACKNOWLEDGED','UNKNOWN') OR customer_notification_claimed_at IS NOT NULL", name="ck_paypal_customer_notice_claim"),
        CheckConstraint("owner_notification_state NOT IN ('CLAIMED','ACKNOWLEDGED','UNKNOWN') OR owner_notification_claimed_at IS NOT NULL", name="ck_paypal_owner_notice_claim"),
        Index("uq_paypal_blocking_advisory", "advisory_id", unique=True,
              postgresql_where=text("state <> 'CLOSED_NO_CHARGE'"), sqlite_where=text("state <> 'CLOSED_NO_CHARGE'")),
        *(UniqueConstraint("provider_account_scope", "environment", field, name="uq_paypal_" + field)
          for field in ("paypal_order_id", "paypal_capture_id", "create_request_id", "capture_request_id")),
        Index("ix_paypal_review", "state", "created_at"),
    )

    def snapshot(self):
        names = ("id", "advisory_id", "origin", "quote_generation", "quote_evidence_ref",
                 "quoted_amount_cents", "currency", "expected_custom_id", "provider_account_scope",
                 "environment", "create_request_id", "capture_request_id", "paypal_order_id",
                 "paypal_capture_id", "state", "claim_id", "version", "capture_started_at",
                 "quote_expires_at", "uncertainty_phase")
        return {key: getattr(self, key) for key in names}


class PayPalPaymentEvent(db.Model):
    __tablename__ = "paypal_payment_event"
    id = db.Column(db.Uuid(as_uuid=False), primary_key=True, default=uid)
    attempt_id = db.Column(db.Uuid(as_uuid=False), db.ForeignKey("paypal_payment_attempt.id", ondelete="RESTRICT"))
    correlation_event_id = db.Column(db.Uuid(as_uuid=False), db.ForeignKey("paypal_payment_event.id", ondelete="RESTRICT"))
    provider_account_scope = db.Column(db.String(64), nullable=False)
    environment = db.Column(db.String(8), nullable=False)
    source = db.Column(db.String(20), nullable=False)
    kind = db.Column(db.String(40), nullable=False)
    provider_event_id = db.Column(db.String(100))
    actor_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=now)
    observed_at = db.Column(db.DateTime(timezone=True))
    from_state = db.Column(db.String(24))
    to_state = db.Column(db.String(24))
    paypal_order_id = db.Column(db.String(36))
    paypal_capture_id = db.Column(db.String(64))
    order_status = db.Column(db.String(24))
    capture_status = db.Column(db.String(24))
    amount_cents = db.Column(db.Integer)
    currency = db.Column(db.String(3))
    authenticated = db.Column(db.Boolean, nullable=False, default=False)
    contract_valid = db.Column(db.Boolean, nullable=False, default=False)
    endpoint = db.Column(db.String(24))
    http_status = db.Column(db.Integer)
    evidence_hash = db.Column(db.String(64), nullable=False)
    operational_reference = db.Column(db.String(100))
    __table_args__ = (
        UniqueConstraint("provider_account_scope", "environment", "provider_event_id", name="uq_paypal_provider_event"),
        CheckConstraint("environment IN ('live', 'sandbox')", name="ck_paypal_event_environment"),
        Index("ix_paypal_event_attempt", "attempt_id", "created_at"),
    )
