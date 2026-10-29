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
    # Do not hold an app context across the test module. Otherwise Flask's
    # g._login_user cache leaks from one HTTP client into another, unlike real
    # requests with independent application contexts.
    yield flask_app
    with flask_app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(isolated_app):
    # Avoid preserving the previous request's app context between calls:
    # separate clients must not reuse flask.g's cached current_user.
    client = isolated_app.test_client()
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
    # Avoid a nested FlaskClient context: a second preserved request context
    # can shadow the owner's current_user during the later request.
    other = isolated_app.test_client()
    login = other.post("/api/login", json={
        "email": "other-05c2-user@example.invalid",
        "password": "other-fixture-password",
    })
    assert login.status_code == 200
    denied = other.get("/api/descargar/" + token)
    assert denied.status_code == 403, denied.get_data(as_text=True)[:200]

    # A rejected cross-user attempt must not consume the owner's token.
    with client.session_transaction() as session:
        assert session.get("pdf_token") == token
    owner = client.get("/api/descargar/" + token)
    assert owner.status_code == 200, owner.get_data(as_text=True)[:200] if owner.mimetype != "application/pdf" else ""
    assert owner.data.startswith(b"%PDF-")


@pytest.mark.parametrize("case", [
    "foreign_quote",
    "foreign_settlement",
    "missing_settlement_currency",
    "foreign_fee",
    "unverifiable_fee",
    "stable_foreign_fee",
    "unknown_event",
])
def test_bitvavo_material_unknown_or_non_eur_blocks_pdf_and_token(client, case):
    """No fiscal report from a Bitvavo CSV that cannot establish its EUR basis."""
    original = _csv_bytes("bitvavo", with_purchase=True).decode("utf-8")
    assert "EUR,30000,EUR,-300,EUR,0" in original
    cases = {
        "foreign_quote": ("EUR,30000,EUR,-300,EUR,0", "USDT,30000,EUR,-300,EUR,0"),
        "foreign_settlement": ("EUR,30000,EUR,-300,EUR,0", "EUR,30000,USDT,-300,EUR,0"),
        "missing_settlement_currency": ("EUR,30000,EUR,-300,EUR,0", "EUR,30000,,-300,EUR,0"),
        "foreign_fee": ("EUR,30000,EUR,-300,EUR,0", "EUR,30000,EUR,-300,BTC,-0.001"),
        "unverifiable_fee": ("EUR,30000,EUR,-300,EUR,0", "EUR,30000,EUR,-300,EUR,1000"),
    }
    if case == "unknown_event":
        content = original + "UTC,2025-02-03,10:00:00,unknown_fiscal_event,BTC,1,EUR,1,EUR,1,EUR,0,Completed,unknown-id,\n"
    elif case == "stable_foreign_fee":
        content = original + "UTC,2025-02-03,10:00:00,buy,USDT,100,EUR,1,EUR,-100,USDT,-1,Completed,stable-id,\n"
    else:
        before, after = cases[case]
        content = original.replace(before, after, 1)
        assert content != original

    response = client.post("/api/analizar", data={
        "csv": (io.BytesIO(content.encode("utf-8")), "bitvavo-synthetic-negative.csv"),
        "exchange": "bitvavo",
        "nombre": "Synthetic - no personal data",
        "ejercicio": "2025",
    }, content_type="multipart/form-data")
    assert response.status_code == 422, (case, response.get_data(as_text=True)[:600])
    payload = response.get_json() or {}
    assert "token" not in payload and "resumen" not in payload
    assert "operaciones" not in payload
    assert payload.get("ok") is not True


