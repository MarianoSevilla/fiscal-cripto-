"""P0 FIFO Fase 1: synthetic fiscal acceptance, never production data."""
import csv
import io
from types import SimpleNamespace

import openpyxl
import pytest

from app import (
    app, _motor_a_json, _validar_aceptacion_fuentes_fifo,
    procesar_mexc, procesar_bitget, procesar_kucoin,
)
from clasificador_mexc import ClasificadorMEXC
from clasificador_bitget import ClasificadorBitget, ClasificadorBitgetMulti
from clasificador_kucoin import ClasificadorKuCoin
from motor_fifo import MotorFIFO


def _motor_eur():
    m = MotorFIFO()
    m.registrar_compra("2024-01-01 10:00:00", "BTC", 1, 100, "EUR", "EUR", 0)
    m.registrar_venta("2025-01-01 10:00:00", "BTC", 1, 150, "EUR", "EUR", 0)
    return m


def _classifier(kind, quote="EUR", unknown=False, informational=False):
    cls = {"mexc": ClasificadorMEXC, "bitget": ClasificadorBitget,
           "bitget_multi": ClasificadorBitgetMulti,
           "kucoin": ClasificadorKuCoin}[kind]
    c = cls.__new__(cls)
    c.compraventas = [SimpleNamespace(contraparte=quote)]
    c.swaps = []
    c.rendimientos = []
    c.movimientos = []
    c.desconocidas = ([SimpleNamespace(subtipo="unmapped taxable operation")]
                     if unknown else [])
    c.advertencias = ["Depósito sin repercusión fiscal"] if informational else []
    c._no_reconocidos = []
    c._fuentes_materiales_omitidas = []
    return c


@pytest.mark.parametrize("kind", ["mexc", "bitget", "bitget_multi", "kucoin"])
def test_unknown_fiscal_transaction_fails_closed(kind):
    c = _classifier(kind, unknown=True)
    with pytest.raises(ValueError, match="operaciones no interpretadas"):
        _motor_a_json(_motor_eur(), c)


@pytest.mark.parametrize("kind,quote", [
    ("mexc", "USDT"), ("bitget", "USD"), ("bitget_multi", "USDC"),
    ("kucoin", "USDT"), ("mexc", "BTC"),
])
def test_non_eur_quote_fails_closed(kind, quote):
    with pytest.raises(ValueError, match="valoración histórica"):
        _motor_a_json(_motor_eur(), _classifier(kind, quote=quote))


@pytest.mark.parametrize("kind", ["mexc", "bitget", "bitget_multi", "kucoin"])
def test_eur_sale_and_informational_warning_are_preserved(kind):
    c = _classifier(kind, informational=True)
    summary, _, operations = _motor_a_json(_motor_eur(), c)
    assert summary["resultado_neto"] == 50
    assert len(operations) == 1 and operations[0]["ganancia_perdida"] == 50


def test_kucoin_unreconciled_dust_does_not_become_success():
    c = _classifier("kucoin")
    c.movimientos = [SimpleNamespace(subtipo="Convert Dust (revisar)",
                                    observacion="Permuta a KCS pendiente")]
    with pytest.raises(ValueError, match="adquisición o permuta"):
        _motor_a_json(_motor_eur(), c)


def test_bitget_card_purchase_and_unvalued_interest_are_material():
    c = _classifier("bitget")
    c.movimientos = [SimpleNamespace(subtipo="Deposit",
                                    observacion="Compra con tarjeta: valoración EUR no disponible")]
    with pytest.raises(ValueError, match="adquisición o permuta"):
        _motor_a_json(_motor_eur(), c)
    c.movimientos = []
    c.rendimientos = [SimpleNamespace(cantidad=1, subtipo="Staking/Earn")]
    with pytest.raises(ValueError, match="rendimientos sin"):
        _motor_a_json(_motor_eur(), c)


def test_bitget_omitted_futures_and_unrecognized_attachment():
    c = _classifier("bitget_multi")
    c._fuentes_materiales_omitidas = ["futures.csv"]
    with pytest.raises(ValueError, match="omitieron archivos"):
        _motor_a_json(_motor_eur(), c)
    c._fuentes_materiales_omitidas = []
    c._no_reconocidos = ["unreadable.csv"]
    with pytest.raises(ValueError, match="archivos"):
        _motor_a_json(_motor_eur(), c)


