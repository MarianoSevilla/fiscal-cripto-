import hashlib
import hmac
import json
import time

import stripe
import pytest

from models import db, User
from credit_ledger import create_purchase, balance, CreditError, attach_checkout_session
from credits_stripe import checkout_session_params, process_signed_test_event
from flask import Flask


@pytest.fixture
def paid_context(tmp_path):
    app = Flask("credits-stripe-test")
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "stripe-credits.sqlite"),
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=True)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        user = User(email="stripe-credit-synthetic@example.invalid", is_active=True)
        db.session.add(user)
        db.session.commit()
        purchase = create_purchase(user_id=user.id, package_key="advanced")
        attach_checkout_session(purchase_id=purchase.id, session_id="cs_test_credit_session")
        yield user.id, purchase
        db.session.remove()
        db.drop_all()


def _signed(event, secret="whsec_synthetic_credit_secret"):
    payload = json.dumps(event, separators=(",", ":")).encode()
    stamp = int(time.time())
    digest = hmac.new(secret.encode(), str(stamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
    return payload, f"t={stamp},v1={digest}"


def _event(purchase, **updates):
    obj = {
        "id": "cs_test_credit_session", "livemode": False, "mode": "payment",
        "status": "complete", "payment_status": "paid",
        "amount_total": purchase.amount_cents, "currency": "eur",
        "payment_intent": "pi_credit_synthetic",
        "metadata": {"credits_purchase_id": purchase.id},
    }
    obj.update(updates)
    return {"id": "evt_credit_synthetic", "livemode": False,
            "type": "checkout.session.completed", "data": {"object": obj}}


def test_checkout_is_one_time_server_priced_and_contains_no_customer_tax_data(paid_context):
    _, purchase = paid_context
    params = checkout_session_params(purchase=purchase, base_url="https://marianosevilla.com")
    assert params["mode"] == "payment"
    assert params["allowed_payment_method_types"] == ["card"]
    assert "payment_method_types" not in params
    assert params["line_items"][0]["price_data"]["unit_amount"] == 4990
    assert "subscription_data" not in params
    assert params["metadata"] == {"credits_purchase_id": purchase.id}
    assert "email" not in str(params).lower()
    with pytest.raises(CreditError):
        checkout_session_params(purchase=purchase, base_url="http://example.com")


def test_signed_test_checkout_event_grants_only_once(paid_context):
    user_id, purchase = paid_context
    payload, signature = _signed(_event(purchase))
    assert process_signed_test_event(stripe_module=stripe, payload=payload,
                                     signature=signature,
                                     webhook_secret="whsec_synthetic_credit_secret")
    assert not process_signed_test_event(stripe_module=stripe, payload=payload,
                                        signature=signature,
                                        webhook_secret="whsec_synthetic_credit_secret")
    assert balance(user_id)["available"] == 460


@pytest.mark.parametrize("updates", [
    {"livemode": True}, {"payment_status": "unpaid"},
    {"amount_total": 1}, {"currency": "usd"}, {"mode": "subscription"},
])
def test_invalid_paid_event_never_grants_credits(paid_context, updates):
    user_id, purchase = paid_context
    payload, signature = _signed(_event(purchase, **updates))
    with pytest.raises(CreditError):
        process_signed_test_event(stripe_module=stripe, payload=payload,
                                  signature=signature,
                                  webhook_secret="whsec_synthetic_credit_secret")
    assert balance(user_id)["available"] == 0


def test_invalid_webhook_signature_never_grants_credits(paid_context):
    user_id, purchase = paid_context
    payload, signature = _signed(_event(purchase))
    with pytest.raises(CreditError):
        process_signed_test_event(stripe_module=stripe, payload=payload,
                                  signature=signature,
                                  webhook_secret="whsec_other_secret")
    assert balance(user_id)["available"] == 0


def test_signed_refund_event_freezes_spending_for_manual_reconciliation(paid_context):
    user_id, purchase = paid_context
    paid_payload, paid_signature = _signed(_event(purchase))
    process_signed_test_event(stripe_module=stripe, payload=paid_payload,
                              signature=paid_signature,
                              webhook_secret="whsec_synthetic_credit_secret")
    refund = {"id": "evt_credit_refund", "livemode": False,
              "type": "charge.refunded", "data": {"object": {
                  "id": "ch_synthetic", "livemode": False,
                  "payment_intent": "pi_credit_synthetic", "amount_refunded": 4990,
                  "currency": "eur",
              }}}
    payload, signature = _signed(refund)
    assert process_signed_test_event(stripe_module=stripe, payload=payload,
                                     signature=signature,
                                     webhook_secret="whsec_synthetic_credit_secret")
    assert balance(user_id) == {"available": 460, "reserved": 0, "frozen": True}
