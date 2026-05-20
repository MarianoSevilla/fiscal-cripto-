"""
Tests unitarios para modelo721.py

Casos cubiertos:
  1. CSV con compras y saldo final positivo → genera entrada 721.
  2. CSV con saldo cero a 31 diciembre → no genera activo declarable.
  3. Exchange extranjero conocido → marcado como potencialmente extranjero.
  4. Exchange español (Bit2Me) → extranjero=False, potencialmente_obligado=False.
  5. Falta país del custodio (exchange desconocido) → advertencia generada.
  6. Falta valoración EUR → advertencia siempre presente.
  7. La función no rompe el flujo FIFO actual.
  8. Múltiples activos → todos aparecen en la entrada.
  9. Resultado siempre JSON-serializable (sin Decimal ni datetime).
 10. informe_orientativo siempre True.
 11-22. Snapshot 31/12: posicion_a_fecha() correcta para el Modelo 721.
"""

import json
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from motor_fifo import MotorFIFO
from modelo721 import generar_datos_modelo_721, EXCHANGES_CATALOG, DENOMINACIONES_CRIPTO


# ── Helpers ───────────────────────────────────────────────────────────────────

def _motor_con_compra(activo, cantidad, importe,
                      fecha="2025-06-01 00:00:00", contraparte="EUR"):
    m = MotorFIFO()
    m.registrar_compra(
        fecha=fecha, activo=activo, cantidad=cantidad,
        importe=importe, contraparte=contraparte,
        fee_activo="", fee_cantidad=0.0,
    )
    return m


# ── Test 1: Saldo positivo → genera entrada ───────────────────────────────────

def test_compra_sin_venta_genera_entrada_721():
    """0.5 BTC comprado, sin vender → aparece en activos del 721."""
    m = _motor_con_compra("BTC", 0.5, 30_000.0)
    r = generar_datos_modelo_721(m, "binance", 2025)

    assert r["modelo"] == "721"
    assert r["ejercicio"] == 2025
    assert len(r["exchanges"]) == 1

    activos = r["exchanges"][0]["activos"]
    assert len(activos) == 1
    btc = activos[0]
    assert btc["activo"] == "BTC"
    assert btc["cantidad"] == "0.500000"
    assert btc["denominacion"] == "Bitcoin"
    assert btc["siglas"] == "BTC"


def test_cantidad_se_serializa_con_6_decimales():
    """Cantidad siempre tiene 6 decimales en la salida."""
    m = _motor_con_compra("ETH", 1.123456789, 3_000.0)
    r = generar_datos_modelo_721(m, "kraken", 2025)
    cantidad = r["exchanges"][0]["activos"][0]["cantidad"]
    # Decimal truncado/redondeado a 6 decimales
    assert "." in cantidad
    decimales = cantidad.split(".")[1]
    assert len(decimales) <= 6


# ── Test 2: Saldo cero a 31/12 → sin activos declarables ─────────────────────

def test_saldo_cero_no_genera_activo():
    """Compra 1 BTC + venta 1 BTC → posición cero → exchanges=[], obligado=False."""
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2025-03-01 00:00:00", activo="BTC", cantidad=1.0,
        importe=50_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2025-09-01 00:00:00", activo="BTC", cantidad=1.0,
        importe=55_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )

    r = generar_datos_modelo_721(m, "bitvavo", 2025)

    assert r["potencialmente_obligado"] is False
    assert r["exchanges"] == []
    assert any("No se detectan" in adv for adv in r["advertencias"])


def test_motor_vacio_no_genera_activos():
    """Motor sin ninguna transacción → sin activos declarables."""
    r = generar_datos_modelo_721(MotorFIFO(), "coinbase", 2024)
    assert r["potencialmente_obligado"] is False
    assert r["exchanges"] == []


# ── Test 3: Exchange extranjero conocido ──────────────────────────────────────

def test_bitvavo_extranjero_nl():
    """Bitvavo → extranjero=True, codigo_pais_iso='NL', potencialmente_obligado=True."""
    m = _motor_con_compra("ETH", 2.0, 4_000.0)
    r = generar_datos_modelo_721(m, "bitvavo", 2025)

    exc = r["exchanges"][0]
    assert exc["extranjero"] is True
    assert exc["codigo_pais_iso"] == "NL"
    assert r["potencialmente_obligado"] is True


