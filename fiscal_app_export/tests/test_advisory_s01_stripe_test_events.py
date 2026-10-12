"""S01 consumidor idempotente de evento Stripe firmado — datos sintéticos.

No hay endpoint, pagos, llamadas reales ni datos personales. SQLite solo prueba
secuencialidad y rollback; concurrencia PG18 requiere suite específica posterior.
"""
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from uuid import uuid4

from flask import Flask
import pytest
from sqlalchemy import event as sa_event

from advisory_s01_stripe_test_events import (
    S01EventRejected, S01EventStorageError, process_signed_s01_test_webhook,
)
from models import (
    db, FiscalAdvisoryRequest, FiscalAdvisoryStatusHistory,
    S01StripeCheckoutAttempt, S01StripeEventReceipt,
)

SECRET = "whsec_s01_synthetic_fake_secret"
TOKEN = "A" * 43
AMOUNT = 26000
SESSION = "cs_test_s01synthetic123"
PI = "pi_s01synthetic123"


@pytest.fixture
def populated(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "testing")
    app = Flask("stripe-ledger-s01-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "stripe-ledger.sqlite"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=True,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        request = FiscalAdvisoryRequest(
            full_name="Cliente sintético", email="synthetic@example.invalid",
            tax_residence_country="España", tax_year=2025,
            service_type="presupuesto_personalizado",
            case_description="Caso de pruebas sin datos reales.",
            is_test=True, status="quote_sent", payment_link_token=TOKEN,
            quoted_amount=AMOUNT, rafa_fee_cents=20000,
            commission_cents=6000, commission_rate_bps=3000,
            stripe_checkout_session_id=SESSION,
        )
        db.session.add(request)
        db.session.flush()
        attempt_id = str(uuid4())
        db.session.add(S01StripeCheckoutAttempt(
            id=attempt_id, advisory_id=request.id,
            quote_fingerprint=hashlib.sha256(TOKEN.encode("ascii")).hexdigest(),
            idempotency_key="s01-checkout-v1-" + attempt_id,
            expected_amount_cents=AMOUNT, currency="eur", status="ready",
            checkout_session_id=SESSION,
        ))
        db.session.commit()
        yield request.id, attempt_id
        db.session.remove()
        db.drop_all()


def signed(advisory_id, attempt_id, *,
           event_id="evt_s01synthetic123", updates=None, envelope=None,
           secret=SECRET, sign_secret=None, timestamp=None):
    obj = {
        "id": SESSION, "livemode": False, "mode": "payment",
        "status": "complete", "payment_status": "paid",
        "amount_total": AMOUNT, "currency": "eur",
        "client_reference_id": str(advisory_id), "payment_intent": PI,
        "metadata": {
            "s01_attempt_id": attempt_id,
            "s01_advisory_id": str(advisory_id),
            "s01_quote_sha256": hashlib.sha256(TOKEN.encode("ascii")).hexdigest(),
        },
    }
    if updates:
        obj.update(updates)
    d = {
        "id": event_id, "object": "event", "livemode": False,
        "type": "checkout.session.completed",
        "data": {"object": obj},
    }
    if envelope:
        d.update(envelope)
    payload = json.dumps(d, separators=(",", ":")).encode("utf-8")
    stamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(
        (sign_secret or secret).encode("utf-8"),
        str(stamp).encode() + b"." + payload, hashlib.sha256,
    ).hexdigest()
    return dict(payload=payload, signature=f"t={stamp},v1={digest}",
                webhook_secret=secret)


def consume(populated, **opts):
    advisory_id, attempt_id = populated
    return process_signed_s01_test_webhook(
        **signed(advisory_id, attempt_id, **opts)
    )


def stats(advisory_id, attempt_id):
    advisory = db.session.get(FiscalAdvisoryRequest, advisory_id)
    attempt = db.session.get(S01StripeCheckoutAttempt, attempt_id)
    return {
        "status": advisory.status, "paid": advisory.amount_paid,
        "pi": advisory.stripe_payment_intent_id,
        "provider": advisory.payment_provider, "paid_at": advisory.paid_at,
        "attempt_status": attempt.status, "attempt_pi": attempt.payment_intent_id,
        "events": S01StripeEventReceipt.query.count(),
        "hist": FiscalAdvisoryStatusHistory.query.filter_by(
            request_id=advisory_id, status="paid_received"
        ).count(),
    }


def test_genuine_signed_event_commits_all_four_records(populated):
    advisory_id, attempt_id = populated
    assert consume(populated) == "paid"
    state = stats(advisory_id, attempt_id)
    assert state["status"] == "paid_received"
    assert state["paid"] == AMOUNT
    assert state["provider"] == "stripe"
    assert state["pi"] == PI
    assert state["attempt_pi"] == PI
    assert state["attempt_status"] == "paid"
    assert state["paid_at"] is not None
    assert (state["events"], state["hist"]) == (1, 1)


def test_exact_replay_and_second_event_are_idempotent(populated):
    advisory_id, attempt_id = populated
    assert consume(populated) == "paid"
    assert consume(populated) == "duplicate"
    assert consume(populated, event_id="evt_s01synthetic124") == "already_paid"
    assert consume(populated, event_id="evt_s01synthetic124") == "duplicate"
    state = stats(advisory_id, attempt_id)
    assert (state["events"], state["hist"]) == (2, 1)


