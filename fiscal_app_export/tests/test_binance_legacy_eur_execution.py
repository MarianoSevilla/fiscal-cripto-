"""Synthetic-only regression for safe legacy EUR recognition."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from binance_legacy_trade_evidence import audit_legacy_trades
from binance_legacy_eur_execution import resolve_legacy_eur_trades


def row(op, sym, qty, stamp="2020-01-03 10:00:00", account="Spot"):
    return {"operación": op, "moneda": sym, "cambio": str(qty),
            "cuenta": account, "tiempo": stamp}


def resolve(*rows, native=(), blocked=()):
    return resolve_legacy_eur_trades(
        audit_legacy_trades(rows), native, blocked_groups=blocked,
    )


def native(given="EUR", amount="20", received="XRP", qty="10",
           fee_asset=None, fee_amount="0"):
    return SimpleNamespace(
        local_time="2020-01-03 10:00:00", given_asset=given,
        given_amount=Decimal(amount), received_asset=received,
        received_amount=Decimal(qty), fee_asset=fee_asset,
        fee_amount=Decimal(fee_amount),
    )


def test_explicit_eur_purchase_without_fee():
    r = resolve(row("Sell", "EUR", "-20"), row("Buy", "XRP", "10"))
    assert len(r.trades) == 1 and r.unresolved_groups == 0
    assert r.trades[0].given_amount == Decimal("20")
    assert r.trades[0].received_amount == Decimal("10")


def test_eur_purchase_fee_in_eur():
    r = resolve(row("Sell", "EUR", "-20"), row("Buy", "XRP", "10"),
                row("Fee", "EUR", "-1"))
    assert r.trades[0].fee_asset == "EUR" and r.trades[0].fee_amount == 1


def test_purchase_fee_received_asset_preserves_net_in_engine():
    r = resolve(row("Sell", "EUR", "-20"), row("Buy", "XRP", "10"),
                row("Fee", "XRP", "-0.1"))
    assert r.trades[0].fee_amount == Decimal("0.1")


def test_eur_sale_with_eur_fee():
    r = resolve(row("Sell", "XRP", "-5"), row("Buy", "EUR", "16"),
                row("Fee", "EUR", "-1"))
    assert len(r.trades) == 1 and r.trades[0].received_asset == "EUR"


@pytest.mark.parametrize("rows", [
    (("Sell", "USDT", "-20"), ("Buy", "XRP", "10")),
    (("Sell", "EUR", "-20"), ("Buy", "XRP", "10"), ("Fee", "BNB", "-0.01")),
    (("Sell", "XRP", "-5"), ("Buy", "EUR", "16"), ("Fee", "XRP", "-0.1")),
    (("Sell", "EUR", "-20"), ("Buy", "XRP", "10"), ("Fee", "EUR", "-1"),
     ("Fee", "XRP", "-0.1")),
    (("Sell", "EUR", "-20"), ("Buy", "XRP", "10"), ("Fee", "XRP", "-10")),
    (("Sell", "EUR", "-20"), ("Buy", "XRP", "10"), ("Sell", "EUR", "-30"),
     ("Buy", "XRP", "15")),
])
def test_unsafe_or_ambiguous_groups_remain_unresolved(rows):
    r = resolve(*(row(*values) for values in rows))
    assert not r.trades and not r.remove_groups and r.unresolved_groups == 1


@pytest.mark.parametrize("account", [
    "Funding", "USD-M Futures", "Margin", "Earn", "Fiat",
])
def test_non_spot_eur_pair_cannot_create_lot_or_disappear_as_spot_mirror(account):
    """Matching EUR legs in other wallets never prove a Spot fiscal fill."""
    rows = (row("Sell", "EUR", "-20", account=account),
            row("Buy", "XRP", "10", account=account))
    unresolved = resolve(*rows)
    assert unresolved.unresolved_groups == 1
    assert not unresolved.trades and not unresolved.remove_groups
    # Even if a native Spot fill happens to match quantity and second, an
    # independent Funding/Margin/Futures pair must not be discarded.
    with_native = resolve(*rows, native=[native()])
    assert with_native.unresolved_groups == 1
    assert with_native.mirrored_groups == 0
    assert not with_native.trades and not with_native.remove_groups


def test_spot_wallet_casefold_remains_supported():
    r = resolve(row("Sell", "EUR", "-20", account="sPoT"),
                row("Buy", "XRP", "10", account="sPoT"))
    assert len(r.trades) == 1 and r.unresolved_groups == 0


def test_exact_native_mirror_skipped_once():
    r = resolve(row("Sell", "EUR", "-20"), row("Buy", "XRP", "10"),
                native=[native()])
    assert r.mirrored_groups == 1 and not r.trades
    assert len(r.remove_groups) == 1


def test_native_amount_mismatch_stays_unresolved():
    r = resolve(row("Sell", "EUR", "-20"), row("Buy", "XRP", "10"),
                native=[native(amount="21")])
    assert not r.remove_groups and r.unresolved_groups == 1


def test_multiple_natives_cannot_hide_group():
    r = resolve(row("Sell", "EUR", "-20"), row("Buy", "XRP", "10"),
                native=[native(), native()])
    assert r.unresolved_groups == 1 and not r.remove_groups


def test_other_native_same_second_asset_conflict():
    r = resolve(row("Sell", "EUR", "-20"), row("Buy", "XRP", "10"),
                native=[native(received="BTC")])
    assert r.unresolved_groups == 1 and not r.remove_groups


def test_other_trade_row_same_account_second_blocks_import():
    key = ("2020-01-03 10:00:00", "Spot")
    r = resolve(row("Sell", "EUR", "-20"), row("Buy", "XRP", "10"),
                blocked={key})
    assert r.unresolved_groups == 1 and not r.remove_groups


def test_orphan_fee_or_futures_never_imported():
    assert resolve(row("Fee", "BNB", "-0.001")).unresolved_groups == 1
    assert resolve(row("Fee", "USDT", "1", account="USD-M Futures")).unresolved_groups == 1


def test_only_validated_evidence_is_accepted():
    with pytest.raises(TypeError):
        resolve_legacy_eur_trades([], ())

def test_native_zero_fee_label_is_equivalent_to_no_fee():
    r = resolve(row("Sell", "EUR", "-20"), row("Buy", "XRP", "10"),
                native=[native(fee_asset="XRP", fee_amount="0")])
    assert r.mirrored_groups == 1 and not r.trades
