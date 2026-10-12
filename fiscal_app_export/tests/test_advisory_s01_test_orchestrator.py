"""S01 TEST orquestación de cobros sin llamadas reales al proveedor.

Pruebas del ciclo de reserva/creación con SQLite efímera. No sustituyen la
prueba futura entre dos procesos de PostgreSQL 18 ni la conciliación externa.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
import pytest

from advisory_s01_checkout import S01CheckoutBlocked
from advisory_s01_test_orchestrator import create_synthetic_checkout
from models import FiscalAdvisoryRequest, S01StripeCheckoutAttempt, db


NOW = 1_800_000_000
ORIGIN = "https://checkout-test.example.invalid"
TOKEN = "A" * 43


@pytest.fixture
def synthetic_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "testing")
    app = Flask("s01_orchestrator_synthetic")
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "test-s01.sqlite3"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        item = FiscalAdvisoryRequest(
            full_name="Cliente Sintético",
            email="synthetic@example.invalid",
            case_description="Caso fiscal inventado de pruebas.",
            tax_residence_country="España",
            tax_year=2025,
            service_type="presupuesto_personalizado",
            status="quote_sent",
            payment_link_token=TOKEN,
            quoted_amount=26000,
            rafa_fee_cents=20000,
            commission_cents=6000,
            commission_rate_bps=3000,
            is_test=True,
            quote_expires_at=datetime.fromtimestamp(NOW + 5 * 86400, tz=timezone.utc)
                .replace(tzinfo=None),
        )
        db.session.add(item)
        db.session.commit()
        yield item.id
        db.session.remove()
        db.drop_all()


class FakeProvider:
    def __init__(self, *, changes=None, error=None):
        self.calls = []
        self.changes = changes or {}
        self.error = error

    def create_session(self, *, params, idempotency_key):
        # Evidencia de reserva ya confirmada EN BD antes de cualquier POST.
        attempt = S01StripeCheckoutAttempt.query.filter_by(
            id=params["metadata"]["s01_attempt_id"]
        ).first()
        assert attempt is not None
        assert attempt.status == "creating"
        assert attempt.idempotency_key == idempotency_key
        assert attempt.checkout_session_id is None
        self.calls.append((params, idempotency_key))
        if self.error:
            raise self.error

        response = {
            "id": "cs_test_synthetic_session",
            "livemode": False,
            "mode": "payment",
            "status": "open",
            "payment_status": "unpaid",
            "amount_total": params["line_items"][0]["price_data"]["unit_amount"],
            "currency": "eur",
            "client_reference_id": params["client_reference_id"],
            "metadata": dict(params["metadata"]),
            "url": "https://checkout.stripe.com/c/pay/cs_test_synthetic_session#fixture",
        }
        response.update(self.changes)
        return response


def launch(advisory_id, provider, **changes):
    kwargs = dict(
        advisory_id=advisory_id,
        token=TOKEN,
        now_ts=NOW,
        base_url=ORIGIN,
        stripe_test_key="sk_test_synthetic-only",
        provider=provider,
    )
    kwargs.update(changes)
    return create_synthetic_checkout(**kwargs)


def test_committed_reservation_before_provider_and_exact_link(synthetic_store):
    provider = FakeProvider()
    result = launch(synthetic_store, provider)
    assert result.session_id == "cs_test_synthetic_session"
    assert result.url.startswith("https://checkout.stripe.com/c/pay/")
    assert len(provider.calls) == 1
    params, idempotency_key = provider.calls[0]
    assert idempotency_key == "s01-checkout-v1-" + result.attempt_id
    assert params["line_items"][0]["price_data"]["unit_amount"] == 26000
    assert params["payment_method_types"] == ["card"]
    attempt = S01StripeCheckoutAttempt.query.one()
    advisory = db.session.get(FiscalAdvisoryRequest, synthetic_store)
    assert attempt.status == "ready"
    assert attempt.checkout_session_id == result.session_id
    assert advisory.stripe_checkout_session_id == result.session_id
    assert advisory.status == "quote_sent"  # JAMÁS confirmar pago al crear Checkout
    assert advisory.paid_at is None


def test_second_browser_request_is_blocked_even_if_ready(synthetic_store):
    provider = FakeProvider()
    launch(synthetic_store, provider)
    with pytest.raises(S01CheckoutBlocked, match="ya reservado|actividad financiera previa"):
        launch(synthetic_store, provider)
    assert len(provider.calls) == 1
    assert S01StripeCheckoutAttempt.query.count() == 1


@pytest.mark.parametrize("key,environment", [
    ("sk_live_test-must-never-run", "testing"),
    ("sk_test_any", "production"),
    ("sk_test_any", "staging"),
    ("", "testing"),
])
def test_live_or_incomplete_configuration_never_calls_provider(
    synthetic_store, monkeypatch, key, environment,
):
    monkeypatch.setenv("FLASK_ENV", environment)
    provider = FakeProvider()
    with pytest.raises(S01CheckoutBlocked):
        launch(synthetic_store, provider, stripe_test_key=key)
    assert not provider.calls
    assert S01StripeCheckoutAttempt.query.count() == 0


def test_real_customer_flag_is_never_eligible(synthetic_store):
    item = db.session.get(FiscalAdvisoryRequest, synthetic_store)
    item.is_test = False
    db.session.commit()
    provider = FakeProvider()
    with pytest.raises(S01CheckoutBlocked, match="no apto"):
        launch(synthetic_store, provider)
    assert provider.calls == []


@pytest.mark.parametrize("changes", [
    {"total_cents":26001},
    {"commission_cents":5900},
    {"commission_rate_bps":2000},
    {"status":"submitted"},
    {"payment_link_token":"B"*43},
    {"paypal_order_id":"unreconciled-paypal-order"},
    {"stripe_payment_intent_id":"pi_old"},
    {"quoted_amount":20000},
])
def test_wrong_quote_or_existing_financial_references_rejected(
    synthetic_store, changes,
):
    item = db.session.get(FiscalAdvisoryRequest, synthetic_store)
    for key, value in changes.items():
        if key == "total_cents":
            item.quoted_amount = value
        else:
            setattr(item, key, value)
    db.session.commit()
    provider = FakeProvider()
    with pytest.raises(S01CheckoutBlocked):
        launch(synthetic_store, provider)
    assert not provider.calls
    assert S01StripeCheckoutAttempt.query.count() == 0


@pytest.mark.parametrize("url", [
    "https://marianosevilla.com",
    "https://www.marianosevilla.com",
    "https://checkout.stripe.com",
    "http://checkout-test.example.invalid",
    "https://pay.evil.example",
])
def test_origin_must_be_synthetic_or_staging(synthetic_store, url):
    provider = FakeProvider()
    with pytest.raises(S01CheckoutBlocked):
        launch(synthetic_store, provider, base_url=url)
    assert not provider.calls


def test_provider_timeout_blocks_all_retry(synthetic_store):
    provider = FakeProvider(error=TimeoutError("synthetic timeout"))
    with pytest.raises(S01CheckoutBlocked, match="incierto"):
        launch(synthetic_store, provider)
    attempt = S01StripeCheckoutAttempt.query.one()
    assert attempt.status == "uncertain"
    assert attempt.checkout_session_id is None
    with pytest.raises(S01CheckoutBlocked, match="ya reservado|actividad financiera previa"):
        launch(synthetic_store, provider)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("changes", [
    {"livemode":True}, {"id":"cs_live_wrong"}, {"currency":"usd"},
    {"amount_total":20000}, {"payment_status":"paid"}, {"status":"complete"},
    {"client_reference_id":"other-id"}, {"url":"https://evil.example/pay/"},
    {"metadata":{}},
])
def test_invalid_stripe_result_remains_uncertain(synthetic_store, changes):
    provider = FakeProvider(changes=changes)
    with pytest.raises(S01CheckoutBlocked, match="incierto"):
        launch(synthetic_store, provider)
    assert len(provider.calls) == 1
    attempt = S01StripeCheckoutAttempt.query.one()
    assert attempt.status == "uncertain"
    assert attempt.checkout_session_id is None
    assert db.session.get(FiscalAdvisoryRequest, synthetic_store).status == "quote_sent"


def test_no_facturas_emails_or_charge_confirmed(synthetic_store):
    provider = FakeProvider()
    assert launch(synthetic_store, provider).session_id.startswith("cs_test_")
    assert S01StripeCheckoutAttempt.query.count() == 1
    advisory = db.session.get(FiscalAdvisoryRequest, synthetic_store)
    assert advisory.amount_paid is None
    assert advisory.paid_at is None
    assert advisory.payment_provider is None


def test_no_provider_or_reservation_without_valid_id(synthetic_store):
    provider = FakeProvider()
    with pytest.raises(S01CheckoutBlocked):
        launch(0, provider)
    assert provider.calls == []
    assert S01StripeCheckoutAttempt.query.count() == 0


def test_sdk16_stripeobject_checkout_response_is_supported(synthetic_store):
    """Stripe SDK v16 devuelve StripeObject, no siempre dict."""
    import stripe

    class StripeObjectProvider(FakeProvider):
        def create_session(self, *, params, idempotency_key):
            response = super().create_session(
                params=params, idempotency_key=idempotency_key
            )
            return stripe.StripeObject(**response)

    provider = StripeObjectProvider()
    result = launch(synthetic_store, provider)
    assert result.session_id == "cs_test_synthetic_session"
    assert result.url.startswith("https://checkout.stripe.com/c/pay/")
    assert len(provider.calls) == 1
    a = S01StripeCheckoutAttempt.query.one()
    assert a.status == "ready"
    assert a.checkout_session_id == result.session_id
    assert db.session.get(FiscalAdvisoryRequest, synthetic_store).stripe_checkout_session_id == result.session_id


def test_invalid_sdk16_stripeobject_keeps_reservation_uncertain(synthetic_store):
    import stripe

    class InvalidStripeObjectProvider(FakeProvider):
        def create_session(self, *, params, idempotency_key):
            response = super().create_session(
                params=params, idempotency_key=idempotency_key
            )
            response["amount_total"] = 100
            return stripe.StripeObject(**response)

    provider = InvalidStripeObjectProvider()
    with pytest.raises(S01CheckoutBlocked, match="incierto"):
        launch(synthetic_store, provider)
    assert len(provider.calls) == 1
    a = S01StripeCheckoutAttempt.query.one()
    assert a.status == "uncertain"
    assert a.checkout_session_id is None
    assert db.session.get(FiscalAdvisoryRequest, synthetic_store).stripe_checkout_session_id is None


def test_sdk_conversion_exception_fails_closed(synthetic_store):
    class UnparseableSDKResponse:
        def to_dict(self):
            raise ValueError("Synthetic SDK conversion failure")

    class InvalidProvider(FakeProvider):
        def create_session(self, *, params, idempotency_key):
            super().create_session(params=params, idempotency_key=idempotency_key)
            return UnparseableSDKResponse()

    provider = InvalidProvider()
    with pytest.raises(S01CheckoutBlocked, match="incierto"):
        launch(synthetic_store, provider)
    assert len(provider.calls) == 1
    assert S01StripeCheckoutAttempt.query.one().status == "uncertain"
    assert db.session.get(FiscalAdvisoryRequest, synthetic_store).stripe_checkout_session_id is None
