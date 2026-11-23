"""Borrador provisional Binance. Todas las pruebas usan datos inventados."""
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_borrador import (
    construir_borrador_binance, clasificar_accion_incidencia,
)


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
        {"codigo": "origen", "tipo": "documentacion", "titulo": "Lotes pendientes",
         "descripcion": "Falta coste de adquisición",
         "siguiente_paso": "Aportar fuente original"}
    ], "evidencias": [{
        "codigo": "compras_eur", "titulo": "Compras pagadas en EUR",
        "descripcion": "Hay adquisiciones con precio y comisión documentados.",
        "siguiente_paso": "Conservar recibos originales",
    }]}
    b = construir_borrador_binance(
        _clasificador(), diagnostico, "2025",
        archivos_aportados=[{"nombre": "Binance/Spot-(UTC+1).csv", "formato": "csv", "bytes": 123}],
        alcance_declarado="solo_binance",
    )
    assert b["estado"] == "INCOMPLETO_NO_APTO_PARA_DECLARAR"
    assert b["no_es_informe_fiscal"] is True
    assert b["pdf_fiscal_disponible"] is False
    assert b["costes_fifo_calculados"] is False
    assert b["ganancias_y_perdidas_eur"] is None
    assert b["operaciones_detectadas"]["compraventas_candidatas"] == 2
    assert b["operaciones_detectadas"]["comisiones_referidos_analizadas"] == 12
    assert len(b["fuentes"]) == 2
    assert b["pendientes"][0]["codigo"] == "origen"
    assert b["pendientes"][0]["accion"] == "APORTAR_DOCUMENTACION"
    assert "siguiente_paso" in b["pendientes"][0]
    assert b["evidencias"][0]["titulo"] == "Compras pagadas en EUR"
    assert b["archivos_aportados"] == [{
        "nombre": "Spot-(UTC+1).csv", "formato": "csv", "bytes": 123,
    }]
    assert b["alcance_declarado"] == "solo_binance"


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


def test_clasificacion_de_acciones_de_incidente_es_sencilla_y_conservadora():
    assert clasificar_accion_incidencia("archivo") == "CORREGIR_ARCHIVO"
    assert clasificar_accion_incidencia("documentacion") == "APORTAR_DOCUMENTACION"
    assert clasificar_accion_incidencia("soporte") == "CONTACTAR_SOPORTE"
    assert clasificar_accion_incidencia("reintentar") == "REINTENTAR"
    assert clasificar_accion_incidencia("nuevo_tipo_no_previsto") == "MANTENER_PROVISIONAL"
