"""Fase 3: auditoría independiente, SOLO LECTURA, del núcleo FIFO global.

Reconstruye con Decimal el vínculo venta -> lotes de adquisición, verifica
el detalle del MotorFIFO heredado y registra límites de evidencia originales.
No modifica motor, clasificadores, rutas, PostgreSQL ni PDF.

IMPORTANT: una trazabilidad interna coherente NO acredita por sí misma que
el usuario haya aportado todos los historiales ni que las cuentas sean propias.
"""
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal, localcontext

from clasificador_bitvavo import ClasificadorBitvavo, TIPOS_RENDIMIENTO
from fifo_global import (
    FifoGlobalError, FuenteGlobal, OperacionGlobal, ResultadoGlobal,
    calcular_fifo_global, _fecha_utc,
)


# The legacy engine uses float. We fail closed if its output differs from
# the independent Decimal ledger by more than one millionth EUR / 1e-12 unit.
_MAX_EUR_DIFF = Decimal("0.000001")
_MAX_QTY_DIFF = Decimal("0.000000000001")


@dataclass(frozen=True)
class EvidenciaOperacion:
    operacion_id: str
    exchange: str
    source_id: str
    archivo_sha256: str
    indice_clasificador: int
    fila_csv: int | None
    id_nativo: str | None
    tipo_vinculo: str  # fila_bitvavo | indice_clasificador


@dataclass(frozen=True)
class ConsumoTrazado:
    venta_id: str
    adquisicion_id: str
    cantidad: Decimal
    coste_eur: Decimal


@dataclass(frozen=True)
class VentaTrazada:
    venta_id: str
    activo: str
    fecha_utc: object
    transmision_neta_eur: Decimal
    coste_fifo_eur: Decimal
    ganancia_perdida_eur: Decimal
    consumos: tuple[ConsumoTrazado, ...]


@dataclass(frozen=True)
class AuditoriaGlobal:
    ejercicio: int
    fuentes: tuple[EvidenciaOperacion, ...]
    ventas: tuple[VentaTrazada, ...]
    ventas_ejercicio: tuple[VentaTrazada, ...]
    limitaciones: tuple[str, ...]
    historial_exhaustivo_acreditado: bool
    apto_informe_fiscal_publico: bool


@dataclass
class _Lote:
    adquisicion_id: str
    fecha_utc: object
    cantidad_original: Decimal
    restante: Decimal
    coste_eur: Decimal


def _dec(valor, descripcion: str) -> Decimal:
    try:
        d = Decimal(str(valor))
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise FifoGlobalError(f"Integridad FIFO: {descripcion} inválida") from exc
    if not d.is_finite():
        raise FifoGlobalError(f"Integridad FIFO: {descripcion} no finita")
    return d


def _igual_decimal(real, esperado: Decimal, tolerancia: Decimal, campo: str):
    if abs(_dec(real, campo) - esperado) > tolerancia:
        raise FifoGlobalError(f"Integridad FIFO: {campo} no coincide con los lotes originales")


