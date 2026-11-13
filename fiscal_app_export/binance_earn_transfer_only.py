"""Aceptación limitada de principal Simple Earn: solo traslados demostrados.

Este módulo no crea ingresos ni lotes nuevos al suscribir/redimir Earn.
Construye un inventario Decimal independiente desde compras y ventas Spot
estrictamente EUR y exige que las transferencias de principal cuadren en
billetera y segundo. Cualquier recompensa, depósito externo, Convert,
historial incompleto o fila ambigua deja la aceptación anterior fail-closed.
No confirma que un contribuyente no tenga tenencias en otros exchanges.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from binance_earn_inventory import BinanceEarnInventoryError, BinanceFungibleInventory

_ALLOWED_FLAGS = {
    "earn_flexible_requiere_inventario_y_valoracion_fiscal",
    "earn_ledger_sin_lotes_ni_valoracion_acreditados",
}
_ALLOWED_LEDGER_EARN = {
    "Simple Earn Flexible Subscription",
    "Simple Earn Flexible Redemption",
}
_EARN_TYPES = {"earn_flexible_subscription", "earn_flexible_redemption"}


@dataclass(frozen=True)
class BinancePrincipalOnlyAudit:
    """Prueba de custodia, no certificación de FIFO externo global."""
    transfer_events: int
    spot_trades: int
    assets: tuple[str, ...]
    sold: tuple[tuple[str, str, Decimal, Decimal], ...] = ()
    remaining: tuple[tuple[str, Decimal, Decimal], ...] = ()
    fifo_effect: str = "none"

    @property
    def fiscal_ready(self):
        # Esto solo acredita neutralidad de los TRASLADOS;
        # el PDF requiere las demás pruebas fiscales del pipeline.
        return False


def verify_principal_only_earn(classifier) -> BinancePrincipalOnlyAudit | None:
    events = tuple(getattr(classifier, "earn_events", ()))
    if not events or any(e.source not in _EARN_TYPES for e in events):
        return None
    sections = getattr(classifier, "_sections", {})
    rewards_section = sections.get("earn_flexible_rewards")
    if (rewards_section is None or not rewards_section.detectado
            or rewards_section.registros or not rewards_section.vacio):
        # Se requiere el CSV nativo de recompensas EXPRESAMENTE vacío;
        # la ausencia de un CSV no es prueba de que no haya rentas.
        return None
    bridge = getattr(classifier, "earn_reconciliation", None)
    rewards = getattr(classifier, "earn_reward_reconciliation", None)
    if (bridge is None or not bridge.instant_reconciled
            or bridge.native_events != len(events)
            or bridge.ledger_events != len(events)
            or bridge.matched_to_second != len(events)
            or rewards is None or rewards.native_records or rewards.ledger_records):
        return None
    if (getattr(classifier, "swaps", ()) or getattr(classifier, "rendimientos", ())
            or getattr(classifier, "desconocidas", ())
            or getattr(classifier, "comisiones_pendientes", ())
            or getattr(classifier, "valoraciones_pendientes", ())):
        return None
    if set(getattr(classifier, "fuentes_materiales_no_soportadas", ())) - _ALLOWED_FLAGS:
        return None
    if any(
        getattr(classifier, "_source_rows", {}).get(source)
        for source in (
            "fiat_trade", "fiat_exchange", "fiat_deposit", "fiat_withdrawal",
            "crypto_deposit", "crypto_withdrawal", "convert_orders",
            "recurring_convert", "earn_flexible_exchange",
        )
    ):
        return None
    for event in events:
        if event.precision != "second":
            return None
        if event.source == "earn_flexible_subscription":
            if event.origin.strip().upper() != "SPOT":
                return None
        elif event.destination.strip().upper() != "SPOT":
            return None
    for row, _filename in getattr(classifier, "_source_rows", {}).get("transaction_history", ()):
        kind = str(row.get("operación", "")).strip()
        if kind.startswith(("Simple Earn Flexible ", "Simple Earn Locked ")):
            if kind not in _ALLOWED_LEDGER_EARN:
                return None

    spot = tuple(getattr(classifier, "intercambios_nativos", ()))
    if len(spot) != len(getattr(classifier, "compraventas", ())):
        return None
    for event in spot:
        if event.source not in {"Spot BUY", "Spot SELL"}:
            return None
        if not ((event.given_asset == "EUR") ^ (event.received_asset == "EUR")):
            return None
        if event.fee_amount and event.fee_asset not in {
            "EUR", event.received_asset
        }:
            return None
    if not spot:
        # Una transferencia sin compra/venta no acredita inventario original.
        return None

    order = []
    for index, event in enumerate(spot):
        kind = "buy" if event.given_asset == "EUR" else "sell"
        asset = event.received_asset if kind == "buy" else event.given_asset
        order.append((event.local_time, asset, kind, index, event))
    for index, event in enumerate(events):
        kind = "subscribe" if event.source == "earn_flexible_subscription" else "redeem"
        order.append((event.original_time, event.asset, kind, index, event))
    # La precisión a segundos no demuestra si una compra, venta o transferencia
    # de la misma moneda dentro del mismo segundo sucedió primero.
    keys = [(stamp, asset) for stamp, asset, *_ in order]
    if len(keys) != len(set(keys)):
        return None

    book = BinanceFungibleInventory()
    sales = []
    try:
        for stamp, asset, kind, index, event in sorted(order):
            if kind == "buy":
                net = event.received_amount
                if event.fee_asset == event.received_asset:
                    net -= event.fee_amount
                cost = event.given_amount
                if event.fee_asset == "EUR":
                    cost += event.fee_amount
                book.acquire(
                    asset=asset, quantity=net, acquired_at=stamp,
                    wallet="SPOT", reference=f"native-buy-{index}",
                    cost_eur=cost,
                )
            elif kind == "sell":
                pieces = book.dispose(
                    asset=asset, quantity=event.given_amount,
                    timestamp=stamp, wallet="SPOT",
                    reference=f"native-sell-{index}",
                )
                if any(p.allocated_cost_eur is None for p in pieces):
                    return None
                sales.append((
                    stamp, asset, event.given_amount,
                    sum((p.allocated_cost_eur for p in pieces), Decimal("0")),
                ))
            elif kind == "subscribe":
                book.transfer(
                    asset=asset, quantity=event.amount,
                    timestamp=stamp, origin="SPOT",
                    destination="EARN_FLEXIBLE",
                    reference=f"native-earn-subscribe-{index}",
                )
            else:
                book.transfer(
                    asset=asset, quantity=event.amount,
                    timestamp=stamp, origin="EARN_FLEXIBLE",
                    destination="SPOT",
                    reference=f"native-earn-redeem-{index}",
                )
    except (BinanceEarnInventoryError, ValueError, ArithmeticError):
        return None
    assets = tuple(sorted({asset for _, asset, *_ in order}))
    if not all(book.conserved(asset) for asset in assets):
        return None
    # Evitar la aceptación de principal no redimido: el MotorFIFO legado no
    # informa por billetera ni posiciona saldos activos en Earn.
    if any(book.wallet_balance("EARN_FLEXIBLE", asset) != Decimal("0")
           for asset in assets):
        return None
    remaining = []
    for asset in assets:
        lots = book.lots(asset)
        if any(lot.cost_eur is None for lot in lots):
            return None
        remaining.append((
            asset,
            sum((lot.quantity for lot in lots), Decimal("0")),
            sum((lot.cost_eur for lot in lots), Decimal("0")),
        ))
    return BinancePrincipalOnlyAudit(
        transfer_events=len(events),
        spot_trades=len(spot),
        assets=assets,
        sold=tuple(sales),
        remaining=tuple(remaining),
    )


def validate_principal_only_motor(audit, motor) -> None:
    """Compara el motor fiscal con un inventario Decimal independiente.

    Ningún permiso parcial: importe FIFO, cantidad y posición completa han
    de concordar antes de JSON, PDF y generación del token.
    """
    if not isinstance(audit, BinancePrincipalOnlyAudit):
        raise ValueError("Datos fiscales no seguros: auditoría Earn inexistente.")
    results = tuple(motor.resultados)
    if len(results) != len(audit.sold):
        raise ValueError("Datos fiscales no seguros: ventas Earn no conciliadas con FIFO.")
    cent = Decimal("0.01")

    def same_eur(actual, exact):
        try:
            got = Decimal(str(actual))
            return (got.is_finite()
                    and abs(got - exact) <= Decimal("0.000000001")
                    and got.quantize(cent, rounding=ROUND_HALF_UP)
                    == exact.quantize(cent, rounding=ROUND_HALF_UP))
        except (ValueError, ArithmeticError):
            return False

    for result, (stamp, asset, qty, exact_cost) in zip(results, audit.sold):
        if (result.tipo_operacion != "venta"
                or result.fecha.strftime("%Y-%m-%d %H:%M:%S") != stamp
                or result.activo != asset
                or Decimal(str(result.cantidad_vendida)) != qty
                or not same_eur(result.precio_coste, exact_cost)):
            raise ValueError(
                "Datos fiscales no seguros: el coste FIFO de Earn no coincide "
                "con el inventario global Decimal."
            )
    current = {p.activo: p for p in motor.posicion_actual()}
    expected = {asset: (qty, cost) for asset, qty, cost in audit.remaining
                if qty > 0}
    if set(current) != set(expected):
        raise ValueError("Datos fiscales no seguros: posiciones Earn no conciliadas.")
    for asset, (qty, cost) in expected.items():
        position = current[asset]
        if (Decimal(str(position.cantidad_total)) != qty
                or not same_eur(position.coste_total, cost)):
            raise ValueError("Datos fiscales no seguros: saldo o coste Earn divergente.")
