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
