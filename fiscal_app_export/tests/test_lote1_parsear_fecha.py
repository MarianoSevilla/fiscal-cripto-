"""
LOTE 1 — Tarea 4: soporte de fechas con milisegundos en MotorFIFO._parsear_fecha.

Antes solo se aceptaban 4 formatos sin fracción de segundo; un CSV con
timestamps tipo '2024-03-15 10:30:45.123' (str(pandas.Timestamp) cuando el
export trae milisegundos) lanzaba ValueError → error 500 genérico.

Cobertura:
  · compatibilidad total con los 4 formatos históricos
  · milisegundos y microsegundos (espacio y 'T')
  · ISO-8601 con offset (+00:00) y sufijo 'Z' → datetime naive
  · cadenas inválidas siguen lanzando ValueError
"""

import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from motor_fifo import MotorFIFO

_parsear = MotorFIFO._parsear_fecha


# ── Compatibilidad con los formatos históricos ────────────────────────────────

@pytest.mark.parametrize("texto,esperado", [
    ("2024-03-15 10:30:45", datetime(2024, 3, 15, 10, 30, 45)),
    ("2024-03-15",          datetime(2024, 3, 15)),
    ("15/03/2024 10:30:45", datetime(2024, 3, 15, 10, 30, 45)),
    ("15/03/2024",          datetime(2024, 3, 15)),
    ("  2024-03-15 10:30:45  ", datetime(2024, 3, 15, 10, 30, 45)),  # strip
])
def test_formatos_historicos(texto, esperado):
    assert _parsear(texto) == esperado


# ── Fechas reales de exchanges con fracción de segundo ───────────────────────

@pytest.mark.parametrize("texto,esperado", [
    # str(pandas.Timestamp) con milisegundos (Binance con format="mixed")
    ("2024-03-15 10:30:45.123",    datetime(2024, 3, 15, 10, 30, 45, 123000)),
    # microsegundos completos
    ("2024-03-15 10:30:45.123456", datetime(2024, 3, 15, 10, 30, 45, 123456)),
    # variante dd/mm con milisegundos
    ("15/03/2024 10:30:45.500",    datetime(2024, 3, 15, 10, 30, 45, 500000)),
    # ISO-8601 con 'T' (exports de Coinbase/Uphold re-procesados)
    ("2024-03-15T10:30:45",        datetime(2024, 3, 15, 10, 30, 45)),
    ("2024-03-15T10:30:45.123",    datetime(2024, 3, 15, 10, 30, 45, 123000)),
])
def test_fechas_con_fraccion_de_segundo(texto, esperado):
    assert _parsear(texto) == esperado


# ── ISO-8601 con zona horaria → naive ─────────────────────────────────────────

@pytest.mark.parametrize("texto,esperado", [
    ("2024-03-15T10:30:45+00:00",     datetime(2024, 3, 15, 10, 30, 45)),
    ("2024-03-15T10:30:45.123+00:00", datetime(2024, 3, 15, 10, 30, 45, 123000)),
    ("2024-03-15T10:30:45Z",          datetime(2024, 3, 15, 10, 30, 45)),
    ("2024-03-15T10:30:45.123Z",      datetime(2024, 3, 15, 10, 30, 45, 123000)),
])
def test_iso_con_timezone_devuelve_naive(texto, esperado):
    dt = _parsear(texto)
    assert dt == esperado
    assert dt.tzinfo is None, "el motor trabaja con datetimes naive"


# ── Inválidas siguen fallando ─────────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "no-es-fecha",
    "2024/03/15 10:30:45",   # separador no soportado (igual que antes)
    "32/13/2024",
    "",
])
def test_invalidas_lanzan_valueerror(texto):
    with pytest.raises(ValueError):
        _parsear(texto)


# ── Integración mínima con el motor ──────────────────────────────────────────

def test_motor_acepta_compra_y_venta_con_milisegundos():
    """El caso que antes provocaba el 500: operación con timestamp .123."""
    motor = MotorFIFO()
    motor.registrar_compra(
        fecha="2024-03-15 10:30:45.123", activo="BTC", cantidad=1.0,
        importe=30000.0, contraparte="EUR", fee_activo="EUR", fee_cantidad=0.0,
    )
    motor.registrar_venta(
        fecha="2024-06-20 09:15:30.456", activo="BTC", cantidad=1.0,
        importe=35000.0, contraparte="EUR", fee_activo="EUR", fee_cantidad=0.0,
    )
    assert len(motor.resultados) == 1
    assert motor.resultados[0].ganancia_perdida == pytest.approx(5000.0)
