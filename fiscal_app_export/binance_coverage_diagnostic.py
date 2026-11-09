"""Diagnóstico NO fiscal de cobertura de saldos Binance con fecha inicial explícita.

Uso: pruebas de integridad de exportaciones multifuente. El saldo inicial cero
se aplica exclusivamente a la CUENTA Binance en la fecha asumida; jamás
implica coste de adquisición cero, ausencia de operaciones en otras plataformas
ni derecho a generar PDF. No modifica MotorFIFO ni clases de importación.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from itertools import groupby


class BinanceCoverageError(ValueError):
    pass


@dataclass(frozen=True)
class BinanceCoverageDeficit:
    activo: str
    primera_fecha: str
    saldo_minimo: Decimal


@dataclass(frozen=True)
class BinanceCoverageResult:
    fecha_inicio: str
    operaciones_contabilizadas: int
    activos_con_deficit: tuple[BinanceCoverageDeficit, ...]
    activos_depositados_sin_coste_acreditado: tuple[str, ...]
    movimientos_no_contabilizados: tuple[str, ...]

    @property
    def conciliacion_saldos_ok(self) -> bool:
        return not self.activos_con_deficit and not self.movimientos_no_contabilizados

    @property
    def coste_fiscal_acreditado(self) -> bool:
        # Un saldo no negativo es condición necesaria, NUNCA prueba que
        # la base fiscal esté reconstruida; ningún CSV de transferencia
        # documenta el coste previo del activo depositado.
        return False


def _decimal_positivo(value, *, allow_zero: bool = False) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BinanceCoverageError("Cantidad Binance no interpretable") from exc
    if not d.is_finite() or d < 0 or (not allow_zero and d == 0):
        raise BinanceCoverageError("Cantidad Binance inválida")
    return d


def _date(value: str) -> datetime:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise BinanceCoverageError("Fecha Binance no interpretable") from exc


def diagnosticar_saldo_inicial_cero(clasificador, *, inicio: str) -> BinanceCoverageResult:
    """Diagnóstico por evento, agrupado por segundo y activo.

    NO intenta reconstruir inventario global ni FIFO. En particular:
    - Las transferencias recibidas aumentan la cantidad, sin inventar coste.
    - Las comisiones en criptomonedas consumen cantidad.
    - Los movimientos no nativos se señalan como no conciliados.
    - El déficit es indicio de fuentes omitidas/incompletas, no prueba de
      adquisiciones anteriores a la fecha asumida.
    """
    if not isinstance(inicio, str) or len(inicio) != 10:
        raise BinanceCoverageError("Fecha de inicio inválida")
    try:
        fecha_inicio = datetime.strptime(inicio, "%Y-%m-%d")
    except ValueError as exc:
        raise BinanceCoverageError("Fecha de inicio inválida") from exc
    if fecha_inicio.strftime("%Y-%m-%d") != inicio:
        raise BinanceCoverageError("Fecha de inicio inválida")

    events: list[tuple[datetime, str, Decimal]] = []
    transferred_in: set[str] = set()
    uncovered: set[str] = set()
    date_checked = 0

    def movement(fecha, activo, cantidad):
        nonlocal date_checked
        dt = _date(fecha)
        if dt < fecha_inicio:
            raise BinanceCoverageError(
                "Existe una operación anterior al saldo inicial cero supuesto"
            )
        asset = str(activo or "").strip().upper()
        if not asset or any(ch.isspace() for ch in asset):
            raise BinanceCoverageError("Activo Binance inválido")
        q = Decimal(str(cantidad))
        if not q.is_finite():
            raise BinanceCoverageError("Cantidad Binance no finita")
        events.append((dt, asset, q))
        date_checked += 1

    for op in getattr(clasificador, "intercambios_nativos", ()):
        amount_give = _decimal_positivo(op.given_amount)
        amount_recv = _decimal_positivo(op.received_amount)
        movement(op.local_time, op.given_asset, -amount_give)
        movement(op.local_time, op.received_asset, amount_recv)
        fee = _decimal_positivo(op.fee_amount, allow_zero=True)
        if fee:
            if not op.fee_asset:
                raise BinanceCoverageError("Comisión sin moneda")
            movement(op.local_time, op.fee_asset, -fee)

    accepted_movements = {
        "Depósito cripto", "Retiro cripto", "Depósito fiat", "Retiro fiat",
    }
    for op in getattr(clasificador, "movimientos", ()):
        if op.subtipo not in accepted_movements:
            uncovered.add(str(op.subtipo or "movimiento no reconocido"))
            continue
        movement(op.fecha, op.activo, op.cantidad)
        if op.subtipo == "Depósito cripto":
            transferred_in.add(str(op.activo).upper())

    # Comisión de retiro: no está incorporada a OperacionMovimiento.
    for fee in getattr(clasificador, "comisiones_pendientes", ()):
        if fee.get("fuente") == "Retiro cripto":
            movement(fee["fecha"], fee["activo"], -_decimal_positivo(fee["cantidad"]))

    if getattr(clasificador, "rendimientos", ()):
        uncovered.add("rendimientos sin lotes fiscales")
    if getattr(clasificador, "desconocidas", ()):
        uncovered.add("operaciones no reconocidas")
    if getattr(clasificador, "fuentes_materiales_no_soportadas", ()):
        uncovered.add("fuentes materiales no soportadas")

    events.sort(key=lambda e: (e[0], e[1]))
    balances: dict[str, Decimal] = defaultdict(Decimal)
    first_negative: dict[str, str] = {}
    minima: dict[str, Decimal] = {}
    for (dt, asset), segment in groupby(events, lambda e: (e[0], e[1])):
        change = sum((q for _, _, q in segment), Decimal("0"))
        balances[asset] += change
        if balances[asset] < 0:
            first_negative.setdefault(asset, dt.strftime("%Y-%m-%d"))
            minima[asset] = min(minima.get(asset, Decimal("0")), balances[asset])
    return BinanceCoverageResult(
        fecha_inicio=inicio, operaciones_contabilizadas=date_checked,
        activos_con_deficit=tuple(
            BinanceCoverageDeficit(asset, first_negative[asset], minima[asset])
            for asset in sorted(first_negative)
        ),
        activos_depositados_sin_coste_acreditado=tuple(sorted(transferred_in)),
        movimientos_no_contabilizados=tuple(sorted(uncovered)),
    )
