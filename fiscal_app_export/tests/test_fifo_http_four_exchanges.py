"""05-C2: real HTTP CSV -> FIFO -> PDF -> single-use download for four exchanges.

All records are deliberately synthetic and have no connection to a real account.
The classifier, tax engine, PDF generator, HTTP handlers and session token are
NOT mocked. Tests execute against the existing isolated SQLite test fixture.
Only basic EUR purchases/sales are asserted; broader fiscal coverage stays
in the classifier, integrity, and fail-closed suites.
"""
import csv
import io
import os
import tempfile
import time
from datetime import datetime

import pdfplumber
import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", "sqlite:///" + _TEST_DB)
os.environ.setdefault("SECRET_KEY", "synthetic-only-05c2-secret")

from app import app as flask_app, db  # noqa: E402
from models import User  # noqa: E402


EXCHANGES = {
    # Buy 0.02 BTC for 600 EUR; sell half for 400 EUR => 100 EUR gain.
    "binance": (100.0, 0.01),
    # Buy 0.01 BTC for 300 EUR; sell half for 160 EUR => 10 EUR gain.
    "bitvavo": (10.0, 0.005),
    # Buy 0.002 BTC for 100 EUR; sell all for 150 EUR => 50 EUR gain.
    "kraken": (50.0, 0.002),
    # Buy 0.01 BTC for 550 EUR; sell half for 300 EUR => 25 EUR gain.
    "coinbase": (25.0, 0.005),
}


def _csv_bytes(exchange, *, with_purchase):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)

    if exchange == "binance":
        writer.writerow(["ID de usuario", "Tiempo", "Cuenta", "Operación",
                         "Moneda", "Cambio", "Observación"])
        if with_purchase:
            writer.writerows([
                ["123", "2024-01-02 10:00:00", "Spot", "Buy Crypto With Fiat",
                 "BTC", "0.02", "Wallet/BUY123"],
                ["123", "2024-01-02 10:00:00", "Spot", "Buy Crypto With Fiat",
                 "EUR", "-600", "Wallet/BUY123"],
            ])
        writer.writerows([
            ["123", "2025-02-02 10:00:00", "Spot", "Sell Crypto To Fiat",
             "BTC", "-0.01", "Wallet/SELL123"],
            ["123", "2025-02-02 10:00:00", "Spot", "Sell Crypto To Fiat",
             "EUR", "400", "Wallet/SELL123"],
        ])
    elif exchange == "bitvavo":
        writer.writerow(["Timezone", "Date", "Time", "Type", "Currency", "Amount",
                         "Quote Currency", "Quote Price", "Received / Paid Currency",
                         "Received / Paid Amount", "Fee currency", "Fee amount",
                         "Status", "Transaction ID", "Address"])
        if with_purchase:
            writer.writerow(["UTC", "2024-01-02", "10:00:00", "buy", "BTC", "0.01",
                             "EUR", "30000", "EUR", "-300", "EUR", "0",
                             "Completed", "synthetic-buy", ""])
        writer.writerow(["UTC", "2025-02-02", "10:00:00", "sell", "BTC", "0.005",
                         "EUR", "32000", "EUR", "160", "EUR", "0",
                         "Completed", "synthetic-sell", ""])
    elif exchange == "kraken":
        writer.writerow(["txid", "refid", "time", "type", "subtype", "aclass",
                         "subclass", "asset", "wallet", "amount", "fee", "balance"])
        if with_purchase:
            writer.writerows([
                ["TX1", "REF1", "2024-01-02 10:00:00", "spend", "", "currency",
                 "fiat", "EUR", "spot / main", "-100", "0", "0"],
                ["TX2", "REF1", "2024-01-02 10:00:00", "receive", "", "currency",
                 "crypto", "BTC", "spot / main", "0.002", "0", "0.002"],
            ])
        writer.writerows([
            ["TX3", "REF2", "2025-02-02 10:00:00", "spend", "", "currency",
             "crypto", "BTC", "spot / main", "-0.002", "0", "0"],
            ["TX4", "REF2", "2025-02-02 10:00:00", "receive", "", "currency",
             "fiat", "EUR", "spot / main", "150", "0", "150"],
        ])
    elif exchange == "coinbase":
        writer.writerow([""])
        writer.writerow(["Transactions"])
        writer.writerow(["synthetic@example.invalid"])
        writer.writerow(["ID", "Timestamp", "Transaction Type", "Asset",
                         "Quantity Transacted", "Price Currency",
                         "Price at Transaction", "Subtotal",
                         "Total (inclusive of fees and/or spread)",
                         "Fees and/or Spread", "Notes", "Sender Address",
                         "Recipient Address"])
        if with_purchase:
            writer.writerow(["C1", "2024-01-02T10:00:00Z", "Buy", "BTC", "0.01",
                             "EUR", "€55000", "€550", "€550", "€0", "", "", ""])
        writer.writerow(["C2", "2025-02-02T10:00:00Z", "Sell", "BTC", "0.005",
                         "EUR", "€60000", "€300", "€300", "€0", "", "", ""])
    else:
        raise AssertionError("Unknown test exchange")
    return stream.getvalue().encode("utf-8")


