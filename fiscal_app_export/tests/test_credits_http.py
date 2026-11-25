from io import BytesIO
from uuid import uuid4
import hashlib
import hmac
import json
import time
import base64
import tempfile
import os

import pytest
from flask import Flask, jsonify, request
from flask_login import LoginManager, login_required

from models import db, User, CreditWallet, CreditPurchase, CreditAnalysis
from credit_ledger import attach_checkout_session, confirm_test_payment
from credits_routes import credits_bp, register_analysis_hooks


@pytest.fixture
def web(tmp_path):
    app = Flask("credits-http-test")
    app.config.update(
        SECRET_KEY="synthetic-credit-http-test-secret",
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "credits-http.sqlite"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        CREDITS_ENABLED=True, CREDITS_TEST_MODE=True,
        STRIPE_CREDITS_TEST_SECRET="sk_test_synthetic_only",
        STRIPE_CREDITS_TEST_WEBHOOK_SECRET="whsec_synthetic_credit_http",
        FIFO_CREDITS_REPORT_KEY=base64.urlsafe_b64encode(b"credits-test-key-32-bytes-long!!").decode().rstrip("="),
        APP_BASE_URL="https://marianosevilla.com",
    )
    db.init_app(app)
    login = LoginManager(app)

    @login.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    app.register_blueprint(credits_bp)
    register_analysis_hooks(app)
    token_name = "fifo_report_credits_http_test.pdf"
    token_path = os.path.join(tempfile.gettempdir(), token_name)
    with open(token_path, "wb") as pdf:
        pdf.write(b"%PDF-1.4\nsynthetic credit report\n")

    @app.post("/api/analizar")
    @login_required
    def analizar():
        result = request.form.get("test_result")
        if result == "definitive":
            return jsonify({"ok": True, "result_type": "definitive", "token": token_name})
        if result == "provisional":
            return jsonify({"ok": False, "result_type": "provisional",
                            "borrador_fifo": {
                                "estado": "INCOMPLETO_NO_APTO_PARA_DECLARAR",
                                "no_es_informe_fiscal": True,
                                "costes_fifo_calculados": False,
                                "pdf_fiscal_disponible": False,
                                "ganancias_y_perdidas_eur": None,
                                "pendientes": [], "fuentes": [],
                                "archivos_aportados": [], "evidencias": [],
                                "exchange_nombre": "Binance",
                            }}), 422
        return jsonify({"ok": False, "result_type": "processing_error", "error": "synthetic failure"}), 500

    with app.app_context():
        db.create_all()
        first = User(email="credits-user-a@example.invalid", is_active=True)
        second = User(email="credits-user-b@example.invalid", is_active=True)
        db.session.add_all([first, second])
        db.session.flush()
        db.session.add_all([
            CreditWallet(user_id=first.id, available_credits=460),
            CreditWallet(user_id=second.id, available_credits=0),
        ])
        db.session.commit()
        user_ids = first.id, second.id
    yield app, user_ids
    with app.app_context():
        db.session.remove()
        db.drop_all()
    try:
        os.unlink(token_path)
    except OSError:
        pass


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


def _file(data=b"Date,Symbol,Amount\n2025-01-01,BTC,1\n"):
    return (BytesIO(data), "transactions.csv")


def _quote(client, *, contents=None, correction_of_id=None):
    data = {"exchange": "binance", "fiscal_years": "2025", "csv": _file(contents or b"Date,Symbol,Amount\n2025-01-01,BTC,1\n")}
    if correction_of_id:
        data["correction_of_id"] = correction_of_id
    return client.post("/api/credits/quote", data=data, content_type="multipart/form-data")


def _authorize(client, quote, csrf):
    return client.post("/api/credits/authorize", json={"quote_token": quote["quote_token"]},
                       headers={"X-Credits-CSRF": csrf, "Idempotency-Key": str(uuid4())})


def _analysis(client, reservation_id, result, contents=None):
    return client.post("/api/analizar", data={
        "exchange": "binance", "ejercicio": "2025", "test_result": result,
        "credit_analysis_id": reservation_id,
        "csv": _file(contents or b"Date,Symbol,Amount\n2025-01-01,BTC,1\n"),
    }, content_type="multipart/form-data")


