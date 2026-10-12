"""Offline regression for the real Stripe webhook controller (SEC-STRIPE-SIG-001).

The handler is extracted from app.py by AST to avoid the application's import-
time database bootstrap. Stripe signature verification uses the real installed
SDK and synthetic HMAC signatures. All database/provider side effects are mocks.
"""
import ast
import copy
import hashlib
import hmac
import json
import socket
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import stripe
from flask import Flask, jsonify, request


SYNTHETIC_KEY = "sk_test_offline_synthetic_not_a_real_credential"
SYNTHETIC_SECRET = "whsec_offline_synthetic_not_a_real_credential"
SYNTHETIC_SESSION = "cs_test_synthetic_invoice_001"
SYNTHETIC_PI = "pi_test_synthetic_001"
WEBHOOK_PATH = "/api/webhooks/stripe"


def synthetic_event(kind="checkout.session.completed"):
    return {
        "id": "evt_test_synthetic_001",
        "object": "event",
        "type": kind,
        "data": {
            "object": {
                "id": SYNTHETIC_SESSION,
                "payment_intent": SYNTHETIC_PI,
                "amount_total": 4900,
                "currency": "eur",
            }
        },
    }


def signed_payload(event=None, *, secret=SYNTHETIC_SECRET, timestamp=None):
    payload = json.dumps(event or synthetic_event(), separators=(",", ":"))
    timestamp = int(time.time()) if timestamp is None else timestamp
    signature = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return payload, f"t={timestamp},v1={signature}"


@pytest.fixture
def handler():
    """Load ONLY the original function and register it in synthetic Flask."""
    flask_app = Flask("stripe-signature-offline")
    flask_app.config["TESTING"] = True
    query = Mock()
    query.filter_by.return_value = query
    query.first.return_value = None
    payment_complete = Mock()
    db_session = Mock()
    namespace = {
        "app": flask_app,
        "jsonify": jsonify,
        "request": request,
        "db": SimpleNamespace(session=db_session),
        "FiscalAdvisoryRequest": SimpleNamespace(query=query),
        "_stripe_available": True,
        "_STRIPE_SECRET_KEY": SYNTHETIC_KEY,
        "_STRIPE_WEBHOOK_SECRET": SYNTHETIC_SECRET,
        "_stripe_module": stripe,
        "_on_payment_completed": payment_complete,
    }

    source = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    definition = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "stripe_webhook"
    )
    definition = copy.deepcopy(definition)
    definition.decorator_list = []
    module = ast.Module(body=[definition], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(source), "exec"), namespace)
    flask_app.add_url_rule(
        WEBHOOK_PATH,
        view_func=namespace["stripe_webhook"],
        methods=["POST"],
    )

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("SEC-STRIPE-SIG-001 must not access network")

    with patch.object(socket.socket, "connect", forbid_network), \
         patch.object(socket, "create_connection", forbid_network), \
         patch.object(socket, "getaddrinfo", forbid_network):
        yield SimpleNamespace(
            app=flask_app,
            client=flask_app.test_client(),
            namespace=namespace,
            query=query,
            complete=payment_complete,
            db_session=db_session,
        )


def post_event(h, event=None, *, secret=SYNTHETIC_SECRET, header=True, timestamp=None):
    payload, signature = signed_payload(event, secret=secret, timestamp=timestamp)
    headers = {"Stripe-Signature": signature} if header else {}
    return h.client.post(WEBHOOK_PATH, data=payload, headers=headers,
                         content_type="application/json")


def assert_no_financial_side_effects(h):
    h.query.filter_by.assert_not_called()
    h.complete.assert_not_called()
    h.db_session.commit.assert_not_called()


@pytest.mark.parametrize("available,key,secret", [
    (False, SYNTHETIC_KEY, SYNTHETIC_SECRET),
    (True, "", SYNTHETIC_SECRET),
    (True, None, SYNTHETIC_SECRET),
    (True, SYNTHETIC_KEY, ""),
    (True, SYNTHETIC_KEY, None),
    (True, SYNTHETIC_KEY, "   "),
    (True, "   ", SYNTHETIC_SECRET),
])
def test_incomplete_configuration_refuses_event_and_does_not_ack(handler, available, key, secret):
    handler.namespace["_stripe_available"] = available
    handler.namespace["_STRIPE_SECRET_KEY"] = key
    handler.namespace["_STRIPE_WEBHOOK_SECRET"] = secret
    response = post_event(handler)
    assert response.status_code == 503
    assert response.get_json() == {"error": "Webhook unavailable."}
    assert_no_financial_side_effects(handler)


