"""
Tests del refuerzo estructural del tratamiento de errores de Binance
(incidente 6b73e4de234d0158 — KeyError: 'Tiempo' en etapa classify).

Causas reales demostradas con csv_context de producción:
  1. BOM + línea completa envuelta en un único par de comillas
     ("ID de usuario,Tiempo,...") → pandas colapsa todo en una columna.
  2. Historial de depósitos/retiros de cripto (Time,Coin,Network,Amount,
     Address,TXID,Status) subido como historial de transacciones.

Capas cubiertas:
  - csv_schema: normalización de cabeceras, reparación de líneas
    entrecomilladas, lectura robusta.
  - Validación de esquema antes de clasificar (ningún KeyError posible).
  - Excepciones tipificadas con mensaje de usuario limpio.
  - Detección del historial de depósitos de cripto.
  - Fingerprint estable y no-regresión FIFO/PDF.

Todas las fixtures son sintéticas y anonimizadas.
"""

import sys
import os

import pytest
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from csv_schema import CsvUserError, normalizar_cabeceras, leer_csv_texto
from clasificador import (
    ClasificadorBinance,
    BinanceArchivoVacioError,
    BinanceColumnasAusentesError,
    BinanceFechaInvalidaError,
    COLS_OBLIGATORIAS_BINANCE,
)
from clasificador_binance_tx import ClasificadorBinanceTx
from error_tracking import build_processing_error_fingerprint
from app import _detectar_formato_binance, procesar_con_fifo


# ── Fixtures sintéticas ───────────────────────────────────────────────────────

HEADER_ES = "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"
HEADER_EN = "User ID,Time,Account,Operation,Coin,Change,Remark\n"

FILAS_ES = (
    "12345678,2024-03-01 10:00:00,Spot,Deposit,EUR,1000.00,\n"
    "12345678,2024-03-01 10:00:05,Spot,Buy Crypto With Fiat,BTC,0.02,Wallet/AAA111\n"
    "12345678,2024-03-01 10:00:05,Spot,Buy Crypto With Fiat,EUR,-600.00,Wallet/AAA111\n"
    "12345678,2024-06-01 12:00:00,Spot,Sell Crypto To Fiat,BTC,-0.01,Wallet/BBB222\n"
    "12345678,2024-06-01 12:00:00,Spot,Sell Crypto To Fiat,EUR,400.00,Wallet/BBB222\n"
    "12345678,2024-07-01 09:00:00,Spot,Simple Earn Flexible Interest,BTC,0.0001,\n"
)

FILAS_EN = FILAS_ES  # los valores no cambian entre idiomas, solo la cabecera


def _csv(tmp_path, contenido: str, nombre: str = "binance.csv", bom: bool = False) -> str:
    p = tmp_path / nombre
    data = contenido.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    p.write_bytes(data)
    return str(p)


def _resumen(clasificador) -> dict:
    return clasificador.clasificar().resumen()


# ── 1-3 · CSV válidos: ES, cabecera Tiempo, alias EN con paridad ─────────────

def test_csv_es_valido(tmp_path):
    r = _resumen(ClasificadorBinanceTx(_csv(tmp_path, HEADER_ES + FILAS_ES)))
    assert r["compraventas"] == 2
    assert r["rendimientos"] == 1
    assert r["desconocidas"] == 0


def test_alias_ingles_paridad_con_espanol(tmp_path):
    """El alias EN verificado (commit b4b72e9) produce resultado idéntico al ES."""
    r_es = _resumen(ClasificadorBinanceTx(_csv(tmp_path, HEADER_ES + FILAS_ES, "es.csv")))
    r_en = _resumen(ClasificadorBinanceTx(_csv(tmp_path, HEADER_EN + FILAS_EN, "en.csv")))
    assert r_es == r_en


# ── 4-5 · BOM y espacios en cabeceras ────────────────────────────────────────

def test_bom_en_primera_cabecera(tmp_path):
    r = _resumen(ClasificadorBinanceTx(_csv(tmp_path, HEADER_ES + FILAS_ES, bom=True)))
    assert r["compraventas"] == 2


def test_espacios_alrededor_de_cabeceras(tmp_path):
    header = " ID de usuario , Tiempo , Cuenta , Operación , Moneda , Cambio , Observación \n"
    # pandas conserva los espacios en los nombres; la normalización los quita
    r = _resumen(ClasificadorBinanceTx(_csv(tmp_path, header + FILAS_ES)))
    assert r["compraventas"] == 2


def test_normalizar_cabeceras_espacios_multiples():
    assert normalizar_cabeceras(["﻿ID  de   usuario ", " Tiempo"]) == ["ID de usuario", "Tiempo"]


# ── Causa real 1 · líneas completas entrecomilladas + BOM ────────────────────