def test_nonzero_bitget_transaction_fee_not_silently_discarded():
    c = _classifier("bitget")
    c._procesar_otros_tipos({
        "Date": "2025-01-01 10:00:00", "Coin": "BGB",
        "Type": "Transaction fee deduct", "Amount": "0", "Fee": "-0.5",
    })
    with pytest.raises(ValueError, match="operaciones no interpretadas"):
        _motor_a_json(_motor_eur(), c)


SPOT = ["UID", "order_id", "symbol", "create_time(UTC+01:00)", "side",
        "source", "currency", "quantity", "price", "amount_usdt",
        "fee_currency", "fee", "fee_usdt", "liquidity", "trade_type"]


def _mexc_xlsx(tmp_path, rows):
    p = tmp_path / "mexc_synthetic.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(SPOT)
    for row in rows:
        ws.append(row)
    wb.save(p)
    return str(p)


def _mexc_row(date, side, quote="EUR"):
    return ["synthetic", "order", "BTC-" + quote, date, side, "APP",
            "BTC", "1", "100" if side == "BUY" else "150",
            "100", quote, "0", "0", "MAKER", "SPOT"]


def test_real_mexc_xlsx_eur_and_non_eur_and_unknown(tmp_path):
    p = _mexc_xlsx(tmp_path, [
        _mexc_row("2024-01-01 10:00:00", "BUY"),
        _mexc_row("2025-01-01 10:00:00", "SELL"),
    ])
    m, _, c = procesar_mexc(p)
    summary, _, operations = _motor_a_json(m, c)
    assert summary["resultado_neto"] == 50
    assert len(operations) == 1

    p = _mexc_xlsx(tmp_path, [_mexc_row("2024-01-01 10:00:00", "BUY", "USDT")])
    m, _, c = procesar_mexc(p)
    with pytest.raises(ValueError, match="valoración histórica"):
        _motor_a_json(m, c)

    p = _mexc_xlsx(tmp_path, [_mexc_row("2024-01-01 10:00:00", "HOLD")])
    m, _, c = procesar_mexc(p)
    with pytest.raises(ValueError, match="operaciones no interpretadas"):
        _motor_a_json(m, c)


BITGET_HEADERS = [
    "Date", "Trading pair", "Base Asset", "Quote Asset", "Direction",
    "Price", "Amount", "Total", "Fee", "Fee Coin", "",
]


def test_real_bitget_csv_eur_and_usdt_are_distinguished(tmp_path):
    p = tmp_path / "bitget_synthetic.csv"
    def write(quote):
        with p.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(BITGET_HEADERS)
            for date, direction, price in (
                ("2024-01-01 10:00:00", "Buy", 100),
                ("2025-01-01 10:00:00", "Sell", 150),
            ):
                writer.writerow([date, "BTC/" + quote, "BTC", quote,
                                 direction, price, 1, price, 0, quote, ""])

    write("EUR")
    motor, _, classifier = procesar_bitget(str(p))
    summary, _, _ = _motor_a_json(motor, classifier)
    assert summary["resultado_neto"] == 50

    write("USDT")
    motor, _, classifier = procesar_bitget(str(p))
    with pytest.raises(ValueError, match="valoración histórica"):
        _motor_a_json(motor, classifier)


LEDGER_HEADER = (
    "UID,Account Type,Currency,Side,Amount,Fee,"
    "Time(UTC+02:00),Remark,Type"
)


def test_real_kucoin_csv_unknown_vs_information(tmp_path):
    p = tmp_path / "kucoin.csv"
    p.write_text(LEDGER_HEADER +
                 "\n1,m,BTC,Deposit,1,0,2024-01-01 10:00:00,,Spot"
                 "\n1,m,EUR,Withdrawal,100,0,2024-01-01 10:00:00,,Spot"
                 "\n1,m,BTC,Withdrawal,1,0,2025-01-01 10:00:00,,Spot"
                 "\n1,m,EUR,Deposit,150,0,2025-01-01 10:00:00,,Spot\n",
                 encoding="utf-8-sig")
    m, _, c = procesar_kucoin([str(p)], [p.name])
    assert c.advertencias  # Generic coverage warning must not block valid EUR.
    result, _, _ = _motor_a_json(m, c)
    assert result["resultado_neto"] == 50

    p.write_text(LEDGER_HEADER +
                 "\n1,m,BTC,Deposit,1,0,2024-01-01 10:00:00,,Spot"
                 "\n1,m,EUR,Withdrawal,100,0,2024-01-01 10:00:00,,Spot"
                 "\n1,m,BTC,Deposit,1,0,2025-01-01 10:00:00,,Staking\n",
                 encoding="utf-8-sig")
    m, _, c = procesar_kucoin([str(p)], [p.name])
    with pytest.raises(ValueError, match="operaciones no interpretadas"):
        _motor_a_json(m, c)


