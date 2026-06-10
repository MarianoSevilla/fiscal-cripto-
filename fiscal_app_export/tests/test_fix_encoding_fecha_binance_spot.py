"""
Tests de regresión para los fixes aplicados en ClasificadorBinance (spot):
  Fix 1: pd.read_csv con encoding='utf-8-sig' — evita UnicodeDecodeError en CSVs con BOM
  Fix 2: pd.to_datetime con format="mixed" — evita ValueError con fechas año-4-dígitos
"""

import textwrap
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from clasificador import ClasificadorBinance


HEADER = "Tiempo,Operación,Moneda,Cambio,Cuenta\n"

FILA_COMPRA_2DIGIT = "24-06-15 10:00:00,Transaction Buy,BTC,0.001,Spot\n"
FILA_SPEND_2DIGIT  = "24-06-15 10:00:00,Transaction Spend,EUR,-250.00,Spot\n"

FILA_COMPRA_4DIGIT = "2025-12-31 14:30:00,Transaction Buy,ETH,0.5,Spot\n"
FILA_SPEND_4DIGIT  = "2025-12-31 14:30:00,Transaction Spend,EUR,-900.00,Spot\n"


def _write_csv(tmp_path, content: str, encoding: str = "utf-8") -> str:
    p = tmp_path / "binance_spot.csv"
    p.write_bytes(content.encode(encoding))
    return str(p)


def _write_csv_bom(tmp_path, content: str) -> str:
    """Escribe CSV con BOM UTF-8 (utf-8-sig), como produce Excel en Windows."""
    p = tmp_path / "binance_spot_bom.csv"
    p.write_bytes(content.encode("utf-8-sig"))
    return str(p)


# ── Fix 1: encoding='utf-8-sig' ───────────────────────────────────────────────

def test_binance_spot_utf8_bom_no_lanza_unicode_error(tmp_path):
    """CSV con BOM UTF-8 (generado por Excel/Windows) debe procesarse sin error."""
    csv = HEADER + FILA_COMPRA_2DIGIT + FILA_SPEND_2DIGIT
    filepath = _write_csv_bom(tmp_path, csv)
    clf = ClasificadorBinance(filepath).clasificar()
    assert len(clf.compraventas) == 1


def test_binance_spot_utf8_sin_bom_sigue_funcionando(tmp_path):
    """CSV UTF-8 puro (sin BOM) sigue funcionando tras el cambio de encoding."""
    csv = HEADER + FILA_COMPRA_2DIGIT + FILA_SPEND_2DIGIT
    filepath = _write_csv(tmp_path, csv, encoding="utf-8")
    clf = ClasificadorBinance(filepath).clasificar()
    assert len(clf.compraventas) == 1


# ── Fix 2: format="mixed" en pd.to_datetime ───────────────────────────────────

def test_binance_spot_fecha_4_digitos_no_lanza_valueerror(tmp_path):
    """CSV con fecha año-4-dígitos (2025-12-31 14:30:00) debe procesarse sin ValueError."""
    csv = HEADER + FILA_COMPRA_4DIGIT + FILA_SPEND_4DIGIT
    filepath = _write_csv(tmp_path, csv)
    clf = ClasificadorBinance(filepath).clasificar()
    assert len(clf.compraventas) == 1
    assert clf.compraventas[0].activo == "ETH"


def test_binance_spot_fecha_2_digitos_sigue_funcionando(tmp_path):
    """CSV con fecha año-2-dígitos (formato histórico) sigue funcionando."""
    csv = HEADER + FILA_COMPRA_2DIGIT + FILA_SPEND_2DIGIT
    filepath = _write_csv(tmp_path, csv)
    clf = ClasificadorBinance(filepath).clasificar()
    assert len(clf.compraventas) == 1
    assert clf.compraventas[0].activo == "BTC"


def test_binance_spot_fecha_sin_hora_no_lanza_error(tmp_path):
    """CSV con fecha sin componente horaria (2025-12-31) no lanza error."""
    csv = HEADER + "2025-12-31,Transaction Buy,ETH,0.5,Spot\n2025-12-31,Transaction Spend,EUR,-900.00,Spot\n"
    filepath = _write_csv(tmp_path, csv)
    clf = ClasificadorBinance(filepath).clasificar()
    assert len(clf.compraventas) == 1


def test_binance_spot_bom_con_fecha_4_digitos(tmp_path):
    """CSV con BOM Y fecha año-4-dígitos aplica ambos fixes simultáneamente."""
    csv = HEADER + FILA_COMPRA_4DIGIT + FILA_SPEND_4DIGIT
    filepath = _write_csv_bom(tmp_path, csv)
    clf = ClasificadorBinance(filepath).clasificar()
    assert len(clf.compraventas) == 1
    assert clf.compraventas[0].activo == "ETH"