def test_http_authorization_charges_definitive_and_provisional_and_releases_errors(web):
    app, (user_id, _) = web
    client = app.test_client()
    _login(client, user_id)
    csrf = client.get("/api/credits/csrf").json["csrf_token"]

    for result, expected_charge, contents in (
        ("definitive", 50, b"Date,Symbol,Amount\n2025-01-01,BTC,1\n"),
        ("provisional", 50, b"Date,Symbol,Amount\n2025-02-01,ETH,2\n"),
    ):
        quote = _quote(client, contents=contents).json
        assert quote["max_credits"] == 50
        authorization = _authorize(client, quote, csrf)
        assert authorization.status_code == 201
        response = _analysis(client, authorization.json["analysis_id"], result, contents)
        assert response.status_code == (200 if result == "definitive" else 422)
        assert response.json["credits_charged"] == expected_charge
        if result == "definitive":
            url = response.json["download_url"]
            first = client.get(url); second = client.get(url)
            assert first.status_code == second.status_code == 200
            assert first.data == second.data and first.mimetype == "application/pdf"
            other = app.test_client(); _login(other, 2)
            assert other.get(url).status_code == 404

    quote = _quote(client, contents=b"Date,Symbol,Amount\n2025-03-01,SOL,3\n").json
    authorization = _authorize(client, quote, csrf)
    failed = _analysis(client, authorization.json["analysis_id"], "error",
                       b"Date,Symbol,Amount\n2025-03-01,SOL,3\n")
    assert failed.status_code == 500
    assert failed.json["credit_message"] == "No se han consumido créditos. Tu saldo permanece intacto"
    assert failed.json["balance"]["reserved"] == 0
    assert failed.json["balance"]["available"] == 360


