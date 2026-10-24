"""Núcleo experimental FIFO multiexchange: Binance + Bitvavo.

Sin rutas, persistencia, PDF ni efectos externos. No habilitar para usuarios hasta
validar evidencias de titularidad, cobertura histórica y conciliación.
Los importes EUR no se infieren ni se convierten desde stablecoins.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re

from clasificador import ClasificadorBinance
from clasificador_binance_tx import ClasificadorBinanceTx
from clasificador_bitvavo import ClasificadorBitvavo
from motor_fifo import MotorFIFO


class FifoGlobalError(ValueError):
    """No se dispone de evidencia bastante para calcular un FIFO global."""


@dataclass(frozen=True)
class FuenteGlobal:
    exchange: str
    titular_id: int
    source_id: str
    archivo_sha256: str
    clasificador: object
    zona_horaria: str


@dataclass(frozen=True)
class TransferenciaConfirmada:
    salida_id: str
    entrada_id: str
    mismo_titular_verificado: bool


@dataclass(frozen=True)
class OperacionGlobal:
    id: str
    source_id: str
    exchange: str
    fecha_utc: datetime
    tipo: str
    activo: str
    cantidad: Decimal
    importe_eur: Decimal
    fee_eur: Decimal


@dataclass
class ResultadoGlobal:
    motor: MotorFIFO
    ejercicio: int
    operaciones: tuple[OperacionGlobal, ...]
    resultados_ejercicio: tuple
    transferencias_conciliadas: tuple[TransferenciaConfirmada, ...]


@dataclass(frozen=True)
class _Movimiento:
    id: str
    source_id: str
    fecha_utc: datetime
    tipo: str
    activo: str
    cantidad: Decimal


_ASSETS = re.compile(r"^[A-Z0-9]{2,30}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_FIXED_ZONE = re.compile(r"^(?:UTC)?([+-])(\d{2}):(\d{2})$")


def _decimal(value, label: str, *, allow_zero: bool = False) -> Decimal:
    try:
        num = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FifoGlobalError(f"{label}: número inválido") from exc
    if not num.is_finite() or num < 0 or (num == 0 and not allow_zero):
        raise FifoGlobalError(f"{label}: cantidad o valoración no positiva/finita")
    return num


def _activo(value: str) -> str:
    asset = str(value).strip().upper()
    if not _ASSETS.fullmatch(asset) or asset == "EUR":
        raise FifoGlobalError("Activo no identificable o distinto de criptoactivo")
    return asset


def _zona(zona: str):
    if zona == "UTC":
        return timezone.utc
    match = _FIXED_ZONE.fullmatch(str(zona))
    if match:
        sign, hh, mm = match.groups()
        hours, minutes = int(hh), int(mm)
        if hours <= 14 and minutes < 60 and (hours < 14 or minutes == 0):
            offset = timedelta(hours=hours, minutes=minutes)
            return timezone(offset if sign == "+" else -offset)
    raise FifoGlobalError("Zona horaria de origen no acreditada: usar UTC o un offset explícito")


def _fecha_utc(value, zona_horaria: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise FifoGlobalError("Fecha de operación inválida o ambigua") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_zona(zona_horaria))
    return dt.astimezone(timezone.utc)


def _validar_fuente(fuente: FuenteGlobal, titular_id: int) -> None:
    if fuente.titular_id != titular_id or not isinstance(titular_id, int) or titular_id <= 0:
        raise FifoGlobalError("Fuentes de distinto titular o titular sin validar")
    if not _SOURCE_ID.fullmatch(fuente.source_id) or not _SHA256.fullmatch(fuente.archivo_sha256):
        raise FifoGlobalError("Identificador de fuente o huella SHA-256 inválida")
    if fuente.exchange == "binance":
        if not isinstance(fuente.clasificador, (ClasificadorBinance, ClasificadorBinanceTx)):
            raise FifoGlobalError("Clasificador Binance incompatible")
    elif fuente.exchange == "bitvavo":
        if not isinstance(fuente.clasificador, ClasificadorBitvavo):
            raise FifoGlobalError("Clasificador Bitvavo incompatible")
        df = getattr(fuente.clasificador, "df", None)
        # Bitvavo includes a per-row Timezone field: the current parser drops
        # it when building naive timestamps. Require proof of UTC for EVERY row.
        if (fuente.zona_horaria != "UTC" or df is None
                or "Timezone" not in df.columns
                or df.empty or
                not df["Timezone"].astype(str).str.strip().eq("UTC").all()):
            raise FifoGlobalError("Bitvavo: exportación sin zona UTC acreditada por fila")
    else:
        raise FifoGlobalError("Exchange no incluido en el núcleo global inicial")
    _zona(fuente.zona_horaria)
    c = fuente.clasificador
    for name in ("compraventas", "swaps", "rendimientos", "movimientos", "desconocidas"):
        if not isinstance(getattr(c, name, None), list):
            raise FifoGlobalError(f"Clasificador sin conjunto completo: {name}")
    if c.desconocidas or getattr(c, "_no_reconocidos", ()) or getattr(c, "_fuentes_materiales_omitidas", ()):
        raise FifoGlobalError("Hay fuentes u operaciones fiscales no interpretadas")
    if c.swaps:
        raise FifoGlobalError("Permutas sin valoración EUR suficiente: no emitir FIFO global")


def _extraer(fuente: FuenteGlobal):
    operaciones, movimientos = [], []
    c = fuente.clasificador
    for index, op in enumerate(c.compraventas):
        kind = str(op.tipo).upper()
        if kind not in ("COMPRA", "VENTA"):
            raise FifoGlobalError("Tipo de compraventa no soportado")
        quote = str(op.contraparte).upper()
        if quote != "EUR":
            raise FifoGlobalError("Compraventa sin valoración histórica acreditada en EUR")
        asset = _activo(op.activo)
        qty = _decimal(op.cantidad, "Cantidad compraventa")
        gross = _decimal(op.importe, "Importe compraventa")
        fee = _decimal(op.fee_cantidad, "Comisión", allow_zero=True)
        fee_asset = str(op.fee_activo or "").upper()
        if fee and fee_asset != "EUR":
            raise FifoGlobalError("Comisión en cripto no valorada ni incorporada al inventario")
        if kind == "VENTA" and fee >= gross:
            raise FifoGlobalError("Comisión de venta igual o superior al importe")
        operations_id = f"{fuente.source_id}:cv:{index}"
        operaciones.append(OperacionGlobal(
            operations_id, fuente.source_id, fuente.exchange,
            _fecha_utc(op.fecha, fuente.zona_horaria), kind, asset, qty, gross, fee,
        ))

    for index, income in enumerate(c.rendimientos):
        qty = _decimal(income.cantidad, "Cantidad rendimiento")
        eur = _decimal(getattr(income, "valor_eur", None), "Rendimiento sin EUR acreditado")
        operaciones.append(OperacionGlobal(
            f"{fuente.source_id}:reward:{index}", fuente.source_id, fuente.exchange,
            _fecha_utc(income.fecha, fuente.zona_horaria), "RENDIMIENTO",
            _activo(income.activo), qty, eur, Decimal(0),
        ))

    for index, mov in enumerate(c.movimientos):
        asset = str(mov.activo).strip().upper()
        tipo = str(mov.subtipo).strip().lower()
        if asset == "EUR" and tipo in ("deposit", "withdraw", "withdrawal"):
            _decimal(mov.cantidad if mov.cantidad >= 0 else -mov.cantidad,
                     "Movimiento fiat", allow_zero=False)
            continue
        if tipo not in ("deposit", "withdraw", "withdrawal"):
            raise FifoGlobalError("Movimiento no conciliable que podría modificar el inventario")
        _activo(asset)
        qty = _decimal(abs(Decimal(str(mov.cantidad))), "Cantidad transferencia")
        movimientos.append(_Movimiento(
            f"{fuente.source_id}:movement:{index}", fuente.source_id,
            _fecha_utc(mov.fecha, fuente.zona_horaria),
            "entrada" if tipo == "deposit" else "salida", asset, qty,
        ))
    return operaciones, movimientos


def _conciliar(movimientos: list[_Movimiento],
               confirmaciones: tuple[TransferenciaConfirmada, ...]):
    por_id = {m.id: m for m in movimientos}
    if len(por_id) != len(movimientos):
        raise FifoGlobalError("ID de movimiento repetido")
    usados = set()
    for pair in confirmaciones:
        if not pair.mismo_titular_verificado:
            raise FifoGlobalError("Transferencia sin titularidad verificada")
        if pair.salida_id in usados or pair.entrada_id in usados:
            raise FifoGlobalError("Movimiento conciliado dos veces")
        salida, entrada = por_id.get(pair.salida_id), por_id.get(pair.entrada_id)
        if salida is None or entrada is None:
            raise FifoGlobalError("Transferencia referida a un movimiento inexistente")
        if (salida.tipo != "salida" or entrada.tipo != "entrada"
                or salida.source_id == entrada.source_id or salida.activo != entrada.activo):
            raise FifoGlobalError("Transferencia con origen/destino incompatibles")
        lapse = entrada.fecha_utc - salida.fecha_utc
        if not timedelta(0) <= lapse <= timedelta(hours=72):
            raise FifoGlobalError("Transferencia fuera de ventana temporal verificable")
        if salida.cantidad != entrada.cantidad:
            raise FifoGlobalError("Transferencia con diferencia de cantidad o comisión no valorada")
        usados.update((salida.id, entrada.id))
    if usados != set(por_id):
        raise FifoGlobalError("Movimientos de cripto sin conciliación explícita")
    return confirmaciones


def calcular_fifo_global(fuentes: tuple[FuenteGlobal, ...], *,
                         titular_id: int, ejercicio: int,
                         transferencias: tuple[TransferenciaConfirmada, ...] = ()) -> ResultadoGlobal:
    """Calcular únicamente en memoria; rechazar fuentes incompletas sin emitir nada.

    Solo Binance+Bitvavo (exactamente una fuente por exchange). Los ficheros
    deben abarcar todas las adquisiciones previas necesarias: si no se puede
    demostrar su exhaustividad, este núcleo NO constituye informe certificable.
    """
    if not isinstance(ejercicio, int) or not 2009 <= ejercicio <= 2100:
        raise FifoGlobalError("Ejercicio fiscal inválido")
    if len(fuentes) != 2 or {f.exchange for f in fuentes} != {"binance", "bitvavo"}:
        raise FifoGlobalError("La entrega inicial requiere Binance y Bitvavo, sin fuentes duplicadas")
    if len({f.source_id for f in fuentes}) != 2:
        raise FifoGlobalError("ID de fuente duplicado")
    if len({f.archivo_sha256.lower() for f in fuentes}) != 2:
        raise FifoGlobalError("Se ha importado dos veces el mismo archivo")

    operaciones, movimientos = [], []
    for f in fuentes:
        _validar_fuente(f, titular_id)
        ops, movs = _extraer(f)
        operaciones.extend(ops)
        movimientos.extend(movs)
    if not operaciones:
        raise FifoGlobalError("Los archivos no contienen adquisiciones ni ventas procesables")

    # No deduplicate trades by amount: identical economic amounts can be real
    # independent trades. A tied buy/sell of the same asset is ambiguous.
    timeline = sorted(operaciones, key=lambda o: (o.fecha_utc, o.activo, o.tipo, o.source_id, o.id))
    grouped = {}
    for op in timeline:
        grouped.setdefault((op.fecha_utc, op.activo), set()).add(op.tipo)
    if any("VENTA" in kinds and len(kinds) > 1 for kinds in grouped.values()):
        raise FifoGlobalError("Compra y venta del mismo activo con orden temporal ambiguo")
    _conciliar(movimientos, transferencias)

    motor = MotorFIFO()
    for op in timeline:
        fecha = op.fecha_utc.strftime("%Y-%m-%d %H:%M:%S.%f")
        if op.tipo in ("COMPRA", "RENDIMIENTO"):
            motor.registrar_compra(fecha, op.activo, float(op.cantidad),
                                  float(op.importe_eur + op.fee_eur), "EUR", "EUR", 0.0)
        elif op.tipo == "VENTA":
            motor.registrar_venta(fecha, op.activo, float(op.cantidad),
                                 float(op.importe_eur), "EUR", "EUR", float(op.fee_eur))
    motor.validar_integridad()
    if motor.advertencias or any(r.inventario_incompleto for r in motor.resultados):
        raise FifoGlobalError("Inventario global incompleto o cálculo con advertencias")
    if len(motor.resultados) != sum(o.tipo == "VENTA" for o in timeline):
        raise FifoGlobalError("Una venta no produjo un resultado FIFO íntegro")
    return ResultadoGlobal(
        motor, ejercicio, tuple(timeline),
        tuple(r for r in motor.resultados if r.fecha.year == ejercicio),
        tuple(transferencias),
    )