def _binance_legacy_bytes(*, invalid_group=None):
    """Synthetic six-column classic Binance CSV (not Binance TX)."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Tiempo", "Operación", "Moneda", "Cambio", "Cuenta", "Observación"])
    buy_time = "2024-01-02 10:00:00"
    sell_time = "2025-02-02 10:00:00"
    rows = [
        [buy_time, "Transaction Buy", "BTC", "0.02", "Spot", ""],
        [buy_time, "Transaction Spend", "EUR", "-600", "Spot", ""],
        [sell_time, "Transaction Buy", "EUR", "400", "Spot", ""],
        [sell_time, "Transaction Spend", "BTC", "-0.01", "Spot", ""],
    ]
    extras = {
        "duplicate_buy": [buy_time, "Transaction Buy", "ETH", "1", "Spot", ""],
        "duplicate_spend": [buy_time, "Transaction Spend", "USDT", "-100", "Spot", ""],
        "duplicate_fee": [buy_time, "Transaction Fee", "EUR", "-1", "Spot", ""],
        "orphan_buy": [buy_time, "Transaction Buy", "ETH", "1", "Spot", ""],
        "orphan_spend": [buy_time, "Transaction Spend", "EUR", "-1", "Spot", ""],
        "orphan_fee": [buy_time, "Transaction Fee", "EUR", "-1", "Spot", ""],
    }
    if invalid_group == "duplicate_fee":
        rows.extend([extras[invalid_group], extras[invalid_group]])
    elif invalid_group == "orphan_buy":
        rows = [r for r in rows if r[0] != buy_time]
        rows.append(extras[invalid_group])
    elif invalid_group == "orphan_spend":
        rows = [r for r in rows if r[0] != buy_time]
        rows.append(extras[invalid_group])
    elif invalid_group == "orphan_fee":
        rows = [r for r in rows if r[0] != buy_time]
        rows.append(extras[invalid_group])
    elif invalid_group:
        rows.append(extras[invalid_group])
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def test_binance_legacy_unique_eur_pairs_still_generate_fiscal_pdf(client):
    """A valid classic Binance CSV must not regress to a rejected import."""
    response = client.post("/api/analizar", data={
        "csv": (io.BytesIO(_binance_legacy_bytes()), "binance-classic-synthetic.csv"),
        "exchange": "binance", "nombre": "Synthetic", "ejercicio": "2025",
    }, content_type="multipart/form-data")
    assert response.status_code == 200, response.get_data(as_text=True)[:550]
    payload = response.get_json()
    assert len(payload["operaciones"]) == 1
    assert payload["resumen"]["resultado_neto"] == pytest.approx(100, abs=0.01)
    token = payload["token"]
    download = client.get("/api/descargar/" + token + "?exchange=binance")
    assert download.status_code == 200
    assert download.data.startswith(b"%PDF-")
    assert client.get("/api/descargar/" + token).status_code == 403


@pytest.mark.parametrize("invalid_group", [
    "duplicate_buy", "duplicate_spend", "duplicate_fee",
    "orphan_buy", "orphan_spend", "orphan_fee",
])
def test_binance_legacy_ambiguous_or_incomplete_pairs_block_fiscal_pdf(client, invalid_group):
    """Every unpaired or extra CSV leg must block the entire report and token."""
    response = client.post("/api/analizar", data={
        "csv": (io.BytesIO(_binance_legacy_bytes(invalid_group=invalid_group)),
                "binance-classic-synthetic.csv"),
        "exchange": "binance", "nombre": "Synthetic", "ejercicio": "2025",
    }, content_type="multipart/form-data")
    assert response.status_code == 422, (
        invalid_group, response.status_code, response.get_data(as_text=True)[:550]
    )
    payload = response.get_json() or {}
    assert "Datos fiscales no seguros" in payload.get("error", "")
    assert "token" not in payload and "resumen" not in payload
    assert "operaciones" not in payload


@pytest.mark.parametrize("orphan_type,currency,amount", [
    ("Transaction Buy", "ETH", "1"),
    ("Transaction Spend", "BTC", "-0.001"),
    ("Transaction Fee", "BNB", "-0.0001"),
])
def test_binance_tx_orphan_leg_rejects_report_before_pdf_token(
    client, orphan_type, currency, amount,
):
    """A Binance TX export must never omit unpaired trade/fee rows in a fiscal PDF."""
    # Original valid Binance TX fixture has an EUR purchase (2024) and
    # an EUR sale (2025); add one unmatched material row at a distinct time.
    valid_csv = _csv_bytes("binance", with_purchase=True).decode("utf-8")
    writer_buffer = io.StringIO(newline="")
    writer = csv.writer(writer_buffer)
    writer.writerow([
        "123", "2025-03-03 10:00:00", "Spot", orphan_type,
        currency, amount, "Synthetic/ORPHAN",
    ])
    original_plus_orphan = valid_csv + writer_buffer.getvalue()
    response = client.post("/api/analizar", data={
        "csv": (io.BytesIO(original_plus_orphan.encode("utf-8")),
                "binance-tx-synthetic-orphan.csv"),
        "exchange": "binance",
        "nombre": "Synthetic - no personal data",
        "ejercicio": "2025",
    }, content_type="multipart/form-data")
    assert response.status_code == 422, (
        orphan_type, response.status_code, response.get_data(as_text=True)[:550]
    )
    payload = response.get_json() or {}
    assert "Datos fiscales no seguros" in payload.get("error", "")
    assert "token" not in payload and "resumen" not in payload
    assert "operaciones" not in payload



def _binance_tx_fifo_with_fee(fee_currency=None, fee_amount=None, fee_on_sale=False):
    """Synthetic Binance TX: EUR purchase, later EUR sale, optional fee row."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "ID de usuario", "Tiempo", "Cuenta", "Operación", "Moneda",
        "Cambio", "Observación",
    ])
    purchase = "2024-01-02 10:00:00"
    sale = "2025-02-02 10:00:00"
    writer.writerows([
        ["123", purchase, "Spot", "Transaction Spend", "EUR", "-600", ""],
        ["123", purchase, "Spot", "Transaction Buy", "BTC", "0.02", ""],
        ["123", sale, "Spot", "Transaction Spend", "BTC", "-0.01", ""],
        ["123", sale, "Spot", "Transaction Buy", "EUR", "400", ""],
    ])
    if fee_currency is not None:
        writer.writerow([
            "123", sale if fee_on_sale else purchase, "Spot",
            "Transaction Fee", fee_currency, str(fee_amount), "",
        ])
    return output.getvalue().encode("utf-8")


