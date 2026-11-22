"""PDF no fiscal de Binance: solo evidencia sintética y sin datos personales."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_diagnostico_pdf import (
    _validar_borrador, generar_pdf_diagnostico_binance,
)
from binance_borrador import construir_borrador_binance
from types import SimpleNamespace


def draft(n_issues=3):
    classifier = SimpleNamespace(
        compraventas=[], swaps=[], movimientos=[], rendimientos=[],
        desconocidas=[], commission_evidence_summary=SimpleNamespace(records=0),
        resumen_archivos={
            "transaction_history": {
                "detectado": True, "vacio": False, "registros": 32223,
            }
        },
    )
    entries = []
    for i in range(n_issues):
        code = ["legacy_sin_eur", "earn_lotes", "comisiones_referidos"][i % 3]
        entries.append({
            "codigo": code,
            "titulo": "Movimiento sin documentación " + str(i),
            "descripcion": ("Es necesaria evidencia para identificar el coste. " * 11),
            "siguiente_paso": ("Descarga el historial original. " * 8),
        })
    return construir_borrador_binance(classifier, {"incidencias": entries}, "2025")


def test_pdf_diagnostico_valido_y_sin_resultados_fiscales():
    b = draft()
    assert [x["grupo"] for x in b["pendientes"]] == [
        "operaciones", "earn", "comisiones"
    ]
    output = generar_pdf_diagnostico_binance(b)
    assert output.startswith(b"%PDF-")
    assert len(output) > 1800
    assert b"32223" not in output  # flujos comprimidos: no afirmar texto extraído
    assert b["ganancias_y_perdidas_eur"] is None
    assert b["pdf_fiscal_disponible"] is False


def test_marca_agua_impresa_en_todas_las_paginas(monkeypatch):
    from binance_diagnostico_pdf import _watermark
    import binance_diagnostico_pdf

    seen = []

    def wrapped(canvas, doc):
        seen.append(doc.page)
        _watermark(canvas, doc)

    monkeypatch.setattr(binance_diagnostico_pdf, "_watermark", wrapped)
    output = generar_pdf_diagnostico_binance(draft(n_issues=27))
    assert output.startswith(b"%PDF-")
    assert len(seen) >= 2
    assert seen == list(range(1, len(seen) + 1))


@pytest.mark.parametrize("field,bad_value", [
    ("estado", "COMPLETO"),
    ("no_es_informe_fiscal", False),
    ("pdf_fiscal_disponible", True),
    ("costes_fifo_calculados", True),
    ("ganancias_y_perdidas_eur", 0),
])
def test_no_permitir_pdf_diagnostico_para_informe_fiscal(field, bad_value):
    b = draft()
    b[field] = bad_value
    with pytest.raises(ValueError):
        _validar_borrador(b)


def test_pdf_no_admite_payload_vacio_o_arbitrario():
    with pytest.raises(ValueError):
        generar_pdf_diagnostico_binance({"pendientes": []})
