"""Evidencia de comisiones Binance para inventario, sin calificación fiscal.

Las tres etiquetas nativas no prueban por sí solas quién pagó la comisión,
si es reembolso de gastos propios, o cuál es la categoría de renta en IRPF.
El usuario puede acreditar afiliación fuera del CSV; nunca se deduce de ella
la naturaleza de TODAS las filas. No construir compras ficticias ni coste 0.

Iterador de memoria constante para grandes volúmenes. No almacena PII,
no escribe archivos y no habilita el PDF fiscal.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re


class BinanceCommissionEvidenceError(ValueError):
    """Error genérico sin exponer valores privados."""


COMMISSION_OPERATIONS = frozenset({
    "Commission History", "Commission Rebate", "Referrer Commission",
})
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


@dataclass(frozen=True)
class BinanceCommissionEvidence:
    ordinal: int
    source_operation: str
    earned_at: str
    asset: str
    quantity: Decimal
    wallet: str
    value_eur: Decimal | None = None
    fiscal_category: None = None

    @property
    def fiscal_ready(self):
        return False


@dataclass(frozen=True)
class BinanceCommissionAudit:
    records: int
    operation_counts: tuple[tuple[str, int], ...]
    asset_counts: tuple[tuple[str, int], ...]
    quantities_by_asset: tuple[tuple[str, Decimal], ...]
    pending_eur_valuations: int
    pending_fiscal_classifications: int

    @property
    def fiscal_ready(self):
        return False


def is_binance_commission(row):
    return str(row.get("operación", "")).strip() in COMMISSION_OPERATIONS


def iter_binance_commissions(rows):
    """Conserva multiplicidad: dos abonos idénticos pueden ser distintos.

    La identidad de un registro es su ordinal en el flujo recibido. No
    deduplicar por segundo, activo o cantidad. Si hay ZIP solapados, otro
    control debe detectar/conciliar ese solapamiento antes de emitir FIFO.
    """
    for ordinal, row in enumerate(rows):
        operation = str(row.get("operación", "")).strip()
        if operation not in COMMISSION_OPERATIONS:
            continue
        stamp = str(row.get("tiempo", "")).strip()
        if not _STAMP.fullmatch(stamp):
            raise BinanceCommissionEvidenceError("Fecha de comisión inválida")
        try:
            datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise BinanceCommissionEvidenceError("Fecha de comisión inválida") from exc
        symbol = str(row.get("moneda", "")).strip().upper()
        if not _SYMBOL.fullmatch(symbol):
            raise BinanceCommissionEvidenceError("Activo de comisión inválido")
        raw = row.get("cambio")
        if isinstance(raw, (bool, float)):
            raise BinanceCommissionEvidenceError("Cantidad de comisión requiere Decimal o texto")
        try:
            quantity = Decimal(str(raw).strip())
        except (InvalidOperation, ValueError) as exc:
            raise BinanceCommissionEvidenceError("Cantidad de comisión inválida") from exc
        if not quantity.is_finite() or quantity <= 0:
            raise BinanceCommissionEvidenceError("Comisión sin entrada positiva válida")
        wallet = str(row.get("cuenta", "")).strip()
        if not wallet:
            raise BinanceCommissionEvidenceError("Cuenta de comisión no identificada")
        yield BinanceCommissionEvidence(
            ordinal=ordinal, source_operation=operation, earned_at=stamp,
            asset=symbol, quantity=quantity, wallet=wallet,
            value_eur=(quantity if symbol == "EUR" else None),
        )


def audit_binance_commissions(rows):
    """Resumen pequeño en memoria; filas originales siguen en la fuente.

    Nunca suma activos distintos como si fueran EUR; el total es por activo.
    """
    by_operation, by_asset = Counter(), Counter()
    quantities = defaultdict(Decimal)
    count = 0
    pending_value = 0
    for evidence in iter_binance_commissions(rows):
        count += 1
        if evidence.value_eur is None:
            pending_value += 1
        by_operation[evidence.source_operation] += 1
        by_asset[evidence.asset] += 1
        quantities[evidence.asset] += evidence.quantity
    return BinanceCommissionAudit(
        records=count,
        operation_counts=tuple(sorted(by_operation.items())),
        asset_counts=tuple(sorted(by_asset.items())),
        quantities_by_asset=tuple(sorted(quantities.items())),
        pending_eur_valuations=pending_value,
        pending_fiscal_classifications=count,
    )
