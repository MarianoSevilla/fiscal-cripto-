"""
Tests para ClasificadorCoinbase.

Cubre:
  DETECCIÓN DE CABECERA
  1.  CSV estándar con 3 filas de metadatos → cabecera detectada en fila 3.
  2.  CSV sin metadatos (cabecera en fila 0) → cabecera detectada.
  3.  CSV con 1 fila de metadatos → cabecera detectada.
  4.  CSV con 2 filas de metadatos → cabecera detectada.
  5.  CSV con 4 filas de metadatos → cabecera detectada.
  6.  CSV con "Timestamp" en texto pero sin columnas reales → ValueError descriptivo.
  7.  Fichero vacío → ValueError descriptivo.
  8.  ValueError contiene texto específico de Coinbase.

  CLASIFICACIÓN — tipos principales
  9.  Buy → OperacionCompraventa COMPRA.
  10. Sell → OperacionCompraventa VENTA.
  11. Convert → OperacionSwap con activos y cantidades correctos.
  12. Staking Income → OperacionRendimiento.
  13. Withdrawal → OperacionMovimiento.
  14. Tipo desconocido → OperacionDesconocida + advertencia.

  PIPELINE
  15. Pipeline FIFO completo no rompe con CSV estándar.
  16. CSV estándar con 3 metadatos produce los mismos resultados que antes del fix.
"""

import csv
import io
import os
import tempfile
import pytest

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from clasificador_coinbase import ClasificadorCoinbase, _detectar_fila_cabecera


# ── HELPERS ───────────────────────────────────────────────────────────────────

CABECERA = [
    "ID", "Timestamp", "Transaction Type", "Asset", "Quantity Transacted",
    "Price Currency", "Price at Transaction", "Subtotal",
    "Total (inclusive of fees and/or spread)", "Fees and/or Spread",
    "Notes", "Sender Address", "Recipient Address",
]

FILA_BUY = [
    "abc123", "2024-03-15T10:30:00Z", "Buy", "BTC", "0.01",
    "EUR", "€55000", "€550", "€556.50", "€6.50",
    "", "", "",
]

FILA_SELL = [
    "def456", "2024-06-20T14:00:00Z", "Sell", "BTC", "0.005",
    "EUR", "€60000", "€300", "€293.00", "€7.00",
    "", "", "",
]

FILA_CONVERT = [
    "ghi789", "2024-07-01T09:00:00Z", "Convert", "DOGE", "100",
    "EUR", "€0.10", "€10", "€9.80", "€0.20",
    "Converted 100 DOGE to 12.5 XRP", "", "",
]

FILA_STAKING = [
    "jkl012", "2024-08-01T00:00:00Z", "Staking Income", "ETH", "0.005",
    "EUR", "€2000", "€10", "€10", "€0",
    "", "", "",
]

FILA_WITHDRAWAL = [
    "mno345", "2024-09-01T12:00:00Z", "Withdrawal", "BTC", "0.002",
    "EUR", "€0", "€0", "€0", "€0",
    "", "", "",
]

FILA_DESCONOCIDA = [
    "pqr678", "2024-10-01T08:00:00Z", "TipoRaro", "ADA", "50",
    "EUR", "€0.50", "€25", "€24.50", "€0.50",
    "", "", "",
]

METADATOS_STD = ["", "", "user@example.com"]  # 3 filas estándar de Coinbase


def _csv_tmp(rows, prefix_rows=None) -> str:
    """Escribe un CSV temporal; prefix_rows son filas antes de la cabecera."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if prefix_rows:
            for r in prefix_rows:
                writer.writerow(r)
        writer.writerow(CABECERA)
        writer.writerows(rows)
    return path


def _csv_tmp_sin_header(texto: str) -> str:
    """Escribe CSV crudo (texto) a un fichero temporal."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(texto)
    return path


# ── DETECCIÓN DE CABECERA ─────────────────────────────────────────────────────

def test_01_cabecera_estandar_3_metadatos():
    path = _csv_tmp([FILA_BUY], prefix_rows=[[""], ["Transactions"], ["user@example.com"]])
    assert _detectar_fila_cabecera(path) == 3
    os.unlink(path)


def test_02_cabecera_sin_metadatos():
    path = _csv_tmp([FILA_BUY], prefix_rows=None)
    assert _detectar_fila_cabecera(path) == 0
    os.unlink(path)


def test_03_cabecera_1_metadato():
    path = _csv_tmp([FILA_BUY], prefix_rows=[["Transactions"]])
    assert _detectar_fila_cabecera(path) == 1
    os.unlink(path)


def test_04_cabecera_2_metadatos():
    path = _csv_tmp([FILA_BUY], prefix_rows=[[""], ["Transactions"]])
    assert _detectar_fila_cabecera(path) == 2
    os.unlink(path)


