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
