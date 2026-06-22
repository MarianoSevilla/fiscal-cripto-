"""
Tests de la separación Ventas / Permutas en el informe PDF FIFO.

Cubren:
  - Clasificación venta vs permuta (cripto→EUR, cripto↔cripto, cripto↔stable).
  - registrar_swap rellena el campo informativo `activo_recibido`.
  - Invariante: totales de ventas + permutas == total patrimonial == neto del motor.
  - Smoke de generar_pdf: mixto / solo ventas / solo permutas sin LayoutError.

NO comprueban el cálculo FIFO en sí (eso vive en test_motor_fifo.py); aquí solo
se verifica que la AGRUPACIÓN para Renta es correcta y que el PDF no rompe.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from motor_fifo import MotorFIFO
from generador_pdf import (
    generar_pdf,
    _clasificar_grupo_renta,
    _particionar_ventas_permutas,
    _totales_grupo,
)


# ── Helpers para construir motores reales ────────────────────────────────────

def _motor_venta_cripto_eur():
    """Compra de BTC y venta posterior por EUR."""
    m = MotorFIFO()
    m.registrar_compra("2024-01-01", "BTC", 1.0, 20000.0, "EUR", "EUR", 0.0)
    m.registrar_venta("2024-06-01", "BTC", 1.0, 30000.0, "EUR", "EUR", 0.0)
    return m


def _motor_permuta_cripto_cripto():
    """Compra de ETH y permuta ETH→BTC (cripto↔cripto)."""
    m = MotorFIFO()
    m.registrar_compra("2024-01-01", "ETH", 10.0, 10000.0, "EUR", "EUR", 0.0)
    m.registrar_swap("2024-06-01", "ETH", 5.0, "BTC", 0.2)
    return m


def _motor_swap_cripto_stable():
    """Compra de ETH y swap ETH→USDT (cripto↔stable → se trata como venta)."""
    m = MotorFIFO()
    m.registrar_compra("2024-01-01", "ETH", 10.0, 10000.0, "EUR", "EUR", 0.0)
    m.registrar_swap("2024-06-01", "ETH", 5.0, "USDT", 6000.0)
    return m


def _motor_mixto():
    m = MotorFIFO()
    m.registrar_compra("2024-01-01", "BTC", 1.0, 20000.0, "EUR", "EUR", 0.0)
    m.registrar_compra("2024-01-02", "ETH", 10.0, 10000.0, "EUR", "EUR", 0.0)
    m.registrar_venta("2024-06-01", "BTC", 0.5, 15000.0, "EUR", "EUR", 0.0)  # venta
    m.registrar_swap("2024-06-02", "ETH", 4.0, "BTC", 0.1)                    # permuta
    m.registrar_swap("2024-06-03", "ETH", 2.0, "USDT", 2500.0)               # venta (stable)
    return m


# ── Clasificación ────────────────────────────────────────────────────────────

def test_venta_cripto_eur_va_a_ventas():
    m = _motor_venta_cripto_eur()
    assert len(m.resultados) == 1
    assert _clasificar_grupo_renta(m.resultados[0]) == "venta"


def test_swap_cripto_cripto_va_a_permutas():
    m = _motor_permuta_cripto_cripto()
    assert len(m.resultados) == 1
    assert _clasificar_grupo_renta(m.resultados[0]) == "permuta"


def test_swap_cripto_stable_va_a_ventas():
    m = _motor_swap_cripto_stable()
    assert len(m.resultados) == 1
    assert _clasificar_grupo_renta(m.resultados[0]) == "venta"


def test_resultado_sin_activo_recibido_se_trata_como_venta():
    """Retrocompatibilidad: un swap sin activo_recibido (resultado antiguo) no
    puede confirmarse como cripto↔cripto → se clasifica conservadoramente como venta."""
    m = _motor_permuta_cripto_cripto()
    r = m.resultados[0]
    r.activo_recibido = ""          # simula un ResultadoFIFO antiguo
    assert _clasificar_grupo_renta(r) == "venta"


# ── Campo informativo activo_recibido ────────────────────────────────────────

def test_registrar_swap_rellena_activo_recibido():
    m = _motor_permuta_cripto_cripto()
    assert m.resultados[0].activo_recibido == "BTC"


def test_registrar_venta_no_pone_activo_recibido():
    m = _motor_venta_cripto_eur()
    assert m.resultados[0].activo_recibido == ""


# ── Invariante de totales ────────────────────────────────────────────────────

def test_totales_ventas_mas_permutas_igual_total_patrimonial():
    m = _motor_mixto()
    ventas, permutas = _particionar_ventas_permutas(m.resultados)
    _, _, _, gv = _totales_grupo(ventas)
    _, _, _, gp = _totales_grupo(permutas)

    neto_motor = m.resumen_fiscal()["resultado_neto"]
    # El neto del motor está redondeado a 2 decimales; comparamos con tolerancia.
    assert round(gv + gp, 2) == neto_motor
    # Y no se ha perdido ni duplicado ninguna operación al particionar.
    assert len(ventas) + len(permutas) == len(m.resultados)


def test_particion_preserva_todas_las_operaciones():
    m = _motor_mixto()
    ventas, permutas = _particionar_ventas_permutas(m.resultados)
    assert len(ventas) == 2      # venta BTC + swap ETH→USDT
    assert len(permutas) == 1    # swap ETH→BTC


# ── Smoke de generación de PDF ───────────────────────────────────────────────

def test_pdf_mixto_no_lanza_layout_error():
    m = _motor_mixto()
    pdf = generar_pdf(m, "Tester", "2024", "Binance")
    assert isinstance(pdf, (bytes, bytearray)) and len(pdf) > 1000


def test_pdf_solo_ventas_funciona():
    m = _motor_venta_cripto_eur()
    pdf = generar_pdf(m, "Tester", "2024", "Binance")
    assert isinstance(pdf, (bytes, bytearray)) and len(pdf) > 1000


def test_pdf_solo_permutas_funciona():
    m = _motor_permuta_cripto_cripto()
    pdf = generar_pdf(m, "Tester", "2024", "Binance")
    assert isinstance(pdf, (bytes, bytearray)) and len(pdf) > 1000
