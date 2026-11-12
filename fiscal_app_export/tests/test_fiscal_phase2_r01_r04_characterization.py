"""Fase 2: oráculos fiscales independientes — caracterización de R01–R04.

Son pruebas de REPRODUCCIÓN, NO de aceptación. Un test verde aquí demuestra
que la discrepancia descrita sigue existiendo; NO significa que sea correcta.

Base legal R01: AEAT Manual IRPF 2025, artículo 37.1.h LIRPF:
https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c11-ganancias-perdidas-patrimoniales/monedas-virtuales/compra-venta-monedas-virtuales-tributacion-inversor.html

Se usan importes, tipos de cambio y CSV enteramente sintéticos.
No se consulta producción, no se escribe en una base real.
"""
import csv
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import _pipeline_motor, _motor_a_json
from clasificador_nexo import ClasificadorNexo
from clasificador_uphold import ClasificadorUphold
from generador_pdf import generar_pdf
from motor_fifo import MotorFIFO


def _new_motor_with_one_lot():
    m = MotorFIFO()
    m.registrar_compra("2024-01-01 10:00:00", "BTC", 1.0, 100.0, "EUR", "EUR", 0.0)
    return m


def _write_csv(tmp_path, name, columns, records):
    f = tmp_path / name
    with f.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
    return str(f)


def test_control_fifo_sale_eur_with_full_history_is_correct():
    """Control positivo: adquisición 100 EUR, venta 150 EUR => 50 EUR."""
    m = _new_motor_with_one_lot()
    m.registrar_venta("2025-01-01 10:00:00", "BTC", 1.0, 150.0, "EUR", "EUR", 0.0)
    assert m.resumen_fiscal()["resultado_neto"] == 50.0
    assert m.resultados[0].inventario_incompleto is False
    assert _motor_a_json(m)[0]["resultado_neto"] == 50.0


def test_r01_swap_market_value_300_is_not_historical_cost_100():
    """Oráculo AEAT: plusvalía 200 EUR y coste ETH recibido 300 EUR.

    La prueba constata la discrepancia de la implementación vigente.
    NO certifica el comportamiento como fiscalmente correcto.
    """
    m = _new_motor_with_one_lot()
    m.registrar_swap("2025-01-01 10:00:00", "BTC", 1.0, "ETH", 2.0)
    expected_gain = Decimal("300") - Decimal("100")
    expected_eth_cost = Decimal("300")
    actual_gain = Decimal(str(m.resumen_fiscal()["resultado_neto"]))
    actual_eth_cost = Decimal(str(next(p.coste_total for p in m.posicion_actual() if p.activo == "ETH")))
    assert expected_gain == 200 and expected_eth_cost == 300
    assert actual_gain == 0, f"Caracterización cambió: ganancia {actual_gain}"
    assert actual_eth_cost == 100, f"Caracterización cambió: coste ETH {actual_eth_cost}"
    assert actual_gain != expected_gain and actual_eth_cost != expected_eth_cost
    pdf = generar_pdf(m, "AUDIT SYNTHETIC", "2025", "Synthetic", [])
    assert pdf.startswith(b"%PDF")


def test_r01_pipeline_ignores_supplied_swap_price_fmv_300():
    """El pipeline recibe un FMV explícito pero el motor no lo utiliza."""
    buy = SimpleNamespace(
        fecha="2024-01-01 10:00:00", tipo="COMPRA", activo="BTC",
        cantidad=1.0, importe=100.0, contraparte="EUR",
        fee_activo="EUR", fee_cantidad=0.0,
    )
    swap = SimpleNamespace(
        fecha="2025-01-01 10:00:00", activo_entregado="BTC",
        cantidad_entregada=1.0, activo_recibido="ETH",
        cantidad_recibida=2.0, precio_fmv_eur=300.0, nota="synthetic oracle",
    )
    c = SimpleNamespace(compraventas=[buy], swaps=[swap], rendimientos=[])
    m = _pipeline_motor(c)
    assert m.resumen_fiscal()["resultado_neto"] == 0
    assert next(p.coste_total for p in m.posicion_actual() if p.activo == "ETH") == 100
    assert m.resumen_fiscal()["resultado_neto"] != 200


