"""Conciliación de cantidades Earn y conservación de lotes globales Binance.

Fase de ingeniería independiente del IRPF. NO construye resultados de venta,
NO acredita costes EUR y NO permite emitir PDF fiscal. Los lotes globales
permanecen inalterados cuando una unidad se mueve entre billeteras.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
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
    mixed = 0

    for e in earn_events:
        direction = _SOURCE_DIRECTION.get(e.source)
        if direction is None:
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
    return BinanceEarnSourceBridge(
        ledger_events=sum(ledger.values()) + count_strict,
        native_events=sum(native.values()) + count_strict,
        matched_to_second=count_strict,
        matched_same_day=daily,
        ledger_unmatched=sum((lday-matches).values()),
        native_unmatched=sum((nday-matches).values()),
        ambiguous_same_day=ambiguous,
        mixed_or_unknown_origin=mixed,
    )


@dataclass(frozen=True)
class BinanceGlobalLot:
    """Adquisición original, independiente de dónde se custodien las unidades."""
    asset: str
    quantity: Decimal
    acquired_at: str
    cost_eur: Decimal | None
    reference: str


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
        name = str(value).strip().upper()
        if name not in {"SPOT", "EARN_FLEXIBLE", "FUNDING"}:
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

    def transfer(self, *, asset, quantity, timestamp, origin, destination):
        a = _asset(asset)
        q = _quantity(quantity)
        source, dest = self._wallet(origin), self._wallet(destination)
        dt = self._check_time(timestamp)
        if source == dest:
            raise BinanceEarnInventoryError("Transferencia sin cambio de billetera")
        if self._wallets[(source, a)] < q:
            raise BinanceEarnInventoryError("Saldo de origen insuficiente")
        # Solo cambia custodia; ni se modifica ni se divide ningún lote global.
        self._wallets[(source, a)] -= q
        self._wallets[(dest, a)] += q
        self._latest = dt

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
