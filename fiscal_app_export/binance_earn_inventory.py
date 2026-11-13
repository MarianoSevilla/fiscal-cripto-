"""Conciliación de cantidades Earn y conservación de lotes globales Binance.

Fase de ingeniería independiente del IRPF. NO construye resultados de venta,
NO acredita costes EUR y NO permite emitir PDF fiscal. Los lotes globales
permanecen inalterados cuando una unidad se mueve entre billeteras.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from decimal import Decimal, InvalidOperation
import re


class BinanceEarnInventoryError(ValueError):
    """Solo mensajes técnicos genéricos; no incluir filas del usuario."""


_OP_DIRECTION = {
    "Simple Earn Flexible Subscription": "subscription",
    "Simple Earn Flexible Redemption": "redemption",
}
_SOURCE_DIRECTION = {
    "earn_flexible_subscription": "subscription",
    "earn_flexible_redemption": "redemption",
}
_ASSET = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")


def _asset(value):
    asset = str(value).strip().upper()
    if not _ASSET.fullmatch(asset):
        raise BinanceEarnInventoryError("Activo no válido")
    return asset


def _quantity(value, *, allow_zero=False):
    if isinstance(value, (float, bool)):
        raise BinanceEarnInventoryError("Cantidad requiere Decimal o texto")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BinanceEarnInventoryError("Cantidad no interpretable") from exc
    if not amount.is_finite() or amount < 0 or (not allow_zero and amount == 0):
        raise BinanceEarnInventoryError("Cantidad debe ser finita y positiva")
    return amount


def _second(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise BinanceEarnInventoryError("Fecha con precisión de segundo requerida") from exc


@dataclass(frozen=True)
class BinanceEarnSourceBridge:
    ledger_events: int
    native_events: int
    matched_to_second: int
    matched_same_day: int
    ledger_unmatched: int
    native_unmatched: int
    ambiguous_same_day: int
    mixed_or_unknown_origin: int
    day_only_with_other_economic_activity: int = 0
    day_only_without_other_economic_activity: int = 0
    # Desglose de las filas sin homólogo, tras conciliar por segundo/día.
    # Los años no acreditan por sí solos la existencia de un CSV descargable.
    ledger_unmatched_by_year: tuple[tuple[int, int], ...] = ()
    native_unmatched_by_year: tuple[tuple[int, int], ...] = ()

    @property
    def quantities_reconciled(self):
        return self.ledger_unmatched == 0 and self.native_unmatched == 0

    @property
    def instant_reconciled(self):
        return (
            self.quantities_reconciled and self.matched_same_day == 0
            and self.ambiguous_same_day == 0
            and self.mixed_or_unknown_origin == 0
        )

    @property
    def fiscal_ready(self):
        # Coincidir en unidades no demuestra compras, origen, coste EUR,
        # recompensas, orden FIFO global ni todos los activos en otras cuentas.
        return False


def conciliar_earn_con_ledger(earn_events, ledger_rows):
    """Concilia *multiplicidades*, no empareja filas por cercanía temporal.

    Dos fuentes pueden tener la misma fecha/moneda/cantidad pero marcas de
    segundo distintas. Se informa coincidencia diaria, SIN asumir que
    se conoce el orden intradía. Repeticiones no se deduplican.
    """
    native = Counter()
    ledger = Counter()
    economic_days = set()
    mixed = 0

    for e in earn_events:
        direction = _SOURCE_DIRECTION.get(e.source)
        if direction is None:
            # Recompensas Earn del mismo día pueden crear nuevos lotes.
            if str(e.source) == "earn_flexible_rewards":
                dt = str(e.original_time)
                date = dt[:10]
                if len(dt) == 10:
                    try:
                        datetime.strptime(date, "%Y-%m-%d")
                    except ValueError as exc:
                        raise BinanceEarnInventoryError("Fecha Earn inválida") from exc
                else:
                    _second(dt)
                economic_days.add((date, _asset(e.asset)))
            continue
        dt = str(e.original_time)
        if len(dt) == 10:
            try:
                datetime.strptime(dt, "%Y-%m-%d")
            except ValueError as exc:
                raise BinanceEarnInventoryError("Fecha Earn inválida") from exc
        else:
            _second(dt)
        qty = _quantity(e.amount)
        key = (direction, dt, _asset(e.asset), qty)
        native[key] += 1
        if direction == "subscription":
            # Una suscripción desde SPOT+FUNDING no se debe imputar íntegra
            # a SPOT. Tampoco inventamos las proporciones de cada origen.
            if str(e.origin).strip().upper() != "SPOT":
                mixed += 1
        elif str(e.destination).strip().upper() != "SPOT":
            mixed += 1

    for row in ledger_rows:
        direction = _OP_DIRECTION.get(str(row.get("operación", "")).strip())
        if direction is None:
            # Exposición potencial al orden intradía cuando en ese activo
            # hubo hechos distintos del movimiento interno (ventas, fees,
            # intereses, depósitos, etc.). No deduce la hora correcta.
            stamp = str(row.get("tiempo", "")).strip()
            symbol = str(row.get("moneda", "")).strip().upper()
            if len(stamp) == 19 and _ASSET.fullmatch(symbol):
                _second(stamp)
                economic_days.add((stamp[:10], symbol))
            continue
        raw = str(row.get("tiempo", ""))
        _second(raw)
        asset = _asset(row.get("moneda", ""))
        amount_text = str(row.get("cambio", ""))
        try:
            signed = Decimal(amount_text)
        except (InvalidOperation, ValueError) as exc:
            raise BinanceEarnInventoryError("Cantidad Earn del ledger inválida") from exc
        if not signed.is_finite() or signed == 0:
            raise BinanceEarnInventoryError("Cantidad Earn del ledger inválida")
        if ((direction == "subscription" and signed >= 0) or
                (direction == "redemption" and signed <= 0)):
            raise BinanceEarnInventoryError("Dirección Earn del ledger incoherente")
        if str(row.get("cuenta", "")).strip().upper() != "SPOT":
            mixed += 1
        ledger[(direction, raw, asset, abs(signed))] += 1

    strict = native & ledger
    count_strict = sum(strict.values())
    native.subtract(strict)
    ledger.subtract(strict)
    native += Counter()
    ledger += Counter()

    def by_day(items):
        result = Counter()
        for (direction, dt, asset, qty), multiplicity in items.items():
            result[(direction, dt[:10], asset, qty)] += multiplicity
        return result

    nday = by_day(native)
    lday = by_day(ledger)
    matches = nday & lday
    daily = sum(matches.values())
    ambiguous = sum(count for key, count in matches.items()
                    if nday[key] > 1 or lday[key] > 1)
    with_activity = sum(count for (_dir, day, asset, _qty), count in matches.items()
                        if (day, asset) in economic_days)
    without_activity = daily - with_activity
    missing_ledger = lday - matches
    missing_native = nday - matches

    def by_year(unmatched):
        counts = Counter()
        for (_direction, day, _asset, _qty), count in unmatched.items():
            counts[int(day[:4])] += count
        return tuple(sorted(counts.items()))

    return BinanceEarnSourceBridge(
        ledger_events=sum(ledger.values()) + count_strict,
        native_events=sum(native.values()) + count_strict,
        matched_to_second=count_strict,
        matched_same_day=daily,
        ledger_unmatched=sum(missing_ledger.values()),
        native_unmatched=sum(missing_native.values()),
        ambiguous_same_day=ambiguous,
        mixed_or_unknown_origin=mixed,
        day_only_with_other_economic_activity=with_activity,
        day_only_without_other_economic_activity=without_activity,
        ledger_unmatched_by_year=by_year(missing_ledger),
        native_unmatched_by_year=by_year(missing_native),
    )


@dataclass(frozen=True)
class BinanceGlobalLot:
    """Adquisición original, independiente de dónde se custodien las unidades."""
    asset: str
    quantity: Decimal
    acquired_at: str
    cost_eur: Decimal | None
    reference: str


@dataclass(frozen=True)
class BinanceConsumedLot:
    """Parte efectivamente consumida de un lote global, SIN ganancia fiscal."""
    acquisition_reference: str
    acquired_at: str
    quantity: Decimal
    allocated_cost_eur: Decimal | None


class BinanceFungibleInventory:
    """Inventario global con saldos por billetera; transferencia NO modifica lotes.

    Una transferencia interna no crea lote, no cambia antigüedad o valor fiscal
    y no registra compraventa. Esto es una base de conciliación, NO motor IRPF.
    """

    def __init__(self):
        self._lots = defaultdict(list)
        self._wallets = defaultdict(Decimal)
        self._refs = set()
        self._latest = None

    def _check_time(self, timestamp):
        value = _second(timestamp)
        if self._latest is not None and value < self._latest:
            raise BinanceEarnInventoryError("Operaciones desordenadas temporalmente")
        return value

    @staticmethod
    def _wallet(value):
        # Las seis cuentas listadas aparecen realmente en los históricos
        # Binance; EARN_FLEXIBLE es una custodia interna conciliada por
        # los CSV Earn, no un tipo de cuenta fiscal.
        #
        # Reconocer una billetera NO clasifica su actividad económica,
        # ni convierte derivados/futuros en adquisiciones FIFO.
        if not isinstance(value, str):
            raise BinanceEarnInventoryError("Billetera no identificada")
        name = value.strip().upper()
        if name not in {
            "SPOT", "EARN_FLEXIBLE", "FUNDING", "USD-M FUTURES",
            "COIN-M FUTURES", "POOL", "ALPHA",
        }:
            raise BinanceEarnInventoryError("Billetera no identificada")
        return name

    def acquire(self, *, asset, quantity, acquired_at, wallet, reference, cost_eur=None):
        a = _asset(asset)
        q = _quantity(quantity)
        w = self._wallet(wallet)
        dt = self._check_time(acquired_at)
        if not isinstance(reference, str) or not reference.strip() or reference in self._refs:
            raise BinanceEarnInventoryError("Referencia de lote ausente o repetida")
        cost = None if cost_eur is None else _quantity(cost_eur)
        # Toda mutación después de validar TODOS los campos.
        self._lots[a].append(BinanceGlobalLot(a, q, acquired_at, cost, reference))
        self._wallets[(w, a)] += q
        self._refs.add(reference)
        self._latest = dt

    def transfer(self, *, asset, quantity, timestamp, origin, destination,
                 reference):
        """Traslada custodia una sola vez: las referencias impiden replays.

        Una coincidencia de moneda/importe/segundo NO acredita identidad.
        La capa llamadora debe aportar una referencia unívoca verificada; no
        debe fabricar referencias distintas para duplicados del mismo hecho.
        """
        a = _asset(asset)
        q = _quantity(quantity)
        source, dest = self._wallet(origin), self._wallet(destination)
        dt = self._check_time(timestamp)
        if not isinstance(reference, str) or not reference.strip() or reference in self._refs:
            raise BinanceEarnInventoryError(
                "Referencia de transferencia ausente o repetida"
            )
        if source == dest:
            raise BinanceEarnInventoryError("Transferencia sin cambio de billetera")
        if self._wallets[(source, a)] < q:
            raise BinanceEarnInventoryError("Saldo de origen insuficiente")
        # Solo cambia custodia; ni se modifica ni se divide ningún lote global.
        self._wallets[(source, a)] -= q
        self._wallets[(dest, a)] += q
        self._refs.add(reference)
        self._latest = dt

    def transfer_split(self, *, asset, quantity, timestamp,
                       origin_allocations, destination, reference):
        """Traslada una suscripción multibilletera SOLO con reparto documentado.

        'SPOT + FUNDING' no acredita las cantidades por origen. Esta función
        requiere ambas cantidades explícitas; no las deduce ni iguala el total
        a SPOT. Verifica todas las patas antes de mutar, conserva lotes y no
        autoriza un resultado fiscal.
        """
        a = _asset(asset)
        q = _quantity(quantity)
        dst = self._wallet(destination)
        dt = self._check_time(timestamp)
        if not isinstance(reference, str) or not reference.strip() or reference in self._refs:
            raise BinanceEarnInventoryError("Referencia de transferencia ausente o repetida")
        if not isinstance(origin_allocations, dict) or len(origin_allocations) < 2:
            raise BinanceEarnInventoryError("Reparto de origen multibilletera no acreditado")
        sources = {}
        for wallet, amount in origin_allocations.items():
            src = self._wallet(wallet)
            if src == dst or src in sources:
                raise BinanceEarnInventoryError("Orígenes de transferencia incompatibles")
            sources[src] = _quantity(amount)
        if sum(sources.values(), Decimal(0)) != q:
            raise BinanceEarnInventoryError("El reparto no coincide con el total transferido")
        if any(self._wallets.get((src, a), Decimal(0)) < amount
               for src, amount in sources.items()):
            raise BinanceEarnInventoryError("Saldo de origen insuficiente")

        for src, amount in sources.items():
            self._wallets[(src, a)] -= amount
        self._wallets[(dst, a)] += q
        self._refs.add(reference)
        self._latest = dt

    def dispose(self, *, asset, quantity, timestamp, wallet, reference):
        """Descuenta unidades de una venta/fee mediante FIFO *global*.

        Solo inventario: no calcula transmisión, valor de mercado, rendimientos,
        ni autoriza PDF. Usa el saldo de la billetera para verificar custodia,
        pero elige lotes por fecha global, aun si fueron trasladados a Earn.
        Rechaza orden intrasegundo ambiguo y duplicidades por referencia.
        Valida todo antes de mutar el estado.
        """
        a = _asset(asset)
        q = _quantity(quantity)
        w = self._wallet(wallet)
        dt = self._check_time(timestamp)
        if not isinstance(reference, str) or not reference.strip() or reference in self._refs:
            raise BinanceEarnInventoryError("Referencia de disposición ausente o repetida")
        if self._wallets.get((w, a), Decimal(0)) < q:
            raise BinanceEarnInventoryError("Saldo de origen insuficiente")

        remaining = q
        after = []
        consumed = []
        for acquired_at, iterator in groupby(self._lots.get(a, ()), key=lambda l: l.acquired_at):
            group = list(iterator)
            if remaining > 0:
                if _second(acquired_at) >= dt:
                    raise BinanceEarnInventoryError(
                        "No se acredita orden temporal entre adquisición y disposición"
                    )
                group_total = sum((lot.quantity for lot in group), Decimal(0))
                if len(group) > 1 and remaining < group_total:
                    raise BinanceEarnInventoryError(
                        "Lotes adquiridos al mismo segundo sin orden FIFO acreditado"
                    )
            for lot in group:
                taken = min(remaining, lot.quantity)
                if not taken:
                    after.append(lot)
                    continue
                cost_used = (
                    None if lot.cost_eur is None
                    else lot.cost_eur * taken / lot.quantity
                )
                consumed.append(BinanceConsumedLot(
                    acquisition_reference=lot.reference,
                    acquired_at=lot.acquired_at,
                    quantity=taken,
                    allocated_cost_eur=cost_used,
                ))
                rest = lot.quantity - taken
                if rest:
                    after.append(BinanceGlobalLot(
                        asset=a, quantity=rest, acquired_at=lot.acquired_at,
                        cost_eur=(None if lot.cost_eur is None
                                  else lot.cost_eur - cost_used),
                        reference=lot.reference,
                    ))
                remaining -= taken
        if remaining:
            raise BinanceEarnInventoryError("Inventario global insuficiente")

        self._lots[a] = after
        self._wallets[(w, a)] -= q
        self._refs.add(reference)
        self._latest = dt
        return tuple(consumed)

    def wallet_balance(self, wallet, asset):
        return self._wallets[(self._wallet(wallet), _asset(asset))]

    def lots(self, asset):
        return tuple(self._lots.get(_asset(asset), ()))

    def conserved(self, asset):
        a = _asset(asset)
        wallet_total = sum(
            (q for (wallet, symbol), q in self._wallets.items() if symbol == a),
            Decimal(0),
        )
        lot_total = sum((lot.quantity for lot in self._lots[a]), Decimal(0))
        return wallet_total == lot_total

    @property
    def fiscal_ready(self):
        # Nunca utilizar esta clase como autorización para emitir IRPF.
        return False
