"""S01 HTTP TEST synthetic-only: exact Stripe signature and atomic outbox.

No hay blueprints montados en app.py; fixture Flask SQLite aislada.
"""
from datetime import datetime
from hashlib import sha256
import hashlib
import hmac
import json
import time
from uuid import uuid4
from pathlib import Path

from flask import Flask
import pytest
from sqlalchemy import event as sa_event

from advisory_s01_test_http import build_s01_synthetic_webhook_blueprint
from models import (
    db, FiscalAdvisoryRequest, FiscalAdvisoryStatusHistory,
    S01StripeCheckoutAttempt, S01StripeEventReceipt,
    S01StripeNotificationOutbox,
)

SECRET = "whsec_s01_http_synthetic_secret"
TOKEN = "A" * 43
AMOUNT = 26000
SID = "cs_test_s01synthetichttp"
PI = "pi_s01synthetichttp"
ROUTE = "/__synthetic__/s01/stripe/webhook"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "testing")
    app = Flask("s01-synthetic-http-fixture")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "s01_http_test.sqlite"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    app.register_blueprint(
        build_s01_synthetic_webhook_blueprint(webhook_secret=SECRET)
    )
    with app.app_context():
        db.create_all()
        advisory = FiscalAdvisoryRequest(
            full_name="Cliente de pruebas",
            email="synthetic@example.invalid",
            tax_residence_country="España",
            tax_year=2025,
            service_type="presupuesto_personalizado",
            case_description="Fixture HTTP local ficticia.",
            is_test=True,
            status="quote_sent",
            quoted_amount=AMOUNT,
            rafa_fee_cents=20000,
            commission_cents=6000,
            commission_rate_bps=3000,
            stripe_checkout_session_id=SID,
            payment_link_token=TOKEN,
        )
        db.session.add(advisory)
        db.session.flush()
        attempt_id = str(uuid4())
        db.session.add(S01StripeCheckoutAttempt(
            id=attempt_id, advisory_id=advisory.id,
            quote_fingerprint=sha256(TOKEN.encode("ascii")).hexdigest(),
            idempotency_key="s01-checkout-v1-" + attempt_id,
            expected_amount_cents=AMOUNT,
            currency="eur", status="ready",
            checkout_session_id=SID,
        ))
        db.session.commit()
        yield app, advisory.id, attempt_id
        db.session.remove()
        db.drop_all()


def signed(store, *, event_id="evt_http_synthetic_001", amount=AMOUNT,
           secret=SECRET, actual_secret=None, live=False,
           timestamp=None):
    _, advisory_id, attempt_id = store
    checkout = {
        "id": SID, "livemode": live, "mode": "payment",
        "status": "complete", "payment_status": "paid",
        "amount_total": amount, "currency": "eur",
        "client_reference_id": str(advisory_id), "payment_intent": PI,
        "metadata": {
            "s01_attempt_id": attempt_id,
            "s01_advisory_id": str(advisory_id),
            "s01_quote_sha256": sha256(TOKEN.encode("ascii")).hexdigest(),
        },
    }
    data = {
        "id": event_id, "object": "event", "livemode": live,
        "type": "checkout.session.completed",
        "data": {"object": checkout},
    }
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    t = int(time.time()) if timestamp is None else timestamp
    mac = hmac.new(
        (actual_secret or secret).encode("utf-8"),
        str(t).encode() + b"." + payload,
        hashlib.sha256,
    ).hexdigest()
    return payload, f"t={t},v1={mac}"


def post(store, **options):
    payload, signature = signed(store, **options)
    return store[0].test_client().post(
        ROUTE, data=payload, headers={"Stripe-Signature": signature},
        content_type="application/json",
    )


def counts(store):
    _, advisory_id, attempt_id = store
    db.session.remove()
    advisory = db.session.get(FiscalAdvisoryRequest, advisory_id)
    return {
        "state": advisory.status,
        "amount": advisory.amount_paid,
        "hist": FiscalAdvisoryStatusHistory.query.filter_by(
            request_id=advisory_id, status="paid_received",
        ).count(),
        "events": S01StripeEventReceipt.query.filter_by(
            attempt_id=attempt_id,
        ).count(),
        "outbox": S01StripeNotificationOutbox.query.filter_by(
            attempt_id=attempt_id,
        ).count(),
    }


def test_valid_http_and_replays_do_not_duplicate_outbox(store):
    first = post(store)
    assert first.status_code == 200
    assert first.get_json() == {"result": "paid"}
    assert post(store).get_json() == {"result": "duplicate"}
    assert post(store, event_id="evt_http_synthetic_002").get_json() == {
        "result": "already_paid"
    }
    assert counts(store) == {
        "state": "paid_received", "amount": AMOUNT,
        "hist": 1, "events": 2, "outbox": 2,
    }
    outbox = S01StripeNotificationOutbox.query.all()
    assert {item.kind for item in outbox} == {
        "customer_payment_confirmed", "advisor_payment_confirmed",
    }
    assert all(item.status == "pending" and item.sent_at is None for item in outbox)


@pytest.mark.parametrize("options", [
    {"actual_secret": "whsec_wrong_http_secret"},
    {"timestamp": 1},
])
def test_http_rejects_unsigned_or_expired(store, options):
    assert post(store, **options).status_code == 400
    assert counts(store)["outbox"] == 0
    assert counts(store)["state"] == "quote_sent"


def test_http_rejects_missing_signature(store):
    data, _ = signed(store)
    response = store[0].test_client().post(ROUTE, data=data)
    assert response.status_code == 400
    assert counts(store)["events"] == 0


@pytest.mark.parametrize("options", [
    {"amount": 19999},
    {"live": True},
])
def test_http_does_not_ack_unreconciled_events(store, options):
    response = post(store, **options)
    assert response.status_code == 409
    assert counts(store)["outbox"] == 0
    assert counts(store)["state"] == "quote_sent"


def test_http_excessive_payload_rejected_before_parsing(store):
    res = store[0].test_client().post(
        ROUTE,
        data=b"x" * 66000,
        headers={"Stripe-Signature": "t=1,v1=fake"},
    )
    assert res.status_code == 413
    assert counts(store)["events"] == 0


def test_http_storage_failure_rolls_back_outbox_and_receipt(store):
    def fail_notice(conn, cursor, statement, params, context, many):
        if "insert into s01_stripe_notification_outbox" in statement.lower():
            raise RuntimeError("synthetic outbox failure")

    sa_event.listen(db.engine, "before_cursor_execute", fail_notice)
    try:
        res = post(store)
        assert res.status_code == 503
    finally:
        sa_event.remove(db.engine, "before_cursor_execute", fail_notice)

    assert counts(store) == {
        "state": "quote_sent", "amount": None,
        "hist": 0, "events": 0, "outbox": 0,
    }
    assert post(store).status_code == 200
    assert counts(store)["outbox"] == 2


def test_test_only_guard_at_factory_and_at_request(store, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    with pytest.raises(RuntimeError):
        build_s01_synthetic_webhook_blueprint(webhook_secret=SECRET)
    assert post(store).status_code == 503
    assert counts(store)["outbox"] == 0


def test_flask_testing_flag_required(store):
    store[0].config["TESTING"] = False
    assert post(store).status_code == 503
    assert counts(store)["outbox"] == 0


def test_blueprint_is_never_imported_or_mounted_in_runtime_app():
    app_py = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    assert "advisory_s01_test_http" not in app_py
    assert "__synthetic__/s01/stripe/webhook" not in app_py
    assert "build_s01_synthetic_webhook_blueprint" not in app_py
