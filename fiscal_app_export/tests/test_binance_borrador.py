"""Borrador provisional Binance. Todas las pruebas usan datos inventados."""
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_borrador import construir_borrador_binance


def _clasificador():
    return SimpleNamespace(
        compraventas=[object(), object()],
        swaps=[object()],
        movimientos=[object()],
        rendimientos=[object(), object(), object()],
        desconocidas=[object()],
        commission_evidence_summary=SimpleNamespace(records=12),
        resumen_archivos={
            "spot_trades": {"detectado": True, "vacio": False, "registros": 2},
            "convert_orders": {"detectado": True, "vacio": False, "registros": 1},
            "crypto_deposit": {"detectado": False, "vacio": True, "registros": 0},
        },
    )


def test_borrador_separa_cobertura_de_resultado_fiscal():
    diagnostico = {"incidencias": [
        {"codigo": "origen", "titulo": "Lotes pendientes",
         "descripcion": "Falta coste de adquisición",
         "siguiente_paso": "Aportar fuente original"}
    ]}
    b = construir_borrador_binance(_clasificador(), diagnostico, "2025")
    assert b["estado"] == "INCOMPLETO_NO_APTO_PARA_DECLARAR"
    assert b["no_es_informe_fiscal"] is True
    assert b["pdf_fiscal_disponible"] is False
    assert b["costes_fifo_calculados"] is False
    assert b["ganancias_y_perdidas_eur"] is None
    assert b["operaciones_detectadas"]["compraventas_candidatas"] == 2
    assert b["operaciones_detectadas"]["comisiones_referidos_analizadas"] == 12
    assert len(b["fuentes"]) == 2
    assert b["pendientes"][0]["codigo"] == "origen"
    assert "siguiente_paso" in b["pendientes"][0]


def test_borrador_no_expone_datos_de_usuario_ni_cotizaciones():
    c = _clasificador()
    c.compraventas = [SimpleNamespace(
        user_id="NO_INCLUIR", txid="NO_INCLUIR",
        fecha="2025-09-05", cantidad="9999.99", importe="888888.88")]
    b = construir_borrador_binance(c, {"incidencias": []})
    assert "NO_INCLUIR" not in repr(b)
    assert "9999.99" not in repr(b)
    assert "888888.88" not in repr(b)
    assert "2025-09-05" not in repr(b)
    assert b["pendientes"] == []
    assert b["estado"] == "INCOMPLETO_NO_APTO_PARA_DECLARAR"


def test_sin_clasificacion_no_se_emite_borrador_engañoso():
    import pytest
    with pytest.raises(ValueError):
        construir_borrador_binance(None, {"incidencias": []})
