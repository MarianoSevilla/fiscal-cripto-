"""
Tests unitarios para ClasificadorBitvavo.

FASE 2: KeyError 'Date' — normalización y validación de columnas.
Cubre:
  - CSV con columnas canónicas (formato estándar Bitvavo)
  - CSV con columnas en minúsculas
  - CSV con alias de columna (e.g. "Transaction Date" en lugar de "Date")
  - CSV sin columnas obligatorias → ValueError claro
  - Clasificación basic buy/sell/staking con columnas canónicas
"""

import textwrap
import pytest
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from clasificador_bitvavo import (
    ClasificadorBitvavo,
    _normalizar_columnas,
    _validar_columnas,
    _COLS_OBLIGATORIAS,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _csv_to_tmpfile(csv_text: str, tmp_path, name="bitvavo_test.csv"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(csv_text).strip(), encoding="utf-8")
    return str(p)


# Cabecera canónica de Bitvavo (formato estándar)
HEADER_CANONICAL = (
    "Timezone,Date,Time,Type,Currency,Amount,Quote Currency,"
    "Quote Price,Received / Paid Currency,Received / Paid Amount,"
    "Fee currency,Fee amount,Status,Transaction ID,Address\n"
)

# Fila buy de ejemplo: compra 0.01 BTC a 30000 EUR, fee 0.30 EUR
ROW_BUY_BTC = (
    "UTC,2024-06-15,10:00:00,buy,BTC,0.01,EUR,"
    "30000,EUR,-300,EUR,-0.30,Completed,txn001,\n"
)

# Fila sell: venta 0.005 BTC a 32000 EUR
ROW_SELL_BTC = (
    "UTC,2024-09-01,12:00:00,sell,BTC,0.005,EUR,"
    "32000,EUR,160,EUR,-0.16,Completed,txn002,\n"
)

# Fila staking
ROW_STAKING_ETH = (
    "UTC,2024-07-01,08:00:00,staking,ETH,0.001,EUR,"
    "3500,,,,,Distributed,txn003,\n"
)


# ── Test 1: columnas canónicas — clasificación básica ─────────────────────────

def test_buy_btc_columnas_canonicas(tmp_path):
    """CSV con columnas canónicas: buy BTC debe generar una COMPRA."""
    csv = HEADER_CANONICAL + ROW_BUY_BTC
    c = ClasificadorBitvavo(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.compraventas) == 1
    cv = c.compraventas[0]
    assert cv.tipo    == "COMPRA"
    assert cv.activo  == "BTC"
    assert len(c.desconocidas) == 0


def test_sell_btc_columnas_canonicas(tmp_path):
    """sell BTC debe generar una VENTA."""
    csv = HEADER_CANONICAL + ROW_SELL_BTC
    c = ClasificadorBitvavo(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.compraventas) == 1
    cv = c.compraventas[0]
    assert cv.tipo   == "VENTA"
    assert cv.activo == "BTC"


def test_staking_eth_columnas_canonicas(tmp_path):
    """staking ETH debe generar un RENDIMIENTO."""
    csv = HEADER_CANONICAL + ROW_STAKING_ETH
    c = ClasificadorBitvavo(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.rendimientos) == 1
    r = c.rendimientos[0]
    assert r.activo  == "ETH"
    assert r.subtipo == "staking"


# ── Test 2: columnas en minúsculas ────────────────────────────────────────────

def test_columnas_minusculas(tmp_path):
    """
    Export con columnas en minúsculas: 'date', 'time', 'type', etc.
    Debe funcionar igual que con columnas canónicas — el KeyError 'Date'
    que ocurría en producción queda corregido.
    """
    header_lower = (
        "timezone,date,time,type,currency,amount,quote currency,"
        "quote price,received / paid currency,received / paid amount,"
        "fee currency,fee amount,status,transaction id,address\n"
    )
    row = (
        "UTC,2024-06-15,10:00:00,buy,BTC,0.01,EUR,"
        "30000,EUR,-300,EUR,-0.30,Completed,txn001,\n"
    )
    csv = header_lower + row
    c = ClasificadorBitvavo(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.compraventas) == 1
    assert c.compraventas[0].tipo == "COMPRA"


# ── Test 3: alias de columna Date ─────────────────────────────────────────────

def test_alias_trade_date(tmp_path):
    """
    Columna 'Trade Date' en lugar de 'Date' — alias reconocido.
    Verifica que _normalizar_columnas lo mapea al canónico.
    """
    header_alias = (
        "Timezone,Trade Date,Time,Type,Currency,Amount,Quote Currency,"
        "Quote Price,Received / Paid Currency,Received / Paid Amount,"
        "Fee currency,Fee amount,Status,Transaction ID,Address\n"
    )
    csv = header_alias + ROW_BUY_BTC
    c = ClasificadorBitvavo(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    assert len(c.compraventas) == 1


# ── Test 4: columnas obligatorias faltantes → error claro ────────────────────

def test_columnas_obligatorias_faltantes_lanza_error(tmp_path):
    """
    CSV sin columna 'Date' (ni alias conocido): debe lanzar ValueError
    con mensaje que identifica las columnas faltantes.
    """
    header_roto = "Timezone,Fecha,Hora,Tipo,Moneda,Importe\n"
    row_rota    = "UTC,2024-06-15,10:00:00,buy,BTC,0.01\n"
    csv = header_roto + row_rota

    with pytest.raises(ValueError) as exc_info:
        ClasificadorBitvavo(_csv_to_tmpfile(csv, tmp_path)).clasificar()

    msg = str(exc_info.value)
    assert "obligatorias" in msg.lower() or "Date" in msg
    assert "Bitvavo" in msg


def test_csv_completamente_vacio_lanza_error(tmp_path):
    """CSV con solo una línea de texto sin columnas válidas."""
    csv = "esto no es un CSV válido\n"
    with pytest.raises((ValueError, Exception)):
        ClasificadorBitvavo(_csv_to_tmpfile(csv, tmp_path)).clasificar()


# ── Test 5: normalizar_columnas — test unitario ───────────────────────────────

def test_normalizar_columnas_lowercase():
    """_normalizar_columnas convierte 'date' y 'time' a canónicos."""
    df = pd.DataFrame(columns=["date", "time", "type", "currency", "amount"])
    df_norm = _normalizar_columnas(df)
    assert "Date"     in df_norm.columns
    assert "Time"     in df_norm.columns
    assert "Type"     in df_norm.columns
    assert "Currency" in df_norm.columns
    assert "Amount"   in df_norm.columns


def test_normalizar_columnas_canonicas_no_cambia():
    """Columnas ya canónicas no deben renombrarse."""
    cols_orig = ["Date", "Time", "Type", "Currency", "Amount", "Status"]
    df = pd.DataFrame(columns=cols_orig)
    df_norm = _normalizar_columnas(df)
    assert list(df_norm.columns) == cols_orig


def test_normalizar_columnas_alias_trade_date():
    """'Trade Date' se mapea a 'Date'."""
    df = pd.DataFrame(columns=["Trade Date", "Time", "Type", "Currency", "Amount"])
    df_norm = _normalizar_columnas(df)
    assert "Date" in df_norm.columns
    assert "Trade Date" not in df_norm.columns


# ── Test 6: validar_columnas ──────────────────────────────────────────────────

def test_validar_columnas_ok():
    """DataFrame con todas las obligatorias: no debe lanzar excepción."""
    df = pd.DataFrame(columns=_COLS_OBLIGATORIAS + ["Status"])
    _validar_columnas(df)  # no debe lanzar


def test_validar_columnas_faltantes():
    """DataFrame sin 'Date' y 'Amount': ValueError con ambas listadas."""
    df = pd.DataFrame(columns=["Time", "Type", "Currency"])
    with pytest.raises(ValueError) as exc_info:
        _validar_columnas(df)
    msg = str(exc_info.value)
    assert "Date"   in msg
    assert "Amount" in msg
