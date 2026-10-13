"""S01 G07/G08: isolated synthetic quote acceptance and Checkout HTTP harness.

NOT registered by app.py or any production entrypoint. Never calls Stripe,
PayPal or an HTTP client. No invoices, emails, transfers or payouts.
The provider is deliberately an in-process fake, not a configurable adapter.

The real customer route /pagar/<token> stays PREFREEZE (503).
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import os
import re
import secrets
import time

from flask import Blueprint, current_app, jsonify, request, session

from advisory_s01_checkout import S01CheckoutBlocked
from advisory_s01_test_orchestrator import (
    S01AcceptanceIntent,
    create_synthetic_checkout,
)
from models import FiscalAdvisoryRequest, S01StripeCheckoutAttempt, db

SYNTHETIC_ORIGIN = "https://checkout-test.example.invalid"
SYNTHETIC_TEST_KEY = "sk_test_s01_in_process_fake_no_network"
MAX_JSON_BYTES = 4096
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,64}\Z")
_CSRF_SESSION_KEY = "s01_synthetic_quote_csrf"
_CONFIRM_KEYS = frozenset(("csrf_token", "confirm", "total_cents"))


def _eligible(*, item: FiscalAdvisoryRequest, now_ts: int) -> bool:
    if (
        item.status != "quote_sent" or item.is_test is not True
        or item.quote_accepted_at is not None or not item.payment_link_token
        or item.quoted_amount is None or item.rafa_fee_cents is None
        or item.commission_cents is None or item.commission_rate_bps != 3000
        or any(type(n) is not int for n in (
            item.quoted_amount, item.rafa_fee_cents, item.commission_cents))
    ):
        return False
    fee = item.rafa_fee_cents
    total = item.quoted_amount
    if (fee < 100 or item.commission_cents != (fee * 30 + 50) // 100
            or total != fee + item.commission_cents
            or not 100 <= total <= 99_999_999):
        return False
    expiry = item.quote_expires_at
    if not isinstance(expiry, datetime):
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if expiry.timestamp() < now_ts + 1800:
        return False
    if any(value is not None for value in (
        item.paypal_order_id, item.paypal_capture_id, item.payment_provider,
        item.stripe_checkout_session_id, item.stripe_payment_intent_id,
        item.amount_paid, item.paid_at,
    )):
        return False
    if S01StripeCheckoutAttempt.query.filter_by(advisory_id=item.id).first() is not None:
        return False
    return True


def _runtime_ok() -> bool:
    return (
        os.environ.get("FLASK_ENV") == "testing"
        and current_app.testing is True
        and current_app.config.get("S01_SYNTHETIC_HTTP_HARNESS") is True
        and current_app.config.get("SECRET_KEY") is not None
    )


def _strict_token() -> str | None:
    supplied = request.headers.get("X-S01-Quote-Token")
    return supplied if isinstance(supplied, str) and _TOKEN_RE.fullmatch(supplied) else None


def _no_cache(payload: dict, code: int):
    response = jsonify(payload)
    response.status_code = code
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _csrf_valid(*, advisory_id: int, token: str, submitted: str) -> bool:
    data = session.get(_CSRF_SESSION_KEY)
    if not isinstance(data, dict):
        return False
    if data.get("advisory_id") != advisory_id:
        return False
    if not isinstance(submitted, str) or not (30 <= len(submitted) <= 128):
        return False
    token_digest = sha256(token.encode("ascii")).hexdigest()
    return (
        hmac.compare_digest(str(data.get("quote_digest", "")), token_digest)
        and hmac.compare_digest(str(data.get("nonce", "")), submitted)
    )


class _InProcessFakeStripeProvider:
    """Owns no HTTP/SDK client or credentials: deterministically fakes Session.create."""

    def create_session(self, *, params: dict, idempotency_key: str) -> dict:
        # The real orchestrator checks DB COMMIT before this call.
        attempt_id = params["metadata"]["s01_attempt_id"]
        if not idempotency_key == "s01-checkout-v1-" + attempt_id:
            raise S01CheckoutBlocked("Fake idempotency mismatch")
        fake_session_id = "cs_test_s01offline_" + attempt_id.replace("-", "")
        return {
            "id": fake_session_id,
            "livemode": False,
            "mode": "payment",
            "status": "open",
            "payment_status": "unpaid",
            "amount_total": params["line_items"][0]["price_data"]["unit_amount"],
            "currency": "eur",
            "client_reference_id": params["client_reference_id"],
            "metadata": dict(params["metadata"]),
            # This is NEVER returned to the browser or visited by this harness.
            "url": "https://checkout.stripe.com/c/pay/" + fake_session_id,
        }


def build_s01_synthetic_acceptance_blueprint(*, clock=None) -> Blueprint:
    """Factory to be used ONLY in local isolated Flask TEST fixtures.

    No app.py import/registration. Its fake provider cannot call Stripe Test,
    let alone Live. A real HTTP/provider integration requires separate review.
    """
    if os.environ.get("FLASK_ENV") != "testing":
        raise RuntimeError("S01 synthetic quote HTTP unavailable")
    _clock = clock if clock is not None else time.time
    bp = Blueprint("s01_offline_quote_acceptance", __name__)

    @bp.get("/__synthetic__/s01/quotes/<int:advisory_id>")
    def preview_quote(advisory_id: int):
        if not _runtime_ok():
            return _no_cache({"error": "unavailable"}, 503)
        token = _strict_token()
        if token is None or advisory_id < 1:
            return _no_cache({"error": "not_found"}, 404)
        item = FiscalAdvisoryRequest.query.filter_by(
            id=advisory_id, payment_link_token=token
        ).first()
        now_ts = int(_clock())
        if item is None or not _eligible(item=item, now_ts=now_ts):
            return _no_cache({"error": "not_available"}, 404)

        nonce = secrets.token_urlsafe(32)
        session[_CSRF_SESSION_KEY] = {
            "advisory_id": advisory_id,
            "quote_digest": sha256(token.encode("ascii")).hexdigest(),
            "nonce": nonce,
        }
        # Do not return customer name, email, token, IP, billing data or URL.
        return _no_cache({
            "state": "synthetic_quote_ready",
            "rafa_fee_cents": item.rafa_fee_cents,
            "commission_cents": item.commission_cents,
            "total_cents": item.quoted_amount,
            "commission_rate_bps": item.commission_rate_bps,
            "currency": "eur",
            "must_confirm_amount": True,
            "csrf_token": nonce,
        }, 200)

    @bp.post("/__synthetic__/s01/quotes/<int:advisory_id>/accept")
    def accept_quote(advisory_id: int):
        if not _runtime_ok():
            return _no_cache({"error": "unavailable"}, 503)
        # Explicit same-origin + session-bound CSRF; no GET side effects.
        if request.headers.get("Origin") != SYNTHETIC_ORIGIN:
            return _no_cache({"error": "forbidden"}, 403)
        if request.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
            return _no_cache({"error": "forbidden"}, 403)
        if (request.content_length is None
                or request.content_length > MAX_JSON_BYTES
                or not request.is_json):
            return _no_cache({"error": "invalid_request"}, 400)
        raw = request.get_data(cache=True)
        if len(raw) > MAX_JSON_BYTES:
            return _no_cache({"error": "invalid_request"}, 400)
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != _CONFIRM_KEYS:
            return _no_cache({"error": "invalid_request"}, 400)
        token = _strict_token()
        if (token is None or advisory_id < 1
                or data.get("confirm") is not True
                or type(data.get("total_cents")) is not int):
            return _no_cache({"error": "invalid_request"}, 400)
        if not _csrf_valid(
            advisory_id=advisory_id, token=token, submitted=data.get("csrf_token")
        ):
            return _no_cache({"error": "forbidden"}, 403)

        # One-use, BEFORE database/provider activity, also when validation fails.
        session.pop(_CSRF_SESSION_KEY, None)
        now_ts = int(_clock())
        # The orchestrator now owns BOTH acceptance and the first durable
        # creating attempt under one locked SQL transaction. No prior COMMIT
        # and no HTTP-only acceptance invariant: a crash before reservation
        # leaves neither consent nor attempt; after COMMIT it blocks retries.
        try:
            created = create_synthetic_checkout(
                advisory_id=advisory_id,
                token=token,
                now_ts=now_ts,
                base_url=SYNTHETIC_ORIGIN,
                stripe_test_key=SYNTHETIC_TEST_KEY,
                provider=_InProcessFakeStripeProvider(),
                acceptance=S01AcceptanceIntent(
                    total_cents=data["total_cents"],
                    accepted_at_ts=now_ts,
                ),
            )
        except S01CheckoutBlocked:
            return _no_cache({"error": "requires_reconciliation"}, 409)
        except Exception:
            return _no_cache({"error": "requires_reconciliation"}, 503)
        # Never return a fake checkout.stripe.com URL: it is not bookable/payable.
        return _no_cache({
            "state": "synthetic_checkout_reserved_not_paid",
            "attempt_id": created.attempt_id,
            "payment_confirmed": False,
            "external_stripe_called": False,
        }, 202)

    return bp