def test_incidente_lineas_entrecomilladas_reparado(tmp_path):
    """La variante real del incidente (BOM + cada línea envuelta en comillas)
    ahora se procesa y produce el mismo resultado que el archivo sin alterar."""
    lineas = (HEADER_ES + FILAS_ES).strip().split("\n")
    quoted = "\n".join(f'"{l}"' for l in lineas) + "\n"
    r_quoted = _resumen(ClasificadorBinanceTx(_csv(tmp_path, quoted, "q.csv", bom=True)))
    r_normal = _resumen(ClasificadorBinanceTx(_csv(tmp_path, HEADER_ES + FILAS_ES, "n.csv")))
    assert r_quoted == r_normal


def test_lineas_entrecomilladas_sigue_detectando_tx(tmp_path):
    lineas = (HEADER_ES + FILAS_ES).strip().split("\n")
    quoted = "\n".join(f'"{l}"' for l in lineas) + "\n"
    assert _detectar_formato_binance(_csv(tmp_path, quoted, bom=True)) == "tx"


# ── 6 · Columna obligatoria ausente ──────────────────────────────────────────

@pytest.mark.parametrize("columna", COLS_OBLIGATORIAS_BINANCE)
def test_columna_obligatoria_ausente_tx(tmp_path, columna):
    """Quitar cualquier obligatoria produce error tipificado, nunca KeyError."""
    cols = HEADER_ES.strip().split(",")
    idx = cols.index(columna)
    header = ",".join(c for i, c in enumerate(cols) if i != idx) + "\n"
    filas = "\n".join(
        ",".join(v for i, v in enumerate(l.split(",")) if i != idx)
        for l in FILAS_ES.strip().split("\n")
    ) + "\n"
    with pytest.raises(BinanceColumnasAusentesError) as exc_info:
        ClasificadorBinanceTx(_csv(tmp_path, header + filas))
    assert exc_info.value.category == "parser_error"
    assert exc_info.value.code == "columnas_obligatorias_ausentes"
    assert columna in exc_info.value.columnas


def test_columna_ausente_legacy_es_user_error(tmp_path):
    csv = "Tiempo,Operación,Moneda,Cuenta\n2024-01-01 10:00:00,Deposit,BTC,Spot\n"
    with pytest.raises(BinanceColumnasAusentesError) as exc_info:
        ClasificadorBinance(_csv(tmp_path, csv))
    assert exc_info.value.category == "user_error"
    assert "Cambio" in exc_info.value.columnas


# ── 7 · Archivo vacío o solo cabecera ────────────────────────────────────────

def test_archivo_sin_contenido(tmp_path):
    with pytest.raises(BinanceArchivoVacioError):
        ClasificadorBinanceTx(_csv(tmp_path, ""))
    with pytest.raises(BinanceArchivoVacioError):
        ClasificadorBinance(_csv(tmp_path, "", "l.csv"))


def test_archivo_solo_cabecera(tmp_path):
    """Antes generaba un informe con cero operaciones; ahora bloquea con mensaje."""
    with pytest.raises(BinanceArchivoVacioError) as exc_info:
        ClasificadorBinanceTx(_csv(tmp_path, HEADER_ES))
    assert "no contiene operaciones" in str(exc_info.value)


# ── Causa real 2 / 8 · Historial de depósitos de cripto (archivo equivocado) ─

def test_detectar_historial_depositos_cripto(tmp_path):
    """Cabecera real del evento 42 del incidente → variante crypto_deposits."""
    csv = ("Time,Coin,Network,Amount,Address,TXID,Status\n"
           "2024-01-01 10:00:00,BTC,BTC,0.01,bc1qsyntheticaddr,txidsintetico,Completed\n")
    assert _detectar_formato_binance(_csv(tmp_path, csv, bom=True)) == "crypto_deposits"


def test_deteccion_tx_no_regresa(tmp_path):
    assert _detectar_formato_binance(_csv(tmp_path, HEADER_ES + FILAS_ES)) == "tx"
    assert _detectar_formato_binance(_csv(tmp_path, HEADER_EN + FILAS_EN, "en.csv")) == "tx"


# ── 9 · Fecha inválida ───────────────────────────────────────────────────────

def test_fecha_invalida_error_tipificado(tmp_path):
    csv = HEADER_ES + "12345678,esto-no-es-una-fecha,Spot,Deposit,EUR,100.00,\n"
    with pytest.raises(BinanceFechaInvalidaError) as exc_info:
        ClasificadorBinanceTx(_csv(tmp_path, csv))
    assert exc_info.value.category == "parser_error"


# ── 10 · Cantidad no numérica (comportamiento actual, pendiente de gobierno) ─

