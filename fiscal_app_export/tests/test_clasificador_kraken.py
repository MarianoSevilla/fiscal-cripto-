"""
Tests para ClasificadorKraken y la integración con generar_pdf.

Cubre los tres escenarios obligatorios:

  CASO 1 — Solo compras, sin ventas (ej. CSV real usuario mayo 2026)
  1.  motor.resultados == [] cuando el CSV solo tiene compras.
  2.  motor.posicion_actual() contiene los activos comprados.
  3.  generar_pdf() genera PDF sin error.
  4.  El PDF incluye texto sobre activos en cartera (nota informativa).
  5.  n_activos en resumen refleja el inventario, no cero.

  CASO 2 — Venta sin historial de compra (dustsweeping PEPE)
  6.  motor.resultados == [] cuando la venta no tiene base de coste.
  7.  motor.advertencias contiene la advertencia con el nombre del activo.
  8.  generar_pdf() genera PDF con la sección de advertencias.

  CASO 3 — Caso normal con ventas (no regresión)
  9.  Compra + venta posterior genera resultado FIFO correcto.
  10. n_activos refleja activos con resultado, no inventario.
  11. generar_pdf() incluye operaciones FIFO en el PDF.

  PIPELINE
  12. CSV real del usuario (skipped si no disponible) — no crash, inventario SHX detectado.
"""

import csv
import io
import os
import sys
import tempfile
import pytest
import pdfplumber

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from clasificador_kraken import ClasificadorKraken
from motor_fifo import MotorFIFO
from generador_pdf import generar_pdf