@pytest.mark.parametrize("eur_per_usd", [Decimal("0.90"), Decimal("0.85")])
def test_r02_nexo_usd_equivalent_is_used_as_eur(tmp_path, eur_per_usd):
    """El FX es HIPOTÉTICO, no un tipo histórico: aísla el riesgo de unidades."""
    columns = [
        "Date / Time (UTC)", "Type", "Input Currency", "Output Currency",
        "Input Amount", "Output Amount", "USD Equivalent",
        "Fee", "Fee Currency", "Details",
    ]
    rows = [
        {
            "Date / Time (UTC)": "2024-01-01 10:00:00",
            "Type": "Exchange", "Input Currency": "EURX", "Output Currency": "BTC",
            "Input Amount": "-100", "Output Amount": "1",
            "USD Equivalent": "110", "Fee": "0", "Fee Currency": "",
            "Details": "Synthetic acquisition",
        },
        {
            "Date / Time (UTC)": "2025-01-01 10:00:00",
            "Type": "Exchange", "Input Currency": "BTC", "Output Currency": "USDT",
            "Input Amount": "-1", "Output Amount": "200",
            "USD Equivalent": "200", "Fee": "0", "Fee Currency": "",
            "Details": "Synthetic disposal",
        },
    ]
    c = ClasificadorNexo(_write_csv(tmp_path, "synthetic_nexo.csv", columns, rows)).clasificar()
    m = _pipeline_motor(c)
    expected_eur_disposal = Decimal("200") * eur_per_usd
    expected_gain = expected_eur_disposal - Decimal("100")
    actual_gain = Decimal(str(m.resumen_fiscal()["resultado_neto"]))
    assert actual_gain == 100
    assert actual_gain != expected_gain
    assert any("Convierte manualmente" in message for message in c.advertencias)
    # Main API /api/analizar passes only motor.advertencias to UI/PDF for Nexo.
    assert not any("Convierte manualmente" in message for message in m.advertencias)
    assert generar_pdf(m, "AUDIT SYNTHETIC", "2025", "Nexo", c.rendimientos).startswith(b"%PDF")


def test_r03_missing_all_acquisition_lots_has_no_taxable_sale():
    """Venta 300 EUR sin lotes: la operación fiscal no figura en los resultados."""
    m = MotorFIFO()
    m.registrar_venta("2025-01-01 10:00:00", "BTC", 1.0, 300.0, "EUR", "EUR", 0.0)
    summary, _pos, operations = _motor_a_json(m)
    assert summary["operaciones_con_resultado"] == 0
    assert summary["resultado_neto"] == 0
    assert not operations
    assert any("no hay lotes" in a for a in m.advertencias)
    assert generar_pdf(m, "AUDIT SYNTHETIC", "2025", "Synthetic", []).startswith(b"%PDF")


def test_r03_insufficient_lots_produce_numerical_gain_anyway():
    """2 BTC vendidos a 400 EUR con lotes solo para 1 BTC: coste parcial."""
    m = _new_motor_with_one_lot()
    m.registrar_venta("2025-01-01 10:00:00", "BTC", 2.0, 400.0, "EUR", "EUR", 0.0)
    r = m.resultados[0]
    assert r.inventario_incompleto is True
    assert r.precio_coste == 100.0
    assert r.ganancia_perdida == 300.0
    assert any("inventario insuficiente" in a for a in m.advertencias)
    assert _motor_a_json(m)[0]["resultado_neto"] == 300.0
    assert generar_pdf(m, "AUDIT SYNTHETIC", "2025", "Synthetic", []).startswith(b"%PDF")


def test_r04_uphold_brave_reward_lot_zero_cost_and_unknown_eur_income(tmp_path):
    """Oráculo con valor en fecha de abono conocido: 10 EUR por 1 BAT.

    CSV de Uphold no proporciona ese FMV; se prueba que hoy aparece 0,
    el PDF se genera, y el coste de la futura venta queda distorsionado.
    """
    columns = [
        "Date", "Status", "Type", "Origin", "Origin Currency",
        "Destination Currency", "Origin Amount", "Destination Amount",
        "Fee Amount", "Fee Currency", "Id",
    ]
    rows = [
        {
            "Date": "Fri Jan 10 2025 10:00:00 GMT+0000",
            "Status": "completed", "Type": "in", "Origin": "uphold",
            "Origin Currency": "BAT", "Destination Currency": "BAT",
            "Origin Amount": "1", "Destination Amount": "1",
            "Fee Amount": "0", "Fee Currency": "BAT", "Id": "reward-synthetic",
        },
        {
            "Date": "Sat Jan 11 2025 10:00:00 GMT+0000",
            "Status": "completed", "Type": "transfer", "Origin": "",
            "Origin Currency": "BAT", "Destination Currency": "EUR",
            "Origin Amount": "1", "Destination Amount": "25",
            "Fee Amount": "0", "Fee Currency": "EUR", "Id": "sell-synthetic",
        },
    ]
    c = ClasificadorUphold(_write_csv(tmp_path, "synthetic_uphold.csv", columns, rows)).clasificar()
    m = _pipeline_motor(c)
    assert len(c.rendimientos) == 1
    assert c.rendimientos[0].valor_eur == 0.0
    assert m.resultados[0].precio_coste == 0.0
    assert m.resumen_fiscal()["resultado_neto"] == 25.0
    assert m.resumen_fiscal()["resultado_neto"] != 15.0
    assert any("no provee valor EUR" in a for a in c.advertencias)
    assert not m.advertencias
    assert generar_pdf(m, "AUDIT SYNTHETIC", "2025", "Uphold", c.rendimientos).startswith(b"%PDF")