def test_05_cabecera_4_metadatos():
    path = _csv_tmp([FILA_BUY], prefix_rows=[[""], ["Transactions"], ["user@example.com"], [""]])
    assert _detectar_fila_cabecera(path) == 4
    os.unlink(path)


def test_06_timestamp_en_texto_pero_sin_cabecera_real():
    # "Timestamp" aparece en texto pero no hay fila con las 4 columnas requeridas
    contenido = "Timestamp exported: 2024-01-01\nother data\n"
    path = _csv_tmp_sin_header(contenido)
    with pytest.raises(ValueError, match="cabecera de transacciones"):
        _detectar_fila_cabecera(path)
    os.unlink(path)


def test_07_fichero_vacio():
    path = _csv_tmp_sin_header("")
    with pytest.raises(ValueError, match="cabecera de transacciones"):
        _detectar_fila_cabecera(path)
    os.unlink(path)


def test_08_valueerror_mensaje_especifico_coinbase():
    path = _csv_tmp_sin_header("foo,bar\n1,2\n")
    with pytest.raises(ValueError) as exc_info:
        ClasificadorCoinbase(path)
    msg = str(exc_info.value)
    assert "Coinbase" in msg
    assert "historial completo de transacciones" in msg
    os.unlink(path)


# ── CLASIFICACIÓN ─────────────────────────────────────────────────────────────

def test_09_buy_genera_compraventa():
    path = _csv_tmp([FILA_BUY], prefix_rows=METADATOS_STD)
    c = ClasificadorCoinbase(path).clasificar()
    os.unlink(path)
    assert len(c.compraventas) == 1
    op = c.compraventas[0]
    assert op.tipo == "COMPRA"
    assert op.activo == "BTC"
    assert abs(op.cantidad - 0.01) < 1e-9


def test_10_sell_genera_compraventa():
    path = _csv_tmp([FILA_SELL], prefix_rows=METADATOS_STD)
    c = ClasificadorCoinbase(path).clasificar()
    os.unlink(path)
    assert len(c.compraventas) == 1
    op = c.compraventas[0]
    assert op.tipo == "VENTA"
    assert op.activo == "BTC"


def test_11_convert_genera_swap():
    path = _csv_tmp([FILA_BUY, FILA_CONVERT], prefix_rows=METADATOS_STD)
    c = ClasificadorCoinbase(path).clasificar()
    os.unlink(path)
    assert len(c.swaps) == 1
    s = c.swaps[0]
    assert s.activo_entregado == "DOGE"
    assert s.activo_recibido == "XRP"
    assert abs(s.cantidad_entregada - 100.0) < 1e-9
    assert abs(s.cantidad_recibida - 12.5) < 1e-9


def test_12_staking_income_genera_rendimiento():
    path = _csv_tmp([FILA_STAKING], prefix_rows=METADATOS_STD)
    c = ClasificadorCoinbase(path).clasificar()
    os.unlink(path)
    assert len(c.rendimientos) == 1
    r = c.rendimientos[0]
    assert r.subtipo == "Staking Income"
    assert r.activo == "ETH"


def test_13_withdrawal_genera_movimiento():
    path = _csv_tmp([FILA_WITHDRAWAL], prefix_rows=METADATOS_STD)
    c = ClasificadorCoinbase(path).clasificar()
    os.unlink(path)
    assert len(c.movimientos) == 1
    assert c.movimientos[0].subtipo == "Withdrawal"


def test_14_tipo_desconocido_genera_desconocida_y_advertencia():
    path = _csv_tmp([FILA_BUY, FILA_DESCONOCIDA], prefix_rows=METADATOS_STD)
    c = ClasificadorCoinbase(path).clasificar()
    os.unlink(path)
    assert len(c.desconocidas) == 1
    assert any("TipoRaro" in adv for adv in c.advertencias)


# ── PIPELINE ──────────────────────────────────────────────────────────────────

def test_15_pipeline_fifo_no_rompe():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from app import procesar_coinbase
    path = _csv_tmp([FILA_BUY, FILA_SELL], prefix_rows=METADATOS_STD)
    motor, rendimientos, clasificador = procesar_coinbase(path)
    os.unlink(path)
    assert motor is not None
    assert len(motor.resultados) >= 1


def test_16_estandar_3_metadatos_igual_resultado_que_antes():
    # Verifica que el fix no altera la clasificación del formato canónico
    path = _csv_tmp([FILA_BUY, FILA_SELL, FILA_STAKING], prefix_rows=METADATOS_STD)
    c = ClasificadorCoinbase(path).clasificar()
    os.unlink(path)
    assert len(c.compraventas) == 2
    assert len(c.rendimientos) == 1
    assert len(c.swaps) == 0
    assert len(c.movimientos) == 0