def test_kraken_extranjero_us():
    """Kraken → codigo_pais_iso='US'."""
    m = _motor_con_compra("SOL", 50.0, 8_000.0)
    r = generar_datos_modelo_721(m, "kraken", 2025)
    assert r["exchanges"][0]["codigo_pais_iso"] == "US"
    assert r["potencialmente_obligado"] is True


def test_coinbase_extranjero_us():
    """Coinbase → codigo_pais_iso='US'."""
    m = _motor_con_compra("BTC", 0.1, 5_000.0)
    r = generar_datos_modelo_721(m, "coinbase", 2025)
    assert r["exchanges"][0]["codigo_pais_iso"] == "US"


# ── Test 4: Exchange español → NO extranjero ─────────────────────────────────

def test_bit2me_espanol_no_obligado():
    """Bit2Me (ES) → extranjero=False → potencialmente_obligado=False."""
    m = _motor_con_compra("BTC", 0.5, 25_000.0)
    r = generar_datos_modelo_721(m, "bit2me", 2025)

    exc = r["exchanges"][0]
    assert exc["extranjero"] is False
    assert exc["codigo_pais_iso"] == "ES"
    assert r["potencialmente_obligado"] is False


# ── Test 5: Falta país del custodio → advertencia ────────────────────────────

def test_exchange_desconocido_advertencia_pais():
    """Exchange no catalogado → codigo_pais_iso=None + advertencia de revisión."""
    m = _motor_con_compra("SOL", 10.0, 1_500.0)
    r = generar_datos_modelo_721(m, "exchange_nuevo_xyz", 2025)

    exc = r["exchanges"][0]
    assert exc["codigo_pais_iso"] is None
    assert exc["requiere_revision"] is True

    all_warnings = r["advertencias"] + [
        a for act in exc["activos"] for a in act["advertencias"]
    ]
    texto = " ".join(all_warnings).lower()
    assert "no reconocido" in texto or "no confirmado" in texto


def test_binance_requiere_revision_pais():
    """Binance tiene entidad ambigua → codigo_pais_iso=None, requiere_revision=True."""
    m = _motor_con_compra("BTC", 1.0, 50_000.0)
    r = generar_datos_modelo_721(m, "binance", 2025)

    exc = r["exchanges"][0]
    assert exc["codigo_pais_iso"] is None
    assert exc["requiere_revision"] is True


# ── Test 6: Falta valoración EUR → advertencia siempre ───────────────────────

def test_valor_eur_siempre_none_con_advertencia():
    """Sin fuente de precio externo, valor_eur=None + advertencia para cada activo."""
    m = _motor_con_compra("ETH", 3.0, 6_000.0)
    r = generar_datos_modelo_721(m, "kraken", 2025)

    for activo in r["exchanges"][0]["activos"]:
        assert activo["valor_eur"] is None
        assert activo["requiere_revision"] is True
        texto = " ".join(activo["advertencias"]).lower()
        assert "valor" in texto or "precio" in texto


def test_stablecoin_advertencia_especifica():
    """USDT genera advertencia específica de tipo de cambio EUR/USD."""
    m = _motor_con_compra("USDT", 1_000.0, 950.0)
    r = generar_datos_modelo_721(m, "binance", 2025)

    activos = r["exchanges"][0]["activos"]
    usdt = next(a for a in activos if a["activo"] == "USDT")
    texto = " ".join(usdt["advertencias"]).lower()
    assert "stablecoin" in texto or "eur/usd" in texto or "bce" in texto


# ── Test 7: No rompe el flujo FIFO ───────────────────────────────────────────

