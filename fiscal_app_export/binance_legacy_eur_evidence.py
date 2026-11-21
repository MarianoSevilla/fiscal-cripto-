"""Conservative EUR acquisition evidence from early Binance Buy/Sell/Fee rows.

Only single unambiguous Spot pairs with an explicit EUR debit are candidates.
No market-price inference, tax lot creation or FIFO/PDF authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from binance_legacy_trade_evidence import BinanceLegacyEvidence


@dataclass(frozen=True)
class BinanceLegacyEURAcquisition:
    timestamp: str
    acquired_asset: str
    received_gross: Decimal
    received_net: Decimal
    eur_paid: Decimal
    fee_assets: tuple[str, ...]
    fee_total_cost_eur: Decimal | None
    reason: str

    @property
    def fiscal_ready(self) -> bool:
        return False


@dataclass(frozen=True)
class BinanceLegacyEURAcquisitionReport:
    candidates: tuple[BinanceLegacyEURAcquisition, ...]
    complete_cost_candidates: int
    pending_third_asset_fee: int
    other_legacy_groups: int

    @property
    def fiscal_ready(self) -> bool:
        return False


def audit_legacy_eur_acquisitions(
    evidence: BinanceLegacyEvidence,
) -> BinanceLegacyEURAcquisitionReport:
    """Extract explicit EUR-backed cost candidates; preserve net quantities.

    A fee paid in a third crypto leaves full cost unknown, never zero.
    An in-kind fee reduces received units but cannot create an extra purchase.
    This audit is informational even when the EUR consideration is explicit.
    """
    if not isinstance(evidence, BinanceLegacyEvidence):
        raise TypeError("Legacy evidence required")

    candidates = []
    other = complete = third = 0
    for group in evidence.groups:
        if group.classification != "single_pair_unvalued":
            other += 1
            continue
        bought = [leg for leg in group.legs if leg.operation == "Buy"]
        sold = [leg for leg in group.legs if leg.operation == "Sell"]
        if (len(bought) != 1 or len(sold) != 1
                or sold[0].asset != "EUR" or bought[0].asset == "EUR"):
            other += 1
            continue

        acquired = bought[0]
        paid = -sold[0].quantity
        fees = [leg for leg in group.legs if leg.operation == "Fee"]
        fee_received = sum(
            (-leg.quantity for leg in fees if leg.asset == acquired.asset),
            Decimal(0),
        )
        fee_eur = sum(
            (-leg.quantity for leg in fees if leg.asset == "EUR"), Decimal(0)
        )
        net = acquired.quantity - fee_received
        if net <= 0:
            # Cannot create a zero/negative lot, even provisionally.
            other += 1
            continue
        third_fee = any(
            leg.asset not in {"EUR", acquired.asset} for leg in fees
        )
        cost = None if third_fee else paid + fee_eur
        reason = (
            "third_asset_fee_missing_eur"
            if third_fee else "explicit_eur_cost_candidate"
        )
        if third_fee:
            third += 1
        else:
            complete += 1
        candidates.append(BinanceLegacyEURAcquisition(
            timestamp=group.timestamp,
            acquired_asset=acquired.asset,
            received_gross=acquired.quantity,
            received_net=net,
            eur_paid=paid,
            fee_assets=tuple(leg.asset for leg in fees),
            fee_total_cost_eur=cost,
            reason=reason,
        ))
    return BinanceLegacyEURAcquisitionReport(
        candidates=tuple(candidates),
        complete_cost_candidates=complete,
        pending_third_asset_fee=third,
        other_legacy_groups=other,
    )