def _bitvavo_evidencias(fuente: FuenteGlobal, operaciones: dict[str, OperacionGlobal]):
    """Correlaciona cada trade/reward con SU FILA, sin asumir IDs de otras fuentes."""
    c = fuente.clasificador
    df = c.df
    if df is None or df.empty:
        raise FifoGlobalError("Integridad FIFO: falta tabla de origen Bitvavo")
    trades, rewards = [], []
    usados = set()
    para_mismo_segundo = set()
    sin_id_nativo = False

    for i, fila in df.iterrows():
        if str(fila.get("Status", "")).strip() not in ("Completed", "Distributed"):
            continue
        tipo = str(fila.get("Type", "")).strip().lower()
        if tipo not in ("buy", "sell") and tipo not in TIPOS_RENDIMIENTO:
            continue
        id_nativo = str(fila.get("Transaction ID", "")).strip()
        if id_nativo and id_nativo.lower() not in ("nan", "none"):
            if id_nativo in usados:
                raise FifoGlobalError("Integridad FIFO: Transaction ID Bitvavo duplicado")
            usados.add(id_nativo)
        else:
            id_nativo = None
            sin_id_nativo = True
            # Without a native ID, identical economic rows in the same instant
            # cannot be distinguished from duplicated imports.
            signature = (tipo, str(fila.get("Date")), str(fila.get("Time")),
                         str(fila.get("Currency")), str(fila.get("Amount")),
                         str(fila.get("Received / Paid Amount")))
            if signature in para_mismo_segundo:
                raise FifoGlobalError("Integridad FIFO: fila Bitvavo repetida sin ID nativo")
            para_mismo_segundo.add(signature)
        record = (int(i) + 2, fila, id_nativo)
        if tipo in ("buy", "sell"):
            trades.append(record)
        else:
            rewards.append(record)

    expected_trades = [operaciones[f"{fuente.source_id}:cv:{i}"]
                       for i in range(len(c.compraventas))]
    expected_rewards = [operaciones[f"{fuente.source_id}:reward:{i}"]
                        for i in range(len(c.rendimientos))]
    if len(trades) != len(expected_trades) or len(rewards) != len(expected_rewards):
        raise FifoGlobalError("Integridad FIFO: número de filas Bitvavo diferente del clasificador")

    links = {}
    for tipo_entrada, rows, ops in (
        ("trade", trades, expected_trades), ("reward", rewards, expected_rewards)
    ):
        for n, ((linea, raw, native), op) in enumerate(zip(rows, ops)):
            raw_type = str(raw["Type"]).strip().lower()
            if (op.exchange != "bitvavo"
                    or op.activo != str(raw["Currency"]).strip().upper()
                    or _fecha_utc(str(raw["Date"]) + " " + str(raw["Time"]), "UTC")
                       != op.fecha_utc):
                raise FifoGlobalError("Integridad FIFO: operación Bitvavo no coincide con fila original")
            if tipo_entrada == "trade":
                if op.tipo != raw_type.upper():
                    raise FifoGlobalError("Integridad FIFO: dirección Bitvavo incompatible")
                raw_eur = abs(ClasificadorBitvavo._float(
                    raw["Received / Paid Amount"], required=True))
                _igual_decimal(op.importe_eur, _dec(raw_eur, "importe"),
                               _MAX_EUR_DIFF, "importe de fila Bitvavo")
                fee = abs(ClasificadorBitvavo._float(raw.get("Fee amount", "0")))
                _igual_decimal(op.fee_eur, _dec(fee, "comisión"),
                               _MAX_EUR_DIFF, "comisión de fila Bitvavo")
            else:
                if op.tipo != "RENDIMIENTO" or raw_type not in TIPOS_RENDIMIENTO:
                    raise FifoGlobalError("Integridad FIFO: rendimiento no vinculable")
                raw_qty = abs(ClasificadorBitvavo._float(raw["Amount"]))
                _igual_decimal(op.cantidad, _dec(raw_qty, "cantidad"),
                               _MAX_QTY_DIFF, "cantidad de rendimiento Bitvavo")
            links[op.id] = EvidenciaOperacion(
                op.id, op.exchange, fuente.source_id,
                fuente.archivo_sha256.lower(), n, linea, native, "fila_bitvavo",
            )
    return links, sin_id_nativo