@pytest.mark.parametrize("fee_currency,fee_amount,fee_on_sale", [
    ("BNB", "-0.0001", False),
    ("EUR", "-1.25", False),
    ("EUR", "-1.25", True),
    ("USDT", "-0.5", True),
])
def test_binance_tx_nonzero_fee_cannot_generate_incomplete_fiscal_pdf(
    client, fee_currency, fee_amount, fee_on_sale,
):
    """Before EUR valuation and disposal accounting, never ignore a nonzero fee."""
    response = client.post("/api/analizar", data={
        "csv": (io.BytesIO(_binance_tx_fifo_with_fee(
            fee_currency, fee_amount, fee_on_sale
        )), "binance-tx-fee-synthetic.csv"),
        "exchange": "binance", "nombre": "Synthetic", "ejercicio": "2025",
    }, content_type="multipart/form-data")
    assert response.status_code == 422, (
        fee_currency, fee_on_sale, response.get_data(as_text=True)[:550]
    )
    payload = response.get_json() or {}
    assert "Datos fiscales no seguros" in payload.get("error", "")
    assert "Transaction Fee" in payload.get("error", "")
    assert "token" not in payload and "resumen" not in payload
    assert "operaciones" not in payload


@pytest.mark.parametrize("with_zero_fee", [False, True])
def test_binance_tx_without_material_fee_keeps_eur_fifo_and_pdf(client, with_zero_fee):
    """Valid paired EUR trades still yield the same fiscal result and one-use PDF."""
    file_bytes = _binance_tx_fifo_with_fee(
        "BNB" if with_zero_fee else None,
        "0" if with_zero_fee else None,
    )
    response = client.post("/api/analizar", data={
        "csv": (io.BytesIO(file_bytes), "binance-tx-zero-fee-synthetic.csv"),
        "exchange": "binance", "nombre": "Synthetic", "ejercicio": "2025",
    }, content_type="multipart/form-data")
    assert response.status_code == 200, response.get_data(as_text=True)[:600]
    payload = response.get_json() or {}
    assert payload["resumen"]["resultado_neto"] == pytest.approx(100, abs=0.01)
    assert len(payload["operaciones"]) == 1
    token = payload["token"]
    pdf = client.get("/api/descargar/" + token + "?exchange=binance")
    assert pdf.status_code == 200
    assert pdf.data.startswith(b"%PDF-")
    assert client.get("/api/descargar/" + token).status_code == 403
