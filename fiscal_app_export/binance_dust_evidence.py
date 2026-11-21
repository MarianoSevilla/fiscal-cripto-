"""Evidencia de canjes Dust -> BNB en Binance, sin permutas ficticias.

La conversión de saldos pequeños permite seleccionar muchos activos en un
mismo canje. El ledger general puede reflejar varias patas positivas y
negativas en un segundo; agrupar por segundo/cuenta NO es prueba de que
todas las patas formen una misma operación ni de cómo asignar BNB recibido.

Retener cantidades exactas Decimal y multiplicidad, no inferir contravalor
EUR, comisiones individuales ni lotes fiscales. Fail-closed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re


DUST_OPERATION = "Small Assets Exchange BNB"


class BinanceDustEvidenceError(ValueError):
    """Error de validación sin importes ni identificadores privados."""


_TIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")


@dataclass(frozen=True)
class BinanceDustGroup:
    occurred_at: str
    wallet: str
    debits: tuple[tuple[str, Decimal], ...]
    credits: tuple[tuple[str, Decimal], ...]
    row_count: int

    @property
    def only_bnb_received(self) -> bool:
        return bool(self.credits) and all(asset == "BNB" for asset, _ in self.credits)

    @property
    def identifiable_single_pair(self) -> bool:
        # Aun un grupo de solo dos patas NO acredita identidad transaccional.
        return len(self.debits) == len(self.credits) == 1 and self.only_bnb_received

    @property
    def fiscal_ready(self) -> bool:
        return False


@dataclass(frozen=True)
class BinanceDustAudit:
    rows: int
    groups: int
    single_pair_candidates: int
    multi_leg_groups: int
    groups_without_bnb_credit: int
    groups_with_non_bnb_credit: int
    bnb_credited: Decimal

    @property
    def fiscal_ready(self) -> bool:
        return False


def audit_binance_dust(rows):
    """Devuelve evidencias por segundo y wallet; no crea swaps fiscales.

    Soporta que el CSV lleve datos adicionales y validación estricta de
    signos, fechas, cuentas, nombres y cantidades.
    """
    grouped = defaultdict(list)
    row_count = 0
    for row in rows:
        if str(row.get("operación", "")).strip() != DUST_OPERATION:
            continue
        stamp = str(row.get("tiempo", "")).strip()
        if not _TIME.fullmatch(stamp):
            raise BinanceDustEvidenceError("Fecha del canje de saldos inválida")
        try:
            datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise BinanceDustEvidenceError("Fecha del canje de saldos inválida") from exc
        wallet = str(row.get("cuenta", "")).strip()
        if not wallet:
            raise BinanceDustEvidenceError("Billetera del canje sin identificar")
        asset = str(row.get("moneda", "")).strip().upper()
        if not _SYMBOL.fullmatch(asset):
            raise BinanceDustEvidenceError("Activo del canje no válido")
        raw = row.get("cambio")
        if isinstance(raw, (bool, float)):
            raise BinanceDustEvidenceError("Importe del canje debe ser Decimal o texto")
        try:
            qty = Decimal(str(raw).strip())
        except (InvalidOperation, ValueError) as exc:
            raise BinanceDustEvidenceError("Importe del canje no válido") from exc
        if not qty.is_finite() or qty == 0:
            raise BinanceDustEvidenceError("Importe de canje nulo o no finito")
        grouped[(stamp, wallet)].append((asset, qty))
        row_count += 1

    bundles = []
    one_pair = multi = no_bnb = other_credit = 0
    bnb_total = Decimal(0)
    for (stamp, wallet), legs in sorted(grouped.items()):
        debits = tuple((asset, -qty) for asset, qty in legs if qty < 0)
        credits = tuple((asset, qty) for asset, qty in legs if qty > 0)
        bnb_total += sum((qty for asset, qty in credits if asset == "BNB"),
                         Decimal(0))
        bundle = BinanceDustGroup(stamp, wallet, debits, credits, len(legs))
        if bundle.identifiable_single_pair:
            one_pair += 1
        else:
            multi += 1
        if not any(asset == "BNB" for asset, _ in credits):
            no_bnb += 1
        if any(asset != "BNB" for asset, _ in credits):
            other_credit += 1
        bundles.append(bundle)

    audit = BinanceDustAudit(
        rows=row_count, groups=len(bundles),
        single_pair_candidates=one_pair, multi_leg_groups=multi,
        groups_without_bnb_credit=no_bnb,
        groups_with_non_bnb_credit=other_credit,
        bnb_credited=bnb_total,
    )
    return audit, tuple(bundles)
