"""Pruebas aisladas de permutas fiscales Binance, sin usar datos de clientes."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_eur_valuation import (
    BinanceHistoricalEURPrices, BinancePriceEvidenceError, TradePriceEvidence,
)
from binance_fiscal_swap import aplicar_permuta_binance_valorada
from motor_fifo import MotorFIFO


WHEN = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def book():
    return BinanceHistoricalEURPrices([
        TradePriceEvidence("XRP", "EUR", Decimal("2"), WHEN, 1, "a" * 64),
        TradePriceEvidence("USDC", "EUR", Decimal("0.9"), WHEN, 2, "b" * 64),
    ])


def evidence():
    return book().value_swap(
        timestamp=WHEN, given_asset="XRP", given_amount=Decimal("5"),
        received_asset="USDC", received_amount=Decimal("11"),
    )


def seeded_motor():
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-12-01 12:00:00", activo="XRP",
        cantidad=10.0, importe=10.0, contraparte="EUR",
        fee_activo="EUR", fee_cantidad=0.0,
    )
    return m


def apply(m, v, **overrides):
    args = {
        "motor": m, "fecha_local": "2025-01-01 13:00:00",
        "export_filename": "Binance-Convert-(UTC+1).zip",
        "given_asset": "XRP", "given_amount": Decimal("5"),
        "received_asset": "USDC", "received_amount": Decimal("11"),
        "valuation": v,
    }
    args.update(overrides)
    return aplicar_permuta_binance_valorada(**args)


def test_permuta_fiscal_usa_mayor_mercado_y_registra_coste_adquisicion_usdc():
    m = seeded_motor()
    apply(m, evidence())
    assert len(m.resultados) == 1
    outcome = m.resultados[0]
    assert outcome.activo == "XRP"
    assert outcome.activo_recibido == "USDC"
    assert outcome.tipo_operacion == "swap"
    assert outcome.precio_transmision == pytest.approx(10)
    assert outcome.precio_coste == pytest.approx(5)
    assert outcome.ganancia_perdida == pytest.approx(5)
    assert sum(l.cantidad_restante for l in m.inventario["XRP"]) == pytest.approx(5)
    assert sum(l.cantidad_restante for l in m.inventario["USDC"]) == pytest.approx(11)
    assert m.inventario["USDC"][0].precio_coste_unitario == pytest.approx(10 / 11)
    m.registrar_venta(
        fecha="2025-01-02 13:00:00", activo="USDC",
        cantidad=11, importe=9, contraparte="EUR",
        fee_activo="EUR", fee_cantidad=0,
    )
    assert m.resultados[-1].ganancia_perdida == pytest.approx(-1)


def test_swap_no_se_aplica_si_hora_utc_no_coincide():
    m = seeded_motor()
    with pytest.raises(BinancePriceEvidenceError, match="instante"):
        apply(m, evidence(), fecha_local="2025-01-01 12:00:00")
    assert m.resultados == []


def test_swap_no_se_aplica_con_fee_pendiente():
    m = seeded_motor()
    with pytest.raises(BinancePriceEvidenceError, match="Comisión"):
        apply(m, evidence(), fee_amount=Decimal("0.01"))
    assert m.resultados == []


def test_swap_no_se_aplica_con_cantidad_inconsistente():
    m = seeded_motor()
    with pytest.raises(BinancePriceEvidenceError, match="Cantidades"):
        apply(m, evidence(), received_amount=Decimal("10"))
    assert m.resultados == []


def test_swap_no_crea_lote_si_falta_inventario_entregado():
    m = MotorFIFO()
    with pytest.raises(BinancePriceEvidenceError, match="inventario previo"):
        apply(m, evidence())
    assert m.inventario.get("USDC", []) == []
