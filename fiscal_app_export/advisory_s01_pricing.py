"""Cálculo determinista de S01: honorarios de Rafa + comisión del 30 %.

Los importes monetarios se expresan exclusivamente en céntimos enteros.
No incluye IVA ni establece quién factura; requieren decisión fiscal separada.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re

COMMISSION_RATE_BPS = 3000  # 30 % sobre los honorarios de Rafa
MAX_TOTAL_CENTS = 99_999_999  # límite operativo para evitar importes desmesurados


class QuotePricingError(ValueError):
    """Importe no representable de forma segura como céntimos de EUR."""


@dataclass(frozen=True)
class S01Quote:
    rafa_fee_cents: int
    commission_cents: int
    total_cents: int
    commission_rate_bps: int = COMMISSION_RATE_BPS


def calculate_s01_quote(rafa_fee_eur: object) -> S01Quote:
    """Convierte los honorarios indicados por Rafa en desglose auditable.

    Se acepta un entero, una cadena o Decimal con hasta dos decimales.
    También se acepta float procedente de JSON solo si su representación
    decimal es exacta a céntimos. Se rechazan valores exponenciales,
    redondeos implícitos, NaN, negativos, booleanos y formatos ambiguos.

    La comisión se redondea por HALF_UP a un céntimo, una sola vez.
    Ejemplo: 200,00 EUR -> 20000 + 6000 = 26000 céntimos.
    """
    if rafa_fee_eur is None or isinstance(rafa_fee_eur, bool):
        raise QuotePricingError("Introduce unos honorarios válidos.")
    if not isinstance(rafa_fee_eur, (str, int, float, Decimal)):
        raise QuotePricingError("Formato de importe no admitido.")

    literal = str(rafa_fee_eur).strip().replace(",", ".")
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?", literal):
        raise QuotePricingError("Utiliza euros con un máximo de dos decimales.")

    fee = Decimal(literal)
    if fee < Decimal("1.00"):
        raise QuotePricingError("Los honorarios deben ser de al menos 1,00 €.")

    fee_cents = int(fee * 100)
    commission = int(
        (Decimal(fee_cents) * Decimal(COMMISSION_RATE_BPS) / Decimal(10_000))
        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    total = fee_cents + commission
    if total > MAX_TOTAL_CENTS:
        raise QuotePricingError("El importe supera el máximo operativo.")

    return S01Quote(
        rafa_fee_cents=fee_cents,
        commission_cents=commission,
        total_cents=total,
    )