@pytest.fixture(scope="module")
def isolated_app():
    flask_app.config.update(
        TESTING=True, RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False,
        SESSION_COOKIE_SECURE=False, SQLALCHEMY_ENGINE_OPTIONS={},
    )
    with flask_app.app_context():
        db.create_all()
        user = User(
            email="four-exchanges-05c2@example.invalid",
            full_name="Test Sintético 05-C2",
            email_verified_at=datetime.utcnow(),
        )
        user.set_password("test-fixture-only")
        db.session.add(user)
        db.session.commit()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(isolated_app):
    with isolated_app.test_client() as client:
        response = client.post("/api/login", json={
            "email": "four-exchanges-05c2@example.invalid",
            "password": "test-fixture-only",
        })
        assert response.status_code == 200, response.get_data(as_text=True)[:200]
        yield client


def _analyse(client, exchange, *, with_purchase):
    return client.post("/api/analizar", data={
        "csv": (io.BytesIO(_csv_bytes(exchange, with_purchase=with_purchase)),
                exchange + "-synthetic.csv"),
        "exchange": exchange,
        "nombre": "Informe de prueba - sin datos personales",
        "ejercicio": "2025",
    }, content_type="multipart/form-data")


@pytest.mark.parametrize("exchange", EXCHANGES)
def test_csv_fifo_pdf_download_and_replay_rejected(client, exchange):
    """Real parser, FIFO, PDF and download for each supported CSV format."""
    expected_profit, expected_quantity = EXCHANGES[exchange]
    response = _analyse(client, exchange, with_purchase=True)
    assert response.status_code == 200, (exchange, response.get_data(as_text=True)[:450])
    data = response.get_json()
    assert data["ok"] is True
    operations = data["operaciones"]
    assert len(operations) == 1, (exchange, operations)
    operation = operations[0]
    assert operation["fecha"] == "2025-02-02"
    assert operation["activo"] == "BTC"
    assert operation["cantidad"] == pytest.approx(expected_quantity, abs=1e-9)
    assert operation["ganancia_perdida"] == pytest.approx(expected_profit, abs=0.01)
    assert data["resumen"]["resultado_neto"] == pytest.approx(expected_profit, abs=0.01)

    token = data["token"]
    assert isinstance(token, str) and token.endswith(".pdf")
    download = client.get("/api/descargar/" + token + "?exchange=" + exchange)
    assert download.status_code == 200, (exchange, download.status_code)
    assert download.mimetype == "application/pdf"
    assert download.data.startswith(b"%PDF-")
    assert len(download.data) > 1000
    assert "attachment" in download.headers.get("Content-Disposition", "")
    assert not os.path.exists(os.path.join(tempfile.gettempdir(), token))
    with pdfplumber.open(io.BytesIO(download.data)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "BTC" in text, (exchange, text[:350])
    assert client.get("/api/descargar/" + token).status_code == 403


@pytest.mark.parametrize("exchange", EXCHANGES)
def test_sale_without_acquisition_is_rejected_without_pdf_token(client, exchange):
    """Fail closed on incomplete inventory instead of emitting a fiscal report."""
    response = _analyse(client, exchange, with_purchase=False)
    assert response.status_code == 422, (exchange, response.status_code,
                                         response.get_data(as_text=True)[:450])
    data = response.get_json()
    assert "Datos fiscales no seguros" in data["error"]
    assert "token" not in data
    assert "resumen" not in data


def test_missing_pdf_preserves_session_token_until_response_is_ready(client):
    analysis = _analyse(client, "bitvavo", with_purchase=True)
    assert analysis.status_code == 200
    token = analysis.get_json()["token"]
    path = os.path.join(tempfile.gettempdir(), token)
    with open(path, "rb") as stream:
        pdf_bytes = stream.read()
    os.unlink(path)
    try:
        missing = client.get("/api/descargar/" + token)
        assert missing.status_code == 404
        with client.session_transaction() as session:
            assert session.get("pdf_token") == token
        # Simulate a transient storage disappearance before successful delivery.
        with open(path, "wb") as stream:
            stream.write(pdf_bytes)
        ok = client.get("/api/descargar/" + token)
        assert ok.status_code == 200
        assert ok.data.startswith(b"%PDF-")
        assert not os.path.exists(path)
        assert client.get("/api/descargar/" + token).status_code == 403
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_expired_pdf_token_rejects_without_serving_file(client):
    analysis = _analyse(client, "bitvavo", with_purchase=True)
    assert analysis.status_code == 200
    token = analysis.get_json()["token"]
    path = os.path.join(tempfile.gettempdir(), token)
    try:
        with client.session_transaction() as session:
            session["pdf_token_exp"] = time.time() - 1
        response = client.get("/api/descargar/" + token)
        assert response.status_code == 403
        assert os.path.exists(path)  # physical expiry is handled by the reaper
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_token_cannot_be_used_by_another_authenticated_account(client, isolated_app):
    analysis = _analyse(client, "bitvavo", with_purchase=True)
    assert analysis.status_code == 200
    token = analysis.get_json()["token"]
    with isolated_app.app_context():
        stranger = User(
            email="other-05c2-user@example.invalid",
            full_name="Other synthetic account",
            email_verified_at=datetime.utcnow(),
        )
        stranger.set_password("other-fixture-password")
        db.session.add(stranger)
        db.session.commit()
    with isolated_app.test_client() as other:
        login = other.post("/api/login", json={
            "email": "other-05c2-user@example.invalid",
            "password": "other-fixture-password",
        })
        assert login.status_code == 200
        assert other.get("/api/descargar/" + token).status_code == 403
    owner = client.get("/api/descargar/" + token)
    assert owner.status_code == 200
    assert owner.data.startswith(b"%PDF-")