def test_http_rejection_does_not_emit_pdf_token_or_generated_record(monkeypatch):
    import app as application
    import flask_login.utils as login_utils
    user = SimpleNamespace(id=970011, role="user", email="test@example.invalid",
                           is_authenticated=True, is_active=True)
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)
    monkeypatch.setattr(application, "_validar_csv", lambda *a, **kw: (True, ""))
    monkeypatch.setattr(application, "procesar_bitget",
                        lambda p: (_motor_eur(), [], _classifier("bitget", quote="USDT")))
    reports, tokens, pdf_calls = [], [], []
    monkeypatch.setattr(application, "_registrar_informe",
                        lambda **kw: reports.append(kw) or 1)
    monkeypatch.setattr(application, "_guardar_token_pdf",
                        lambda *a: tokens.append(a))
    monkeypatch.setattr(application, "generar_pdf_bitget",
                        lambda *a, **kw: pdf_calls.append(1) or b"%PDF")
    monkeypatch.setattr(application, "record_processing_error_safe", lambda **kw: None)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    with app.test_client() as client:
        resp = client.post("/api/analizar", data={
            "csv": (io.BytesIO(b"Date,Test\n2025-01-01,1\n"), "synthetic.csv"),
            "exchange": "bitget", "nombre": "Synthetic", "ejercicio": "2025",
        }, content_type="multipart/form-data")
    assert resp.status_code == 422
    assert "token" not in resp.json and "resumen" not in resp.json
    assert not tokens and not pdf_calls
    assert reports and all(r["status"] == "failed" for r in reports)


def test_sqlite_real_persistence_rejection_and_valid_eur(tmp_path):
    """Isolated DB, synthetic user; verify 422 -> failed and 200 -> generated."""
    import os
    import subprocess
    import sys
    import textwrap
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1]
    db_file = tmp_path / "phase1.sqlite"
    pdf_file = tmp_path / "fifo_report_valid.pdf"
    program = r'''
import io
from pathlib import Path
from types import SimpleNamespace
import flask_login.utils as login_utils
import app as api
from app import app
from models import db, User, FifoReport
from motor_fifo import MotorFIFO
from clasificador_bitget import ClasificadorBitget

app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
with app.app_context():
    db.create_all()
    user = User(email="phase1@example.invalid", is_active=True, role="user", plan="free")
    db.session.add(user)
    db.session.commit()
    uid = user.id

login_utils._get_user = lambda: SimpleNamespace(
    id=uid, role="user", email="phase1@example.invalid",
    is_authenticated=True, is_active=True,
)
api._validar_csv = lambda *a, **kw: (True, "")
api.record_processing_error_safe = lambda **kw: None
pdf = Path(PDF_FILE)
api._derivar_ruta_pdf = lambda *a: str(pdf)
api.generar_pdf_bitget = lambda *a, **kw: b"%PDF-TEST"
api._guardar_token_pdf = lambda *a: None

def scenario(quote):
    motor = MotorFIFO()
    motor.registrar_compra("2024-01-01", "BTC", 1, 100, "EUR", "EUR", 0)
    motor.registrar_venta("2025-01-01", "BTC", 1, 150, "EUR", "EUR", 0)
    c = ClasificadorBitget.__new__(ClasificadorBitget)
    c.compraventas = [SimpleNamespace(contraparte=quote)]
    c.swaps, c.movimientos, c.rendimientos, c.desconocidas = [], [], [], []
    c.advertencias = ["Aviso exclusivamente informativo"]
    return motor, [], c

for index, quote in enumerate(("USDT", "EUR")):
    if pdf.exists():
        pdf.unlink()
    api.procesar_bitget = lambda path, q=quote: scenario(q)
    with app.test_client() as client:
        response = client.post("/api/analizar", data={
            "csv": (io.BytesIO(b"Date,Test\n2025-01-01,1\n"), "synthetic.csv"),
            "exchange": "bitget", "nombre": "Synthetic", "ejercicio": "2025",
        }, content_type="multipart/form-data")
    assert response.status_code == (422 if index == 0 else 200)
    if index == 0:
        assert "token" not in response.json
        assert not pdf.exists()
    else:
        assert response.json["resumen"]["resultado_neto"] == 50
        assert response.json["token"] == pdf.name
        assert pdf.read_bytes() == b"%PDF-TEST"
    with app.app_context():
        reports = FifoReport.query.order_by(FifoReport.id).all()
        assert len(reports) == index + 1
        assert reports[-1].status == ("failed" if index == 0 else "generated")
print("P0_PHASE1_SQLITE: PASS 422 failed / 200 generated")
'''
    program = program.replace("PDF_FILE", repr(str(pdf_file)))
    env = {
        "FLASK_ENV": "testing",
        "DATABASE_URL": "sqlite:///" + str(db_file),
        "PYTHONPATH": str(app_dir),
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(program)],
        cwd=app_dir, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (result.stdout + "\n" + result.stderr)[-4500:]
    assert "P0_PHASE1_SQLITE: PASS" in result.stdout