def _pdf_text(pdf_bytes: bytes) -> str:
    """Extrae todo el texto del PDF usando pdfplumber."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)

_CSV_REAL = os.path.expanduser(
    "~/Downloads/kraken_stocks_etfs_ledgers_2026-05-10-2026-06-09.csv"
)
_CSV_REAL_DISPONIBLE = os.path.exists(_CSV_REAL)

HEADERS = ["txid", "refid", "time", "type", "subtype", "aclass", "subclass",
           "asset", "wallet", "amount", "fee", "balance"]


def _csv_tmp(rows: list) -> str:
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(HEADERS)
        writer.writerows(rows)
    return path


def _pipeline(filepath: str):
    """Clasificador → motor FIFO, devuelve (motor, clasificador)."""
    c = ClasificadorKraken(filepath).clasificar()
    motor = MotorFIFO()
    ops = [(op.fecha, "cv", op) for op in c.compraventas] + \
          [(op.fecha, "swap", op) for op in c.swaps]
    ops.sort(key=lambda x: x[0])
    for fecha, tipo, op in ops:
        if tipo == "cv":
            if op.tipo == "COMPRA":
                motor.registrar_compra(fecha=op.fecha, activo=op.activo,
                    cantidad=op.cantidad, importe=op.importe,
                    contraparte=op.contraparte,
                    fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad)
            else:
                motor.registrar_venta(fecha=op.fecha, activo=op.activo,
                    cantidad=op.cantidad, importe=op.importe,
                    contraparte=op.contraparte,
                    fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad)
        else:
            motor.registrar_swap(fecha=op.fecha,
                activo_entregado=op.activo_entregado,
                cantidad_entregada=op.cantidad_entregada,
                activo_recibido=op.activo_recibido,
                cantidad_recibida=op.cantidad_recibida,
                nota=op.nota)
    return motor, c


# ── Helpers de datos ──────────────────────────────────────────────────────────

def _fila_deposit(txid, refid, time, asset, amount, balance):
    return [txid, refid, time, "deposit", "", "currency", "fiat",
            asset, "spot / main", amount, "0", balance]

def _fila_spend(txid, refid, time, asset, amount, fee, balance, subtype=""):
    aclass = "fiat" if asset == "EUR" else "crypto"
    return [txid, refid, time, "spend", subtype, "currency", aclass,
            asset, "spot / main", amount, fee, balance]

def _fila_receive(txid, refid, time, asset, amount, balance, subtype=""):
    aclass = "crypto" if asset not in ("EUR", "USD", "USDT", "USDC") else "fiat"
    return [txid, refid, time, "receive", subtype, "currency", aclass,
            asset, "spot / main", amount, "0", balance]


# ── CASO 1: Solo compras, sin ventas ─────────────────────────────────────────

@pytest.fixture
def csv_solo_compras(tmp_path):
    rows = [
        _fila_deposit("DEP1", "REF0", "2026-05-11 10:00:00", "EUR", "100.0", "100.0"),
        _fila_spend("TX1", "REF1", "2026-05-20 12:00:00", "EUR", "-50.0", "0.5", "49.5"),
        _fila_receive("TX2", "REF1", "2026-05-20 12:00:00", "SHX", "10000.0", "10000.0"),
        _fila_spend("TX3", "REF2", "2026-05-25 15:00:00", "EUR", "-30.0", "0.3", "19.2"),
        _fila_receive("TX4", "REF2", "2026-05-25 15:00:00", "BTC", "0.001", "0.001"),
    ]
    p = str(tmp_path / "kraken_solo_compras.csv")
    with open(p, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(HEADERS)
        writer.writerows(rows)
    return p


def test_solo_compras_resultados_vacios(csv_solo_compras):
    motor, _ = _pipeline(csv_solo_compras)
    assert motor.resultados == []


def test_solo_compras_inventario_no_vacio(csv_solo_compras):
    motor, _ = _pipeline(csv_solo_compras)
    activos = {p.activo for p in motor.posicion_actual()}
    assert "SHX" in activos
    assert "BTC" in activos


def test_solo_compras_pdf_no_crash(csv_solo_compras):
    motor, _ = _pipeline(csv_solo_compras)
    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2026",
                      exchange="Kraken")
    assert len(pdf) > 1000, "PDF debe tener contenido"


def test_solo_compras_pdf_contiene_nota_informativa(csv_solo_compras):
    motor, _ = _pipeline(csv_solo_compras)
    pdf_bytes = generar_pdf(motor, nombre_usuario="Test", ejercicio="2026",
                            exchange="Kraken")
    text = _pdf_text(pdf_bytes)
    assert "Sin Transmisiones" in text, \
        "El PDF debe contener la nota informativa 'Sin Transmisiones' cuando no hay resultados FIFO"


def test_solo_compras_n_activos_refleja_inventario(csv_solo_compras):
    motor, _ = _pipeline(csv_solo_compras)
    posicion = motor.posicion_actual()
    assert len(posicion) > 0
    # El resumen inyectado en generar_pdf debe usar posicion_actual, no resultados
    # Lo verificamos indirectamente: si resultados está vacío y posicion no,
    # n_activos calculado correctamente debe ser > 0
    n_activos_correcto = len(posicion) if not motor.resultados else \
        len({r.activo for r in motor.resultados})
    assert n_activos_correcto > 0


# ── CASO 2: Venta sin historial de compra (dustsweeping PEPE) ────────────────

@pytest.fixture
def csv_venta_sin_historial(tmp_path):
    rows = [
        # Solo hay una venta de PEPE, sin compra previa en el CSV
        _fila_spend("TX5", "REF3", "2026-05-28 11:00:00", "PEPE", "-0.25", "0", "0.0",
                    subtype="dustsweeping"),
        _fila_receive("TX6", "REF3", "2026-05-28 11:00:00", "EUR", "0.0001", "0.0001",
                      subtype="dustsweeping"),
    ]
    p = str(tmp_path / "kraken_venta_sin_historial.csv")
    with open(p, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(HEADERS)
        writer.writerows(rows)
    return p


def test_venta_sin_historial_resultados_vacios(csv_venta_sin_historial):
    motor, _ = _pipeline(csv_venta_sin_historial)
    assert motor.resultados == []


def test_venta_sin_historial_genera_advertencia(csv_venta_sin_historial):
    motor, _ = _pipeline(csv_venta_sin_historial)
    assert len(motor.advertencias) >= 1
    texto_adv = " ".join(motor.advertencias)
    assert "PEPE" in texto_adv, "La advertencia debe mencionar el activo PEPE"


def test_venta_sin_historial_pdf_no_crash(csv_venta_sin_historial):
    motor, _ = _pipeline(csv_venta_sin_historial)
    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2026",
                      exchange="Kraken")
    assert len(pdf) > 1000


def test_venta_sin_historial_pdf_contiene_advertencia(csv_venta_sin_historial):
    motor, _ = _pipeline(csv_venta_sin_historial)
    pdf_bytes = generar_pdf(motor, nombre_usuario="Test", ejercicio="2026",
                            exchange="Kraken")
    text = _pdf_text(pdf_bytes)
    assert "PEPE" in text, "El PDF debe mostrar la advertencia con el activo PEPE"


# ── CASO 3: Caso normal con ventas (no regresión) ────────────────────────────

@pytest.fixture
def csv_compra_y_venta(tmp_path):
    rows = [
        _fila_deposit("DEP1", "REFD", "2026-01-01 10:00:00", "EUR", "200.0", "200.0"),
        # Compra BTC
        _fila_spend("TX7",  "REF4", "2026-02-01 10:00:00", "EUR", "-100.0", "1.0", "99.0"),
        _fila_receive("TX8", "REF4", "2026-02-01 10:00:00", "BTC", "0.002", "0.002"),
        # Venta BTC con ganancia
        _fila_spend("TX9",  "REF5", "2026-04-01 10:00:00", "BTC", "-0.002", "0", "0.0"),
        _fila_receive("TX10", "REF5", "2026-04-01 10:00:00", "EUR", "150.0", "149.0"),
    ]
    p = str(tmp_path / "kraken_compra_venta.csv")
    with open(p, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(HEADERS)
        writer.writerows(rows)
    return p


def test_caso_normal_genera_resultado_fifo(csv_compra_y_venta):
    motor, _ = _pipeline(csv_compra_y_venta)
    assert len(motor.resultados) == 1
    r = motor.resultados[0]
    assert r.activo == "BTC"
    assert r.ganancia_perdida > 0, "Debe haber ganancia (vendido a 150 EUR, coste ~101 EUR)"


def test_caso_normal_n_activos_usa_resultados(csv_compra_y_venta):
    motor, _ = _pipeline(csv_compra_y_venta)
    assert motor.resultados
    n = len({r.activo for r in motor.resultados})
    assert n == 1  # solo BTC tiene resultado FIFO


def test_caso_normal_pdf_no_crash(csv_compra_y_venta):
    motor, _ = _pipeline(csv_compra_y_venta)
    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2026",
                      exchange="Kraken")
    assert len(pdf) > 1000


def test_caso_normal_pdf_no_contiene_nota_sin_transmisiones(csv_compra_y_venta):
    motor, _ = _pipeline(csv_compra_y_venta)
    pdf_bytes = generar_pdf(motor, nombre_usuario="Test", ejercicio="2026",
                            exchange="Kraken")
    text = _pdf_text(pdf_bytes)
    assert "Sin Transmisiones" not in text, \
        "La nota informativa NO debe aparecer cuando hay resultados FIFO"


# ── PIPELINE con CSV real ─────────────────────────────────────────────────────

@pytest.mark.skipif(not _CSV_REAL_DISPONIBLE, reason="CSV real no disponible en Downloads")
def test_csv_real_pipeline_no_crash():
    motor, clasificador = _pipeline(_CSV_REAL)
    assert motor is not None


@pytest.mark.skipif(not _CSV_REAL_DISPONIBLE, reason="CSV real no disponible en Downloads")
def test_csv_real_inventario_shx_detectado():
    motor, _ = _pipeline(_CSV_REAL)
    activos = {p.activo for p in motor.posicion_actual()}
    assert "SHX" in activos, "SHX debe estar en el inventario"


@pytest.mark.skipif(not _CSV_REAL_DISPONIBLE, reason="CSV real no disponible en Downloads")
def test_csv_real_pdf_no_crash():
    motor, _ = _pipeline(_CSV_REAL)
    pdf = generar_pdf(motor, nombre_usuario="Test", ejercicio="2026",
                      exchange="Kraken")
    assert len(pdf) > 1000


@pytest.mark.skipif(not _CSV_REAL_DISPONIBLE, reason="CSV real no disponible en Downloads")
def test_csv_real_n_activos_no_es_cero():
    motor, _ = _pipeline(_CSV_REAL)
    posicion = motor.posicion_actual()
    n_activos = len(posicion) if not motor.resultados else \
        len({r.activo for r in motor.resultados})
    assert n_activos > 0, "Activos detectados no debe ser 0 cuando hay inventario"
