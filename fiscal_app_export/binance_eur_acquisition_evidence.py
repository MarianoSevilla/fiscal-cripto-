"""Evidencia nativa explícita de adquisiciones pagadas en EUR.

La evidencia de una compra en EUR NO certifica el FIFO global: pueden
existir lotes anteriores en otras plataformas, comisiones en terceros
activos o fuentes que no figuran en el historial importado.
No añade registros a MotorFIFO ni autoriza PDF.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


class BinanceEURAcquisitionError(ValueError):
    """Entrada inválida en evidencia de compras EUR de Binance."""


_EUR_ACQUISITION_SOURCES = frozenset(("Spot BUY", "Convert", "Fiat trade"))


@dataclass(frozen=True)
class BinanceExplicitEURAcquisition:
    source: str
    local_time: str
    asset: str
    gross_quantity: Decimal
    net_quantity: Decimal
    eur_outlay: Decimal
    fee_asset: str | None
    fee_quantity: Decimal
    # None NO representa coste cero; el total requiere comprobación.
    complete_cost_eur: Decimal | None
    outstanding_reason: str | None
    # Posición original, nunca identificador de ejecución único.
    native_ordinal: int

    @property
    def fiscal_ready(self) -> bool:
        return False


@dataclass(frozen=True)
class BinanceExplicitEURAcquisitionAudit:
    candidates: tuple[BinanceExplicitEURAcquisition, ...]
    by_year_source: tuple[tuple[int, str, int], ...]
    complete_cost_candidates: int
    incomplete_cost_candidates: int

    @property
    def fiscal_ready(self) -> bool:
        return False


def _positive(value, *, allow_zero=False):
    if isinstance(value, (bool, float)):
        raise BinanceEURAcquisitionError("Importe EUR nativo no verificable")
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BinanceEURAcquisitionError(
            "Importe EUR nativo no verificable"
        ) from exc
    if not n.is_finite() or n < 0 or (not allow_zero and n == 0):
        raise BinanceEURAcquisitionError("Importe EUR nativo no verificable")
    return n


def auditar_adquisiciones_eur_nativas(native_events):
    """Extrae importes EUR explícitos SIN extrapolar USD/USDT/USDC.

    Un fee pagado con una tercera cripto requiere valoración separada.
    En compras por canal fiat con comisión, 'Cantidad a gastar'
    puede no identificar inequívocamente si la comisión va incluida:
    no se asume una base EUR fiscal completa sin contrastarla.
    """
    entries = []
    years = Counter()
    for ordinal, event in enumerate(native_events):
        source = str(getattr(event, "source", "")).strip()
        given = str(getattr(event, "given_asset", "")).strip().upper()
        asset = str(getattr(event, "received_asset", "")).strip().upper()
        if source not in _EUR_ACQUISITION_SOURCES or given != "EUR":
            continue
        if not asset or asset == "EUR":
            raise BinanceEURAcquisitionError("Activo de compra nativa inválido")
        timestamp = str(getattr(event, "local_time", ""))
        if len(timestamp) != 19:
            raise BinanceEURAcquisitionError("Fecha de compra EUR no acreditada")
        try:
            from datetime import datetime
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise BinanceEURAcquisitionError(
                "Fecha de compra EUR no acreditada"
            ) from exc

        euro = _positive(getattr(event, "given_amount", None))
        gross = _positive(getattr(event, "received_amount", None))
        fee = _positive(getattr(event, "fee_amount", 0), allow_zero=True)
        fee_asset = getattr(event, "fee_asset", None)
        fee_asset = str(fee_asset).strip().upper() if fee_asset else None
        if fee > 0 and not fee_asset:
            raise BinanceEURAcquisitionError(
                "Moneda de comisión nativa sin acreditar"
            )
        net = gross - fee if fee_asset == asset else gross
        if net <= 0:
            raise BinanceEURAcquisitionError("Comisión excede el importe recibido")
        complete = euro
        reason = None
        if fee > 0 and fee_asset not in {asset, "EUR"}:
            complete = None
            reason = "comision_en_tercer_activo_sin_eur"
        elif fee > 0 and fee_asset == "EUR":
            if source == "Fiat trade":
                # No resolver sin prueba de si el total 'a gastar' incluye fee.
                complete = None
                reason = "comision_fiat_incluida_o_adicional_no_acreditada"
            else:
                complete = euro + fee

        entries.append(BinanceExplicitEURAcquisition(
            source=source, local_time=timestamp, asset=asset,
            gross_quantity=gross, net_quantity=net, eur_outlay=euro,
            fee_asset=fee_asset, fee_quantity=fee,
            complete_cost_eur=complete, outstanding_reason=reason,
            native_ordinal=ordinal,
        ))
        years[(dt.year, source)] += 1

    complete_count = sum(1 for e in entries if e.complete_cost_eur is not None)
    return BinanceExplicitEURAcquisitionAudit(
        candidates=tuple(entries),
        by_year_source=tuple(
            (year, source, n) for (year, source), n in sorted(years.items())
        ),
        complete_cost_candidates=complete_count,
        incomplete_cost_candidates=len(entries) - complete_count,
    )
