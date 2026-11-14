"""Pruebas sintéticas de priorización: jamás sustituyen un FIFO completo."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_earn_impact import (
    BinanceEarnImpactError, analizar_impacto_earn_historico,
)


def evidence(stamp, asset, *, relation="sin_fuente_nativa"):
    return SimpleNamespace(
        ledger_time=stamp, asset=asset, relation=relation,
        cost_eur=None, fiscal_ready=False,
    )


def ledger(stamp, kind, asset, value):
    return {"tiempo": stamp, "operación": kind,
            "moneda": asset, "cambio": value}


def swap(stamp, kind, given, amount="1"):
    return SimpleNamespace(source=kind, local_time=stamp,
                           given_asset=given, given_amount=Decimal(amount))


def test_2025_distingue_riesgo_observado_sin_declarar_fifo_fiscal():
    report = analizar_impacto_earn_historico(
        SimpleNamespace(ledger_unresolved_evidence=[
            evidence("2020-02-01 01:00:00", "AAA"),
            evidence("2021-02-01 01:00:00", "AAA"),
            evidence("2022-02-01 01:00:00", "BBB"),
            evidence("2023-02-01 01:00:00", "CCC"),
            evidence("2025-02-01 01:00:00", "AAA"),  # no anterior a 2025
            evidence("2020-02-01 01:00:00", "DDD",
                     relation="solo_total_diario"),  # no falta fuente
        ]),
        [
            ledger("2025-01-01 08:00:00", "Transaction Sold", "AAA", "-1"),
            ledger("2025-01-01 08:00:00", "Transaction Spend", "EUR", "-5"),
            ledger("2025-01-01 08:00:00", "Simple Earn Flexible Subscription",
                   "BBB", "-1"),  # solo movimiento interno
            ledger("2025-01-01 08:00:00", "Withdraw", "BBB", "-0.5"),
            ledger("2024-01-01 08:00:00", "Binance Convert", "CCC", "-1"),
        ],
        [swap("2025-02-03 10:00:00", "Convert", "CCC")],
        exercise=2025,
    )
    assert report.prior_ledger_only_rewards == 4
    assert report.with_possible_disposal == 3
    assert report.without_observed_disposal == 1
    assert report.affected_assets == 2
    assert report.assets_without_observed_disposal == 1
    assert report.with_external_withdrawal == 1
    assert report.fifo_acreditado is False


def test_transferencia_no_se_parece_a_venta_ni_un_retiro_demuestra_venta():
    report = analizar_impacto_earn_historico(
        SimpleNamespace(ledger_unresolved_evidence=[
            evidence("2023-01-01 00:00:00", "AAA"),
        ]),
        [
            ledger("2025-01-01 00:00:00", "Transfer", "AAA", "-1"),
            ledger("2025-01-02 00:00:00", "Withdraw", "AAA", "-1"),
            ledger("2025-01-03 00:00:00", "Transaction Sold", "AAA", "1"),
        ],
        [], exercise=2025,
    )
    assert report.with_possible_disposal == 0
    assert report.without_observed_disposal == 1
    assert report.with_external_withdrawal == 1
    assert not report.fifo_acreditado


def test_native_spot_o_convert_se_consideran_sin_duplicar_activo():
    report = analizar_impacto_earn_historico(
        SimpleNamespace(ledger_unresolved_evidence=[
            evidence("2020-01-01 00:00:00", "ETH"),
            evidence("2021-01-01 00:00:00", "ETH"),
        ]),
        [
            ledger("2025-01-03 12:00:00", "Binance Convert", "ETH", "-1")
        ],
        [
            swap("2025-01-03 12:00:00", "Spot SELL", "ETH"),
            swap("2025-01-03 12:00:00", "Spot BUY", "EUR"),
        ],
        exercise=2025,
    )
    assert report.with_possible_disposal == 2
    assert report.affected_assets == 1


def test_ninguna_salida_observada_no_acredita_irrelevancia():
    report = analizar_impacto_earn_historico(
        SimpleNamespace(ledger_unresolved_evidence=[
            evidence("2021-01-01 00:00:00", "ABC"),
        ]),
        [], [], exercise=2025,
    )
    assert report.without_observed_disposal == 1
    assert report.fifo_acreditado is False


@pytest.mark.parametrize("year", [True, "2025", 0, 2018, 2201])
def test_ejercicio_no_verificado_rechazado(year):
    with pytest.raises(BinanceEarnImpactError, match="Ejercicio"):
        analizar_impacto_earn_historico(
            SimpleNamespace(ledger_unresolved_evidence=()),
            [], [], exercise=year,
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "abc", -0.1])
def test_debito_2025_no_fiable_no_puede_marcarse_como_ausencia_de_impacto(value):
    with pytest.raises(BinanceEarnImpactError, match="Cantidad"):
        analizar_impacto_earn_historico(
            SimpleNamespace(ledger_unresolved_evidence=[
                evidence("2023-01-01 00:00:00", "ABC"),
            ]),
            [ledger("2025-01-01 01:00:00", "Binance Convert", "ABC", value)],
            [], exercise=2025,
        )


def test_debito_con_separador_de_miles_binance_mantiene_prioridad():
    result = analizar_impacto_earn_historico(
        SimpleNamespace(ledger_unresolved_evidence=[
            evidence("2020-01-01 00:00:00", "ABC"),
        ]),
        [ledger("2025-01-01 10:00:00", "Binance Convert", "ABC",
                "-1,234.567890")],
        [], exercise=2025,
    )
    assert result.with_possible_disposal == 1
    assert result.fifo_acreditado is False


@pytest.mark.parametrize("raw", ["1,23.45", "-1,23", "-1.234,5"])
def test_separadores_miles_irregulares_no_se_interpretan_como_eur(raw):
    with pytest.raises(BinanceEarnImpactError, match="Cantidad"):
        analizar_impacto_earn_historico(
            SimpleNamespace(ledger_unresolved_evidence=[
                evidence("2023-01-01 00:00:00", "ABC"),
            ]),
            [ledger("2025-01-01 01:00:00", "Binance Convert", "ABC",
                    raw)],
            [], exercise=2025,
        )
