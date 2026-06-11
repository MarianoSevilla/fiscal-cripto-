"""
LOTE 1 — Tarea 1: fix descarga PDF MEXC.

Causa raíz: pdf_tmp = tmp_path.replace(".csv", ".pdf") era un no-op para
ficheros .xlsx → el PDF sobreescribía el temporal XLSX y el token resultante
(tmpXXX.xlsx) no pasaba la regex ^[a-zA-Z0-9_\\-]+\\.pdf$ de /api/descargar.

Verifica que _derivar_ruta_pdf produce siempre una ruta .pdf distinta del
fichero subido y cuyo basename es un token de descarga válido.
"""

import os
import re
import sys
import tempfile

os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}")
os.environ.setdefault("SECRET_KEY", "test-secret-key-lote1-pdf")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import _derivar_ruta_pdf

# Misma regex que valida el token en /api/descargar/<token>
_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.pdf$")


def test_csv_produce_pdf_distinto():
    """Caso histórico (CSV): comportamiento idéntico al replace anterior."""
    ruta = _derivar_ruta_pdf("/tmp/tmpabc123.csv")
    assert ruta == "/tmp/tmpabc123.pdf"
    assert ruta != "/tmp/tmpabc123.csv"


def test_xlsx_produce_pdf_distinto():
    """Caso del bug: XLSX de MEXC debe producir una ruta .pdf separada."""
    ruta = _derivar_ruta_pdf("/tmp/tmpabc123.xlsx")
    assert ruta == "/tmp/tmpabc123.pdf"
    assert ruta != "/tmp/tmpabc123.xlsx"


def test_xls_produce_pdf_distinto():
    ruta = _derivar_ruta_pdf("/tmp/tmpabc123.xls")
    assert ruta == "/tmp/tmpabc123.pdf"


def test_token_valido_para_descarga_csv_y_xlsx():
    """El basename de la ruta PDF debe pasar la regex de /api/descargar
    para nombres reales de tempfile.NamedTemporaryFile."""
    for suffix in (".csv", ".xlsx", ".xls"):
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
            token = os.path.basename(_derivar_ruta_pdf(tmp.name))
            assert _TOKEN_RE.match(token), (
                f"token '{token}' (de {suffix}) no pasa la regex de descarga"
            )


def test_xlsx_no_sobreescribe_el_fichero_subido():
    """Regresión del bug original: escribir el PDF no debe tocar el XLSX."""
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(b"contenido-xlsx-original")
        tmp_path = tmp.name
    try:
        pdf_path = _derivar_ruta_pdf(tmp_path)
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-fake")
        with open(tmp_path, "rb") as f:
            assert f.read() == b"contenido-xlsx-original"
    finally:
        for p in (tmp_path, _derivar_ruta_pdf(tmp_path)):
            try:
                os.unlink(p)
            except OSError:
                pass
