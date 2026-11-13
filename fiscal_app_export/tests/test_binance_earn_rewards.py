"""Pruebas sin importes, cuentas ni fechas reales de clientes."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import csv
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_earn_rewards import BinanceEarnRewardsError, reconcile_earn_rewards
from clasificador_binance_multi import ClasificadorBinanceMulti


def reward(stamp, qty, *, asset="ABC", kind="Real-time APR Rewards"):
    return SimpleNamespace(
        source="earn_flexible_rewards", original_time=stamp, asset=asset,
        amount=Decimal(qty), kind=kind,
    )


def subscription(stamp, qty, *, kind="Auto"):
    return SimpleNamespace(
        source="earn_flexible_subscription", original_time=stamp, asset="ABC",
        amount=Decimal(qty), kind=kind,
    )


def tx(stamp, qty, *, asset="ABC", operation="Simple Earn Flexible Interest"):
    return {"operación": operation, "tiempo": stamp, "moneda": asset,
            "cambio": qty, "cuenta": "Spot"}


def test_un_espejo_exactamente_igual_no_crea_un_segundo_lote():
    e = reward("2025-01-04 08:04:05", "0.125",
               kind="Bonus Tiered APR Rewards")
    bridge, candidates = reconcile_earn_rewards(
        [e], [tx("2025-01-04 08:04:05", "0.125")]
    )
    assert bridge.matched_exact == 1
    assert bridge.candidate_lots == len(candidates) == 1
    assert candidates[0].quantity == Decimal("0.125")
    assert candidates[0].cost_eur is None
    assert candidates[0].acquired_at_for_fifo is None
    assert not bridge.fiscal_ready


def test_apr_en_tiempo_real_sin_espejo_spot_es_normal_pero_no_fiscal():
    bridge, candidates = reconcile_earn_rewards(
        [reward("2025-01-04", "0.01")], []
    )
    assert bridge.native_not_in_ledger == 0  # Real-time no tiene espejo Spot.
    assert bridge.real_time_apr_records == 1
    assert bridge.ledger_not_in_native == 0
    assert bridge.native_day_only == 1
    assert candidates[0].precision == "day"
    assert candidates[0].expected_wallet == "EARN_FLEXIBLE"
    assert candidates[0].acquired_at_for_fifo is None
    assert not bridge.fiscal_ready


def test_bonus_es_recompensa_spot_no_traslado_de_principal():
    bridge, candidates = reconcile_earn_rewards(
        [reward("2025-01-05 01:02:03", "0.02",
                kind="Bonus Tiered APR Rewards")], []
    )
    assert bridge.native_records == 1
    assert candidates[0].expected_wallet == "SPOT"
    assert candidates[0].cost_eur is None


def test_subscripcion_auto_no_es_recompensa_ni_lote():
    bridge, candidates = reconcile_earn_rewards(
        [subscription("2025-01-04 02:00:00", "2")], []
    )
    assert bridge.auto_subscriptions == 1
    assert bridge.native_records == 0
    assert candidates == ()


def test_dos_recompensas_repetidas_no_son_un_unico_ingreso():
    e = reward("2025-01-01 08:00:00", "0.125",
               kind="Bonus Tiered APR Rewards")
    bridge, candidates = reconcile_earn_rewards(
        [e, e], [tx("2025-01-01 08:00:00", "0.125")] * 2
    )
    assert bridge.matched_exact == 2
    assert bridge.repeated_match_records == 2
    assert len(candidates) == 2
    assert candidates[0].source_ordinal != candidates[1].source_ordinal


def test_diferencia_de_segundos_se_reconoce_solo_a_nivel_dia():
    bridge, candidates = reconcile_earn_rewards(
        [reward("2025-01-04 01:01:01", "0.125",
                kind="Bonus Tiered APR Rewards")],
        [tx("2025-01-04 01:01:02", "0.125")],
    )
    assert bridge.matched_exact == 0
    assert bridge.matched_by_day == 1
    assert bridge.native_not_in_ledger == bridge.ledger_not_in_native == 0
    assert not bridge.fiscal_ready


def test_suma_diaria_igual_con_filas_distintas_no_da_match_univoco():
    bridge, candidates = reconcile_earn_rewards(
        [reward("2025-01-04", "0.1", kind="Bonus Tiered APR Rewards"),
         reward("2025-01-04", "0.2", kind="Bonus Tiered APR Rewards")],
        [tx("2025-01-04 09:00:00", "0.3")],
    )
    assert bridge.matched_exact == bridge.matched_by_day == 0
    assert bridge.daily_aggregate_only_groups == 1
    assert bridge.aggregate_only_native_records == 2
    assert bridge.aggregate_only_ledger_records == 1
    assert len(candidates) == 2
    assert bridge.native_not_in_ledger == bridge.ledger_not_in_native == 0


def test_sumatorio_solo_parecido_no_se_admite_como_cuadre():
    bridge, _ = reconcile_earn_rewards(
        [reward("2025-01-04", "0.10000001", kind="Bonus Tiered APR Rewards"),
         reward("2025-01-04", "0.2", kind="Bonus Tiered APR Rewards")],
        [tx("2025-01-04 09:00:00", "0.3")],
    )
    assert bridge.daily_aggregate_only_groups == 0
    assert bridge.native_not_in_ledger == 2
    assert bridge.ledger_not_in_native == 1


def test_interes_ledger_sin_zip_earn_es_cobertura_incompleta():
    bridge, candidates = reconcile_earn_rewards(
        [], [tx("2025-01-04 12:00:00", "0.125")]
    )
    assert bridge.ledger_not_in_native == 1
    assert candidates == ()


def test_otros_rendimientos_no_se_confunden_con_earn_flexible():
    bridge, candidates = reconcile_earn_rewards(
        [reward("2025-01-04", "0.125")],
        [tx("2025-01-04 12:00:00", "0.125",
            operation="Simple Earn Locked Rewards")],
    )
    assert bridge.native_not_in_ledger == 0
    assert bridge.ledger_records == 0
    assert len(candidates) == 1


def test_tipo_no_documentado_no_crea_lote():
    bridge, candidates = reconcile_earn_rewards(
        [reward("2025-01-04", "0.01", kind="Unknown Bonus")], []
    )
    assert bridge.unknown_native_kinds == 1
    assert bridge.candidate_lots == 0
    assert candidates == ()


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "0", "0.1x", 0.1])
def test_interes_ledger_invalido_se_rechaza(bad):
    with pytest.raises(BinanceEarnRewardsError):
        reconcile_earn_rewards([], [tx("2025-01-04 12:00:00", bad)])


def test_fecha_ledger_invalida_se_rechaza_sin_rellenar_hora():
    with pytest.raises(BinanceEarnRewardsError):
        reconcile_earn_rewards([], [tx("2025-02-30 12:00:00", "1")])


def test_clasificador_recompensa_nativa_y_ledger_mantiene_guard(tmp_path):
    def csv_file(name, headers, rows):
        p = tmp_path / name
        with p.open("w", encoding="utf-8-sig", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(headers)
            writer.writerows(rows)
        return str(p)
    native = csv_file("rewards.csv",
                      ["Tiempo", "Moneda", "Cantidad", "Tipo"],
                      [["2025-01-04 11:00:00", "ABC", "0.125",
                        "Bonus Tiered APR Rewards"]])
    ledger = csv_file("ledger.csv",
                      ["ID de usuario", "Tiempo", "Cuenta", "Operación",
                       "Moneda", "Cambio", "Observación"],
                      [["synthetic", "2025-01-04 12:00:00", "Spot",
                        "Simple Earn Flexible Interest", "ABC", "0.125", ""]])
    c = ClasificadorBinanceMulti([native, ledger]).clasificar()
    assert c.earn_reward_reconciliation.matched_by_day == 1
    assert len(c.earn_reward_candidates) == 1
    assert c.earn_reward_candidates[0].cost_eur is None
    assert c.earn_reward_reconciliation.fiscal_ready is False
    assert "earn_flexible_requiere_inventario_y_valoracion_fiscal" in (
        c.fuentes_materiales_no_soportadas
    )


def test_airdrop_nativo_y_ledger_es_un_solo_candidato_sin_billetera_supuesta():
    native = reward("2025-01-04 05:00:01", "0.003",
                    kind="Airdrop Rewards")
    ledger = tx("2025-01-04 05:00:03", "0.003",
                operation="Simple Earn Flexible Airdrop")
    bridge, candidates = reconcile_earn_rewards([native], [ledger])
    assert bridge.native_records == bridge.ledger_records == 1
    assert bridge.matched_by_day == 1
    assert bridge.native_not_in_ledger == bridge.ledger_not_in_native == 0
    assert bridge.unknown_native_kinds == 0
    assert bridge.unlocated_native_rewards == 1
    assert bridge.candidate_lots == len(candidates) == 1
    assert candidates[0].expected_wallet is None
    assert candidates[0].cost_eur is None
    assert not bridge.fiscal_ready


def test_recompensa_realtime_no_puede_suplantar_bonus_mismo_importe():
    e = reward("2025-01-04 10:00:00", "0.03")
    l = tx("2025-01-04 10:00:00", "0.03")
    bridge, candidates = reconcile_earn_rewards([e], [l])
    assert bridge.matched_exact == bridge.matched_by_day == 0
    assert bridge.real_time_apr_records == 1
    assert bridge.ledger_not_in_native == 1
    assert bridge.native_not_in_ledger == 0
    assert len(candidates) == 1


def test_bono_y_airdrop_con_igual_importe_no_se_mezclan():
    e = reward("2025-01-04 10:00:00", "0.03",
               kind="Airdrop Rewards")
    l = tx("2025-01-04 10:00:00", "0.03")
    bridge, _ = reconcile_earn_rewards([e], [l])
    assert bridge.matched_exact == bridge.matched_by_day == 0
    assert bridge.native_not_in_ledger == 1
    assert bridge.ledger_not_in_native == 1
    assert bridge.unlocated_native_rewards == 1


def test_cuatro_tipos_de_lotes_no_se_fabrican_con_mismo_importe():
    earn_events = [
        reward("2025-01-04", "0.03"),
        reward("2025-01-04 10:00:00", "0.03",
               kind="Bonus Tiered APR Rewards"),
        reward("2025-01-04 10:00:00", "0.03",
               kind="Airdrop Rewards"),
        subscription("2025-01-04 10:01:00", "0.03"),
    ]
    ledger = [
        tx("2025-01-04 10:00:00", "0.03"),
        tx("2025-01-04 10:00:00", "0.03",
           operation="Simple Earn Flexible Airdrop"),
    ]
    report, candidates = reconcile_earn_rewards(earn_events, ledger)
    assert report.native_records == 3
    assert report.ledger_records == 2
    assert report.matched_exact == 2
    assert report.real_time_apr_records == 1
    assert report.auto_subscriptions == 1
    assert report.candidate_lots == len(candidates) == 3
    assert report.unlocated_native_rewards == 1
    assert not report.fiscal_ready


def test_cobertura_recompensas_2020_2023_preserva_asientos_sin_lotes():
    rows = [
        tx("2020-12-01 12:00:00", "0.25"),
        tx("2021-06-01 12:00:00", "0.50"),
        tx("2022-06-01 12:00:00", "0.75",
           operation="Simple Earn Flexible Airdrop"),
        tx("2022-06-01 12:00:00", "0.75",
           operation="Simple Earn Flexible Airdrop"),
        tx("2023-01-01 12:00:00", "0.10"),
    ]
    report, candidates = reconcile_earn_rewards([], rows)
    assert candidates == ()
    assert report.ledger_records == report.ledger_not_in_native == 5
    assert report.ledger_missing_by_year_kind == (
        (2020, "Bonus Tiered APR Rewards", 1),
        (2021, "Bonus Tiered APR Rewards", 1),
        (2022, "Airdrop Rewards", 2),
        (2023, "Bonus Tiered APR Rewards", 1),
    )
    assert len(report.ledger_unresolved_evidence) == 5
    assert [x.ledger_ordinal for x in report.ledger_unresolved_evidence] == [
        0, 1, 2, 3, 4
    ]
    assert all(
        x.relation == "sin_fuente_nativa" and x.cost_eur is None
        and x.acquired_at_for_fifo is None and not x.fiscal_ready
        for x in report.ledger_unresolved_evidence
    )
    assert not report.fiscal_ready


def test_coincidencias_exactas_y_diarias_no_crean_recompensas_adicionales():
    events = [
        reward("2024-02-01 10:00:00", "0.1",
               kind="Bonus Tiered APR Rewards"),
        reward("2024-02-02 10:00:00", "0.2",
               kind="Bonus Tiered APR Rewards"),
    ]
    ledger = [
        tx("2024-02-01 10:00:00", "0.1"),
        tx("2024-02-02 10:00:03", "0.2"),
    ]
    report, candidates = reconcile_earn_rewards(events, ledger)
    assert report.matched_exact == report.matched_by_day == 1
    assert report.ledger_not_in_native == report.native_not_in_ledger == 0
    assert report.ledger_unresolved_evidence == ()
    assert report.ledger_missing_by_year_kind == ()
    assert report.native_missing_by_year_kind == ()
    assert len(candidates) == 2
    assert not report.fiscal_ready


def test_total_diario_compatible_conserva_asiento_sin_identidad_individual():
    events = [
        reward("2024-02-01", "0.1", kind="Bonus Tiered APR Rewards"),
        reward("2024-02-01", "0.2", kind="Bonus Tiered APR Rewards"),
    ]
    report, candidates = reconcile_earn_rewards(
        events, [tx("2024-02-01 09:00:00", "0.3")]
    )
    assert report.daily_aggregate_only_groups == 1
    assert report.ledger_not_in_native == report.native_not_in_ledger == 0
    assert report.ledger_missing_by_year_kind == ()
    assert report.native_missing_by_year_kind == ()
    assert len(report.ledger_unresolved_evidence) == 1
    assert report.ledger_unresolved_evidence[0].relation == "solo_total_diario"
    assert report.ledger_unresolved_evidence[0].cost_eur is None
    assert len(candidates) == 2
    assert not report.fiscal_ready


def test_recompensas_solo_nativas_no_desaparecen_en_conciliacion():
    events = [
        reward("2024-01-01 10:00:00", "0.1",
               kind="Bonus Tiered APR Rewards"),
        reward("2024-01-02 10:00:00", "0.2",
               kind="Bonus Tiered APR Rewards"),
    ]
    report, candidates = reconcile_earn_rewards(events, [])
    assert report.native_records == report.native_not_in_ledger == 2
    assert report.native_missing_by_year_kind == (
        (2024, "Bonus Tiered APR Rewards", 2),
    )
    assert report.ledger_unresolved_evidence == ()
    assert [x.quantity for x in candidates] == [
        Decimal("0.1"), Decimal("0.2"),
    ]
    assert all(x.cost_eur is None and not x.fiscal_ready for x in candidates)


def test_apr_diario_se_separa_por_ejercicio_no_inventa_fecha_fifo():
    report, candidates = reconcile_earn_rewards(
        [reward("2025-12-31", "0.01"), reward("2026-01-01", "0.02")],
        [],
    )
    assert report.native_day_only_by_year == ((2025, 1), (2026, 1))
    assert report.real_time_apr_records == 2
    assert report.ledger_not_in_native == 0
    assert all(x.acquired_at_for_fifo is None for x in candidates)
    assert not report.fiscal_ready


def test_recompensa_repetida_no_se_descarta_en_resumen_anual():
    events = [
        reward("2024-01-01", "0.02", kind="Bonus Tiered APR Rewards"),
    ]
    ledger = [
        tx("2024-01-01 09:00:00", "0.02"),
        tx("2024-01-01 09:00:00", "0.02"),
    ]
    report, _ = reconcile_earn_rewards(events, ledger)
    assert report.matched_by_day == 1
    assert report.ledger_not_in_native == 1
    assert report.ledger_missing_by_year_kind == (
        (2024, "Bonus Tiered APR Rewards", 1),
    )
    assert [x.ledger_ordinal for x in report.ledger_unresolved_evidence] == [1]
    assert report.ledger_unresolved_evidence[0].cost_eur is None
