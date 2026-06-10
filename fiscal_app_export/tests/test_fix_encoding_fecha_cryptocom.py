"""
Tests de regresión para los fixes aplicados en ClasificadorCryptoCom:
  Fix 3a: pd.read_csv con encoding='utf-8-sig' — evita UnicodeDecodeError en CSVs con BOM
  Fix 3b: pd.to_datetime con errors='coerce' — evita ValueError con timestamps malformados
"""

import textwrap
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from clasificador_cryptocom import ClasificadorCryptoCom


HEADER = "Timestamp (UTC),Transaction Description,Transaction Kind,Currency,Amount,To Currency,To Amount,Native Currency,Native Amount (in USD),Transaction Hash\n"


def _write_csv(tmp_path, content: str, encoding: str = "utf-8", filename: str = "cc.csv") -> str:
    p = tmp_path / filename
    p.write_bytes(content.encode(encoding))
    return str(p)


CSV_COMPRA_NORMAL = (
    HEADER
    + "2024-03-15 10:00:00,Buy BTC,crypto_purchase,BTC,0.01,,,"
    + "EUR,650.00,\n"
)

CSV_TIMESTAMP_MALFORMADO = (
    HEADER
    + "FECHA_ROTA,Buy BTC,crypto_purchase,BTC,0.01,,,USD,650.00,\n"
)

CSV_TIMESTAMP_VACIO = (
    HEADER
    + ",Buy BTC,crypto_purchase,BTC,0.01,,,USD,650.00,\n"
)


# ── Fix 3a: encoding='utf-8-sig' ─────────────────────────────────────────────

def test_cryptocom_utf8_bom_no_lanza_error(tmp_path):
    """CSV CryptoCom con BOM UTF-8 (Excel/Windows) debe procesarse sin UnicodeDecodeError."""
    filepath = _write_csv(tmp_path, CSV_COMPRA_NORMAL, encoding="utf-8-sig")
    clf = ClasificadorCryptoCom(filepath).clasificar()
    assert isinstance(clf.compraventas, list)


def test_cryptocom_utf8_sin_bom_sigue_funcionando(tmp_path):
    """CSV CryptoCom UTF-8 puro sigue funcionando tras el cambio de encoding."""
    filepath = _write_csv(tmp_path, CSV_COMPRA_NORMAL, encoding="utf-8")
    clf = ClasificadorCryptoCom(filepath).clasificar()
    assert isinstance(clf.compraventas, list)


# ── Fix 3b: errors='coerce' en pd.to_datetime ────────────────────────────────

def test_cryptocom_timestamp_malformado_no_lanza_valueerror(tmp_path):
    """Fila con timestamp no parseable no debe lanzar ValueError — debe ignorarse."""
    filepath = _write_csv(tmp_path, CSV_TIMESTAMP_MALFORMADO)
    clf = ClasificadorCryptoCom(filepath).clasificar()
    assert isinstance(clf.compraventas, list)


def test_cryptocom_timestamp_vacio_no_lanza_valueerror(tmp_path):
    """Fila con timestamp vacío no debe lanzar ValueError."""
    filepath = _write_csv(tmp_path, CSV_TIMESTAMP_VACIO)
    clf = ClasificadorCryptoCom(filepath).clasificar()
    assert isinstance(clf.compraventas, list)


def test_cryptocom_csv_normal_clasifica_compra(tmp_path):
    """CSV normal sigue clasificando correctamente una crypto_purchase."""
    filepath = _write_csv(tmp_path, CSV_COMPRA_NORMAL)
    clf = ClasificadorCryptoCom(filepath).clasificar()
    assert len(clf.compraventas) == 1
    assert clf.compraventas[0].activo == "BTC"


def test_cryptocom_bom_con_timestamp_malformado(tmp_path):
    """BOM + timestamp malformado: ambos fixes actúan simultáneamente sin excepción."""
    filepath = _write_csv(tmp_path, CSV_TIMESTAMP_MALFORMADO, encoding="utf-8-sig")
    clf = ClasificadorCryptoCom(filepath).clasificar()
    assert isinstance(clf.compraventas, list)