def test_identical_acquired_analysis_reuses_report_without_second_charge(web):
    app, (user_id, _) = web
    client = app.test_client(); _login(client, user_id)
    csrf = client.get("/api/credits/csrf").json["csrf_token"]
    original = _quote(client).json
    authorization = _authorize(client, original, csrf)
    result = _analysis(client, authorization.json["analysis_id"], "definitive")
    assert result.status_code == 200
    assert result.json["balance"]["available"] == 410

    repeat = _quote(client)
    assert repeat.status_code == 200
    assert repeat.json["already_acquired"] is True
    assert repeat.json["download_url"] == result.json["download_url"]
    downloaded = client.get(repeat.json["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.data.startswith(b"%PDF-")
    assert client.get("/api/credits/status").json["balance"]["available"] == 410


def test_http_changed_file_is_released_before_fifo_and_owner_binding_is_enforced(web):
    app, (user_a, user_b) = web
    client_a = app.test_client(); _login(client_a, user_a)
    csrf = client_a.get("/api/credits/csrf").json["csrf_token"]
    quote = _quote(client_a).json
    auth = _authorize(client_a, quote, csrf)
    client_b = app.test_client(); _login(client_b, user_b)
    denied = client_b.post("/api/analizar", data={
        "exchange": "binance", "ejercicio": "2025", "test_result": "definitive",
        "credit_analysis_id": auth.json["analysis_id"], "csv": _file(),
    }, content_type="multipart/form-data")
    assert denied.status_code == 402

    changed = client_a.post("/api/analizar", data={
        "exchange": "binance", "ejercicio": "2025", "test_result": "definitive",
        "credit_analysis_id": auth.json["analysis_id"], "csv": _file(b"Different,CSV\n"),
    }, content_type="multipart/form-data")
    assert changed.status_code == 409
    assert changed.json["credit_message"] == "No se han consumido créditos. Tu saldo permanece intacto"


def test_http_one_free_correction_is_explicit_and_never_debits_wallet(web):
    app, (user_id, _) = web
    client = app.test_client(); _login(client, user_id)
    csrf = client.get("/api/credits/csrf").json["csrf_token"]
    initial_quote = _quote(client).json
    first_auth = _authorize(client, initial_quote, csrf)
    first_result = _analysis(client, first_auth.json["analysis_id"], "provisional")
    assert first_result.status_code == 422
    parent_id = first_result.json["credit_analysis_id"]
    corrected = b"Date,Symbol,Amount\n2025-01-01,ETH,2\n"
    correction_quote_response = _quote(client, contents=corrected,
                                       correction_of_id=parent_id)
    assert correction_quote_response.status_code == 200
    correction_quote = correction_quote_response.json
    assert correction_quote["correction_free"] is True
    assert correction_quote["max_credits"] == 0
    correction_auth = _authorize(client, correction_quote, csrf)
    assert correction_auth.json["reserved_credits"] == 0
    result = _analysis(client, correction_auth.json["analysis_id"], "definitive", corrected)
    assert result.status_code == 200
    assert result.json["credits_charged"] == 0
    assert result.json["balance"]["available"] == 410


def test_disabled_flag_hides_credit_purchases_and_live_mode_is_never_accepted(web):
    app, (user_id, _) = web
    app.config["CREDITS_ENABLED"] = False
    client = app.test_client(); _login(client, user_id)
    assert client.get("/api/credits/status").json == {"enabled": False, "balance": None}
    assert client.post("/api/credits/quote", data={
        "exchange": "binance", "fiscal_years": "2025", "csv": _file(),
    }).status_code == 404
    assert client.post("/api/credits/purchases/basic").status_code == 404


def test_unsupported_credit_quote_is_rejected_without_creating_reservation(web):
    app, (user_id, _) = web
    client = app.test_client(); _login(client, user_id)
    unsupported = client.post("/api/credits/quote", data={
        "exchange": "mexc", "fiscal_years": "2025",
        "csv": (BytesIO(b"synthetic workbook"), "history.xlsx"),
    }, content_type="multipart/form-data")
    assert unsupported.status_code == 400
    assert unsupported.json["credits_consumed"] == 0
    with app.app_context():
        assert CreditAnalysis.query.count() == 0


def test_http_checkout_uses_fixed_test_price_and_signed_webhook_grants_once(web, monkeypatch):
    import stripe
    from types import SimpleNamespace
    app, (user_id, _) = web
    client = app.test_client(); _login(client, user_id)
    csrf = client.get("/api/credits/csrf").json["csrf_token"]
    captured = []

    class Sessions:
        def create(self, params, options):
            captured.append((params, options))
            return SimpleNamespace(id="cs_test_http_session", url="https://checkout.stripe.com/test")
    class FakeClient:
        def __init__(self, secret):
            assert secret.startswith("sk_test_")
            self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions()))
    monkeypatch.setattr(stripe, "StripeClient", FakeClient)

    idem = str(uuid4())
    response = client.post("/api/credits/purchases/standard", headers={
        "X-Credits-CSRF": csrf, "Idempotency-Key": idem,
    })
    assert response.status_code == 201
    assert len(captured) == 1
    params, options = captured[0]
    assert params["mode"] == "payment"
    assert params["line_items"][0]["price_data"]["unit_amount"] == 2990
    assert "subscription_data" not in params
    assert options["idempotency_key"].startswith("credits-checkout-v1-")
    purchase_id = response.json["purchase_id"]
    response2 = client.post("/api/credits/purchases/standard", headers={
        "X-Credits-CSRF": csrf, "Idempotency-Key": idem,
    })
    assert response2.status_code == 201
    assert response2.json["purchase_id"] == purchase_id

    event = {"id": "evt_credit_http", "livemode": False,
             "type": "checkout.session.completed", "data": {"object": {
                 "id": "cs_test_http_session", "livemode": False, "mode": "payment",
                 "status": "complete", "payment_status": "paid",
                 "amount_total": 2990, "currency": "eur",
                 "payment_intent": "pi_credit_http",
                 "metadata": {"credits_purchase_id": purchase_id},
             }}}
    payload = json.dumps(event, separators=(",", ":")).encode()
    stamp = int(time.time())
    digest = hmac.new(app.config["STRIPE_CREDITS_TEST_WEBHOOK_SECRET"].encode(),
                      str(stamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
    hook = client.post("/api/webhooks/stripe-credits-test", data=payload,
                       headers={"Stripe-Signature": f"t={stamp},v1={digest}"},
                       content_type="application/json")
    assert hook.status_code == 200 and hook.json["handled"] is True
    replay = client.post("/api/webhooks/stripe-credits-test", data=payload,
                         headers={"Stripe-Signature": f"t={stamp},v1={digest}"},
                         content_type="application/json")
    assert replay.status_code == 200 and replay.json["handled"] is False
    assert client.get("/api/credits/status").json["balance"]["available"] == 690
