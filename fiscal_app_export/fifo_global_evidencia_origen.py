"""Laboratorio Fase 4: verificar bytes y vincular operaciones a filas fuente.

Acepta un subconjunto intencionadamente estrecho: Binance CSV clásico con
pares Transaction Buy/Spend EUR (fee EUR opcional), y Bitvavo buy/sell EUR.
Toda fuente material fuera de ese contrato se rechaza, no se interpreta.
No se guardan archivos ni se valida la exhaustividad histórica o titularidad.
"""
import csv
import hashlib
import io
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from fifo_global import (
    FifoGlobalError, FuenteGlobal, OperacionGlobal, ResultadoGlobal, _fecha_utc,
)
from fifo_global_trazabilidad import auditar_fifo_global


_MAX_BYTES = 25 * 1024 * 1024
_QTY_TOL = Decimal("0.0000000001")
_EUR_TOL = Decimal("0.000001")
_BINANCE_HEADER = ("Tiempo", "Operación", "Moneda", "Cambio", "Cuenta", "Observación")
_BITVAVO_HEADER = (
    "Timezone", "Date", "Time", "Type", "Currency", "Amount",
    "Quote Currency", "Quote Price", "Received / Paid Currency",
    "Received / Paid Amount", "Fee currency", "Fee amount", "Status",
    "Transaction ID", "Address",
)


@dataclass(frozen=True)
class VinculoOriginal:
    operacion_id: str
    source_id: str
    archivo_sha256: str
    linea_final_csv: int
    id_nativo: str | None
    filas_origen: tuple[int, ...]


@dataclass(frozen=True)
class IntervaloObservado:
    source_id: str
    primera_operacion_utc: datetime
    ultima_operacion_utc: datetime
    filas_materiales_verificadas: int


@dataclass(frozen=True)
class RevisionOrigen:
    vinculos: tuple[VinculoOriginal, ...]
    intervalos: tuple[IntervaloObservado, ...]
    hashes_comprobados_con_bytes: bool
    historial_exhaustivo_acreditado: bool
    titularidad_acreditada: bool
    apto_informe_fiscal_publico: bool
    limitaciones: tuple[str, ...]


