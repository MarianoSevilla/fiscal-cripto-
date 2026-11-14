"""Synthetic adversarial tests for EUR Spot BNB fee settlement."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_eur_valuation import (
    BinanceHistoricalEURPrices, BinancePriceEvidenceError, TradePriceEvidence,
)
from binance_spot_bnb_fee_execution import (
    prepare_spot_eur_bnb_fees, apply_spot_eur_trade_with_bnb_fee,
)
from clasificador import OperacionCompraventa
from motor_fifo import MotorFIFO


def quote(price="300", at="2025-01-01 10:00:00"):
    dt = datetime.strptime(at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return BinanceHistoricalEURPrices([
        TradePriceEvidence("BNB", "EUR", Decimal(price),
                           dt-timedelta(seconds=1), 101, "a"*64),
    ])


def trade(give="EUR", given="20", received="XRP", received_qty="10",
          fee="0.005", fee_asset="BNB", at="2025-01-01 11:00:00"):
    return SimpleNamespace(
        source="Spot BUY" if give == "EUR" else "Spot SELL",
        filename="Binance-Spot-(UTC+1).csv",
        local_time=at, given_asset=give, given_amount=Decimal(given),
        received_asset=received, received_amount=Decimal(received_qty),
        fee_asset=fee_asset, fee_amount=Decimal(fee),
    )


def classified(event, *, source_rows=None):
    op = OperacionCompraventa(
        fecha=event.local_time,
        tipo="COMPRA" if event.given_asset == "EUR" else "VENTA",
        activo=event.received_asset if event.given_asset == "EUR" else event.given_asset,
        cantidad=float(event.received_amount if event.given_asset == "EUR"
                       else event.given_amount),
        contraparte="EUR", importe=float(event.given_amount if event.given_asset == "EUR"
                                         else event.received_amount),
        fee_activo=event.fee_asset,
        fee_cantidad=float(event.fee_amount),
    )
    return SimpleNamespace(
        intercambios_nativos=[event],
        compraventas=[op], swaps=[], rendimientos=[], earn_events=[],
        desconocidas=[], movimientos=[], fuentes_materiales_no_soportadas=[],
        comisiones_pendientes=[{
            "fecha": event.local_time, "activo": "BNB",
            "cantidad": str(event.fee_amount), "fuente": event.source,
        }],
        _source_rows={"transaction_history": source_rows or []},
        _commission_files=[],
    )


def test_bnb_fee_market_reference_has_separate_disposal_value():
    c = classified(trade())
    plan = prepare_spot_eur_bnb_fees(c, quote())
    assert len(plan) == 1
    assert plan[0].bnb_amount == Decimal("0.005")
    assert plan[0].eur_value == Decimal("1.500")
    assert len(plan[0].public_trades) == 1


def test_bnb_fee_consumes_fifo_historical_cost_not_market_value():
    c = classified(trade())
    plan = prepare_spot_eur_bnb_fees(c, quote())
    motor = MotorFIFO()
    motor.registrar_compra("2024-01-01 10:00:00", "BNB", 0.01, 2, "EUR", "EUR", 0)
    apply_spot_eur_trade_with_bnb_fee(motor, c.compraventas[0], plan[0])
    assert len(motor.resultados) == 1
    fee_result = motor.resultados[0]
    assert fee_result.activo == "BNB"
    assert fee_result.precio_transmision == pytest.approx(1.5)
    assert fee_result.precio_coste == pytest.approx(1.0)
    assert fee_result.ganancia_perdida == pytest.approx(0.5)
    positions = {p.activo: p for p in motor.posicion_actual()}
    assert positions["XRP"].cantidad_total == pytest.approx(10)
    assert positions["XRP"].coste_total == pytest.approx(21.5)
    assert positions["BNB"].cantidad_total == pytest.approx(0.005)
    assert positions["BNB"].coste_total == pytest.approx(1)


def test_sale_fee_reduces_eur_proceeds_and_disposes_bnb():
    sale = trade(give="XRP", given="4", received="EUR", received_qty="16")
    c = classified(sale)
    plan = prepare_spot_eur_bnb_fees(c, quote())
    motor = MotorFIFO()
    motor.registrar_compra("2024-01-01 10:00:00", "BNB", 0.01, 2, "EUR", "EUR", 0)
    motor.registrar_compra("2024-01-01 10:01:00", "XRP", 10, 20, "EUR", "EUR", 0)
    apply_spot_eur_trade_with_bnb_fee(motor, c.compraventas[0], plan[0])
    assert len(motor.resultados) == 2
    by_asset = {r.activo: r for r in motor.resultados}
    assert by_asset["XRP"].precio_transmision == pytest.approx(14.5)
    assert by_asset["XRP"].precio_coste == pytest.approx(8)
    assert by_asset["BNB"].precio_transmision == pytest.approx(1.5)
    assert by_asset["BNB"].precio_coste == pytest.approx(1)


def test_missing_bnb_inventory_blocks_without_partial_xrp_purchase():
    c = classified(trade())
    plan = prepare_spot_eur_bnb_fees(c, quote())
    motor = MotorFIFO()
    with pytest.raises(BinancePriceEvidenceError, match="inventario FIFO BNB"):
        apply_spot_eur_trade_with_bnb_fee(motor, c.compraventas[0], plan[0])
    assert not motor.resultados and not motor.inventario


def test_future_bnb_lots_cannot_pay_fee():
    c = classified(trade())
    plan = prepare_spot_eur_bnb_fees(c, quote())
    motor = MotorFIFO()
    motor.registrar_compra("2025-01-01 11:00:00", "BNB", 0.01, 2, "EUR", "EUR", 0)
    with pytest.raises(BinancePriceEvidenceError, match="orden cronológico"):
        apply_spot_eur_trade_with_bnb_fee(motor, c.compraventas[0], plan[0])


def test_missing_pinned_market_quote_blocks():
    c = classified(trade())
    with pytest.raises(BinancePriceEvidenceError, match="No existe evidencia"):
        prepare_spot_eur_bnb_fees(c, BinanceHistoricalEURPrices([]))


def test_mismatched_ledger_fees_cannot_be_hidden():
    c = classified(trade(), source_rows=[({"operación": "Transaction Fee"},
                                          "synthetic.csv")])
    with pytest.raises(BinancePriceEvidenceError, match="otras fuentes"):
        prepare_spot_eur_bnb_fees(c, quote())


def test_unsupported_fee_source_keeps_previous_block():
    c = classified(trade(fee_asset="XRP"))
    assert prepare_spot_eur_bnb_fees(c, quote()) == ()


def test_fee_quantity_with_unrepresentable_units_rejected():
    e = trade(fee="0.00000000000000000000019")
    c = classified(e)
    with pytest.raises(BinancePriceEvidenceError, match="precisión de unidades"):
        prepare_spot_eur_bnb_fees(c, quote())


def test_duplicate_same_second_native_fills_block():
    e = trade()
    c = classified(e)
    c.intercambios_nativos.append(e)
    c.compraventas.append(c.compraventas[0])
    c.comisiones_pendientes.append(c.comisiones_pendientes[0])
    with pytest.raises(BinancePriceEvidenceError, match="simultáneas"):
        prepare_spot_eur_bnb_fees(c, quote())


def test_source_outside_spot_eur_rejected():
    e = trade()
    e.source = "Fiat trade"
    c = classified(e)
    c.comisiones_pendientes[0]["fuente"] = "Fiat trade"
    with pytest.raises(BinancePriceEvidenceError, match="Spot/EUR"):
        prepare_spot_eur_bnb_fees(c, quote())


def test_income_or_external_deposit_blocks_even_if_bnb_price_known():
    c = classified(trade())
    c.movimientos.append(object())
    with pytest.raises(BinancePriceEvidenceError, match="otras fuentes"):
        prepare_spot_eur_bnb_fees(c, quote())