def test_no_muta_motor_fifo():
    """generar_datos_modelo_721 es de solo lectura: no muta el motor FIFO."""
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2025-01-10 00:00:00", activo="BTC", cantidad=1.0,
        importe=40_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2025-06-01 00:00:00", activo="BTC", cantidad=0.5,
        importe=30_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )

    n_resultados_antes   = len(m.resultados)
    n_advertencias_antes = len(m.advertencias)
    posicion_antes_qty   = m.posicion_actual()[0].cantidad_total

    # Llamar a la función 721
    _ = generar_datos_modelo_721(m, "bitvavo", 2025)

    # El motor no ha cambiado
    assert len(m.resultados)   == n_resultados_antes
    assert len(m.advertencias) == n_advertencias_antes
    assert m.posicion_actual()[0].cantidad_total == posicion_antes_qty

    # Ganancia del 0.5 BTC vendido intacta: 30000 - 20000 = 10000
    assert m.resultados[0].ganancia_perdida == pytest.approx(10_000.0)


# ── Test 8: Múltiples activos ─────────────────────────────────────────────────

def test_multiples_activos_todos_presentes():
    """BTC + ETH + SOL comprados → los tres aparecen en la entrada 721."""
    m = MotorFIFO()
    for activo, qty, importe in [("BTC", 0.5, 25_000.0), ("ETH", 5.0, 15_000.0), ("SOL", 100.0, 20_000.0)]:
        m.registrar_compra(
            fecha="2025-02-01 00:00:00", activo=activo, cantidad=qty,
            importe=importe, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
        )

    r = generar_datos_modelo_721(m, "kraken", 2025)
    tickers = {a["activo"] for a in r["exchanges"][0]["activos"]}

    assert "BTC" in tickers
    assert "ETH" in tickers
    assert "SOL" in tickers
    assert len(tickers) == 3


# ── Test 9: JSON-serializable ─────────────────────────────────────────────────

def test_resultado_json_serializable():
    """El dict de salida no debe contener Decimal, datetime ni tipos no serializables."""
    m = _motor_con_compra("BTC", 1.0, 50_000.0)
    r = generar_datos_modelo_721(m, "bitvavo", 2025)

    json_str  = json.dumps(r)
    reparsed  = json.loads(json_str)

    assert reparsed["modelo"]    == "721"
    assert reparsed["ejercicio"] == 2025
    assert isinstance(reparsed["exchanges"][0]["activos"][0]["cantidad"], str)


# ── Test 10: informe_orientativo siempre True ─────────────────────────────────

def test_informe_orientativo_siempre_true():
    """El campo informe_orientativo debe ser True en cualquier escenario."""
    casos = [
        (_motor_con_compra("BTC", 1.0, 50_000.0), "binance"),
        (_motor_con_compra("ETH", 5.0, 10_000.0), "bit2me"),
        (MotorFIFO(),                              "coinbase"),
    ]
    for motor, exchange in casos:
        r = generar_datos_modelo_721(motor, exchange, 2025)
        assert r["informe_orientativo"] is True, (
            f"informe_orientativo debe ser True para exchange={exchange}"
        )


# ── Test 11: coste_base_fifo refleja el coste de adquisición ─────────────────

def test_coste_base_fifo_correcto():
    """El coste_base_fifo debe coincidir con el coste de compra registrado."""
    m = _motor_con_compra("BTC", 2.0, 80_000.0)  # 40.000 EUR/BTC
    r = generar_datos_modelo_721(m, "kraken", 2025)

    btc = r["exchanges"][0]["activos"][0]
    # coste_base_fifo debe ser 80000.00 (2 BTC × 40000)
    assert float(btc["coste_base_fifo"]) == pytest.approx(80_000.0)


# ── Test 12: Denominación de activo desconocido ───────────────────────────────

def test_activo_desconocido_usa_ticker_y_advierte():
    """Un ticker no catalogado usa el propio ticker como denominación + advertencia."""
    m = _motor_con_compra("ZZZNEWCOIN", 1000.0, 500.0)
    r = generar_datos_modelo_721(m, "kraken", 2025)

    activo = r["exchanges"][0]["activos"][0]
    assert activo["denominacion"] == "ZZZNEWCOIN"
    assert any("denominación" in adv.lower() or "no reconocida" in adv.lower()
               for adv in activo["advertencias"])


