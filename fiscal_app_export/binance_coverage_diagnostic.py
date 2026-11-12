"""Diagnóstico NO fiscal de cobertura de saldos Binance con fecha inicial explícita.

Uso: pruebas de integridad de exportaciones multifuente. El saldo inicial cero
se aplica exclusivamente a la CUENTA Binance en la fecha asumida; jamás
implica coste de adquisición cero, ausencia de operaciones en otras plataformas
ni derecho a generar PDF. No modifica MotorFIFO ni clases de importación.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
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
    pagos_externos_supuestos: int = 0
    saldos_finales: tuple[tuple[str, Decimal], ...] = ()

    @property
    def conciliacion_saldos_ok(self) -> bool:
        return (
            not self.activos_con_deficit
            and not self.movimientos_no_contabilizados
            and self.pagos_externos_supuestos == 0
        )

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


def diagnosticar_saldo_inicial_cero(
    clasificador, *, inicio: str, metodos_pago_externo: tuple[str, ...] = (),
) -> BinanceCoverageResult:
    """Compatibilidad: apertura de cantidades cero, solo para hipótesis sintéticas."""
    return _diagnosticar_saldos(
        clasificador, inicio=inicio,
        metodos_pago_externo=metodos_pago_externo, saldos_iniciales={},
    )


def diagnosticar_saldo_con_apertura(
    clasificador, *, inicio: str, saldos_iniciales: Mapping[str, Decimal | str],
    metodos_pago_externo: tuple[str, ...] = (),
) -> BinanceCoverageResult:
    """Diagnóstico de cantidades desde una apertura externa, NO de coste fiscal.

    La apertura debe haber sido acreditada fuera de este módulo. No acepta
    floats ni inferencias de coste de adquisición en EUR.
    """
    if not isinstance(saldos_iniciales, Mapping):
        raise BinanceCoverageError("Los saldos de apertura deben ser un mapa de cantidades")
    apertura: dict[str, Decimal] = {}
    for asset, amount in saldos_iniciales.items():
        if not isinstance(asset, str):
            raise BinanceCoverageError("Activo de apertura inválido")
        normalized = asset.strip().upper()
        if (not normalized or len(normalized) > 30
                or any(not (c.isascii() and (c.isalnum() or c in "._-"))
                       for c in normalized)):
            raise BinanceCoverageError("Activo de apertura inválido")
        if normalized in apertura:
            raise BinanceCoverageError("Activo de apertura duplicado")
        if isinstance(amount, (bool, float)) or not isinstance(amount, (str, Decimal)):
            raise BinanceCoverageError("Saldo de apertura: utiliza Decimal o texto, nunca float")
        try:
            qty = Decimal(amount)
        except (InvalidOperation, ValueError) as exc:
            raise BinanceCoverageError("Saldo de apertura inválido") from exc
        if not qty.is_finite() or qty < 0:
            raise BinanceCoverageError("Saldo de apertura negativo o no finito")
        apertura[normalized] = qty
    return _diagnosticar_saldos(
        clasificador, inicio=inicio,
        metodos_pago_externo=metodos_pago_externo, saldos_iniciales=apertura,
    )


def _diagnosticar_saldos(
    clasificador, *, inicio: str, metodos_pago_externo: tuple[str, ...],
    saldos_iniciales: dict[str, Decimal],
) -> BinanceCoverageResult:
    """Diagnóstico por evento, agrupado por segundo y activo.

    NO intenta reconstruir inventario global ni FIFO. En particular:
    - Las transferencias recibidas aumentan la cantidad, sin inventar coste.
    - Las comisiones en criptomonedas consumen cantidad.
    - Los movimientos no nativos se señalan como no conciliados.
    - El déficit es indicio de fuentes omitidas/incompletas, no prueba de
      adquisiciones anteriores a la fecha asumida.
    - Una compra fiat pagada desde el banco no implica necesariamente
      un cargo sobre el saldo fiat de Binance. Solo se descuenta fuera del
      libro si se pasa EXPLÍCITAMENTE el método exacto como hipótesis.
      Este supuesto nunca acredita saldo ni habilita FIFO/PDF.
    """
    if not isinstance(inicio, str) or len(inicio) != 10:
        raise BinanceCoverageError("Fecha de inicio inválida")
    try:
        fecha_inicio = datetime.strptime(inicio, "%Y-%m-%d")
    except ValueError as exc:
        raise BinanceCoverageError("Fecha de inicio inválida") from exc
    if fecha_inicio.strftime("%Y-%m-%d") != inicio:
        raise BinanceCoverageError("Fecha de inicio inválida")

    if not isinstance(metodos_pago_externo, tuple) or any(
        not isinstance(x, str) or not x.strip() for x in metodos_pago_externo
    ):
        raise BinanceCoverageError("Métodos externos deben ser una tupla de textos no vacíos")
    external_methods = {x.strip().casefold() for x in metodos_pago_externo}
    pagos_externos_supuestos = 0
    events: list[tuple[datetime, str, Decimal]] = []
    transferred_in: set[str] = set()
    uncovered: set[str] = set()
    date_checked = 0

    def movement(fecha, activo, cantidad):
        nonlocal date_checked
        dt = _date(fecha)
        if dt < fecha_inicio:
            raise BinanceCoverageError(
                "Existe una operación anterior a la fecha de apertura indicada"
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
        fee = _decimal_positivo(op.fee_amount, allow_zero=True)
        if fee and not op.fee_asset:
            raise BinanceCoverageError("Comisión sin moneda")

        # No confundir una compra de cripto pagada desde el banco con
        # una salida del monedero EUR de Binance. Solo bajo hipótesis
        # indicada explícitamente; el método nativo sigue conservado.
        external_bank_purchase = (
            op.source == "Fiat trade"
            and op.given_asset == "EUR"
            and str(getattr(op, "payment_method", "")).strip().casefold()
                in external_methods
        )
        if external_bank_purchase:
            pagos_externos_supuestos += 1
        else:
            movement(op.local_time, op.given_asset, -amount_give)
        movement(op.local_time, op.received_asset, amount_recv)
        if fee and not (external_bank_purchase and op.fee_asset == "EUR"):
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
    balances: dict[str, Decimal] = defaultdict(Decimal, saldos_iniciales)
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
        pagos_externos_supuestos=pagos_externos_supuestos,
        saldos_finales=tuple(sorted(balances.items())),
    )


@dataclass(frozen=True)
class BinanceStatementBalanceComparison:
    """Contraste de cantidades: NUNCA prueba lotes, coste EUR ni FIFO fiscal."""

    activos_comparados: tuple[str, ...]
    diferencias_materiales: tuple[tuple[str, Decimal, Decimal, Decimal], ...]
    diferencias_en_margen_de_presentacion: tuple[
        tuple[str, Decimal, Decimal, Decimal], ...
    ]
    activos_sin_dato_de_cierre: tuple[str, ...]
    margen_presentacion: Decimal

    @property
    def fifo_fiscal_acreditado(self) -> bool:
        return False


def contrastar_con_saldos_declarados(
    diagnostico: BinanceCoverageResult, *,
    saldos_cierre: Mapping[str, str | Decimal],
    unidad_presentacion: str | Decimal,
) -> BinanceStatementBalanceComparison:
    """Compara el diagnóstico contra cantidades publicadas en un statement.

    Es obligatorio aportar explícitamente la precisión de cantidad del
    extracto (p.ej. '0.000001'); nunca interpretar un activo ausente del
    statement como saldo cero. Como apertura y cierre pueden estar redondeados
    independientemente, una diferencia de hasta DOS unidades de presentación
    es solo compatible con su precisión, NO una conciliación acreditada.
    El análisis de costes y lotes requiere fuentes históricas adicionales.
    """
    if not isinstance(diagnostico, BinanceCoverageResult):
        raise BinanceCoverageError("Diagnóstico de saldos Binance inválido")
    if not isinstance(saldos_cierre, Mapping) or not saldos_cierre:
        raise BinanceCoverageError("Se requiere al menos un saldo de cierre declarado")

    if isinstance(unidad_presentacion, (bool, float)) or not isinstance(
        unidad_presentacion, (str, Decimal)
    ):
        raise BinanceCoverageError("Precisión del extracto debe ser texto o Decimal")
    try:
        unidad = Decimal(unidad_presentacion)
    except (InvalidOperation, ValueError) as exc:
        raise BinanceCoverageError("Precisión del extracto inválida") from exc
    if not unidad.is_finite() or unidad <= 0:
        raise BinanceCoverageError("Precisión del extracto inválida")

    cierre: dict[str, Decimal] = {}
    for raw_asset, raw_amount in saldos_cierre.items():
        if not isinstance(raw_asset, str):
            raise BinanceCoverageError("Activo del extracto inválido")
        asset = raw_asset.strip().upper()
        if (not asset or len(asset) > 30
                or any(not (c.isascii() and (c.isalnum() or c in "._-"))
                       for c in asset)):
            raise BinanceCoverageError("Activo del extracto inválido")
        if asset in cierre:
            raise BinanceCoverageError("Activo del extracto duplicado")
        if isinstance(raw_amount, (float, bool)) or not isinstance(
            raw_amount, (str, Decimal)
        ):
            raise BinanceCoverageError("Saldo del extracto requiere texto o Decimal")
        try:
            amount = Decimal(raw_amount)
        except (InvalidOperation, ValueError) as exc:
            raise BinanceCoverageError("Saldo del extracto inválido") from exc
        if not amount.is_finite() or amount < 0:
            raise BinanceCoverageError("Saldo del extracto inválido")
        cierre[asset] = amount

    calculados = dict(diagnostico.saldos_finales)
    material: list[tuple[str, Decimal, Decimal, Decimal]] = []
    precision: list[tuple[str, Decimal, Decimal, Decimal]] = []
    margen = unidad * 2
    for asset in sorted(cierre):
        calculated = calculados.get(asset, Decimal("0"))
        stated = cierre[asset]
        difference = calculated - stated
        item = (asset, calculated, stated, difference)
        if abs(difference) > margen:
            material.append(item)
        else:
            precision.append(item)
    return BinanceStatementBalanceComparison(
        activos_comparados=tuple(sorted(cierre)),
        diferencias_materiales=tuple(material),
        diferencias_en_margen_de_presentacion=tuple(precision),
        activos_sin_dato_de_cierre=tuple(sorted(set(calculados) - set(cierre))),
        margen_presentacion=margen,
    )
