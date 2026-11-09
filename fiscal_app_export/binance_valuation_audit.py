"""Auditoría offline de valoración EUR sobre hechos Binance con origen conservado.

Este módulo NO habilita PDFs ni intenta resolver honorarios pagados en cripto,
rendimientos, movimientos internos o eventos únicamente presentes en el ledger
legacy. Devuelve evidencia de valoración únicamente cuando todos los swaps
nativos son vinculables de forma inequívoca a una fuente histórica.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from binance_eur_valuation import (
    BinanceHistoricalEURPrices,
    BinancePriceEvidenceError,
    SwapEURValuation,
    binance_export_time_to_utc,
)
from clasificador_binance_multi import BinanceNativeExchange, ClasificadorBinanceMulti


@dataclass(frozen=True)
class BinanceSwapAuditRecord:
    source: BinanceNativeExchange
    valuation: SwapEURValuation


def valorar_permutas_nativas(
    classified: ClasificadorBinanceMulti,
    prices: BinanceHistoricalEURPrices,
) -> tuple[BinanceSwapAuditRecord, ...]:
    """Comprueba todas las permutas nativas y devuelve evidencia sin modificar FIFO.

    Cada registro tiene su propia identidad económica, aunque varios coincidan
    en el mismo segundo. La falta de un solo origen, de precio o de tratamiento
    de comisiones anula todo el resultado (sin informe parcial).
    """
    if not isinstance(classified, ClasificadorBinanceMulti):
        raise TypeError("Se requiere un clasificador multifuente Binance")
    if not isinstance(prices, BinanceHistoricalEURPrices):
        raise TypeError("Se requiere un libro histórico de precios Binance")
    if classified.fuentes_materiales_no_soportadas or classified.desconocidas:
        raise BinancePriceEvidenceError("Existen fuentes Binance sin reconstrucción íntegra")
    if classified.comisiones_pendientes:
        raise BinancePriceEvidenceError("Existen comisiones pendientes de integración FIFO")
    if classified.rendimientos:
        raise BinancePriceEvidenceError("Existen rendimientos sin valoración e inventario integrado")

    native_swaps = [
        e for e in classified.intercambios_nativos
        if e.given_asset != "EUR" and e.received_asset != "EUR"
    ]
    if len(native_swaps) != len(classified.swaps):
        raise BinancePriceEvidenceError(
            "Existen permutas de Transaction History sin trazabilidad nativa completa"
        )
    results: list[BinanceSwapAuditRecord] = []
    for event in native_swaps:
        if event.given_asset == event.received_asset:
            raise BinancePriceEvidenceError("Intercambio nativo con activos iguales")
        if event.fee_amount != Decimal("0"):
            raise BinancePriceEvidenceError(
                "No se pueden valorar permutas con comisiones todavía no integradas"
            )
        at = binance_export_time_to_utc(event.local_time, event.filename)
        v = prices.value_swap(
            timestamp=at,
            given_asset=event.given_asset,
            given_amount=event.given_amount,
            received_asset=event.received_asset,
            received_amount=event.received_amount,
        )
        results.append(BinanceSwapAuditRecord(source=event, valuation=v))
    return tuple(results)