# ══════════════════════════════════════════════════════════════════════════════
# Tests 13-24: Snapshot 31/12 (posicion_a_fecha)
#
# Criterio de aceptación: un CSV con operaciones de 2024 y 2025 debe generar
# para ejercicio 2024 exactamente el saldo a 31/12/2024, no el saldo actual.
# ══════════════════════════════════════════════════════════════════════════════

# ── Helpers específicos de snapshot ──────────────────────────────────────────

def _motor_compra_venta(activo, fecha_c, qty_c, importe_c, fecha_v=None, qty_v=None, importe_v=None):
    """Motor con una compra y opcionalmente una venta del mismo activo."""
    m = MotorFIFO()
    m.registrar_compra(
        fecha=fecha_c, activo=activo, cantidad=qty_c,
        importe=importe_c, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    if fecha_v is not None:
        m.registrar_venta(
            fecha=fecha_v, activo=activo, cantidad=qty_v,
            importe=importe_v, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
        )
    return m


# ── Test 13: Compra en 2024, venta en 2025 → aparece íntegro en snapshot 2024 ─

def test_snapshot_compra_2024_venta_2025_aparece_integro():
    """Compra 1 BTC en 2024, venta en 2025 → snapshot 2024 muestra 1.0 BTC."""
    m = _motor_compra_venta(
        "BTC",
        fecha_c="2024-03-15 00:00:00", qty_c=1.0, importe_c=50_000.0,
        fecha_v="2025-02-10 00:00:00", qty_v=1.0, importe_v=60_000.0,
    )
    r = generar_datos_modelo_721(m, "kraken", 2024)

    activos = r["exchanges"][0]["activos"]
    assert len(activos) == 1
    btc = activos[0]
    assert btc["activo"] == "BTC"
    assert float(btc["cantidad"]) == pytest.approx(1.0, abs=1e-6)


# ── Test 14: Compra en 2025 → no aparece en snapshot 2024 ────────────────────

def test_snapshot_compra_2025_ausente_en_ejercicio_2024():
    """Compra ETH en enero 2025 → no declarable en ejercicio 2024."""
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2025-01-15 00:00:00", activo="ETH", cantidad=3.0,
        importe=9_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    r = generar_datos_modelo_721(m, "kraken", 2024)

    assert r["exchanges"] == []
    assert r["potencialmente_obligado"] is False


# ── Test 15: Venta en 2024 reduce posición en snapshot 2024 ──────────────────

def test_snapshot_venta_2024_reduce_posicion():
    """Compra 1 BTC 2024-01, vende 0.3 en 2024-06 → snapshot 2024 = 0.7 BTC."""
    m = _motor_compra_venta(
        "BTC",
        fecha_c="2024-01-01 00:00:00", qty_c=1.0, importe_c=40_000.0,
        fecha_v="2024-06-15 00:00:00", qty_v=0.3, importe_v=15_000.0,
    )
    r = generar_datos_modelo_721(m, "kraken", 2024)

    btc = r["exchanges"][0]["activos"][0]
    assert float(btc["cantidad"]) == pytest.approx(0.7, abs=1e-6)


# ── Test 16: Venta en 2025 NO reduce posición en snapshot 2024 ───────────────

def test_snapshot_venta_2025_no_reduce_posicion_2024():
    """Compra 1 BTC 2024-01, venta 0.5 en 2025-03 → snapshot 2024 = 1.0 BTC."""
    m = _motor_compra_venta(
        "BTC",
        fecha_c="2024-01-01 00:00:00", qty_c=1.0, importe_c=40_000.0,
        fecha_v="2025-03-01 00:00:00", qty_v=0.5, importe_v=30_000.0,
    )
    r = generar_datos_modelo_721(m, "kraken", 2024)

    btc = r["exchanges"][0]["activos"][0]
    assert float(btc["cantidad"]) == pytest.approx(1.0, abs=1e-6)


# ── Test 17: Múltiples lotes del mismo activo, ventas mixtas ─────────────────

def test_snapshot_multiples_lotes_ventas_mixtas():
    """
    2 lotes de ETH en 2024, una venta parcial en 2024, otra en 2025.
    snapshot 2024 = lote1 + lote2 - venta_2024.
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-01-01 00:00:00", activo="ETH", cantidad=1.0,
        importe=2_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_compra(
        fecha="2024-06-01 00:00:00", activo="ETH", cantidad=2.0,
        importe=5_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2024-09-01 00:00:00", activo="ETH", cantidad=0.5,
        importe=1_500.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2025-01-15 00:00:00", activo="ETH", cantidad=1.0,
        importe=3_500.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )

    r = generar_datos_modelo_721(m, "kraken", 2024)

    eth = r["exchanges"][0]["activos"][0]
    # 1.0 + 2.0 − 0.5 (sell 2024) = 2.5; la venta de 2025 no cuenta
    assert float(eth["cantidad"]) == pytest.approx(2.5, abs=1e-6)


# ── Test 18: Posición cero a 31/12 → no declarable ───────────────────────────

def test_snapshot_posicion_cero_31_diciembre():
    """Compra + venta total en 2024 → posición 0 a 31/12/2024, sin activo declarable."""
    m = _motor_compra_venta(
        "SOL",
        fecha_c="2024-01-10 00:00:00", qty_c=100.0, importe_c=15_000.0,
        fecha_v="2024-11-30 00:00:00", qty_v=100.0, importe_v=18_000.0,
    )
    r = generar_datos_modelo_721(m, "kraken", 2024)

    assert r["exchanges"] == []
    assert r["potencialmente_obligado"] is False


# ── Test 19: Stablecoin — snapshot correcto ───────────────────────────────────

def test_snapshot_stablecoin_cantidad_correcta():
    """5.000 USDC comprados en 2024, 1.000 vendidos en 2025 → snapshot 2024 = 5.000."""
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-05-01 00:00:00", activo="USDC", cantidad=5_000.0,
        importe=4_700.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2025-02-01 00:00:00", activo="USDC", cantidad=1_000.0,
        importe=940.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )

    r = generar_datos_modelo_721(m, "binance", 2024)

    usdc = r["exchanges"][0]["activos"][0]
    assert usdc["activo"] == "USDC"
    assert float(usdc["cantidad"]) == pytest.approx(5_000.0, abs=1e-3)


# ── Test 20: Swap en 2024, venta del activo recibido en 2025 ─────────────────

def test_snapshot_swap_2024_venta_2025():
    """
    Compra BTC 2024-01, swap BTC→ETH en 2024-06.
    Venta de parte del ETH en 2025.
    Snapshot 2024: BTC=0, ETH=2 (íntegro, venta es de 2025).
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-01-01 00:00:00", activo="BTC", cantidad=0.1,
        importe=4_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_swap(
        fecha="2024-06-01 00:00:00",
        activo_entregado="BTC", cantidad_entregada=0.1,
        activo_recibido="ETH",  cantidad_recibida=2.0,
    )
    m.registrar_venta(
        fecha="2025-01-10 00:00:00", activo="ETH", cantidad=1.0,
        importe=3_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )

    r = generar_datos_modelo_721(m, "kraken", 2024)
    activos_dict = {a["activo"]: a for a in r["exchanges"][0]["activos"]}

    # BTC fue swapeado dentro de 2024: ya no existe en el inventario a 31/12/2024
    assert "BTC" not in activos_dict
    # ETH recibido en 2024: 2.0 unidades; la venta es de 2025
    assert "ETH" in activos_dict
    assert float(activos_dict["ETH"]["cantidad"]) == pytest.approx(2.0, abs=1e-6)


# ── Test 21: Operaciones en 2023, 2024 y 2025 — snapshot exacto a 31/12/2024 ─

def test_snapshot_operaciones_mixtas_tres_ejercicios():
    """
    Lote histórico 2023, compras y ventas en 2024, operaciones en 2025.
    Snapshot 2024 = 0.5 (2023) + 0.3 (2024) − 0.2 (venta 2024) = 0.6 BTC.
    El lote de 2025 y la venta de 2025 no afectan.
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2023-05-01 00:00:00", activo="BTC", cantidad=0.5,
        importe=15_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_compra(
        fecha="2024-03-01 00:00:00", activo="BTC", cantidad=0.3,
        importe=12_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2024-09-01 00:00:00", activo="BTC", cantidad=0.2,
        importe=12_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_compra(
        fecha="2025-01-15 00:00:00", activo="BTC", cantidad=0.5,
        importe=25_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2025-06-01 00:00:00", activo="BTC", cantidad=0.4,
        importe=24_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )

    r = generar_datos_modelo_721(m, "kraken", 2024)

    btc = r["exchanges"][0]["activos"][0]
    assert float(btc["cantidad"]) == pytest.approx(0.6, abs=1e-6)


# ── Test 22: Mismo motor → ejercicios distintos dan snapshots distintos ───────

def test_snapshot_mismo_motor_ejercicios_diferentes():
    """
    Motor con compra en 2023 y venta parcial en 2024.
    Ejercicio 2023 → 1.0 BTC.
    Ejercicio 2024 → 0.5 BTC.
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2023-01-01 00:00:00", activo="BTC", cantidad=1.0,
        importe=30_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2024-06-01 00:00:00", activo="BTC", cantidad=0.5,
        importe=25_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )

    r_2023 = generar_datos_modelo_721(m, "kraken", 2023)
    r_2024 = generar_datos_modelo_721(m, "kraken", 2024)

    btc_2023 = r_2023["exchanges"][0]["activos"][0]
    btc_2024 = r_2024["exchanges"][0]["activos"][0]

    assert float(btc_2023["cantidad"]) == pytest.approx(1.0, abs=1e-6)
    assert float(btc_2024["cantidad"]) == pytest.approx(0.5, abs=1e-6)