def test_cantidad_invalida_comportamiento_actual(tmp_path):
    """Documenta el comportamiento vigente: Cambio no numérico → 0.0 silencioso.

    Cambiarlo (bloquear o advertir) altera qué archivos generan informe y está
    pendiente de decisión de gobierno (Regla 1, CLAUDE.md §2). Este test fija
    el comportamiento actual para que cualquier cambio futuro sea deliberado.
    """
    csv = HEADER_ES + "12345678,2024-03-01 10:00:00,Spot,Deposit,EUR,no-numerico,\n"
    c = ClasificadorBinanceTx(_csv(tmp_path, csv))
    assert float(c.df["Cambio"].iloc[0]) == 0.0


# ── 11 · Operación desconocida ───────────────────────────────────────────────

def test_operacion_desconocida_con_advertencia(tmp_path):
    csv = HEADER_ES + "12345678,2024-03-01 10:00:00,Spot,Operacion Inventada XYZ,BTC,0.01,\n"
    c = ClasificadorBinanceTx(_csv(tmp_path, csv)).clasificar()
    assert len(c.desconocidas) == 1
    assert any("no reconocida" in a for a in c.advertencias)


# ── 13 · Mensajes públicos sin detalles internos ─────────────────────────────

_DETALLES_INTERNOS = ("KeyError", "Traceback", "DataFrame", "pandas", "Clasificador",
                      "Error(", ".py", "self.")


def _sin_detalles_internos(mensaje: str):
    for token in _DETALLES_INTERNOS:
        assert token not in mensaje, f"mensaje expone detalle interno: {token!r}"


def test_mensajes_publicos_limpios():
    for exc in (
        BinanceArchivoVacioError(),
        BinanceColumnasAusentesError(["Tiempo", "Cambio"]),
        BinanceFechaInvalidaError(),
    ):
        _sin_detalles_internos(str(exc))
        assert isinstance(exc, ValueError)      # _error_amigable lo muestra tal cual
        assert len(str(exc)) > 20               # condición de _error_amigable
        assert hasattr(exc, "code") and hasattr(exc, "category")


# ── 14 · Fingerprint estable por causa ───────────────────────────────────────

def test_fingerprint_estable_misma_causa(tmp_path):
    """Dos archivos distintos con la misma causa producen el mismo fingerprint."""
    e1 = BinanceColumnasAusentesError(["Tiempo"])
    e2 = BinanceColumnasAusentesError(["Tiempo"])
    fps = {
        build_processing_error_fingerprint("binance", "classify", type(e).__name__, str(e))
        for e in (e1, e2)
    }
    assert len(fps) == 1


def test_fingerprint_incidente_original_eliminado(tmp_path):
    """Ninguna de las dos causas reales puede volver a producir el fingerprint
    6b73e4de234d0158 (KeyError 'Tiempo'): la causa 1 ahora se procesa y la
    causa 2 se rechaza antes de llegar al clasificador."""
    lineas = (HEADER_ES + FILAS_ES).strip().split("\n")
    quoted = "\n".join(f'"{l}"' for l in lineas) + "\n"
    ClasificadorBinanceTx(_csv(tmp_path, quoted, bom=True)).clasificar()  # no lanza

    deposito = ("Time,Coin,Network,Amount,Address,TXID,Status\n"
                "2024-01-01 10:00:00,BTC,BTC,0.01,addr,txid,Completed\n")
    assert _detectar_formato_binance(_csv(tmp_path, deposito, "d.csv")) == "crypto_deposits"


# ── 16 · No regresión: FIFO y PDF para un archivo válido ─────────────────────

def test_pipeline_fifo_y_pdf_sin_cambios(tmp_path):
    from generador_pdf import generar_pdf
    motor, rendimientos, clasif = procesar_con_fifo(
        ClasificadorBinanceTx(_csv(tmp_path, HEADER_ES + FILAS_ES)).clasificar()
    )
    resumen = motor.resumen_fiscal()
    # Compra 0.02 BTC por 600 EUR → coste 300 EUR por 0.01; venta a 400 EUR → +100
    assert resumen["operaciones_con_resultado"] == 1
    assert round(resumen["resultado_neto"], 2) == 100.00
    pdf = generar_pdf(motor, "Test", "all", "Binance", rendimientos)
    assert pdf[:4] == b"%PDF"


def test_pipeline_identico_con_archivo_entrecomillado(tmp_path):
    """El archivo del incidente (reparado) produce exactamente el mismo FIFO."""
    lineas = (HEADER_ES + FILAS_ES).strip().split("\n")
    quoted = "\n".join(f'"{l}"' for l in lineas) + "\n"
    motor_q, _, _ = procesar_con_fifo(
        ClasificadorBinanceTx(_csv(tmp_path, quoted, "q.csv", bom=True)).clasificar())
    motor_n, _, _ = procesar_con_fifo(
        ClasificadorBinanceTx(_csv(tmp_path, HEADER_ES + FILAS_ES, "n.csv")).clasificar())
    assert motor_q.resumen_fiscal() == motor_n.resumen_fiscal()
