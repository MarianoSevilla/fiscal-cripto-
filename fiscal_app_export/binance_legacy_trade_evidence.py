"""Read-only evidence for early Binance Transaction History Buy/Sell/Fee.

One-second ledger groups are not exchange fills or proven tax acquisitions.
This module never creates tax lots, prices, or authorizes a FIFO report.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Iterable, Mapping

_OPS = frozenset(("Buy", "Sell", "Fee"))
_ASSET = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class BinanceLegacyEvidenceError(ValueError):
    """Bad legacy input. Messages never include source transaction data."""


@dataclass(frozen=True)
class BinanceLegacyLeg:
    operation: str
    asset: str
    quantity: Decimal


@dataclass(frozen=True)
class BinanceLegacyGroup:
    timestamp: str
    account: str
    legs: tuple[BinanceLegacyLeg, ...]
    classification: str

    @property
    def fiscal_ready(self) -> bool:
        return False


@dataclass(frozen=True)
class BinanceLegacyEvidence:
    groups: tuple[BinanceLegacyGroup, ...]
    records: int
    single_pair_groups: int
    ambiguous_groups: int
    isolated_fee_groups: int

    @property
    def fiscal_ready(self) -> bool:
        return False


def audit_legacy_trades(rows: Iterable[Mapping[str, str]]) -> BinanceLegacyEvidence:
    """Inventory legacy rows without guessing fills or tax acquisition costs.

    Match by local second and account, *preserving multiplicity and row order*.
    A single positive Buy and negative Sell of different assets is a pair
    candidate, not an automatically accepted acquisition or disposal. Multi-
    fill and mixed-asset groups remain ambiguous even if summed quantities fit.
    A standalone positive USD-M Futures Fee is not a Spot trading commission.
    """
    grouped: dict[tuple[str, str], list[BinanceLegacyLeg]] = defaultdict(list)
    count = 0
    for row in rows:
        operation = row.get("operación", "")
        if operation not in _OPS:
            continue
        timestamp = row.get("tiempo", "")
        account = row.get("cuenta", "")
        asset = str(row.get("moneda", "")).strip().upper()
        if not isinstance(timestamp, str) or not _TIME.fullmatch(timestamp):
            raise BinanceLegacyEvidenceError("Marca temporal legacy inválida")
        try:
            datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise BinanceLegacyEvidenceError("Fecha legacy inexistente") from exc
        if not isinstance(account, str) or not account.strip():
            raise BinanceLegacyEvidenceError("Cuenta legacy ausente")
        if not _ASSET.fullmatch(asset):
            raise BinanceLegacyEvidenceError("Activo legacy inválido")
        raw_amount = row.get("cambio")
        if not isinstance(raw_amount, str):
            raise BinanceLegacyEvidenceError("Cantidad legacy debe ser texto")
        try:
            quantity = Decimal(raw_amount.strip())
        except (InvalidOperation, ValueError) as exc:
            raise BinanceLegacyEvidenceError("Cantidad legacy inválida") from exc
        if not quantity.is_finite() or quantity == 0:
            raise BinanceLegacyEvidenceError("Cantidad legacy no finita o nula")
        if (operation == "Buy" and quantity <= 0) or (operation == "Sell" and quantity >= 0):
            raise BinanceLegacyEvidenceError("Signo legacy incompatible")
        if operation == "Fee" and quantity > 0 and account.strip() != "USD-M Futures":
            raise BinanceLegacyEvidenceError("Fee positiva fuera de futuros")
        grouped[(timestamp, account.strip())].append(
            BinanceLegacyLeg(operation=operation, asset=asset, quantity=quantity)
        )
        count += 1

    result = []
    single = multi = isolated = 0
    for (timestamp, account), legs in sorted(grouped.items()):
        buys = [x for x in legs if x.operation == "Buy"]
        sells = [x for x in legs if x.operation == "Sell"]
        fees = [x for x in legs if x.operation == "Fee"]
        if not buys and not sells and fees:
            classification = "isolated_fee"
            isolated += 1
        elif (len(buys) == len(sells) == 1
              and buys[0].asset != sells[0].asset
              and all(f.quantity < 0 for f in fees)
              and account == "Spot"):
            classification = "single_pair_unvalued"
            single += 1
        else:
            classification = "ambiguous"
            multi += 1
        result.append(BinanceLegacyGroup(
            timestamp=timestamp, account=account,
            legs=tuple(legs), classification=classification,
        ))
    return BinanceLegacyEvidence(
        groups=tuple(result), records=count, single_pair_groups=single,
        ambiguous_groups=multi, isolated_fee_groups=isolated,
    )
