"""Independent adversarial gate for PR119 A01-A04, synthetic fixtures only.

This suite is authored on a separate audit branch based on SHA 8922f93e.
It intentionally does not import any helpers/tests from the correction suite.
"""
import csv
import math
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import procesar_bitvavo, _motor_a_json, _rendimientos_a_json
from clasificador_uphold import ClasificadorUphold
from clasificador_cryptocom import ClasificadorCryptoCom
from clasificador_bitget import ClasificadorBitget
from motor_fifo import MotorFIFO


def save_csv(tmp_path, name, cols, row):
    p = tmp_path / name
    with p.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(cols)
        writer.writerow(row)
    return str(p)


BV = ["Timezone", "Date", "Time", "Type", "Currency", "Amount",
      "Quote Currency", "Quote Price", "Received / Paid Currency",
      "Received / Paid Amount", "Fee currency", "Fee amount",
      "Status", "Transaction ID", "Address"]
UP = ["Date", "Destination", "Destination Amount", "Destination Currency",
      "Fee Amount", "Fee Currency", "Id", "Origin", "Origin Amount",
      "Origin Currency", "Status", "Type"]
CC = ["Timestamp (UTC)", "Transaction Description", "Transaction Kind",
      "Currency", "Amount", "To Currency", "To Amount", "Native Currency",
      "Native Amount", "Native Amount (in USD)", "Transaction Hash"]


@pytest.mark.parametrize("malformed", ["", "not-an-amount", "Infinity", "1e309"])
def test_a01_bitvavo_never_silently_omits_invalid_payment(tmp_path, malformed):
    row = ["UTC", "2024-02-01", "12:00:00", "buy", "BTC", "1",
           "EUR", "250", "EUR", malformed, "EUR", "0", "Completed", "id1", ""]
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        procesar_bitvavo(save_csv(tmp_path, "v.csv", BV, row))


@pytest.mark.parametrize("malformed", ["", "not-an-amount", "Infinity", "1e309"])
def test_a01_uphold_never_silently_omits_invalid_payment(tmp_path, malformed):
    row = ["Fri Sep 26 2025 23:31:25 GMT+0000", "external", "1", "BTC",
           "", "EUR", "id1", "credit-card", malformed, "EUR", "completed", "in"]
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        ClasificadorUphold(save_csv(tmp_path, "u.csv", UP, row)).clasificar()


@pytest.mark.parametrize("malformed", ["", "not-an-amount", "Infinity", "1e309"])
def test_a01_cryptocom_no_usd_fallback_when_eur_missing(tmp_path, malformed):
    row = ["2024-02-01 12:00:00", "Buy BTC", "crypto_purchase", "BTC",
           "1", "", "", "EUR", malformed, "250", "tx1"]
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        ClasificadorCryptoCom(save_csv(tmp_path, "c.csv", CC, row)).clasificar()


def bitget():
    instance = ClasificadorBitget.__new__(ClasificadorBitget)
    instance.compraventas = []
    instance.desconocidas = []
    instance._tiene_pares_usdt = False
    return instance


@pytest.mark.parametrize("fee_location", ["received", "spent"])
def test_a02_bitget_ledger_fee_is_not_treated_as_net_verified(fee_location):
    source = bitget()
    received = {"Coin": "EUR", "Amount": "400", "Fee": "-2" if fee_location == "received" else "0"}
    spent = {"Coin": "BTC", "Amount": "-1", "Fee": "-0.01" if fee_location == "spent" else "0"}
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        source._reconstruir_compraventa("2025-01-01 10:00:00", received, spent)
    assert not source.compraventas


@pytest.mark.parametrize("kind", ["details", "spot"])
def test_a03_bitget_fee_in_disposed_coin_does_not_create_phantom_inventory(kind):
    source = bitget()
    if kind == "details":
        row = {"Date": "2025-01-01 10:00:00", "Base Asset": "BTC",
               "Quote Asset": "EUR", "Direction": "SELL", "Amount": "1",
               "Total": "400", "Fee": "0.005", "Fee Coin": "BTC"}
        action = source._procesar_fila_detalles
    else:
        row = {"Date": "2025-01-01 10:00:00", "Coin": "BTC",
               "Trading pair": "BTCEUR", "Action": "sell",
               "Quantity": "1", "Transacted amount": "400",
               "Fee": "0.005", "Fee deducted in": "BTC"}
        action = source._procesar_fila_spot_trading
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        action(row)
    assert not source.compraventas


def test_a04_positive_finite_disposals_cannot_overflow_into_json_or_pdf():
    m = MotorFIFO()
    for i in range(3):
        m.registrar_compra(f"2023-01-0{i+1}", "BTC", 1, 1, "EUR", "EUR", 0)
        m.registrar_venta(f"2025-01-0{i+1}", "BTC", 1, 9e307, "EUR", "EUR", 0)
    assert all(math.isfinite(x.ganancia_perdida) for x in m.resultados)
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        _motor_a_json(m)
    from generador_pdf import generar_pdf
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        generar_pdf(m, exchange="Bitvavo")


def test_a04_staking_aggregation_cannot_create_nonfinite_json():
    samples = [SimpleNamespace(subtipo="staking", activo="ETH",
               cantidad=1.0, valor_eur=9e307) for _ in range(3)]
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        _rendimientos_a_json(samples)


def test_a03_valid_quote_currency_fee_is_not_over_rejected():
    source = bitget()
    source._procesar_fila_detalles({
        "Date": "2025-01-01 10:00:00", "Base Asset": "BTC",
        "Quote Asset": "EUR", "Direction": "SELL", "Amount": "1",
        "Total": "400", "Fee": "2", "Fee Coin": "EUR",
    })
    assert len(source.compraventas) == 1
    assert source.compraventas[0].cantidad == 1