# PR #125 cierre adversarial: un export identificado pero ignorado no es
# evidencia suficiente para producir un informe fiscal vacío.
def test_bitget_auxiliary_only_fails_closed_with_real_synthetic_csv(tmp_path):
    import csv
    from clasificador_bitget import ClasificadorBitgetMulti, BitgetUserError
    cases = {
        "historial": ["Date", "Type", "Order Id", "Trading pair", "Base Asset",
                      "Quote Asset", "Direction", "Price", "Order amount",
                      "Executed", "Average Price", "Trading volume", "Status"],
        "financial_record": ["Order no.", "Coin", "Type", "Action", "Quantity", "Amount (USDT)"],
    }
    for kind, headers in cases.items():
        path = tmp_path / (kind + ".csv")
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(headers)
            writer.writerow(["synthetic"] * len(headers))
        with pytest.raises(BitgetUserError, match="historial de operaciones spot procesable") as exc:
            ClasificadorBitgetMulti([str(path)], [path.name]).clasificar()
        assert exc.value.code == "insufficient_fifo_source"


def test_bitget_auxiliary_with_valid_spot_eur_is_allowed(tmp_path):
    import csv
    from clasificador_bitget import ClasificadorBitgetMulti
    auxiliary = tmp_path / "financial_record.csv"
    with auxiliary.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Order no.", "Coin", "Type", "Action", "Quantity", "Amount (USDT)"])
        writer.writerow(["123", "BTC", "ORDER_FROZEN", "OUT", "1", "100"])
    spot = tmp_path / "spot_eur.csv"
    with spot.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(BITGET_HEADERS)
        writer.writerow(["2024-01-01 10:00:00", "BTC/EUR", "BTC", "EUR",
                         "Buy", 100, 1, 100, 0, "EUR", ""])
        writer.writerow(["2025-01-01 10:00:00", "BTC/EUR", "BTC", "EUR",
                         "Sell", 150, 1, 150, 0, "EUR", ""])
    classifier = ClasificadorBitgetMulti(
        [str(auxiliary), str(spot)], [auxiliary.name, spot.name]
    ).clasificar()
    assert len(classifier.compraventas) == 2
    assert not classifier.desconocidas
    assert any("Financial Record" in warning for warning in classifier.advertencias)


def test_bitget_recognized_auxiliary_only_http_no_pdf_or_token(monkeypatch, tmp_path):
    import csv
    import app as api
    import flask_login.utils as login_utils
    from clasificador_bitget import ClasificadorBitgetMulti
    headers = ["Order no.", "Coin", "Type", "Action", "Quantity", "Amount (USDT)"]
    file_path = tmp_path / "financial.csv"
    with file_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerow(["12", "BTC", "ORDER_FROZEN", "OUT", "1", "100"])
    user = SimpleNamespace(id=970012, role="user", email="test@example.invalid",
                           is_authenticated=True, is_active=True)
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)
    monkeypatch.setattr(api, "_validar_csv", lambda *a, **kw: (True, ""))
    reports, tokens, pdf_calls = [], [], []
    monkeypatch.setattr(api, "_registrar_informe",
                        lambda **kw: reports.append(kw) or 1)
    monkeypatch.setattr(api, "_guardar_token_pdf",
                        lambda *a: tokens.append(a))
    monkeypatch.setattr(api, "generar_pdf_bitget",
                        lambda *a, **kw: pdf_calls.append(1) or b"%PDF")
    monkeypatch.setattr(api, "record_processing_error_safe", lambda **kw: None)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    with app.test_client() as client:
        response = client.post("/api/bitget/analizar", data={
            "csv": [(io.BytesIO(file_path.read_bytes()), file_path.name)],
            "ejercicio": "2025", "nombre": "Synthetic",
        }, content_type="multipart/form-data")
    assert response.status_code == 422
    assert "token" not in response.get_json()
    assert not tokens and not pdf_calls
    assert not any(r.get("status") == "generated" for r in reports)


