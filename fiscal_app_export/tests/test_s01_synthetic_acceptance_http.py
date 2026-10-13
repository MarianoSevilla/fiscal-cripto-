"""S01 G07/G08 synthetic-only HTTP acceptance contract.

No real account, Stripe SDK calls, PayPal, emails, invoices, transfers or live
routes. All records synthetic and ephemeral.
"""
from datetime import datetime, timezone

from flask import Flask
import pytest

from advisory_s01_synthetic_acceptance_http import (
    SYNTHETIC_ORIGIN,
    build_s01_synthetic_acceptance_blueprint,
)
from models import FiscalAdvisoryRequest, S01StripeCheckoutAttempt, db

NOW = 1_800_000_000
TOKEN = "X" * 43
ROUTE = "/__synthetic__/s01/quotes"
HEADERS = {"X-S01-Quote-Token": TOKEN}


@pytest.fixture
def test_app(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "testing")
    app = Flask("s01_synthetic_acceptance_http")
    app.config.update(
        TESTING=True, SECRET_KEY="s01-local-test-only-csrf-secret",
        S01_SYNTHETIC_HTTP_HARNESS=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "s01-g07.sqlite"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    app.register_blueprint(build_s01_synthetic_acceptance_blueprint(clock=lambda: NOW))
    with app.app_context():
        db.create_all()
        item = FiscalAdvisoryRequest(
            full_name="Cliente ficticio, nunca producción",
            email="customer@example.invalid",
            tax_residence_country="España",
            tax_year=2025,
            service_type="presupuesto_personalizado",
            case_description="Dossier inventado exclusivamente en tests.",
            status="quote_sent", is_test=True, payment_link_token=TOKEN,
            quoted_amount=26000, rafa_fee_cents=20000, commission_cents=6000,
            commission_rate_bps=3000,
            quote_expires_at=datetime.fromtimestamp(
                NOW + 5 * 86400, timezone.utc
            ).replace(tzinfo=None),
        )
        db.session.add(item)
        db.session.commit()
        yield app, item.id
        db.session.remove()
        db.drop_all()


def get_quote(app, ident, *, token=TOKEN):
    return app.test_client().get(
        f"{ROUTE}/{ident}",
        headers={"X-S01-Quote-Token": token},
        base_url=SYNTHETIC_ORIGIN,
    )


def preview_and_accept(app, ident, *, changes=None, token=TOKEN, client=None,
                       origin=SYNTHETIC_ORIGIN):
    client = client or app.test_client()
    path = f"{ROUTE}/{ident}"
    pre = client.get(path, headers={"X-S01-Quote-Token": token},
                     base_url=SYNTHETIC_ORIGIN)
    if pre.status_code != 200:
        return pre
    data = pre.get_json()
    body = {
        "csrf_token": data["csrf_token"], "confirm": True,
        "total_cents": data["total_cents"],
    }
    body.update(changes or {})
    return client.post(path + "/accept", json=body,
                       headers={"X-S01-Quote-Token": token, "Origin": origin},
                       base_url=SYNTHETIC_ORIGIN)


def snapshot(ident):
    db.session.remove()
    adv = db.session.get(FiscalAdvisoryRequest, ident)
    return {
        "accepted": adv.quote_accepted_at is not None,
        "paid": adv.paid_at,
        "provider": adv.payment_provider,
        "amount_paid": adv.amount_paid,
        "state": adv.status,
        "attempt_count": S01StripeCheckoutAttempt.query.filter_by(advisory_id=ident).count(),
    }


def test_preview_is_read_only_and_no_pii_disclosed(test_app):
    app, ident = test_app
    with app.app_context():
        response = get_quote(app, ident)
        assert response.status_code == 200
        data = response.get_json()
        assert data["state"] == "synthetic_quote_ready"
        assert data["rafa_fee_cents"] == 20000
        assert data["commission_cents"] == 6000
        assert data["total_cents"] == 26000
        assert data["commission_rate_bps"] == 3000
        assert data["currency"] == "eur"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Referrer-Policy"] == "no-referrer"
        raw = response.get_data(as_text=True)
        for forbidden in (TOKEN, "example.invalid", "Cliente ficticio", "customer@",
                          "case_description", "quote_message", "payment_link_token"):
            assert forbidden not in raw
        assert snapshot(ident)["accepted"] is False
        assert snapshot(ident)["attempt_count"] == 0


def test_explicit_acceptance_committed_once_and_fake_checkout_never_paid(test_app):
    app, ident = test_app
    with app.app_context():
        res = preview_and_accept(app, ident)
        assert res.status_code == 202
        assert res.get_json()["state"] == "synthetic_checkout_reserved_not_paid"
        assert res.get_json()["external_stripe_called"] is False
        assert res.get_json()["payment_confirmed"] is False
        assert "checkout.stripe.com" not in res.get_data(as_text=True)
        counts = snapshot(ident)
        assert counts == {
            "accepted": True, "paid": None, "provider": None,
            "amount_paid": None, "state": "quote_sent", "attempt_count": 1,
        }
        attempt = S01StripeCheckoutAttempt.query.one()
        assert attempt.status == "ready"
        assert attempt.checkout_session_id.startswith("cs_test_s01offline_")
        assert db.session.get(FiscalAdvisoryRequest, ident).stripe_checkout_session_id == attempt.checkout_session_id
        assert get_quote(app, ident).status_code == 404


@pytest.mark.parametrize("body", [
    {"total_cents": 20000}, {"total_cents": 26001}, {"total_cents": True},
    {"total_cents": "26000"}, {"confirm": False}, {"confirm": 1},
    {"csrf_token": "invalid" * 7}, {"unexpected": "extra"},
])
def test_explicit_amount_or_csrf_tampering_rejected_without_reservation(test_app, body):
    app, ident = test_app
    with app.app_context():
        res = preview_and_accept(app, ident, changes=body)
        assert res.status_code in (400, 403, 409)
        assert snapshot(ident)["attempt_count"] == 0
        assert snapshot(ident)["paid"] is None
        assert snapshot(ident)["accepted"] is False


def test_csrf_bound_to_session_quote_token_and_advisory(test_app):
    app, ident = test_app
    with app.app_context():
        client_a = app.test_client()
        client_b = app.test_client()
        quote = client_a.get(f"{ROUTE}/{ident}", headers=HEADERS,
                             base_url=SYNTHETIC_ORIGIN).get_json()
        body = {"csrf_token": quote["csrf_token"], "confirm": True,
                "total_cents": quote["total_cents"]}
        res = client_b.post(f"{ROUTE}/{ident}/accept", json=body,
                            headers={**HEADERS, "Origin": SYNTHETIC_ORIGIN},
                            base_url=SYNTHETIC_ORIGIN)
        assert res.status_code == 403
        assert snapshot(ident)["attempt_count"] == 0


def test_wrong_token_or_non_test_case_is_not_visible(test_app):
    app, ident = test_app
    with app.app_context():
        assert get_quote(app, ident, token="Y" * 43).status_code == 404
        assert get_quote(app, ident, token="bad").status_code == 404
        item = db.session.get(FiscalAdvisoryRequest, ident)
        item.is_test = False
        db.session.commit()
        assert get_quote(app, ident).status_code == 404
        assert snapshot(ident)["attempt_count"] == 0


def test_expired_quote_rejected_before_acceptance(test_app):
    app, ident = test_app
    with app.app_context():
        item = db.session.get(FiscalAdvisoryRequest, ident)
        item.quote_expires_at = datetime.fromtimestamp(
            NOW + 1700, timezone.utc
        ).replace(tzinfo=None)
        db.session.commit()
        assert get_quote(app, ident).status_code == 404
        assert snapshot(ident)["accepted"] is False


def test_changed_price_after_preview_is_rejected(test_app):
    app, ident = test_app
    with app.app_context():
        client = app.test_client()
        quote = client.get(f"{ROUTE}/{ident}", headers=HEADERS,
                           base_url=SYNTHETIC_ORIGIN).get_json()
        item = db.session.get(FiscalAdvisoryRequest, ident)
        item.quoted_amount = 26100
        db.session.commit()
        res = client.post(f"{ROUTE}/{ident}/accept", json={
            "confirm": True, "csrf_token": quote["csrf_token"],
            "total_cents": 26000,
        }, headers={**HEADERS, "Origin": SYNTHETIC_ORIGIN}, base_url=SYNTHETIC_ORIGIN)
        assert res.status_code == 409
        assert snapshot(ident)["accepted"] is False
        assert snapshot(ident)["attempt_count"] == 0


def test_cross_origin_and_missing_origin_never_accept(test_app):
    app, ident = test_app
    with app.app_context():
        for origin in ("https://malicious.example.invalid", ""):
            client = app.test_client()
            quote = client.get(f"{ROUTE}/{ident}", headers=HEADERS,
                               base_url=SYNTHETIC_ORIGIN).get_json()
            res = client.post(f"{ROUTE}/{ident}/accept", json={
                "confirm": True, "csrf_token": quote["csrf_token"],
                "total_cents": 26000,
            }, headers={**HEADERS, "Origin": origin},
                               base_url=SYNTHETIC_ORIGIN)
            assert res.status_code == 403
        assert snapshot(ident)["attempt_count"] == 0


def test_fake_provider_timeout_still_blocks_new_attempt(test_app, monkeypatch):
    from advisory_s01_synthetic_acceptance_http import _InProcessFakeStripeProvider
    app, ident = test_app
    with app.app_context():
        calls = []

        def fail(self, *, params, idempotency_key):
            calls.append(params["metadata"]["s01_attempt_id"])
            raise TimeoutError("CI fake interruption")

        monkeypatch.setattr(_InProcessFakeStripeProvider, "create_session", fail)
        res = preview_and_accept(app, ident)
        assert res.status_code == 409
        assert snapshot(ident)["accepted"] is True
        assert snapshot(ident)["attempt_count"] == 1
        assert S01StripeCheckoutAttempt.query.one().status == "uncertain"
        assert len(calls) == 1
        assert get_quote(app, ident).status_code == 404
        assert len(calls) == 1


def test_reject_runtime_config_and_no_endpoint_on_real_app(test_app, monkeypatch):
    app, ident = test_app
    with app.app_context():
        client = app.test_client()
        monkeypatch.setenv("FLASK_ENV", "production")
        res = client.get(f"{ROUTE}/{ident}", headers=HEADERS,
                         base_url=SYNTHETIC_ORIGIN)
        assert res.status_code == 503
        monkeypatch.setenv("FLASK_ENV", "testing")
        app.config["S01_SYNTHETIC_HTTP_HARNESS"] = False
        res = client.get(f"{ROUTE}/{ident}", headers=HEADERS,
                         base_url=SYNTHETIC_ORIGIN)
        assert res.status_code == 503
        assert snapshot(ident)["attempt_count"] == 0


def test_replay_does_not_double_reserve(test_app):
    app, ident = test_app
    with app.app_context():
        client = app.test_client()
        quote = client.get(f"{ROUTE}/{ident}", headers=HEADERS,
                           base_url=SYNTHETIC_ORIGIN).get_json()
        body = {"confirm": True, "csrf_token": quote["csrf_token"],
                "total_cents": 26000}
        headers = {**HEADERS, "Origin": SYNTHETIC_ORIGIN}
        first = client.post(f"{ROUTE}/{ident}/accept", json=body,
                            headers=headers, base_url=SYNTHETIC_ORIGIN)
        assert first.status_code == 202
        second = client.post(f"{ROUTE}/{ident}/accept", json=body,
                             headers=headers, base_url=SYNTHETIC_ORIGIN)
        assert second.status_code == 403
        assert snapshot(ident)["attempt_count"] == 1
