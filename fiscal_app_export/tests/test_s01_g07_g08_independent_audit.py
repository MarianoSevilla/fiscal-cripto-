"""Independent S01-G07/G08 security audit using synthetic local SQLite only.

Expected failures (strict XFAIL) intentionally encode contract deficiencies
found at PR #50 SHA 7fb321d893a2fc2f9e583110dc60be5a4f8b7b72.
They do not approve these behaviors. Remove corresponding xfail ONLY after
an independently reviewed remediation branch makes the secure behavior pass.
No Stripe API, Railway, PayPal, live customers, network or production DB.
"""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from flask import Flask
import pytest

from advisory_s01_checkout import S01CheckoutBlocked
from advisory_s01_test_orchestrator import create_synthetic_checkout
import advisory_s01_synthetic_acceptance_http as acceptance
from models import FiscalAdvisoryRequest, S01StripeCheckoutAttempt, db


NOW = 1_800_000_000
QUOTE_TOKEN = "Z" * 43
ORIGIN = acceptance.SYNTHETIC_ORIGIN
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def audit_store(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "testing")
    app = Flask("s01_audit_independent_no_network")
    app.config.update(
        TESTING=True, SECRET_KEY="independent-audit-fixture-secret-only",
        S01_SYNTHETIC_HTTP_HARNESS=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "audit-g07.sqlite"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    app.register_blueprint(
        acceptance.build_s01_synthetic_acceptance_blueprint(clock=lambda: NOW)
    )
    with app.app_context():
        db.create_all()
        case = FiscalAdvisoryRequest(
            full_name="Synthetic Audit Person",
            email="audit@example.invalid",
            tax_residence_country="ES",
            tax_year=2025,
            service_type="presupuesto_personalizado",
            case_description="Fictitious audit fixture; no client information",
            status="quote_sent",
            is_test=True,
            payment_link_token=QUOTE_TOKEN,
            quoted_amount=26000,
            rafa_fee_cents=20000,
            commission_cents=6000,
            commission_rate_bps=3000,
            quote_expires_at=datetime.fromtimestamp(
                NOW + 4 * 86400, timezone.utc
            ).replace(tzinfo=None),
        )
        db.session.add(case)
        db.session.commit()
        yield app, case.id
        db.session.remove()
        db.drop_all()


class OfflineProvider:
    """Fully in-process, with no import of Stripe SDK or HTTP client."""

    def create_session(self, *, params, idempotency_key):
        attempt = S01StripeCheckoutAttempt.query.filter_by(
            advisory_id=int(params["client_reference_id"])
        ).one()
        assert attempt.status == "creating"
        assert idempotency_key == attempt.idempotency_key
        return {
            "id": "cs_test_audit_fictitious_" + str(uuid4()).replace("-", ""),
            "livemode": False,
            "mode": "payment",
            "status": "open",
            "payment_status": "unpaid",
            "amount_total": params["line_items"][0]["price_data"]["unit_amount"],
            "currency": "eur",
            "client_reference_id": params["client_reference_id"],
            "metadata": dict(params["metadata"]),
            "url": "https://checkout.stripe.com/c/pay/cs_test_audit_in_memory",
        }


@pytest.mark.xfail(
    strict=True,
    reason="G07-AUD-001: existing reusable orchestrator does not require accepted quote",
)
def test_aud001_checkout_requires_persisted_quote_acceptance(audit_store):
    """Secure contract: direct reserve without acceptance must fail before IO."""
    _, advisory_id = audit_store
    case = db.session.get(FiscalAdvisoryRequest, advisory_id)
    assert case.quote_accepted_at is None
    with pytest.raises(S01CheckoutBlocked, match="aceptad|consent"):
        create_synthetic_checkout(
            advisory_id=advisory_id,
            token=QUOTE_TOKEN,
            now_ts=NOW,
            base_url=ORIGIN,
            stripe_test_key="sk_test_in_memory_never_external",
            provider=OfflineProvider(),
        )
    assert S01StripeCheckoutAttempt.query.filter_by(
        advisory_id=advisory_id
    ).count() == 0


@pytest.mark.xfail(
    strict=True,
    reason="G07-AUD-002: prior acceptance COMMIT survives failure before reservation",
)
def test_aud002_no_orphan_accepted_quote_after_pre_reservation_failure(
    audit_store, monkeypatch,
):
    """Secure contract: a local preparatory error must not freeze quote forever."""
    app, advisory_id = audit_store

    def offline_preflight_failure(**_kwargs):
        raise S01CheckoutBlocked("synthetic validation before reservation")

    monkeypatch.setattr(
        acceptance, "create_synthetic_checkout", offline_preflight_failure
    )
    client = app.test_client()
    path = f"/__synthetic__/s01/quotes/{advisory_id}"
    preview = client.get(
        path, headers={"X-S01-Quote-Token": QUOTE_TOKEN}, base_url=ORIGIN,
    )
    assert preview.status_code == 200
    nonce = preview.get_json()["csrf_token"]
    result = client.post(
        path + "/accept",
        json={"confirm": True, "total_cents": 26000, "csrf_token": nonce},
        headers={"X-S01-Quote-Token": QUOTE_TOKEN, "Origin": ORIGIN},
        base_url=ORIGIN,
    )
    assert result.status_code in (409, 503)
    db.session.remove()
    case = db.session.get(FiscalAdvisoryRequest, advisory_id)
    assert S01StripeCheckoutAttempt.query.filter_by(advisory_id=advisory_id).count() == 0
    # Current behavior is orphan acceptance; must instead rollback acceptance
    # for *pre-reservation* errors (not for post-POST uncertain provider results).
    assert case.quote_accepted_at is None


def test_aud003_no_runtime_routes_and_legacy_prefreeze_preserved():
    """Affirm the isolated harness is not a payment endpoint in app.py."""
    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "import advisory_s01_synthetic_acceptance_http" not in app_src
    assert "from advisory_s01_synthetic_acceptance_http import" not in app_src
    assert "build_s01_synthetic_acceptance_blueprint" not in app_src
    for decorator in (
        '@app.route("/api/pago/info/<token>", methods=["GET"])',
        '@app.route("/api/pago/iniciar/<token>", methods=["POST"])',
        '@app.route("/api/webhooks/stripe", methods=["POST"])',
    ):
        assert decorator in app_src
        snippet = app_src[app_src.index(decorator):][:240]
        assert "@advisory_financial_prefreeze()" in snippet


def test_aud004_fake_provider_has_no_payment_capability(audit_store):
    """Tests prove scope of fake, not a real Stripe Test session."""
    _, advisory_id = audit_store
    provider = OfflineProvider()
    case = db.session.get(FiscalAdvisoryRequest, advisory_id)
    assert case.quote_accepted_at is None
    assert acceptance._InProcessFakeStripeProvider.__module__ == (
        "advisory_s01_synthetic_acceptance_http"
    )
    assert not hasattr(provider, "api_key")
    assert not hasattr(provider, "capture")
    assert S01StripeCheckoutAttempt.query.count() == 0