def _numero(valor: str, campo: str) -> Decimal:
    try:
        valor = Decimal(str(valor).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FifoGlobalError(f"Evidencia de origen: {campo} inválido") from exc
    if not valor.is_finite():
        raise FifoGlobalError(f"Evidencia de origen: {campo} no finito")
    return valor


def _cotejar(actual: Decimal, esperado: Decimal, tolerancia: Decimal, campo: str):
    if abs(actual - esperado) > tolerancia:
        raise FifoGlobalError(f"Evidencia de origen: {campo} no coincide con el CSV original")


def _filas_originales(data: bytes, cabecera: tuple[str, ...]):
    if not isinstance(data, bytes) or not 0 < len(data) <= _MAX_BYTES:
        raise FifoGlobalError("Evidencia de origen: archivo binario vacío, inválido o excesivo")
    try:
        texto = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FifoGlobalError("Evidencia de origen: CSV no UTF-8 verificable") from exc
    if "\x00" in texto:
        raise FifoGlobalError("Evidencia de origen: archivo con bytes NUL")
    lector = csv.reader(io.StringIO(texto, newline=""), strict=True)
    try:
        encabezado = next(lector)
        if tuple(encabezado) != cabecera:
            raise FifoGlobalError("Evidencia de origen: esquema CSV no reconocido")
        filas = []
        for campos in lector:
            if len(campos) != len(encabezado):
                raise FifoGlobalError("Evidencia de origen: CSV con columnas desalineadas")
            filas.append((dict(zip(encabezado, campos)), lector.line_num))
    except (csv.Error, StopIteration) as exc:
        raise FifoGlobalError("Evidencia de origen: CSV sintácticamente inválido") from exc
    if not filas:
        raise FifoGlobalError("Evidencia de origen: CSV sin filas verificables")
    return filas


def _operaciones_por_fuente(resultado: ResultadoGlobal, source_id: str):
    operaciones = {
        op.id: op for op in resultado.operaciones if op.source_id == source_id
    }
    if not operaciones:
        raise FifoGlobalError("Evidencia de origen: fuente sin operaciones normalizadas")
    return operaciones


def _verificar_binance(fuente: FuenteGlobal, filas, operaciones):
    """Solo parejas inequívocas en un instante; no inventar IDs de Binance."""
    grupos = defaultdict(list)
    for fila, linea in filas:
        tipo = fila["Operación"]
        if tipo not in ("Transaction Buy", "Transaction Spend", "Transaction Fee"):
            raise FifoGlobalError("Evidencia de origen: tipo Binance fuera del subconjunto acreditable")
        t = _fecha_utc(fila["Tiempo"], fuente.zona_horaria)
        grupos[t].append((fila, linea))
    encontrados = []
    for fecha, grupo in grupos.items():
        compra = [(f, line) for f, line in grupo if f["Operación"] == "Transaction Buy"]
        gasto = [(f, line) for f, line in grupo if f["Operación"] == "Transaction Spend"]
        fees = [(f, line) for f, line in grupo if f["Operación"] == "Transaction Fee"]
        if len(compra) != 1 or len(gasto) != 1 or len(fees) > 1:
            raise FifoGlobalError("Evidencia de origen: emparejamiento Binance ambiguo")
        buy, bline = compra[0]
        spend, sline = gasto[0]
        moneda_buy, moneda_spend = buy["Moneda"].strip().upper(), spend["Moneda"].strip().upper()
        buy_qty = _numero(buy["Cambio"], "compra Binance")
        spend_qty = _numero(spend["Cambio"], "gasto Binance")
        if buy_qty <= 0 or spend_qty >= 0:
            raise FifoGlobalError("Evidencia de origen: signo Binance incompatible")
        if moneda_buy == "EUR" and moneda_spend != "EUR":
            tipo, activo, qty, eur = "VENTA", moneda_spend, -spend_qty, buy_qty
        elif moneda_spend == "EUR" and moneda_buy != "EUR":
            tipo, activo, qty, eur = "COMPRA", moneda_buy, buy_qty, -spend_qty
        else:
            raise FifoGlobalError("Evidencia de origen: par Binance no valorado en EUR")
        fee_eur = Decimal(0)
        lines = [bline, sline]
        if fees:
            fee, fline = fees[0]
            if fee["Moneda"].strip().upper() != "EUR":
                raise FifoGlobalError("Evidencia de origen: comisión Binance no EUR")
            amount = _numero(fee["Cambio"], "comisión Binance")
            if amount >= 0:
                raise FifoGlobalError("Evidencia de origen: signo comisión Binance inválido")
            fee_eur = -amount
            lines.append(fline)
        candidates = [op for op in operaciones.values() if
                      op.fecha_utc == fecha and op.tipo == tipo and op.activo == activo]
        if len(candidates) != 1:
            raise FifoGlobalError("Evidencia de origen: vínculo Binance no único")
        op = candidates[0]
        _cotejar(op.cantidad, qty, _QTY_TOL, "cantidad Binance")
        _cotejar(op.importe_eur, eur, _EUR_TOL, "importe Binance")
        _cotejar(op.fee_eur, fee_eur, _EUR_TOL, "comisión Binance")
        encontrados.append(VinculoOriginal(
            op.id, fuente.source_id, fuente.archivo_sha256.lower(),
            max(lines), None, tuple(sorted(lines)),
        ))
    if {x.operacion_id for x in encontrados} != set(operaciones) or len(encontrados) != len(operaciones):
        raise FifoGlobalError("Evidencia de origen: operaciones Binance sin fila verificable")
    return encontrados, len(filas)


def _verificar_bitvavo(fuente: FuenteGlobal, filas, operaciones):
    vinculados, n = [], 0
    for fila, linea in filas:
        if fila["Timezone"].strip() != "UTC":
            raise FifoGlobalError("Evidencia de origen: zona Bitvavo no acreditada")
        if fila["Status"].strip() not in ("Completed", "Distributed"):
            raise FifoGlobalError("Evidencia de origen: estado Bitvavo sin tratamiento verificable")
        tipo = fila["Type"].strip().lower()
        if tipo not in ("buy", "sell"):
            raise FifoGlobalError("Evidencia de origen: evento Bitvavo sin vínculo acreditado")
        opid = f"{fuente.source_id}:cv:{n}"
        op = operaciones.get(opid)
        if op is None or op.tipo != {"buy": "COMPRA", "sell": "VENTA"}[tipo]:
            raise FifoGlobalError("Evidencia de origen: vínculo Bitvavo no único")
        if fila["Quote Currency"].strip().upper() != "EUR" or fila["Received / Paid Currency"].strip().upper() != "EUR":
            raise FifoGlobalError("Evidencia de origen: precio Bitvavo sin EUR acreditado")
        if op.activo != fila["Currency"].strip().upper():
            raise FifoGlobalError("Evidencia de origen: activo Bitvavo incompatible")
        fecha = _fecha_utc(fila["Date"].strip() + " " + fila["Time"].strip(), "UTC")
        if fecha != op.fecha_utc:
            raise FifoGlobalError("Evidencia de origen: fecha Bitvavo incompatible")
        raw_paid = _numero(fila["Received / Paid Amount"], "importe Bitvavo")
        if (tipo == "buy" and raw_paid >= 0) or (tipo == "sell" and raw_paid <= 0):
            raise FifoGlobalError("Evidencia de origen: signo Bitvavo incompatible")
        eur = abs(raw_paid)
        price = _numero(fila["Quote Price"], "precio Bitvavo")
        if price <= 0:
            raise FifoGlobalError("Evidencia de origen: precio Bitvavo no positivo")
        fee = _numero(fila["Fee amount"] or "0", "comisión Bitvavo")
        if fee and fila["Fee currency"].strip().upper() != "EUR":
            raise FifoGlobalError("Evidencia de origen: fee Bitvavo sin EUR")
        _cotejar(op.importe_eur, eur, _EUR_TOL, "importe Bitvavo")
        # ClasificadorBitvavo redondea cantidades a 10 decimales.
        qty = round(float(eur) / float(price), 10)
        _cotejar(op.cantidad, Decimal(str(qty)), _QTY_TOL, "cantidad Bitvavo")
        _cotejar(op.fee_eur, abs(fee), _EUR_TOL, "comisión Bitvavo")
        native = fila["Transaction ID"].strip()
        vinculados.append(VinculoOriginal(
            opid, fuente.source_id, fuente.archivo_sha256.lower(),
            linea, native or None, (linea,),
        ))
        n += 1
    if n != len(operaciones) or {x.operacion_id for x in vinculados} != set(operaciones):
        raise FifoGlobalError("Evidencia de origen: operaciones Bitvavo sin fila verificable")
    return vinculados, len(filas)


def verificar_origen_fifo_global(
    resultado: ResultadoGlobal,
    fuentes: tuple[FuenteGlobal, ...],
    archivos_por_source_id: Mapping[str, bytes],
) -> RevisionOrigen:
    """Vincula cálculo a bytes aportados sin acreditar integridad externa.

    No sustituye la auditoría Fase 3. Ninguna salida es autorización para
    elaborar un PDF fiscal o afirmar que el historial está completo.
    """
    if not isinstance(archivos_por_source_id, Mapping) or len(fuentes) != 2:
        raise FifoGlobalError("Evidencia de origen: fuentes/archivos inválidos")
    if set(archivos_por_source_id) != {f.source_id for f in fuentes}:
        raise FifoGlobalError("Evidencia de origen: archivos y fuentes no coinciden")
    # Re-ejecuta el control fiscal de Fase 2+3 sobre datos clasificados actuales.
    auditoria = auditar_fifo_global(resultado, fuentes)
    if auditoria.apto_informe_fiscal_publico:
        raise FifoGlobalError("Evidencia de origen: aprobación fiscal indebida")
    links, intervalos = [], []
    for fuente in fuentes:
        datos = archivos_por_source_id[fuente.source_id]
        if not isinstance(datos, bytes) or not 0 < len(datos) <= _MAX_BYTES:
            raise FifoGlobalError("Evidencia de origen: bytes inválidos o archivo excesivo")
        sha = hashlib.sha256(datos).hexdigest()
        if sha != fuente.archivo_sha256.lower():
            raise FifoGlobalError("Evidencia de origen: SHA-256 no coincide con bytes")
        if fuente.exchange == "binance":
            rows = _filas_originales(datos, _BINANCE_HEADER)
            evidencias, count = _verificar_binance(
                fuente, rows, _operaciones_por_fuente(resultado, fuente.source_id))
        elif fuente.exchange == "bitvavo":
            rows = _filas_originales(datos, _BITVAVO_HEADER)
            evidencias, count = _verificar_bitvavo(
                fuente, rows, _operaciones_por_fuente(resultado, fuente.source_id))
        else:
            raise FifoGlobalError("Evidencia de origen: exchange no incluido")
        fechas = [op.fecha_utc for op in resultado.operaciones if op.source_id == fuente.source_id]
        intervalos.append(IntervaloObservado(fuente.source_id, min(fechas), max(fechas), count))
        links.extend(evidencias)
    if {link.operacion_id for link in links} != {op.id for op in resultado.operaciones}:
        raise FifoGlobalError("Evidencia de origen: hay operaciones sin vínculo único")
    evidencia_clasificada = {e.operacion_id: e for e in auditoria.fuentes}
    for link in links:
        fase3 = evidencia_clasificada.get(link.operacion_id)
        if fase3 is None or fase3.archivo_sha256 != link.archivo_sha256:
            raise FifoGlobalError("Evidencia de origen: enlace fase 3 y SHA incoherentes")
        if fase3.exchange == "bitvavo" and fase3.id_nativo != link.id_nativo:
            raise FifoGlobalError("Evidencia de origen: ID nativo distinto del CSV original")
    by_id = {link.operacion_id: link for link in links}
    if len(by_id) != len(links):
        raise FifoGlobalError("Evidencia de origen: fila vinculada más de una vez")
    return RevisionOrigen(
        tuple(by_id[op.id] for op in resultado.operaciones), tuple(intervalos),
        True, False, False, False,
        (
            "SHA-256 calculado sobre bytes aportados; no acredita autenticidad externa del exchange.",
            "El mínimo y máximo de las operaciones observadas no demuestran cobertura continua o exhaustiva.",
            "No se contrastan cuentas de custodia ni titularidad mediante evidencia documental.",
            "Solo se aceptan tipos de operaciones con vínculo fuente implementado; se rechazan otros formatos.",
            "No se ha validado esta capa contra exportaciones reales aportadas con consentimiento.",
        ),
    )
