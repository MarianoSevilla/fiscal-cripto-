"""Pruebas totalmente sintéticas para el diagnóstico de canjes Dust -> BNB."""
from decimal import Decimal
from pathlib import Path
import csv
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_dust_evidence import (
    BinanceDustEvidenceError, DUST_OPERATION, audit_binance_dust,
)
from clasificador_binance_multi import BinanceMultiUserError, ClasificadorBinanceMulti


def leg(asset, amount, stamp="2021-08-13 08:04:02", wallet="Spot"):
    return {"operación": DUST_OPERATION, "tiempo": stamp, "cuenta": wallet,
            "moneda": asset, "cambio": amount}


def test_multiple_assets_one_second_remain_distinct_legs():
    rows = [leg("AAA", "-2.125"), leg("BBB", "-0.125"),
            leg("BNB", "0.0004"), leg("BNB", "0.0005")]
    audit, bundles = audit_binance_dust(rows)
    assert audit.rows == 4 and audit.groups == 1
    assert audit.multi_leg_groups == 1
    assert audit.single_pair_candidates == 0
    assert bundles[0].debits == (("AAA", Decimal("2.125")),
                                 ("BBB", Decimal("0.125")))
    assert bundles[0].credits == (("BNB", Decimal("0.0004")),
                                  ("BNB", Decimal("0.0005")))
    assert audit.bnb_credited == Decimal("0.0009")
    assert not bundles[0].fiscal_ready


def test_single_pair_only_candidate_not_accredited_exchange():
    report, bundles = audit_binance_dust(
        [leg("AAA", "-1"), leg("BNB", "0.01")]
    )
    assert report.single_pair_candidates == 1
    assert report.multi_leg_groups == 0
    assert not report.fiscal_ready and not bundles[0].fiscal_ready


def test_missing_positive_bnb_is_not_invented():
    report, bundles = audit_binance_dust([leg("AAA", "-0.01")])
    assert report.groups_without_bnb_credit == 1
    assert report.bnb_credited == 0
    assert bundles[0].credits == ()
    assert not bundles[0].fiscal_ready


def test_cross_wallet_same_second_not_merged():
    report, bundles = audit_binance_dust([
        leg("AAA", "-0.1"), leg("BNB", "0.05"),
        leg("BBB", "-0.1", wallet="Funding"),
        leg("BNB", "0.05", wallet="Funding"),
    ])
    assert report.groups == 2
    assert report.single_pair_candidates == 2
    assert {b.wallet for b in bundles} == {"Spot", "Funding"}


def test_same_asset_and_amount_repetitions_are_preserved():
    report, groups = audit_binance_dust([
        leg("AAA", "-0.2"), leg("AAA", "-0.2"),
        leg("BNB", "0.0002"), leg("BNB", "0.0002"),
    ])
    assert report.rows == 4
    assert len(groups[0].debits) == 2
    assert len(groups[0].credits) == 2


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "0", "", "x", 0.02, True])
def test_bad_amounts_fail_closed(invalid):
    with pytest.raises(BinanceDustEvidenceError):
        audit_binance_dust([leg("AAA", invalid)])


def test_invalid_calendar_date_fail_closed():
    with pytest.raises(BinanceDustEvidenceError):
        audit_binance_dust([leg("AAA", "-1", stamp="2021-02-30 10:00:00")])


def test_multisource_collects_dust_without_minting_fifo_swaps(tmp_path):
    p = tmp_path / "dust.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID de usuario", "Tiempo", "Cuenta", "Operación",
                    "Moneda", "Cambio", "Observación"])
        w.writerows([
            ["synthetic", "2021-08-13 08:04:02", "Spot", DUST_OPERATION, "AAA", "-2", ""],
            ["synthetic", "2021-08-13 08:04:02", "Spot", DUST_OPERATION, "BBB", "-1", ""],
            ["synthetic", "2021-08-13 08:04:02", "Spot", DUST_OPERATION, "BNB", "0.003", ""],
        ])
    result = ClasificadorBinanceMulti([str(p)]).clasificar()
    assert result.dust_evidence_summary.rows == 3
    assert result.dust_evidence_summary.groups == 1
    assert result.dust_evidence_summary.multi_leg_groups == 1
    assert len(result.dust_evidence) == 1
    assert not result.swaps and not result.compraventas
    assert "small_assets_exchange_bnb_sin_permuta_valorada" in (
        result.fuentes_materiales_no_soportadas)