def test_bitget_zero_sided_ledger_pair_is_not_silently_ignored():
    c = _classifier("bitget")
    c._reconstruir_compraventa(
        "2025-01-01 10:00:00",
        {"Coin": "BTC", "Amount": "1", "Fee": "0", "Type": "buy"},
        {"Coin": "EUR", "Amount": "0", "Fee": "0", "Type": "sell"},
    )
    assert len(c.desconocidas) == 2
    with pytest.raises(ValueError, match="operaciones no interpretadas"):
        _motor_a_json(_motor_eur(), c)


# PR #125: a valid CSV signature without processed trades cannot justify a PDF.
_BITGET_SPOT_HEADERS = [
    "Order no.", "Trading pair", "Coin", "Action", "Executed price",
    "Quantity", "Transacted amount", "Fee", "Fee deducted in", "Date",
]


def _bitget_spot_bytes(*, with_purchase=False):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(_BITGET_SPOT_HEADERS)
    if with_purchase:
        writer.writerow([
            "synthetic-buy-1", "BTCEUR", "BTC", "Buy", "100",
            "1", "100", "0", "EUR", "2024-01-01 10:00:00",
        ])
    return stream.getvalue().encode("utf-8-sig")


def test_bitget_empty_spot_header_only_fails_closed(tmp_path):
    from clasificador_bitget import BitgetUserError, detect_bitget_file_type
    path = tmp_path / "spot_header_only.csv"
    path.write_bytes(_bitget_spot_bytes())
    assert detect_bitget_file_type(str(path)) == "spot_trading"
    with pytest.raises(BitgetUserError, match="historial de operaciones spot procesable") as exc:
        ClasificadorBitgetMulti([str(path)], [path.name]).clasificar()
    assert exc.value.code == "insufficient_fifo_source"


def test_bitget_purchase_only_remains_valid_even_with_empty_spot_supplement(tmp_path):
    from app import procesar_con_fifo
    valid = tmp_path / "spot_purchase_only.csv"
    blank = tmp_path / "spot_header_only.csv"
    valid.write_bytes(_bitget_spot_bytes(with_purchase=True))
    blank.write_bytes(_bitget_spot_bytes())

    # An empty later file of the same kind marks section 'vacio' but must
    # not mask actual purchases from another properly parsed spot export.
    c = ClasificadorBitgetMulti(
        [str(valid), str(blank)], [valid.name, blank.name]
    ).clasificar()
    assert c._sec["spot_trading"].registros == 1
    assert c._sec["spot_trading"].vacio is True
    assert len(c.compraventas) == 1 and c.compraventas[0].tipo == "COMPRA"
    motor, _, classified = procesar_con_fifo(c)
    summary, _, operations = _motor_a_json(motor, classified)
    assert summary["operaciones_con_resultado"] == 0
    assert not operations
    assert motor.inventario["BTC"][0].cantidad_restante == 1


def test_bitget_empty_spot_header_only_http_422_without_pdf_token_or_success(monkeypatch):
    import app as api
    import flask_login.utils as login_utils

    user = SimpleNamespace(id=970013, role="user", email="test@example.invalid",
                           is_authenticated=True, is_active=True)
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)
    reports, tokens, pdf_calls = [], [], []
    monkeypatch.setattr(api, "_registrar_informe",
                        lambda **kw: reports.append(kw) or 1)
    monkeypatch.setattr(api, "_guardar_token_pdf",
                        lambda *a: tokens.append(a))
    monkeypatch.setattr(api, "generar_pdf_bitget",
                        lambda *a, **kw: pdf_calls.append(1) or b"%PDF")
    monkeypatch.setattr(api, "record_processing_error_safe", lambda **kw: None)
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
    with app.test_client() as client:
        response = client.post("/api/bitget/analizar", data={
            "csv": [(io.BytesIO(_bitget_spot_bytes()), "spot_header_only.csv")],
            "ejercicio": "2025", "nombre": "Synthetic",
        }, content_type="multipart/form-data")
    assert response.status_code == 422
    assert "Datos fiscales no seguros" in response.get_json()["error"]
    assert "token" not in response.get_json()
    assert not tokens and not pdf_calls
    assert reports and all(report.get("status") == "failed" for report in reports)