@pytest.mark.parametrize("updates", [
    {"amount_total": 20000}, {"amount_total": 26000.0},
    {"currency": "usd"}, {"status": "open"},
    {"payment_status": "unpaid"}, {"mode": "subscription"},
    {"livemode": True}, {"id": "cs_test_wrong"},
    {"payment_intent": None},
    {"client_reference_id": "9876543"}, {"metadata": {}},
])
def test_bad_checkout_is_rejected_without_financial_mutation(populated, updates):
    with pytest.raises(S01EventRejected):
        consume(populated, updates=updates)
    state = stats(*populated)
    assert state["status"] == "quote_sent"
    assert state["paid"] is None
    assert (state["events"], state["hist"]) == (0, 0)


@pytest.mark.parametrize("envelope", [
    {"livemode": True}, {"type": "payment_intent.succeeded"},
    {"id": "evt_bad@"},
])
def test_bad_event_envelope_rejected(populated, envelope):
    with pytest.raises(S01EventRejected):
        consume(populated, envelope=envelope)
    assert stats(*populated)["events"] == 0


def test_invalid_signature_stale_and_tampered_payload_blocked(populated):
    aid, attempt_id = populated
    bad = signed(aid, attempt_id, sign_secret="whsec_not_the_right_one")
    with pytest.raises(S01EventRejected):
        process_signed_s01_test_webhook(**bad)
    stale = signed(aid, attempt_id, timestamp=int(time.time()) - 9999)
    with pytest.raises(S01EventRejected):
        process_signed_s01_test_webhook(**stale)
    valid = signed(aid, attempt_id)
    tampered = {**valid, "payload": valid["payload"].replace(b"26000", b"28000")}
    with pytest.raises(S01EventRejected):
        process_signed_s01_test_webhook(**tampered)
    assert stats(*populated)["events"] == 0


def test_non_testing_environment_is_rejected(populated, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    with pytest.raises(S01EventRejected):
        consume(populated)
    assert stats(*populated)["events"] == 0


@pytest.mark.parametrize("column,value", [
    ("quoted_amount", 20000), ("commission_cents", 5999),
    ("commission_rate_bps", 2000), ("payment_link_token", "B" * 43),
    ("is_test", False), ("status", "cancelled"),
    ("paypal_order_id", "PAYPAL123"),
    ("stripe_checkout_session_id", "cs_test_other123"),
])
def test_advisory_mutation_fails_closed(populated, column, value):
    a = db.session.get(FiscalAdvisoryRequest, populated[0])
    setattr(a, column, value)
    db.session.commit()
    with pytest.raises(S01EventRejected):
        consume(populated)
    assert stats(*populated)["events"] == 0
    assert stats(*populated)["paid"] is None


@pytest.mark.parametrize("column,value", [
    ("status", "uncertain"), ("status", "creating"),
    ("expected_amount_cents", 25000), ("currency", "usd"),
    ("checkout_session_id", "cs_test_other123"),
    ("quote_fingerprint", "0" * 64), ("idempotency_key", "random-key"),
])
def test_attempt_mutation_fails_closed(populated, column, value):
    a = db.session.get(S01StripeCheckoutAttempt, populated[1])
    setattr(a, column, value)
    db.session.commit()
    with pytest.raises(S01EventRejected):
        consume(populated)
    assert stats(*populated)["events"] == 0
    assert stats(*populated)["paid"] is None


def test_transaction_error_rolls_back_history_receipt_and_status(populated):
    def no_history(session, flush_context, instances):
        if any(isinstance(x, FiscalAdvisoryStatusHistory) for x in session.new):
            raise RuntimeError("synthetic storage outage")
    sa_event.listen(db.session.session_factory.class_, "before_flush", no_history)
    try:
        with pytest.raises(S01EventStorageError):
            consume(populated)
    finally:
        sa_event.remove(db.session.session_factory.class_, "before_flush", no_history)
    assert stats(*populated)["status"] == "quote_sent"
    assert stats(*populated)["attempt_status"] == "ready"
    assert (stats(*populated)["events"], stats(*populated)["hist"]) == (0, 0)


def test_conflicting_payment_intent_when_already_persisted_is_rejected(populated):
    attempt = db.session.get(S01StripeCheckoutAttempt, populated[1])
    attempt.payment_intent_id = PI
    db.session.commit()
    with pytest.raises(S01EventRejected):
        consume(populated, updates={"payment_intent": "pi_other"})
    assert stats(*populated)["events"] == 0
    assert stats(*populated)["status"] == "quote_sent"


def test_existing_paid_by_other_provider_is_never_overwritten(populated):
    a = db.session.get(FiscalAdvisoryRequest, populated[0])
    a.status = "paid_received"
    a.payment_provider = "paypal"
    a.amount_paid = 26000
    a.paid_at = datetime.utcnow()
    db.session.commit()
    with pytest.raises(S01EventRejected):
        consume(populated)
    assert stats(*populated)["provider"] == "paypal"
    assert stats(*populated)["events"] == 0