def auditar_fifo_global(resultado: ResultadoGlobal,
                        fuentes: tuple[FuenteGlobal, ...]) -> AuditoriaGlobal:
    """Confirma lotes y sumas, sin certificar cobertura ni titularidad.

    El segundo cálculo vuelve a validar las fuentes actuales: impide aceptar
    un resultado cuyo clasificador se haya alterado tras calcularlo.
    """
    if not isinstance(resultado, ResultadoGlobal) or len(fuentes) != 2:
        raise FifoGlobalError("Integridad FIFO: resultado o fuentes incompatibles")
    owners = {f.titular_id for f in fuentes}
    if len(owners) != 1:
        raise FifoGlobalError("Integridad FIFO: distintas titularidades")
    # Uses Fase 2 guards again, including unknown ops and transfer pairing.
    comprobacion = calcular_fifo_global(
        fuentes, titular_id=next(iter(owners)), ejercicio=resultado.ejercicio,
        transferencias=resultado.transferencias_conciliadas)
    if comprobacion.operaciones != resultado.operaciones:
        raise FifoGlobalError("Integridad FIFO: fuentes alteradas tras el cálculo")
    if len(comprobacion.motor.resultados) != len(resultado.motor.resultados):
        raise FifoGlobalError("Integridad FIFO: resultados FIFO modificados")

    por_fuente = {f.source_id: f for f in fuentes}
    if len(por_fuente) != 2:
        raise FifoGlobalError("Integridad FIFO: fuente repetida")
    originales = {op.id: op for op in resultado.operaciones}
    if len(originales) != len(resultado.operaciones):
        raise FifoGlobalError("Integridad FIFO: operación repetida")

    links = {}
    missing_native = False
    for op in resultado.operaciones:
        f = por_fuente.get(op.source_id)
        if f is None or f.exchange != op.exchange:
            raise FifoGlobalError("Integridad FIFO: procedencia de operación desconocida")
        if op.exchange == "binance":
            # Synthetic classifier IDs are NOT native CSV transaction IDs.
            index = int(op.id.rsplit(":", 1)[1])
            links[op.id] = EvidenciaOperacion(
                op.id, op.exchange, f.source_id, f.archivo_sha256.lower(),
                index, None, None, "indice_clasificador")
        elif op.exchange != "bitvavo":
            raise FifoGlobalError("Integridad FIFO: exchange desconocido")
    for f in fuentes:
        if f.exchange == "bitvavo":
            raw_links, missing_native = _bitvavo_evidencias(f, originales)
            links.update(raw_links)
    if len(links) != len(originales):
        raise FifoGlobalError("Integridad FIFO: fuentes no vinculadas en su totalidad")

    engine_sales = iter(resultado.motor.resultados)
    pendientes = defaultdict(deque)
    ventas = []
    with localcontext() as ctx:
        ctx.prec = 60
        for op in resultado.operaciones:
            if op.tipo in ("COMPRA", "RENDIMIENTO"):
                pendientes[op.activo].append(_Lote(
                    op.id, op.fecha_utc, op.cantidad, op.cantidad,
                    op.importe_eur + op.fee_eur))
                continue
            if op.tipo != "VENTA":
                raise FifoGlobalError("Integridad FIFO: operación ajena a compraventa")
            motor_venta = next(engine_sales, None)
            if motor_venta is None:
                raise FifoGlobalError("Integridad FIFO: venta ausente del motor")
            if (motor_venta.activo != op.activo
                    or motor_venta.tipo_operacion != "venta"
                    or motor_venta.fecha.replace(tzinfo=timezone.utc) != op.fecha_utc):
                raise FifoGlobalError("Integridad FIFO: venta desordenada o cambiada")
            restante = op.cantidad
            detalle = []
            fifo_original = motor_venta.lotes_consumidos
            while restante > 0:
                queue = pendientes[op.activo]
                while queue and queue[0].restante == 0:
                    queue.popleft()
                if not queue:
                    raise FifoGlobalError("Integridad FIFO: lote histórico ausente")
                lot = queue[0]
                if lot.fecha_utc > op.fecha_utc:
                    raise FifoGlobalError("Integridad FIFO: lote adquirido después de la venta")
                consumida = min(restante, lot.restante)
                coste = lot.coste_eur * consumida / lot.cantidad_original
                detalle.append(ConsumoTrazado(op.id, lot.adquisicion_id,
                                              consumida, coste))
                restante -= consumida
                lot.restante -= consumida

            if len(fifo_original) != len(detalle):
                raise FifoGlobalError("Integridad FIFO: número de lotes consumidos diferente")
            for orig, traced in zip(fifo_original, detalle):
                adq = originales[traced.adquisicion_id]
                _igual_decimal(orig["cantidad"], traced.cantidad, _MAX_QTY_DIFF,
                               "cantidad de lote")
                _igual_decimal(orig["coste_parcial"], traced.coste_eur, _MAX_EUR_DIFF,
                               "coste de lote")
                if orig["fecha_compra"] != adq.fecha_utc.strftime("%Y-%m-%d"):
                    raise FifoGlobalError("Integridad FIFO: fecha de lote distinta")
            coste_fifo = sum((d.coste_eur for d in detalle), Decimal(0))
            transmision = op.importe_eur - op.fee_eur
            ganancia = transmision - coste_fifo
            if transmision <= 0:
                raise FifoGlobalError("Integridad FIFO: transmisión neta no positiva")
            _igual_decimal(motor_venta.cantidad_vendida, op.cantidad,
                           _MAX_QTY_DIFF, "cantidad vendida")
            _igual_decimal(motor_venta.precio_coste, coste_fifo,
                           _MAX_EUR_DIFF, "coste FIFO total")
            _igual_decimal(motor_venta.precio_transmision, transmision,
                           _MAX_EUR_DIFF, "valor de transmisión")
            _igual_decimal(motor_venta.ganancia_perdida, ganancia,
                           _MAX_EUR_DIFF, "ganancia patrimonial")
            ventas.append(VentaTrazada(
                op.id, op.activo, op.fecha_utc, transmision,
                coste_fifo, ganancia, tuple(detalle),
            ))
    if next(engine_sales, None) is not None:
        raise FifoGlobalError("Integridad FIFO: transmisiones adicionales en el motor")
    if tuple(resultado.resultados_ejercicio) != tuple(
            r for r in resultado.motor.resultados if r.fecha.year == resultado.ejercicio):
        raise FifoGlobalError("Integridad FIFO: ejercicio fiscal alterado")
    limites = [
        "No se acredita que estén incluidos todos los exchanges, wallets, "
        "operaciones y ejercicios anteriores del titular.",
        "Binance carece aquí de vínculo auditado a las filas/IDs nativos; "
        "el índice del clasificador no sustituye el justificante original.",
        "El SHA-256 ha sido declarado por el llamante, no recalculado "
        "contra los bytes del CSV por esta capa.",
        "El motor de referencia usa float; la concordancia Decimal se "
        "exige con tolerancia estricta, no se sustituye el motor.",
    ]
    if missing_native:
        limites.append("Hay filas Bitvavo sin identificador nativo.")
    if resultado.transferencias_conciliadas:
        limites.append("La titularidad de las transferencias fue declarada "
                       "por un booleano; falta prueba documental independiente.")
    ordered_links = tuple(links[op.id] for op in resultado.operaciones)
    return AuditoriaGlobal(
        resultado.ejercicio, ordered_links, tuple(ventas),
        tuple(v for v in ventas if v.fecha_utc.year == resultado.ejercicio),
        tuple(limites), False, False,
    )