# ── Test 23: coste_base_fifo correcto en snapshot ─────────────────────────────

def test_snapshot_coste_base_fifo_correcto():
    """
    2 lotes de ETH, venta parcial en 2025 (no afecta snapshot 2024).
    coste_base_fifo a 31/12/2024 = 1.0*2000 + 2.0*2500 = 7000 EUR.
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-01-01 00:00:00", activo="ETH", cantidad=1.0,
        importe=2_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_compra(
        fecha="2024-06-01 00:00:00", activo="ETH", cantidad=2.0,
        importe=5_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2025-03-01 00:00:00", activo="ETH", cantidad=1.5,
        importe=5_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )

    r = generar_datos_modelo_721(m, "bitvavo", 2024)

    eth = r["exchanges"][0]["activos"][0]
    assert float(eth["cantidad"]) == pytest.approx(3.0, abs=1e-6)
    assert float(eth["coste_base_fifo"]) == pytest.approx(7_000.0, abs=0.01)


# ── Test 24: posicion_a_fecha no muta el motor ────────────────────────────────

def test_snapshot_no_muta_motor():
    """
    Llamar a generar_datos_modelo_721 (que usa posicion_a_fecha) no debe
    alterar el inventario ni los resultados del motor original.
    """
    m = MotorFIFO()
    m.registrar_compra(
        fecha="2024-01-01 00:00:00", activo="BTC", cantidad=1.0,
        importe=40_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2024-06-01 00:00:00", activo="BTC", cantidad=0.5,
        importe=30_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )
    m.registrar_venta(
        fecha="2025-02-01 00:00:00", activo="BTC", cantidad=0.3,
        importe=20_000.0, contraparte="EUR", fee_activo="", fee_cantidad=0.0,
    )

    # Capturar estado antes
    qty_restante_antes   = m.inventario["BTC"][0].cantidad_restante
    n_resultados_antes   = len(m.resultados)
    n_advertencias_antes = len(m.advertencias)

    # Llamar al generador 721 (internamente usa posicion_a_fecha)
    _ = generar_datos_modelo_721(m, "binance", 2024)
    _ = generar_datos_modelo_721(m, "binance", 2023)

    # El motor no debe haber cambiado
    assert m.inventario["BTC"][0].cantidad_restante == qty_restante_antes
    assert len(m.resultados)   == n_resultados_antes
    assert len(m.advertencias) == n_advertencias_antes
