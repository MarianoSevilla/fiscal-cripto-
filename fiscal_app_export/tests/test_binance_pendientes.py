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
    assert "4 suscripciones y 1 reembolso" in issue["descripcion"]
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


def test_diagnostico_recompensas_historicas_diferencia_dos_brechas():
    c = _clasificador(
        fuentes_materiales_no_soportadas=[
            "earn_intereses_ledger_sin_fuente_nativa_suficiente",
            "earn_recompensas_nativas_sin_asiento_general",
        ],
        earn_reward_reconciliation=SimpleNamespace(
            ledger_not_in_native=5,
            native_not_in_ledger=2,
            ledger_missing_by_year_kind=(
                (2020, "Simple Earn Flexible Interest", 1),
                (2021, "Simple Earn Flexible Interest", 2),
                (2021, "Simple Earn Flexible Airdrop", 2),
            ),
            native_missing_by_year_kind=(
                (2024, "Bonus Tiered APR Rewards", 2),
            ),
        ),
    )
    diag = diagnosticar_pendientes_binance(c)
    codes = _codes(diag)
    assert "earn_recompensas_sin_nativo" in codes
    assert "earn_recompensas_sin_ledger" in codes
    assert "otras_incidencias" not in codes
    missing = next(x for x in diag["incidencias"]
                   if x["codigo"] == "earn_recompensas_sin_nativo")
    assert "2020: 1" in missing["descripcion"]
    assert "2021: 4" in missing["descripcion"]
    assert "5 abonos" in missing["descripcion"]
    assert "coste EUR inventado" in missing["siguiente_paso"]
    native = next(x for x in diag["incidencias"]
                  if x["codigo"] == "earn_recompensas_sin_ledger")
    assert "2024: 2" in native["descripcion"]
    assert "2 recompensas nativas" in native["descripcion"]
    assert diag["validez_fiscal_acreditada"] is False


def test_diagnostico_recompensas_sin_ano_comprobado_no_inventa_ano():
    c = _clasificador(
        earn_reward_reconciliation=SimpleNamespace(
            ledger_not_in_native=4,
            native_not_in_ledger=0,
            ledger_missing_by_year_kind=(
                ("fecha-secreta", "Bonus Tiered APR Rewards", 4),
            ),
        )
    )
    issue = next(x for x in diagnosticar_pendientes_binance(c)["incidencias"]
                 if x["codigo"] == "earn_recompensas_sin_nativo")
    assert "fecha-secreta" not in issue["descripcion"]
    assert "Por ejercicio:" not in issue["descripcion"]


def test_diagnostico_abonos_earn_en_custodia_fuera_de_spot():
    c = _clasificador(
        fuentes_materiales_no_soportadas=[
            "earn_abonos_en_custodia_no_conciliada",
        ],
        earn_reward_reconciliation=SimpleNamespace(
            ledger_not_in_native=1,
            native_not_in_ledger=0,
            ledger_other_wallet_records=1,
            ledger_missing_by_year_kind=(
                (2021, "Simple Earn Flexible Interest", 1),
            ),
        ),
    )
    report = diagnosticar_pendientes_binance(c)
    assert "earn_custodia_no_conciliada" in _codes(report)
    assert "earn_recompensas_sin_nativo" in _codes(report)
    assert "otras_incidencias" not in _codes(report)
    issue = next(i for i in report["incidencias"]
                 if i["codigo"] == "earn_custodia_no_conciliada")
    assert "1 apunte" in issue["descripcion"]
    assert "EUR" in issue["siguiente_paso"]
    assert report["validez_fiscal_acreditada"] is False


def test_priorizacion_2025_muestra_riesgo_sin_presentar_visto_bueno():
    c = _clasificador(
        earn_reward_reconciliation=SimpleNamespace(
            ledger_not_in_native=4,
            native_not_in_ledger=0,
        ),
        earn_reward_impact_2025=SimpleNamespace(
            exercise=2025,
            prior_ledger_only_rewards=4,
            with_possible_disposal=3,
            without_observed_disposal=1,
        ),
    )
    report = diagnosticar_pendientes_binance(c)
    issue = next(i for i in report["incidencias"]
                 if i["codigo"] == "earn_prioridad_2025")
    assert "3 corresponden" in issue["descripcion"]
    assert "Otros 1" in issue["descripcion"]
    assert "no demuestra irrelevancia fiscal" in issue["descripcion"]
    assert "sin excluir los demás" in issue["siguiente_paso"]
    assert report["validez_fiscal_acreditada"] is False


def test_prioridad_earn_no_inventa_impacto_2025_con_recuentos_incoherentes():
    c = _clasificador(
        earn_reward_impact_2025=SimpleNamespace(
            exercise=2025,
            prior_ledger_only_rewards=4,
            with_possible_disposal=6,
            without_observed_disposal=1,
        ),
    )
    report = diagnosticar_pendientes_binance(c)
    assert "earn_prioridad_2025" not in _codes(report)
    assert report["validez_fiscal_acreditada"] is False


def test_prioridad_earn_no_se_presenta_como_riesgo_2024():
    c = _clasificador(
        earn_reward_impact_2025=SimpleNamespace(
            exercise=2024,
            prior_ledger_only_rewards=3,
            with_possible_disposal=2,
            without_observed_disposal=1,
        ),
    )
    report = diagnosticar_pendientes_binance(c)
    assert "earn_prioridad_2025" not in _codes(report)
