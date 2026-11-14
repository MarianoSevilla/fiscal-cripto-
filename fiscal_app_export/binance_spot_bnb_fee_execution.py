"""Narrow, evidence-backed EUR Spot trades with third-asset BNB fees.

A fee paid in BNB is BOTH a directly related EUR expense and a disposal
of BNB acquired previously. Never value its cost at its market price.
This opt-in execution path is strictly limited to native Spot/EUR fills,
known BNB inventory, proven public BNB/EUR market price, and no other
material sources/fees. All other cases remain fail closed.

No HTTP/network requests, external positions, or private data persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from binance_eur_valuation import (
    BinanceHistoricalEURPrices, BinancePriceEvidenceError,
    binance_export_time_to_utc,
)


@dataclass(frozen=True)
class VerifiedBNBSpotFee:
    native_ordinal: int
    timestamp: str
    bnb_amount: Decimal
    eur_value: Decimal
    public_trades: tuple


def _ensure_float_exact_units(amount: Decimal) -> float:
    result = float(amount)
    if Decimal(str(result)) != amount:
        raise BinancePriceEvidenceError(
            "La comisión BNB pierde precisión de unidades en el motor FIFO"
        )
    return result


def _eur_float(amount: Decimal) -> float:
    result = float(amount)
    rounded = Decimal(str(result))
    if (not rounded.is_finite() or abs(rounded - amount) > Decimal("0.0000000001")
            or rounded.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            != amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)):
        raise BinancePriceEvidenceError(
            "La comisión BNB pierde precisión EUR en el motor FIFO"
        )
    return result


def prepare_spot_eur_bnb_fees(classifier, prices):
    """A complete preflight; returns fee positions only for safe Spot-only inputs.

    An empty return means no supported BNB fee was present; other pending fee
    types remain blocked by the existing fiscal guards.
    """
    native = tuple(getattr(classifier, "intercambios_nativos", ()))
    bnb_native = tuple((i, e) for i, e in enumerate(native)
                       if e.fee_asset == "BNB" and e.fee_amount > 0
                       and "BNB" not in (e.given_asset, e.received_asset))
    if not bnb_native:
        return ()
    if not isinstance(prices, BinanceHistoricalEURPrices):
        raise BinancePriceEvidenceError(
            "Falta catálogo EUR histórico verificable de comisiones BNB"
        )
    if (getattr(classifier, "fuentes_materiales_no_soportadas", ())
            or getattr(classifier, "desconocidas", ())
            or getattr(classifier, "swaps", ())
            or getattr(classifier, "rendimientos", ())
            or getattr(classifier, "earn_events", ())
            or getattr(classifier, "movimientos", ())
            # Raw Transaction History may legitimately duplicate Spot fills.
            # Allow it ONLY if every economic ledger row was dropped by
            # _filter_exact_tx_duplicates (legs + fees reconciled exactly).
            or (bool(classifier._source_rows["transaction_history"])
                and getattr(classifier, "_binance_tx_unmatched_rows_count", None) != 0)
            or getattr(classifier, "_commission_files", ())):
        raise BinancePriceEvidenceError(
            "Comisión BNB con otras fuentes económicas sin conciliación completa"
        )
    trades = tuple(getattr(classifier, "compraventas", ()))
    if not native or len(native) != len(trades):
        raise BinancePriceEvidenceError(
            "Comisiones BNB sin identidad unívoca de operaciones Spot/EUR"
        )
    # Same-second fills are admissible only with a single native Spot
    # order ID, pair and side. Different orders in the same second lack
    # a documented intrasecond sequence, so their lot allocation remains
    # blocked rather than inferred from CSV row order.
    by_second = {}
    for event in native:
        by_second.setdefault(event.local_time, []).append(event)
    for at, group in by_second.items():
        if len(group) > 1 and (
                any(not getattr(e, "order_id", "") for e in group)
                or len({(e.order_id, e.source, e.given_asset, e.received_asset)
                        for e in group}) != 1):
            raise BinancePriceEvidenceError(
                "Comisiones BNB con ejecuciones simultáneas sin orden acreditado"
            )
    for event, op in zip(native, trades):
        if (event.source not in ("Spot BUY", "Spot SELL")
                or not ((event.given_asset == "EUR") ^ (event.received_asset == "EUR"))
                or event.fee_amount < 0
                or (event.fee_amount > 0 and event.fee_asset
                    not in {"EUR", event.received_asset, "BNB"})):
            raise BinancePriceEvidenceError(
                "La comisión BNB requiere un inventario Spot/EUR íntegro"
            )
        expected_asset = (event.received_asset if event.given_asset == "EUR"
                          else event.given_asset)
        expected_kind = ("COMPRA" if event.given_asset == "EUR" else "VENTA")
        expected_qty = (event.received_amount
                        - (event.fee_amount if event.fee_asset == expected_asset
                           and expected_kind == "COMPRA" else Decimal("0"))
                        if expected_kind == "COMPRA" else event.given_amount)
        if (event.fee_asset == "BNB" and event.fee_amount > 0
                and "BNB" not in (event.given_asset, event.received_asset)):
            _ensure_float_exact_units(event.fee_amount)
        expected_eur = (event.given_amount + (
            event.fee_amount if event.fee_asset == "EUR" else Decimal(0)
        ) if expected_kind == "COMPRA" else event.received_amount)
        if (op.fecha != event.local_time or op.tipo != expected_kind
                or op.activo != expected_asset or op.contraparte != "EUR"
                or Decimal(str(op.cantidad)) != expected_qty
                or Decimal(str(op.importe)) != expected_eur
                or op.fee_activo != (event.fee_asset or (
                    expected_asset if expected_kind == "COMPRA" else "EUR"
                ))
                or Decimal(str(op.fee_cantidad)) != event.fee_amount):
            raise BinancePriceEvidenceError(
                "Las operaciones FIFO y las ejecuciones nativas no coinciden"
            )
    pending = tuple(getattr(classifier, "comisiones_pendientes", ()))
    if len(pending) != len(bnb_native):
        raise BinancePriceEvidenceError(
            "No todas las comisiones pendientes corresponden a BNB Spot"
        )
    for (index, event), row in zip(bnb_native, pending):
        if (row.get("fecha") != event.local_time
                or row.get("activo") != "BNB"
                or Decimal(str(row.get("cantidad"))) != event.fee_amount
                or row.get("fuente") != event.source):
            raise BinancePriceEvidenceError(
                "Comisiones BNB pendientes sin correspondencia exacta"
            )
    verified = []
    for index, event in bnb_native:
        instant = binance_export_time_to_utc(event.local_time, event.filename)
        bnb_price = prices.price_eur("BNB", instant)
        if not bnb_price.path:
            raise BinancePriceEvidenceError("Precio BNB/EUR sin operaciones públicas")
        value = event.fee_amount * bnb_price.unit_price_eur
        _ensure_float_exact_units(event.fee_amount)
        _eur_float(value)
        verified.append(VerifiedBNBSpotFee(
            index, event.local_time, event.fee_amount, value, bnb_price.path,
        ))
    # A single native order may contain multiple fills. If two acquisitions
    # have distinct all-in EUR unit costs and a later sale uses those lots,
    # their true FIFO sequence is not proven by second-resolution exports.
    indexed_fees = {f.native_ordinal: f for f in verified}
    last_sold = {}
    for event in native:
        if event.received_asset == "EUR":
            last_sold[event.given_asset] = max(
                event.local_time, last_sold.get(event.given_asset, "")
            )
    last_sold["BNB"] = max(
        last_sold.get("BNB", ""),
        *(e.timestamp for e in verified),
    )
    for at, group in by_second.items():
        if len(group) <= 1 or group[0].given_asset != "EUR":
            continue
        asset = group[0].received_asset
        if last_sold.get(asset, "") <= at:
            continue
        unit_costs = set()
        for i, event in enumerate(native):
            if event.local_time != at or event.received_asset != asset:
                continue
            net = event.received_amount - (
                event.fee_amount if event.fee_asset == asset
                else Decimal("0")
            )
            fee_eur = (event.fee_amount if event.fee_asset == "EUR"
                       else indexed_fees[i].eur_value if i in indexed_fees
                       else Decimal("0"))
            if net <= 0:
                raise BinancePriceEvidenceError(
                    "Cantidad neta de adquisición no verificable"
                )
            unit_costs.add((event.given_amount + fee_eur) / net)
        if len(unit_costs) > 1:
            raise BinancePriceEvidenceError(
                "Orden de lotes de una misma orden Spot con costes distintos "
                "no acreditado para ventas posteriores"
            )
    return tuple(verified)


def _settle_bnb_fee_group(motor, fees):
    """Consume one BNB FIFO disposal for the whole same-second fee group."""
    fees = tuple(fees)
    if not fees or len({fee.timestamp for fee in fees}) != 1:
        raise BinancePriceEvidenceError(
            "Grupo de comisiones BNB sin segundo único acreditado"
        )
    at = fees[0].timestamp
    qty = sum((fee.bnb_amount for fee in fees), Decimal("0"))
    price = sum((fee.eur_value for fee in fees), Decimal("0"))
    amount_bnb = _ensure_float_exact_units(qty)
    value_eur = _eur_float(price)
    if qty <= 0 or price <= 0:
        raise BinancePriceEvidenceError(
            "Grupo de comisiones BNB con importes no positivos"
        )
    date = motor._parsear_fecha(at)
    lots = motor.inventario.get("BNB", ())
    if any(x.cantidad_restante > 0 and x.fecha >= date for x in lots):
        raise BinancePriceEvidenceError(
            "BNB para comisiones sin orden cronológico de adquisición verificado"
        )
    available = sum(
        (Decimal(str(x.cantidad_restante)) for x in lots
         if x.cantidad_restante > 0), Decimal("0")
    )
    if available < qty:
        raise BinancePriceEvidenceError(
            "No existe inventario FIFO BNB suficiente para pagar la comisión"
        )
    result = motor._consumir_fifo(
        dt=date, activo="BNB", cantidad=amount_bnb,
        precio_transmision=value_eur, tipo="venta",
        nota="Comisiones Binance Spot pagadas con BNB (referencia EUR verificada)",
    )
    if result is None or result.inventario_incompleto:
        raise BinancePriceEvidenceError(
            "La disposición fiscal agrupada de BNB no está acreditada"
        )
    motor.resultados.append(result)


def apply_spot_eur_trade_with_bnb_fee(motor, operation, fee=None, *,
                                      defer_bnb_disposal=False):
    """Apply original EUR trade and separately dispose fee BNB FIFO lots."""
    if fee is None:
        if operation.tipo == "COMPRA":
            motor.registrar_compra(
                operation.fecha, operation.activo, operation.cantidad,
                operation.importe, operation.contraparte,
                operation.fee_activo, operation.fee_cantidad,
            )
        else:
            motor.registrar_venta(
                operation.fecha, operation.activo, operation.cantidad,
                operation.importe, operation.contraparte,
                operation.fee_activo, operation.fee_cantidad,
            )
        return
    if operation.fecha != fee.timestamp or operation.fee_activo != "BNB":
        raise BinancePriceEvidenceError("Comisión BNB de operación diferente")
    amount_bnb = _ensure_float_exact_units(fee.bnb_amount)
    # EUR expense: increase acquisition cost OR reduce sale proceeds.
    eur_before = Decimal(str(operation.importe))
    eur_effective = (eur_before + fee.eur_value if operation.tipo == "COMPRA"
                     else eur_before - fee.eur_value)
    if eur_effective <= 0:
        raise BinancePriceEvidenceError(
            "La comisión BNB excede el contravalor de la transmisión"
        )
    adjusted = _eur_float(eur_effective)
    if operation.tipo == "COMPRA":
        motor.registrar_compra(
            operation.fecha, operation.activo, operation.cantidad,
            adjusted, "EUR", "BNB", amount_bnb,
        )
    else:
        motor.registrar_venta(
            operation.fecha, operation.activo, operation.cantidad,
            adjusted, "EUR", "BNB", amount_bnb,
        )
    if not defer_bnb_disposal:
        _settle_bnb_fee_group(motor, (fee,))


def settle_spot_bnb_fees_same_second(motor, fees):
    """Commit grouped BNB FIFO disposal after all fills of one native order."""
    _settle_bnb_fee_group(motor, fees)
