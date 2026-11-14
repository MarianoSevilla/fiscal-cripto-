"""Synthetic-only EUR evidence regressions: no client movements."""
from decimal import Decimal

import pytest

from binance_legacy_eur_evidence import audit_legacy_eur_acquisitions
from binance_legacy_trade_evidence import audit_legacy_trades


def row(operation, asset, change, stamp="2021-01-01 12:00:00", wallet="Spot"):
    return {
        "operación": operation, "moneda": asset, "cambio": change,
        "tiempo": stamp, "cuenta": wallet,
    }


def audit(*rows):
    return audit_legacy_eur_acquisitions(audit_legacy_trades(rows))


def test_eur_debit_without_fee_is_cost_candidate():
    report = audit(row("Buy", "BTC", "0.2"), row("Sell", "EUR", "-400"))
    assert report.complete_cost_candidates == 1
    assert report.pending_third_asset_fee == 0
    candidate = report.candidates[0]
    assert candidate.received_net == Decimal("0.2")
    assert candidate.fee_total_cost_eur == Decimal("400")
    assert not report.fiscal_ready and not candidate.fiscal_ready


def test_fee_in_received_asset_reduces_lot_quantity():
    report = audit(row("Buy", "BTC", "0.2"),
                   row("Sell", "EUR", "-400"),
                   row("Fee", "BTC", "-0.001"))
    candidate = report.candidates[0]
    assert candidate.received_gross == Decimal("0.2")
    assert candidate.received_net == Decimal("0.199")
    assert candidate.fee_total_cost_eur == Decimal("400")


def test_fee_in_eur_adds_to_eur_cost():
    report = audit(row("Buy", "ETH", "1"),
                   row("Sell", "EUR", "-1500"),
                   row("Fee", "EUR", "-1.5"))
    assert report.candidates[0].fee_total_cost_eur == Decimal("1501.5")


def test_bnb_fee_keeps_full_cost_unknown():
    report = audit(row("Buy", "BTC", "0.2"),
                   row("Sell", "EUR", "-400"),
                   row("Fee", "BNB", "-0.001"))
    assert report.pending_third_asset_fee == 1
    assert report.complete_cost_candidates == 0
    candidate = report.candidates[0]
    assert candidate.eur_paid == Decimal("400")
    assert candidate.fee_total_cost_eur is None
    assert candidate.reason == "third_asset_fee_missing_eur"


def test_mixed_received_and_third_fee_never_claims_complete_cost():
    report = audit(row("Buy", "BTC", "0.2"),
                   row("Sell", "EUR", "-400"),
                   row("Fee", "BTC", "-0.001"),
                   row("Fee", "BNB", "-0.001"))
    assert report.candidates[0].received_net == Decimal("0.199")
    assert report.candidates[0].fee_total_cost_eur is None


def test_stablecoin_spend_is_not_eur():
    report = audit(row("Buy", "BTC", "0.2"),
                   row("Sell", "USDT", "-400"))
    assert report.candidates == () and report.other_legacy_groups == 1


def test_eur_received_is_proceeds_not_acquisition_cost():
    report = audit(row("Buy", "EUR", "400"),
                   row("Sell", "BTC", "-0.2"))
    assert report.candidates == () and report.other_legacy_groups == 1


def test_multifill_second_remains_ambiguous():
    report = audit(row("Buy", "BTC", "0.2"),
                   row("Sell", "EUR", "-400"),
                   row("Buy", "BTC", "0.1"),
                   row("Sell", "EUR", "-200"))
    assert report.candidates == () and report.other_legacy_groups == 1


def test_fee_exceeding_received_amount_creates_no_candidate():
    report = audit(row("Buy", "BTC", "0.2"),
                   row("Sell", "EUR", "-400"),
                   row("Fee", "BTC", "-0.3"))
    assert report.candidates == () and report.other_legacy_groups == 1


def test_different_wallets_cannot_form_a_pair():
    report = audit(row("Buy", "BTC", "0.2"),
                   row("Sell", "EUR", "-400", wallet="Funding"))
    assert report.candidates == () and report.other_legacy_groups == 2


def test_requires_validated_legacy_evidence_object():
    with pytest.raises(TypeError):
        audit_legacy_eur_acquisitions([])
