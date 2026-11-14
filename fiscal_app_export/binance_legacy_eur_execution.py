"""Conservative matching of Binance legacy Buy/Sell/Fee against EUR.

The ledger contains account movements, not exchange fill identities. Only an
unambiguous Spot pair at a single second with an explicit EUR leg can create a
candidate trade. Never impute stablecoin parity or third-asset commission.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from binance_legacy_trade_evidence import BinanceLegacyEvidence


@dataclass(frozen=True)
class LegacyEURTrade:
    timestamp: str
    account: str
    given_asset: str
    given_amount: Decimal
    received_asset: str
    received_amount: Decimal
    fee_asset: str | None
    fee_amount: Decimal


@dataclass(frozen=True)
class LegacyEURResolution:
    trades: tuple[LegacyEURTrade, ...]
    remove_groups: frozenset[tuple[str, str]]
    mirrored_groups: int
    unresolved_groups: int


def resolve_legacy_eur_trades(evidence: BinanceLegacyEvidence,
                              native_events: Iterable, *,
                              blocked_groups: Iterable[tuple[str, str]] = ()) -> LegacyEURResolution:
    """Accept safe EUR pairs, dedup exact native mirrors; preserve all others.

    A one-second / wallet grouping isn't a fill identifier. All ambiguity
    remains unresolved. A competing native event involving either asset at the
    same second blocks conversion unless one exact event mirrors the ledger.
    """
    if not isinstance(evidence, BinanceLegacyEvidence):
        raise TypeError("validated legacy evidence required")
    native = tuple(native_events)
    blocked = frozenset(blocked_groups)
    trades: list[LegacyEURTrade] = []
    remove: set[tuple[str, str]] = set()
    mirrored = unresolved = 0
    for group in evidence.groups:
        if (group.timestamp, group.account) in blocked:
            unresolved += 1
            continue
        if group.classification != "single_pair_unvalued":
            unresolved += 1
            continue
        buys = [x for x in group.legs if x.operation == "Buy"]
        sells = [x for x in group.legs if x.operation == "Sell"]
        fees = [x for x in group.legs if x.operation == "Fee"]
        if len(buys) != 1 or len(sells) != 1:
            unresolved += 1
            continue
        bought, sold = buys[0], sells[0]
        if ((bought.asset == "EUR") == (sold.asset == "EUR")):
            # Both legs fiat or neither: no EUR-backed crypto trade.
            unresolved += 1
            continue
        given, received = sold.asset, bought.asset
        if len(set(x.asset for x in fees)) > 1:
            unresolved += 1
            continue
        fee_asset = fees[0].asset if fees else None
        fee_amount = sum((-x.quantity for x in fees), Decimal(0))
        # For a purchase fees may be EUR or the acquired asset. For a sale
        # only explicit EUR fees are covered by the existing tax engine.
        allowed_fees = ({"EUR", received} if given == "EUR" else {"EUR"})
        if fee_asset is not None and fee_asset not in allowed_fees:
            unresolved += 1
            continue
        if given == "EUR" and fee_asset == received and fee_amount >= bought.quantity:
            unresolved += 1
            continue
        candidate = LegacyEURTrade(
            timestamp=group.timestamp, account=group.account,
            given_asset=given, given_amount=-sold.quantity,
            received_asset=received, received_amount=bought.quantity,
            fee_asset=fee_asset, fee_amount=fee_amount,
        )
        same_second = [e for e in native if e.local_time == group.timestamp]
        relevant = [e for e in same_second
                    if ({given, received} & {e.given_asset, e.received_asset})]
        if relevant:
            mirrors = [e for e in relevant
                       if (e.given_asset == candidate.given_asset
                           and e.given_amount == candidate.given_amount
                           and e.received_asset == candidate.received_asset
                           and e.received_amount == candidate.received_amount
                           and (e.fee_asset or None) == candidate.fee_asset
                           and e.fee_amount == candidate.fee_amount)]
            if len(mirrors) == 1 and len(relevant) == 1:
                mirrored += 1
                remove.add((group.timestamp, group.account))
            else:
                unresolved += 1
            continue
        trades.append(candidate)
        remove.add((group.timestamp, group.account))
    return LegacyEURResolution(tuple(trades), frozenset(remove), mirrored, unresolved)