def test_unsigned_json_cannot_bypass_missing_secret(handler):
    handler.namespace["_STRIPE_WEBHOOK_SECRET"] = ""
    response = handler.client.post(
        WEBHOOK_PATH, data=json.dumps(synthetic_event()),
        content_type="application/json",
    )
    assert response.status_code == 503
    assert_no_financial_side_effects(handler)


def test_missing_signature_is_rejected_before_database_lookup(handler):
    response = post_event(handler, header=False)
    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid request."}
    assert_no_financial_side_effects(handler)


def test_wrong_signature_is_rejected_before_database_lookup(handler):
    response = post_event(handler, secret="whsec_incorrect_synthetic")
    assert response.status_code == 400
    assert_no_financial_side_effects(handler)


def test_outdated_signature_is_rejected(handler):
    response = post_event(handler, timestamp=int(time.time()) - 3600)
    assert response.status_code == 400
    assert_no_financial_side_effects(handler)


def test_tampered_payload_is_rejected(handler):
    payload, header = signed_payload()
    payload = payload.replace("4900", "9900")
    response = handler.client.post(
        WEBHOOK_PATH, data=payload,
        headers={"Stripe-Signature": header},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert_no_financial_side_effects(handler)


def test_malformed_json_with_a_valid_signature_is_rejected(handler):
    payload = '{"type": '
    timestamp = int(time.time())
    digest = hmac.new(
        SYNTHETIC_SECRET.encode(),
        f"{timestamp}.{payload}".encode(), hashlib.sha256,
    ).hexdigest()
    response = handler.client.post(
        WEBHOOK_PATH, data=payload,
        headers={"Stripe-Signature": f"t={timestamp},v1={digest}"},
        content_type="application/json",
    )
    assert response.status_code == 400
    assert_no_financial_side_effects(handler)


def test_invalid_signature_does_not_leak_payload_to_logs_or_response(handler):
    sensitive_value = "never-log-this@example.invalid"
    event = synthetic_event()
    event["data"]["object"]["customer_email"] = sensitive_value
    with patch.object(handler.app.logger, "warning") as warning:
        response = post_event(handler, event, secret="whsec_wrong")
    assert response.status_code == 400
    warning.assert_called_once_with("stripe_webhook_signature_invalid")
    assert sensitive_value not in response.get_data(as_text=True)
    assert_no_financial_side_effects(handler)


def test_authentic_unrelated_event_is_acknowledged_without_db_access(handler):
    response = post_event(handler, synthetic_event("product.created"))
    assert response.status_code == 200
    assert_no_financial_side_effects(handler)


def test_authentic_checkout_session_without_matching_advisory_is_a_noop(handler):
    response = post_event(handler)
    assert response.status_code == 200
    handler.query.filter_by.assert_called_once_with(
        stripe_checkout_session_id=SYNTHETIC_SESSION
    )
    handler.complete.assert_not_called()
    handler.db_session.commit.assert_not_called()


def test_verified_checkout_can_reach_existing_payment_handler(handler):
    advisory = SimpleNamespace(status="quote_sent", stripe_payment_intent_id=None)
    handler.query.first.return_value = advisory
    response = post_event(handler)
    assert response.status_code == 200
    assert advisory.stripe_payment_intent_id == SYNTHETIC_PI
    handler.query.filter_by.assert_called_once_with(
        stripe_checkout_session_id=SYNTHETIC_SESSION
    )
    handler.complete.assert_called_once_with(
        advisory,
        amount_cents=4900,
        currency="eur",
        provider="stripe",
        capture_note=f"Pago confirmado por Stripe. PI: {SYNTHETIC_PI}",
    )


def test_verified_duplicate_already_paid_does_not_complete_twice(handler):
    advisory = SimpleNamespace(status="paid_received", stripe_payment_intent_id=None)
    handler.query.first.return_value = advisory
    response = post_event(handler)
    assert response.status_code == 200
    handler.complete.assert_not_called()
    assert advisory.stripe_payment_intent_id is None


def test_payment_completion_failure_is_not_acknowledged(handler):
    advisory = SimpleNamespace(status="quote_sent", stripe_payment_intent_id=None)
    handler.query.first.return_value = advisory
    handler.complete.side_effect = RuntimeError("synthetic db failure")
    response = post_event(handler)
    assert response.status_code == 500
    handler.db_session.rollback.assert_called_once_with()
    handler.db_session.commit.assert_not_called()
