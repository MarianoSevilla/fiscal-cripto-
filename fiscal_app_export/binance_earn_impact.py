"""Priorización documental de recompensas Earn frente a salidas observadas.

No reconstruye lotes, no estima costes, no convierte retiros en ventas y
NUNCA decide si el PDF es válido. Solo permite ordenar una investigación
sin inferir que una recompensa concreta fue consumida por FIFO.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re


class BinanceEarnImpactError(ValueError):
    """Entrada de auditoría inválida, sin incluir datos privados."""


# Etiquetas potencialmente económicas del historial general.
# Transaction Spend puede ser la pata de una compra y Transaction Fee es una
# comisión: pertenecer a esta lista NO acredita transmisión fiscal.
_POSSIBLE_DEBITS = frozenset((
    "Transaction Sold", "Transaction Spend", "Binance Convert",
    "Small Assets Exchange BNB", "Transaction Fee",
))
# Withdraw se audita por separado: enviar a otra billetera propia NO es
# necesariamente una transmisión patrimonial.
_EXTERNAL_OUTBOUND = frozenset(("Withdraw",))
_NATIVE_DEBIT_SOURCES = frozenset((
    "Spot SELL", "Convert", "Fiat trade", "Recurring Convert",
))


@dataclass(frozen=True)
class BinanceEarnHistoricalImpact:
    exercise: int
    prior_ledger_only_rewards: int
    with_possible_disposal: int
    without_observed_disposal: int
    affected_assets: int
    assets_without_observed_disposal: int
    # Por separado: salidas de custodia externa no equivalen a ventas.
    with_external_withdrawal: int
    # Esta evaluación NO identifica el coste ni el lote FIFO consumido.
    @property
    def fifo_acreditado(self):
        return False


def _quantity(raw):
    if isinstance(raw, (bool, float)):
        raise BinanceEarnImpactError("Cantidad histórica no válida")
    text = str(raw).strip()
    # Binance también usa comas como separadores de miles. No interpretar
    # agrupaciones inválidas (1,23.45) ni confundir coma decimal con miles.
    if "," in text:
        if not re.fullmatch(
            r"[+-]?\\d{1,3}(?:,\\d{3})+(?:\\.\\d+)?", text
        ):
            raise BinanceEarnImpactError("Cantidad histórica no válida")
        text = text.replace(",", "")
    # No asumir paridad ni convertir formatos ambiguos: las filas contables
    # ya han pasado por el clasificador principal.
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise BinanceEarnImpactError("Cantidad histórica no válida") from exc
    if not value.is_finite():
        raise BinanceEarnImpactError("Cantidad histórica no válida")
    return value


def analizar_impacto_earn_historico(
    rewards_bridge, ledger_rows, native_exchanges, *, exercise
) -> BinanceEarnHistoricalImpact:
    """Cruza SOLO el activo, sin simular la identidad de un lote fiscal.

    ledger_rows: filas normalizadas del historial general, sin credenciales.
    native_exchanges: operaciones Spot/Convert/fiat ya tipadas por el parser.
    La ausencia de salidas observadas NO prueba irrelevancia fiscal: pueden
    existir fuentes omitidas, exchanges externos y retiros de custodia.
    """
    if type(exercise) is not int or not 2019 <= exercise <= 2100:
        raise BinanceEarnImpactError("Ejercicio de análisis no válido")
    original = getattr(rewards_bridge, "ledger_unresolved_evidence", ()) or ()
    prior = Counter()
    for row in original:
        if getattr(row, "relation", None) != "sin_fuente_nativa":
            continue
        stamp = str(getattr(row, "ledger_time", ""))
        asset = str(getattr(row, "asset", "")).strip().upper()
        if len(stamp) != 19 or not stamp[:4].isdigit() or not asset:
            raise BinanceEarnImpactError("Evidencia de recompensa incompleta")
        if int(stamp[:4]) < exercise:
            prior[asset] += 1

    potential_disposals = set()
    external_outbounds = set()
    for row in ledger_rows:
        op = str(row.get("operación", "")).strip()
        if op not in _POSSIBLE_DEBITS | _EXTERNAL_OUTBOUND:
            continue
        stamp = str(row.get("tiempo", "")).strip()
        if not stamp.startswith(str(exercise) + "-"):
            continue
        asset = str(row.get("moneda", "")).strip().upper()
        if not asset or asset == "EUR":
            continue
        if _quantity(row.get("cambio")) >= 0:
            continue
        if op in _EXTERNAL_OUTBOUND:
            external_outbounds.add(asset)
        else:
            potential_disposals.add(asset)

    for trade in native_exchanges:
        if str(getattr(trade, "source", "")) not in _NATIVE_DEBIT_SOURCES:
            continue
        if not str(getattr(trade, "local_time", "")).startswith(
            str(exercise) + "-"
        ):
            continue
        asset = str(getattr(trade, "given_asset", "")).strip().upper()
        if asset and asset != "EUR" and _quantity(
            getattr(trade, "given_amount", None)
        ) > 0:
            potential_disposals.add(asset)

    involved = set(prior) & potential_disposals
    separate = set(prior) - potential_disposals
    with_possible = sum(prior[a] for a in involved)
    without = sum(prior[a] for a in separate)
    return BinanceEarnHistoricalImpact(
        exercise=exercise,
        prior_ledger_only_rewards=with_possible + without,
        with_possible_disposal=with_possible,
        without_observed_disposal=without,
        affected_assets=len(involved),
        assets_without_observed_disposal=len(separate),
        with_external_withdrawal=sum(prior[a] for a in prior
                                     if a in external_outbounds),
    )
