"""Only invented examples: never upload private account fixtures to GitHub."""
from decimal import Decimal
import pytest
from binance_legacy_trade_evidence import (
    BinanceLegacyEvidenceError, audit_legacy_trades,
)


def line(op, asset, amount, *, stamp="2021-01-02 12:00:00", wallet="Spot"):
    return {"operación": op, "moneda": asset, "cambio": amount,
            "tiempo": stamp, "cuenta": wallet}


def test_single_trade_preserves_decimal_and_fee():
    r = audit_legacy_trades([
        line("Sell", "USDT", "-100.50000000"),
        line("Buy", "BTC", "0.00300001"),
        line("Fee", "BNB", "-0.00000001"),
    ])
    assert (r.records, r.single_pair_groups, r.ambiguous_groups) == (3, 1, 0)
    assert r.groups[0].classification == "single_pair_unvalued"
    assert [x.quantity for x in r.groups[0].legs] == [
        Decimal("-100.50000000"), Decimal("0.00300001"), Decimal("-0.00000001")]
    assert not r.fiscal_ready and not r.groups[0].fiscal_ready


def test_same_second_multiple_fills_are_ambiguous_even_if_one_pair():
    rows = [line("Buy", "BTC", "0.2"), line("Sell", "USDT", "-10"),
            line("Buy", "BTC", "0.3"), line("Sell", "USDT", "-20"),
            line("Fee", "BNB", "-0.01"), line("Fee", "BNB", "-0.01")]
    r = audit_legacy_trades(rows)
    assert r.records == len(rows) and r.ambiguous_groups == 1
    assert len(r.groups[0].legs) == 6
    assert [x.quantity for x in r.groups[0].legs[-2:]] == [Decimal("-0.01")]*2


def test_multiple_assets_or_unpaired_rows_stay_ambiguous():
    r = audit_legacy_trades([line("Buy", "BTC", "1"),
                             line("Sell", "BTC", "-1")])
    assert r.ambiguous_groups == 1
    r = audit_legacy_trades([line("Buy", "BTC", "1")])
    assert r.ambiguous_groups == 1


def test_isolated_positive_futures_fee_never_spot():
    r = audit_legacy_trades([line("Fee", "USDT", "+1", wallet="USD-M Futures")])
    assert r.isolated_fee_groups == 1 and r.single_pair_groups == 0


def test_nonlegacy_rows_ignored_and_no_double_count():
    r = audit_legacy_trades([line("Transaction Fee", "BNB", "-1"),
                             line("Sell", "USDT", "-1")])
    assert r.records == 1 and r.ambiguous_groups == 1


@pytest.mark.parametrize("row", [
    line("Buy", "BTC", "-1"), line("Sell", "USDT", "1"),
    line("Fee", "BNB", "1"), line("Fee", "BNB", "NaN"),
    line("Buy", "BTC", "Infinity"), line("Buy", "BTC", "0"),
    line("Sell", "USD T", "-1"), line("Buy", "BTC", "1", stamp="2021-02-30 12:00:00"),
    line("Buy", "BTC", "1", wallet=""),
])
def test_bad_input_fails_closed(row):
    with pytest.raises(BinanceLegacyEvidenceError):
        audit_legacy_trades([row])


def test_separates_accounts_and_seconds():
    r = audit_legacy_trades([
        line("Sell", "USDT", "-10"), line("Buy", "BTC", "0.001"),
        line("Sell", "USDT", "-11", stamp="2021-01-02 12:00:01"),
        line("Buy", "BTC", "0.002", stamp="2021-01-02 12:00:01"),
        line("Fee", "USDT", "1", wallet="USD-M Futures"),
    ])
    assert len(r.groups) == 3 and r.single_pair_groups == 2 and r.isolated_fee_groups == 1
