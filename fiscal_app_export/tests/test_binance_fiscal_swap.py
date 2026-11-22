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
        "valuation": v, "fee_amount": Decimal("0"),
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


def test_swap_con_inventario_insuficiente_no_modifica_lotes_ni_resultados():
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-12-01 12:00:00", activo="XRP",
        cantidad=3.0, importe=3.0, contraparte="EUR",
        fee_activo="EUR", fee_cantidad=0.0,
    )
    before = m.inventario["XRP"][0].cantidad_restante
    with pytest.raises(BinancePriceEvidenceError, match="Inventario de permuta insuficiente"):
        apply(m, evidence())
    assert m.inventario["XRP"][0].cantidad_restante == before
    assert m.inventario.get("USDC", []) == []
    assert m.resultados == []


def test_swap_con_lote_futuro_no_modifica_inventario():
    m = seeded_motor()
    m.registrar_compra(
        fecha="2025-02-01 12:00:00", activo="XRP",
        cantidad=3.0, importe=6.0, contraparte="EUR",
        fee_activo="EUR", fee_cantidad=0.0,
    )
    previous = [l.cantidad_restante for l in m.inventario["XRP"]]
    with pytest.raises(BinancePriceEvidenceError, match="posterior"):
        apply(m, evidence())
    assert [l.cantidad_restante for l in m.inventario["XRP"]] == previous
    assert m.resultados == []


def test_permuta_rechaza_truncamiento_decimal_antes_de_consumir_lotes():
    from binance_eur_valuation import SwapEURValuation, AssetEURPrice
    m = seeded_motor()
    before = m.inventario["XRP"][0].cantidad_restante
    frac = Decimal("0.123456789123456789")
    catalog = book()
    valuation = catalog.value_swap(
        timestamp=WHEN,
        given_asset="XRP", given_amount=frac,
        received_asset="USDC", received_amount=Decimal("11"),
    )
    with pytest.raises(BinancePriceEvidenceError, match="precisión"):
        apply(m, valuation, given_amount=frac)
    assert m.inventario["XRP"][0].cantidad_restante == before
    assert m.inventario.get("USDC", []) == []
    assert m.resultados == []



def test_permuta_eur_por_par_inverso_permite_error_inferior_al_centimo():
    """Un precio EURUSDT de mercado genera una división Decimal periódica.

    La diferencia numérica al convertir un importe EUR al MotorFIFO float
    es menor de 1e-10 EUR, NO cambia céntimos y no altera unidades.
    """
    q = BinanceHistoricalEURPrices([
        TradePriceEvidence("EUR", "USDT", Decimal("1.0527"), WHEN, 5, "c"*64),
        TradePriceEvidence("EUR", "USDC", Decimal("1.0529"), WHEN, 6, "d"*64),
    ])
    v = q.value_swap(
        timestamp=WHEN, given_asset="USDT", given_amount=Decimal("10"),
        received_asset="USDC", received_amount=Decimal("10"),
    )
    assert Decimal(str(float(v.fiscal_value_eur))) != v.fiscal_value_eur
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-12-01 12:00:00", activo="USDT",
        cantidad=10.0, importe=8.0, contraparte="EUR",
        fee_activo="EUR", fee_cantidad=0,
    )
    apply(
        m, v, given_asset="USDT", given_amount=Decimal("10"),
        received_asset="USDC", received_amount=Decimal("10"),
    )
    assert len(m.resultados) == 1
    assert m.resultados[0].precio_transmision == pytest.approx(
        float(v.fiscal_value_eur)
    )
    assert (m._binance_bridge_cumulative_delta_eur
            <= Decimal("0.0000000001"))


def test_permuta_que_cambia_redondeo_en_centimos_sigue_bloqueada():
    """Nunca permitir doble -> Decimal si cambia 0.00 EUR a 0.01 EUR."""
    q = BinanceHistoricalEURPrices([
        TradePriceEvidence("XRP", "EUR", Decimal("0.00099999999999999998"), WHEN, 5, "c"*64),
        TradePriceEvidence("USDC", "EUR", Decimal("0.00001"), WHEN, 6, "d"*64),
    ])
    v = q.value_swap(
        timestamp=WHEN, given_asset="XRP", given_amount=Decimal("5"),
        received_asset="USDC", received_amount=Decimal("11"),
    )
    assert v.fiscal_value_eur < Decimal("0.005")
    assert Decimal(str(float(v.fiscal_value_eur))) == Decimal("0.005")
    m = seeded_motor()
    before = m.inventario["XRP"][0].cantidad_restante
    with pytest.raises(BinancePriceEvidenceError, match="precisión fiscal"):
        apply(m, v)
    assert m.inventario["XRP"][0].cantidad_restante == before
    assert m.resultados == []
    assert m.inventario.get("USDC", []) == []


def test_permuta_importe_eur_grande_con_perdida_absoluta_bloqueada():
    """Aunque coincidiesen los céntimos, la pérdida absoluta está limitada."""
    q = BinanceHistoricalEURPrices([
        TradePriceEvidence("XRP", "EUR", Decimal("100000000.123456789123"), WHEN, 5, "c"*64),
        TradePriceEvidence("USDC", "EUR", Decimal("0.00001"), WHEN, 6, "d"*64),
    ])
    v = q.value_swap(
        timestamp=WHEN, given_asset="XRP", given_amount=Decimal("5"),
        received_asset="USDC", received_amount=Decimal("11"),
    )
    m = seeded_motor()
    with pytest.raises(BinancePriceEvidenceError, match="precisión fiscal"):
        apply(m, v)
    assert not m.resultados


def test_permuta_precision_inventario_sigue_bloqueada_aunque_eur_sea_valido():
    m = seeded_motor()
    frac = Decimal("0.123456789123456789")
    v = book().value_swap(
        timestamp=WHEN, given_asset="XRP", given_amount=frac,
        received_asset="USDC", received_amount=Decimal("11"),
    )
    with pytest.raises(BinancePriceEvidenceError, match="Cantidad"):
        apply(m, v, given_amount=frac)
    assert m.resultados == []
