"""S01 etapa 2: contratos de Checkout sin red ni credenciales."""
from dataclasses import replace
from uuid import uuid4
from unittest.mock import Mock

import pytest

from advisory_s01_checkout import (
    S01CheckoutBlocked,
    S01Reservation,
    build_test_checkout_request,
    verify_test_checkout_paid,
)

NOW = 1_800_000_000


@pytest.fixture
def reservation():
    return S01Reservation(
        attempt_id=str(uuid4()),
        advisory_id=17,
        quote_token="A" * 43,
        rafa_fee_cents=20000,
        commission_cents=6000,
        total_cents=26000,
        quote_expires_at_ts=NOW + 86400 * 5,
        customer_email="cliente@example.test",
    )


@pytest.fixture
def payload(reservation):
    return build_test_checkout_request(
        reservation=reservation, base_url="https://marianosevilla.com", now_ts=NOW
    )


def test_checkout_exact_and_no_live_processing(reservation, payload):
    assert payload["mode"] == "payment"
    assert payload["payment_method_types"] == ["card"]
    assert payload["line_items"][0]["price_data"]["unit_amount"] == 26000
    assert payload["line_items"][0]["price_data"]["currency"] == "eur"
    assert payload["customer_email"] == "cliente@example.test"
    assert payload["client_reference_id"] == "17"
    assert payload["expires_at"] == NOW + 86400
    assert payload["metadata"]["s01_attempt_id"] == reservation.attempt_id
    assert payload["metadata"]["s01_quote_sha256"] == reservation.quote_fingerprint
    assert reservation.quote_token not in str(payload["metadata"])
    assert payload["success_url"].endswith("session_id={CHECKOUT_SESSION_ID}")
    assert "checkout.session.completed" not in str(payload)
    assert reservation.idempotency_key == "s01-checkout-v1-" + reservation.attempt_id


def test_no_network_side_effects(reservation):
    stripe = Mock()
    a = build_test_checkout_request(reservation=reservation, base_url="https://marianosevilla.com", now_ts=NOW)
    b = build_test_checkout_request(reservation=reservation, base_url="https://marianosevilla.com", now_ts=NOW)
    assert a == b
    stripe.assert_not_called()


@pytest.mark.parametrize("mutation", [
    {"rafa_fee_cents":20001}, {"commission_cents":5999}, {"total_cents":25999},
    {"total_cents":0}, {"total_cents":26000.0}, {"rafa_fee_cents":True},
    {"advisory_id":0}, {"quote_token":"bad"}, {"customer_email":"invalid"},
    {"attempt_id":"not-uuid"}, {"quote_expires_at_ts":NOW+1799},
])
def test_invalid_checkout_reservation_fail_closed(reservation,mutation):
    with pytest.raises(S01CheckoutBlocked):
        build_test_checkout_request(reservation=replace(reservation,**mutation),base_url="https://marianosevilla.com",now_ts=NOW)


@pytest.mark.parametrize("url", [
    "http://marianosevilla.com", "https://marianosevilla.com/foo",
    "https://user:password@marianosevilla.com", "https://marianosevilla.com?q=foo",
    "https://marianosevilla.com/#bar", "file:///test", "https://bad host.test",
])
def test_untrusted_base_url_rejected(reservation,url):
    with pytest.raises(S01CheckoutBlocked):
        build_test_checkout_request(reservation=reservation,base_url=url,now_ts=NOW)


def test_quote_expiry_earlier_than_24h(reservation):
    params=build_test_checkout_request(reservation=replace(reservation,quote_expires_at_ts=NOW+3600),base_url="https://marianosevilla.com",now_ts=NOW)
    assert params["expires_at"]==NOW+3600


@pytest.fixture
def paid_session(reservation):
    return dict(
        id="cs_test_synthetic", livemode=False, mode="payment", status="complete",
        payment_status="paid", amount_total=26000, currency="eur",
        client_reference_id="17", metadata={
            "s01_attempt_id":reservation.attempt_id,
            "s01_advisory_id":"17",
            "s01_quote_sha256":reservation.quote_fingerprint,
        },payment_intent="pi_synthetic",
    )


def test_paid_session_verified(reservation,paid_session):
    assert verify_test_checkout_paid(session=paid_session,reservation=reservation,expected_session_id="cs_test_synthetic")=="pi_synthetic"


@pytest.mark.parametrize("changes", [
    {"livemode":True}, {"livemode":None}, {"id":"cs_test_other"},
    {"status":"open"}, {"payment_status":"unpaid"},
    {"amount_total":20000}, {"amount_total":26000.0}, {"currency":"usd"},
    {"client_reference_id":"18"}, {"payment_intent":None},
    {"mode":"subscription"}, {"metadata":{}},
])
def test_payment_mismatch_rejected(reservation,paid_session,changes):
    with pytest.raises(S01CheckoutBlocked):
        verify_test_checkout_paid(session={**paid_session,**changes},reservation=reservation,expected_session_id="cs_test_synthetic")


def test_wrong_metadata_is_rejected(reservation,paid_session):
    for key,value in [
        ("s01_attempt_id",str(uuid4())), ("s01_advisory_id","18"),
        ("s01_quote_sha256","0"*64),
    ]:
        bad=dict(paid_session)
        bad["metadata"]={**bad["metadata"],key:value}
        with pytest.raises(S01CheckoutBlocked):
            verify_test_checkout_paid(session=bad,reservation=reservation,expected_session_id="cs_test_synthetic")


def test_live_session_never_accepted(reservation,paid_session):
    bad={**paid_session,"id":"cs_live_synthetic","livemode":True}
    with pytest.raises(S01CheckoutBlocked):
        verify_test_checkout_paid(session=bad,reservation=reservation,expected_session_id="cs_live_synthetic")
