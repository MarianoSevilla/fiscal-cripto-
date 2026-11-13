"""Pruebas sintéticas del diagnóstico, nunca con operaciones reales."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_pendientes import diagnosticar_pendientes_binance


def _clasificador(**overrides):
    data = {
        "fuentes_materiales_no_soportadas": [],
        "earn_reconciliation": None,
        "earn_events": [],
        "movimientos": [],
        "commission_evidence_summary": None,
        "dust_evidence_summary": None,
        "valoraciones_pendientes": [],
        "comisiones_pendientes": [],
        "desconocidas": [],
        "_unknown_files": 0,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _codes(report):
    return {i["codigo"] for i in report["incidencias"]}


def test_sin_marcadores_no_inventa_archivos_ni_autoriza_fifo():
    result = diagnosticar_pendientes_binance(_clasificador())
    assert result["estado"] == "pendiente_validacion"
    assert result["validez_fiscal_acreditada"] is False
    assert result["incidencias"] == []
    assert "primera adquisición" in result["aviso"]


def test_cobertura_earn_parcial_y_solapamiento_son_incidencias_distintas():
    c = _clasificador(
        fuentes_materiales_no_soportadas=[
            "earn_fuentes_no_conciliadas",
            "filas_identicas_entre_exportaciones_sin_id_unico",
        ],
        earn_reconciliation=SimpleNamespace(ledger_unmatched=7),
        earn_events=[object()],
    )
    result = diagnosticar_pendientes_binance(c)
    assert {"earn_cobertura", "earn_lotes", "solapamiento"} <= _codes(result)
    assert "otras_incidencias" not in _codes(result)
    assert all(isinstance(i["siguiente_paso"], str) for i in result["incidencias"])


def test_deposito_externo_pide_origen_no_impone_coste_cero():
    c = _clasificador(movimientos=[
        SimpleNamespace(subtipo="Depósito cripto", cantidad=3),
    ])
    result = diagnosticar_pendientes_binance(c)
    assert _codes(result) == {"depositos_origen"}
    assert "coste EUR" in result["incidencias"][0]["siguiente_paso"]
    assert "coste cero" not in result["incidencias"][0]["siguiente_paso"]


def test_separa_spot_comisiones_permutas_y_dust():
    c = _clasificador(
        fuentes_materiales_no_soportadas=[
            "spot_orders_ejecutadas_sin_fills_completos",
            "small_assets_exchange_bnb_sin_permuta_valorada",
        ],
        commission_evidence_summary=SimpleNamespace(records=10),
        dust_evidence_summary=SimpleNamespace(rows=4),
        valoraciones_pendientes=[{"motivo": "permuta_sin_valor_eur"}],
        comisiones_pendientes=[{"motivo": "fee"}],
    )
    result = diagnosticar_pendientes_binance(c)
    assert {
        "spot_fills", "comisiones_afiliacion", "conversion_saldos",
        "valoracion_eur", "comisiones_cripto",
    } <= _codes(result)
    assert result["validez_fiscal_acreditada"] is False


def test_marcador_desconocido_no_se_ignora_ni_se_exponen_datos():
    c = _clasificador(
        fuentes_materiales_no_soportadas=["nueva_fuente_sin_interpretar"],
    )
    result = diagnosticar_pendientes_binance(c)
    assert _codes(result) == {"otras_incidencias"}
    assert "nueva_fuente_sin_interpretar" not in str(result)


def test_earn_informa_anos_y_contadores_sin_detalles_privados():
    c = _clasificador(
        earn_reconciliation=SimpleNamespace(
            ledger_unmatched=5,
            ledger_unmatched_by_year=((2020, 2), (2023, 3)),
            ledger_unmatched_by_year_direction=(
                (2020, "subscription", 1),
                (2020, "redemption", 1),
                (2023, "subscription", 3),
            ),
        ),
        fuentes_materiales_no_soportadas=["earn_fuentes_no_conciliadas"],
    )
    diag = diagnosticar_pendientes_binance(c)
    issue = next(i for i in diag["incidencias"]
                 if i["codigo"] == "earn_cobertura")
    assert "2020 (2 movimientos)" in issue["descripcion"]
    assert "2023 (3 movimientos)" in issue["descripcion"]
    assert "4 suscripciones y 1 reembolsos" in issue["descripcion"]
    assert "no adquisiciones fiscales acreditadas" in issue["descripcion"]
    assert "EUR" in issue["siguiente_paso"]
    assert diag["validez_fiscal_acreditada"] is False


def test_earn_no_infiere_periodos_cuando_no_estan_comprobados():
    c = _clasificador(
        earn_reconciliation=SimpleNamespace(
            ledger_unmatched=2,
            ledger_unmatched_by_year=((2020, 1),),
        )
    )
    diag = diagnosticar_pendientes_binance(c)
    issue = next(i for i in diag["incidencias"]
                 if i["codigo"] == "earn_cobertura")
    assert "Períodos identificados" not in issue["descripcion"]
    assert diag["validez_fiscal_acreditada"] is False


def test_earn_no_deduce_tipos_si_contadores_no_coinciden():
    c = _clasificador(
        earn_reconciliation=SimpleNamespace(
            ledger_unmatched=3,
            ledger_unmatched_by_year=((2021, 3),),
            ledger_unmatched_by_year_direction=((2021, "subscription", 2),),
        ),
    )
    issue = next(i for i in diagnosticar_pendientes_binance(c)["incidencias"]
                 if i["codigo"] == "earn_cobertura")
    assert "2021 (3 movimientos)" in issue["descripcion"]
    assert "Desglose:" not in issue["descripcion"]
