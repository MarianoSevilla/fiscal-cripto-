"""
Tests para la detección y rechazo de formatos Binance incorrectos o alterados.

Cubre Micro-Sprint A (tipos incompatibles con FIFO) y Micro-Sprint B (archivos alterados):

  Sprint A — _detectar_formato_binance:
    1. Fiat Deposit History → devuelve "fiat_deposit"
    2. Spot Orders History  → devuelve "spot_orders"
    3. TX History ES (ID de usuario) → devuelve "tx" (regresión)
    4. TX History EN (User ID)        → devuelve "tx" (regresión)

  Sprint A — BinanceUserError:
    5. code="fiat_deposit_history", category="user_error"
    6. code="spot_orders_history",  category="user_error"

  Sprint B — archivos alterados:
    7. Primera línea con "www.binance.com" → devuelve "altered_csv"
    8. Separador ";" dominante             → devuelve "altered_csv"
"""

import sys
import os
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import _detectar_formato_binance, BinanceUserError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _csv_file(tmp_path, contenido: str, nombre: str = "binance.csv") -> str:
    p = tmp_path / nombre
    p.write_text(textwrap.dedent(contenido).strip(), encoding="utf-8")
    return str(p)


# ── Sprint A: _detectar_formato_binance ───────────────────────────────────────

def test_detectar_fiat_deposit_history(tmp_path):
    """Fiat Deposit History tiene 'Importe de depósito' → debe devolver 'fiat_deposit'."""
    csv = "Fecha,Importe de depósito,Moneda,Método de pago,Estado\n2024-01-01,100.00,EUR,Tarjeta,Completado\n"
    assert _detectar_formato_binance(_csv_file(tmp_path, csv)) == "fiat_deposit"


def test_detectar_spot_orders_history(tmp_path):
    """Spot Orders History tiene 'Número de pedido' → debe devolver 'spot_orders'."""
    csv = "Fecha,Número de pedido,Par de trading,Tipo,Precio,Cantidad,Total de trading\n2024-01-01,123456,BTCEUR,COMPRAR,30000,0.01,300\n"
    assert _detectar_formato_binance(_csv_file(tmp_path, csv)) == "spot_orders"


def test_detectar_tx_history_es(tmp_path):
    """TX History ES tiene 'ID de usuario' → debe seguir devolviendo 'tx' (sin regresión)."""
    csv = "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n123,2024-01-01 10:00:00,Spot,Transaction Buy,BTC,0.01,\n"
    assert _detectar_formato_binance(_csv_file(tmp_path, csv)) == "tx"


def test_detectar_tx_history_en(tmp_path):
    """TX History EN tiene 'User ID' → debe seguir devolviendo 'tx' (sin regresión)."""
    csv = "User ID,Time,Account,Operation,Coin,Change,Remark\n123,2024-01-01 10:00:00,Spot,Transaction Buy,BTC,0.01,\n"
    assert _detectar_formato_binance(_csv_file(tmp_path, csv)) == "tx"


# ── Sprint A: atributos de BinanceUserError ───────────────────────────────────

def test_binance_user_error_fiat_deposit_attrs():
    """BinanceUserError fiat_deposit_history tiene category y code correctos."""
    exc = BinanceUserError("fiat_deposit_history", "Mensaje de prueba")
    assert exc.category == "user_error"
    assert exc.code == "fiat_deposit_history"
    assert isinstance(exc, ValueError)


def test_binance_user_error_spot_orders_attrs():
    """BinanceUserError spot_orders_history tiene category y code correctos."""
    exc = BinanceUserError("spot_orders_history", "Mensaje de prueba")
    assert exc.category == "user_error"
    assert exc.code == "spot_orders_history"
    assert isinstance(exc, ValueError)


# ── Sprint B: archivos alterados ──────────────────────────────────────────────

def test_detectar_altered_csv_metadata_web(tmp_path):
    """Primera línea con 'www.binance.com' (metadata de página web) → 'altered_csv'."""
    csv = "www.binance.com;Page 1/12;;;;;;\nFecha;Tiempo;Cuenta;Operación;Moneda;Cambio;Observación\n"
    assert _detectar_formato_binance(_csv_file(tmp_path, csv)) == "altered_csv"


def test_detectar_altered_csv_separador_semicolon(tmp_path):
    """CSV con separador ';' sin metadata web → 'altered_csv' por separador no estándar."""
    csv = "Tiempo;Operación;Moneda;Cambio;Cuenta\n2024-01-01 10:00:00;Transaction Buy;BTC;0.01;Spot\n"
    assert _detectar_formato_binance(_csv_file(tmp_path, csv)) == "altered_csv"
