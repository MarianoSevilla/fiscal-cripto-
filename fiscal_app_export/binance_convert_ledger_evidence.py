"""Conciliación probatoria de Binance Convert contra Transaction History.

Solo vincula hechos por patas exactas (moneda, signo, cantidad Decimal)
en una ventana 0..2 segundos desde la creación de orden. Un segundo no es
una identidad económica; la correspondencia debe ser uno-a-uno y no puede
reutilizar una pata de ledger. NO convierte las marcas del ledger en hora
fiscal de ejecución y NO valora lotes ni relaja bloqueos FIFO.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import re


class BinanceConvertLedgerError(ValueError):
    """Error de conciliación sin exponer movimientos privados."""


@dataclass(frozen=True)
class ConvertLedgerMatch:
    created_at: str
    debit_lag_seconds: int | None
    credit_lag_seconds: int | None
    status: str

    @property
    def exact_two_legs(self) -> bool:
        return self.status == "matched"

    @property
    def execution_time_accredited(self) -> bool:
        # La contabilidad +/- no certifica el instante de ejecución de Convert.
        return False


@dataclass(frozen=True)
class ConvertLedgerAudit:
    native_swaps: int
    matched: int
    no_ledger_day: int
    missing_on_ledger_day: int
    ambiguous: int
    split_seconds: int
    legs_at_created_second: int
    legs_one_second_later: int
    max_leg_delay_seconds: int
    matches: tuple[ConvertLedgerMatch, ...]

    @property
    def reconciled_where_ledger_exists(self) -> bool:
        return self.missing_on_ledger_day == self.ambiguous == 0

    @property
    def fiscal_ready(self) -> bool:
        return False


_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def _stamp(value):
    if not isinstance(value, str) or not _TIME_RE.fullmatch(value):
        raise BinanceConvertLedgerError("Hora de Convert no verificable")
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise BinanceConvertLedgerError("Fecha de Convert inexistente") from exc


def _quantity(value):
    if isinstance(value, (float, bool)):
        raise BinanceConvertLedgerError("Cantidad de Convert no exacta")
    try:
        q = Decimal(str(value).strip())
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise BinanceConvertLedgerError("Cantidad de Convert inválida") from exc
    if not q.is_finite() or not q:
        raise BinanceConvertLedgerError("Cantidad de Convert nula o no finita")
    return q


def audit_convert_ledger(native_exchanges, transaction_rows, *, max_lag_seconds=2):
    if type(max_lag_seconds) is not int or not 0 <= max_lag_seconds <= 2:
        raise BinanceConvertLedgerError("Ventana de conciliación no permitida")
    native = [
        op for op in native_exchanges
        if op.source == "Convert"
        and "EUR" not in (op.given_asset, op.received_asset)
    ]
    bins = defaultdict(list)
    ledger_days = set()
    for idx, row in enumerate(transaction_rows):
        if str(row.get("operación", "")).strip() != "Binance Convert":
            continue
        at = _stamp(row.get("tiempo"))
        asset = str(row.get("moneda", "")).strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{2,20}", asset):
            raise BinanceConvertLedgerError("Moneda de apunte Convert inválida")
        qty = _quantity(row.get("cambio"))
        bins[(asset, qty)].append((at, idx))
        ledger_days.add(at.date())
    candidates = []
    reuse = Counter()
    for event in native:
        start = _stamp(event.local_time)
        given_qty = _quantity(event.given_amount)
        recv_qty = _quantity(event.received_amount)
        if given_qty <= 0 or recv_qty <= 0:
            raise BinanceConvertLedgerError("Orden Convert con cantidad no positiva")
        def matches(asset, qty):
            return [(dt, idx) for dt, idx in bins.get((asset, qty), ())
                    if timedelta(0) <= dt - start <= timedelta(seconds=max_lag_seconds)]
        neg = matches(event.given_asset, -given_qty)
        pos = matches(event.received_asset, recv_qty)
        candidates.append((start, neg, pos))
        for _when, idx in neg + pos:
            reuse[idx] += 1
    outcomes = []
    for start, neg, pos in candidates:
        if not neg and not pos and start.date() not in ledger_days:
            outcomes.append(ConvertLedgerMatch(start.isoformat(sep=" "), None, None,
                                               "no_ledger_day"))
        elif (len(neg) != 1 or len(pos) != 1):
            status = "ambiguous" if len(neg) > 1 or len(pos) > 1 else "missing"
            outcomes.append(ConvertLedgerMatch(start.isoformat(sep=" "), None, None,
                                               status))
        elif reuse[neg[0][1]] > 1 or reuse[pos[0][1]] > 1:
            outcomes.append(ConvertLedgerMatch(start.isoformat(sep=" "), None, None,
                                               "ambiguous"))
        else:
            a = int((neg[0][0] - start).total_seconds())
            b = int((pos[0][0] - start).total_seconds())
            outcomes.append(ConvertLedgerMatch(start.isoformat(sep=" "), a, b, "matched"))
    lag = [x for m in outcomes if m.exact_two_legs for x in (
        m.debit_lag_seconds, m.credit_lag_seconds
    )]
    return ConvertLedgerAudit(
        native_swaps=len(native),
        matched=sum(m.exact_two_legs for m in outcomes),
        no_ledger_day=sum(m.status == "no_ledger_day" for m in outcomes),
        missing_on_ledger_day=sum(m.status == "missing" for m in outcomes),
        ambiguous=sum(m.status == "ambiguous" for m in outcomes),
        split_seconds=sum(
            m.exact_two_legs and m.debit_lag_seconds != m.credit_lag_seconds
            for m in outcomes
        ),
        legs_at_created_second=sum(x == 0 for x in lag),
        legs_one_second_later=sum(x == 1 for x in lag),
        max_leg_delay_seconds=max(lag, default=0),
        matches=tuple(outcomes),
    )
