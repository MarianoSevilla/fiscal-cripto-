"""
Clasificador fiscal de operaciones KuCoin — flujo MULTIARCHIVO
Mariano Sevilla — marianosevilla.com

KuCoin no exporta trades clásicos con par/precio/order id. Exporta varios
historiales contables (ledger). El usuario puede subir uno o varios CSV a la vez;
el sistema detecta el tipo de cada fichero por su cabecera y reconstruye las
operaciones fiscales.

Ficheros reales soportados (Fase 1):
  · Historial de la cuenta — Cuenta de trading      (ledger: Spot, Transfer, Convert Dust to KCS)
  · Historial de la cuenta — Cuenta de financiación  (ledger: Fiat Deposit, Fiat Transactions, Transfer)
  · Órdenes fiat — Depósitos fiat                     (complemento informativo, con deduplicación)
  · Historial de depósitos/retiradas (cripto)         (cabecera reconocida; puede venir vacío)

Decisiones de diseño:
  · Cada fichero ledger se procesa por su columna `Type`, NO por el nombre del
    fichero. "Cuenta de trading" y "Cuenta de financiación" comparten cabecera
    idéntica; la etiqueta para la UX se infiere de los Type presentes.
  · Spot y Fiat Transactions se reconstruyen agrupando filas por (Time, Type):
    Side=Deposit → activo recibido; Side=Withdrawal → activo entregado.
  · 1 moneda recibida + 1 entregada → operación agregada. Mezcla ambigua → advertencia.
  · Convert Dust to KCS → permuta (transmisión patrimonial).
  · Transfer / Fiat Deposit / depósitos-retiros cripto → movimiento, SIN impacto fiscal.
  · Timezone naive: el offset va en el NOMBRE de la columna (Time(UTC+02:00)),
    no en el valor — se conserva tal cual, igual que MEXC. No se convierte a UTC.
  · Encoding UTF-8 con BOM; separador coma; punto decimal; muchos decimales.
  · Archivo con cabecera válida y "No matching records found." (o sin filas) =
    reconocido VACÍO → advertencia suave, nunca error fatal.

Expone la misma interfaz que ClasificadorMEXC / ClasificadorBinance para ser
compatible con _pipeline_motor y procesar_con_fifo:
    compraventas · swaps · movimientos · rendimientos · desconocidas · advertencias
Además expone `resumen_archivos` (dict) para el resumen de subida en la UI.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── EXCEPCIONES TIPIFICADAS (mismo patrón que MEXC) ────────────────────────────

class KucoinUserError(ValueError):
    """
    Error imputable al usuario: ningún fichero reconocido, todos vacíos, etc.
    No es un bug del parser. `analizar` lo interpreta vía .code / .category.
    """
    def __init__(self, code: str, mensaje_usuario: str):
        super().__init__(mensaje_usuario)
        self.code     = code
        self.category = "user_error"


# ── CONSTANTES FISCALES ────────────────────────────────────────────────────────

STABLES_EUR = {"EUR", "EURX"}
STABLES_USD = {"USDT", "USDC", "BUSD", "USD", "FDUSD", "DAI", "TUSD"}
FIAT        = {"EUR", "USD", "GBP", "CHF"}
# Monedas que actúan como contraparte (quote) en una compraventa.
QUOTE_LIKE  = STABLES_EUR | STABLES_USD | FIAT

KCS = "KCS"

# Firma textual de fichero vacío de KuCoin.
_NO_RECORDS = "no matching records found"

_FECHA_FORMATOS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
]

# Ventana (segundos) para agrupar las patas de una misma operación.
# En los exports reales de KuCoin las dos patas de un trade comparten el mismo
# segundo, salvo Fiat Transactions, cuyas patas pueden diferir 1 segundo
# (EUR Withdrawal a HH:MM:40, USDT Deposit a HH:MM:41). Las operaciones DISTINTAS
# están separadas por decenas de segundos como mínimo, así que una ventana pequeña
# agrupa las patas correlativas sin fusionar operaciones independientes.
_GROUP_WINDOW_SEG = 2


# ── DATACLASSES (misma forma que clasificador.py para compatibilidad FIFO) ─────

@dataclass
class OperacionCompraventa:
    fecha: str
    tipo: str           # "COMPRA" | "VENTA"
    activo: str         # moneda base (XRP, BTC…)
    cantidad: float
    contraparte: str    # moneda quote (EUR, USDT…)
    importe: float
    fee_activo: str
    fee_cantidad: float

@dataclass
class OperacionSwap:
    fecha: str
    activo_entregado: str
    cantidad_entregada: float
    activo_recibido: str
    cantidad_recibida: float
    nota: str = ""

@dataclass
class OperacionMovimiento:
    fecha: str
    subtipo: str        # "Fiat Deposit" | "Transfer" | "Deposito cripto" | "Retiro cripto" | "Fiat Order"
    activo: str
    cantidad: float
    observacion: str = ""

@dataclass
class OperacionRendimiento:
    fecha: str
    subtipo: str
    activo: str
    cantidad: float
    cuenta: str = "KuCoin"

@dataclass
class OperacionDesconocida:
    fecha: str
    subtipo: str
    activo: str
    cantidad: float
    cuenta: str = "KuCoin"


# ── DETECCIÓN DE FORMATO ───────────────────────────────────────────────────────

def _norm_header(h: str) -> str:
    """Normaliza una cabecera: minúsculas, sin BOM, sin '(UTC±hh:mm)', sin espacios extra.
    'Time(UTC+02:00)' → 'time' · 'Currency (Fiat)' → 'currency (fiat)'.
    """
    h = (h or "").replace("﻿", "").strip().lower()
    h = re.sub(r"\(utc[^)]*\)", "", h).strip()   # quita el offset de la columna de fecha
    return h


# Firmas por subconjunto de columnas normalizadas (distintivas de cada fichero).
_SIG_FIAT_ORDERS     = {"order id", "currency (fiat)", "fiat amount", "deposit method"}
_SIG_DEPOSITO_CRIPTO = {"coin", "transfer network", "deposit address", "hash"}
_SIG_LEDGER          = {"currency", "side", "amount", "time", "type"}

# Para la validación de subida en app.py (lista de tokens identificativos KuCoin).
KUCOIN_SIGNATURES = [
    "Transfer Network", "Deposit Address",   # depósitos cripto
    "Order ID", "Currency (Fiat)",           # órdenes fiat
    "Side", "Remark",                        # ledger
]


def _detectar_tipo(headers: List[str]) -> str:
    """Devuelve: 'fiat_orders' | 'deposito_cripto' | 'ledger' | 'desconocido'."""
    norm = {_norm_header(h) for h in headers}
    if _SIG_FIAT_ORDERS.issubset(norm):
        return "fiat_orders"
    if _SIG_DEPOSITO_CRIPTO.issubset(norm):
        return "deposito_cripto"
    if _SIG_LEDGER.issubset(norm):
        return "ledger"
    return "desconocido"


# ── HELPERS ────────────────────────────────────────────────────────────────────

def _leer_csv(filepath: str) -> Tuple[List[str], List[dict], bool]:
    """
    Lee un CSV de KuCoin. Devuelve (headers_originales, filas_dict, vacio).

    `vacio` es True si tras la cabecera no hay filas de datos o aparece
    "No matching records found." — fichero reconocido válido vacío.
    Las claves de cada fila se normalizan con _norm_header para acceso estable.
    """
    with open(filepath, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return [], [], True

        norm_keys = [_norm_header(h) for h in headers]
        filas: List[dict] = []
        for row in reader:
            if not any((c or "").strip() for c in row):
                continue
            primera = (row[0] or "").strip().lower()
            if _NO_RECORDS in primera:
                continue
            d = {}
            for i, key in enumerate(norm_keys):
                d[key] = (row[i].strip() if i < len(row) and row[i] is not None else "")
            filas.append(d)

    return headers, filas, (len(filas) == 0)


def _parse_decimal(valor: str) -> Decimal:
    try:
        clean = (valor or "").strip().replace(",", "")
        if not clean:
            return Decimal("0")
        return Decimal(clean)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_fecha(valor: str) -> str:
    """Normaliza a 'YYYY-MM-DD HH:MM:SS'. El offset va en el nombre de columna;
    el valor es naive y se conserva sin convertir (igual que MEXC)."""
    valor = (valor or "").strip()
    for fmt in _FECHA_FORMATOS:
        try:
            return datetime.strptime(valor, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    logger.warning("KuCoin: fecha no reconocida: %r", valor)
    return valor


def _to_dt(valor: str):
    """Parsea el valor de fecha a datetime (naive). Devuelve None si no es válido."""
    valor = (valor or "").strip()
    for fmt in _FECHA_FORMATOS:
        try:
            return datetime.strptime(valor, fmt)
        except ValueError:
            continue
    return None


def _es_deposit(side: str) -> bool:
    return (side or "").strip().lower().startswith("dep")


def _es_withdrawal(side: str) -> bool:
    s = (side or "").strip().lower()
    return s.startswith("with") or s.startswith("retir")


# ── CLASIFICADOR ───────────────────────────────────────────────────────────────

@dataclass
class _ResumenSeccion:
    detectado: bool = False
    vacio: bool = False
    registros: int = 0


class ClasificadorKuCoin:
    """
    Clasificador fiscal multiarchivo para KuCoin.

    Atributos públicos (contrato FIFO):
        compraventas · swaps · movimientos · rendimientos · desconocidas · advertencias
    Extra para la UI:
        resumen_archivos — dict con lo detectado por sección
    """

    def __init__(self, filepaths: List[str], filenames: Optional[List[str]] = None):
        """`filepaths`: rutas en disco. `filenames`: nombres originales (para el
        resumen y advertencias); si se omite, se usa el basename de cada ruta."""
        self.filepaths = list(filepaths)
        self.filenames = list(filenames) if filenames else [self._basename(p) for p in filepaths]

        self.compraventas: List[OperacionCompraventa] = []
        self.swaps:        List[OperacionSwap]        = []
        self.movimientos:  List[OperacionMovimiento]  = []
        self.rendimientos: List[OperacionRendimiento] = []
        self.desconocidas: List[OperacionDesconocida] = []
        self.advertencias: List[str]                  = []

        # Buffers internos
        self._ledger_rows: List[dict]       = []   # todas las filas ledger de todos los ficheros
        self._fiat_orders: List[dict]       = []   # filas de Órdenes fiat (pendientes de dedup)
        self._depositos_fiat_ledger: List[OperacionMovimiento] = []  # Fiat Deposit del ledger (para dedup)
        self._no_reconocidos: List[str]     = []
        self._tiene_pares_usd: bool         = False

        # Resumen para la UI
        self._sec_trading      = _ResumenSeccion()
        self._sec_financiacion = _ResumenSeccion()
        self._sec_cripto       = _ResumenSeccion()
        self._sec_fiat_orders  = _ResumenSeccion()

    @staticmethod
    def _basename(p: str) -> str:
        import os
        return os.path.basename(p)

    # ── ENTRADA PÚBLICA ────────────────────────────────────────────────────────

    def clasificar(self) -> "ClasificadorKuCoin":
        if not self.filepaths:
            raise KucoinUserError("no_files", "No se recibió ningún fichero de KuCoin.")

        algun_reconocido = False

        for fp, fname in zip(self.filepaths, self.filenames):
            try:
                headers, filas, vacio = _leer_csv(fp)
            except Exception as e:
                logger.warning("KuCoin: no se pudo leer %s: %s", fname, e)
                self._no_reconocidos.append(fname)
                continue

            tipo = _detectar_tipo(headers)

            if tipo == "ledger":
                algun_reconocido = True
                self._registrar_ledger_en_resumen(filas, vacio)
                self._ledger_rows.extend(filas)
            elif tipo == "deposito_cripto":
                algun_reconocido = True
                self._sec_cripto.detectado = True
                self._sec_cripto.vacio     = vacio
                self._sec_cripto.registros = len(filas)
                self._procesar_depositos_cripto(filas)
            elif tipo == "fiat_orders":
                algun_reconocido = True
                self._sec_fiat_orders.detectado = True
                self._sec_fiat_orders.vacio     = vacio
                self._sec_fiat_orders.registros = len(filas)
                self._fiat_orders.extend(filas)
            else:
                self._no_reconocidos.append(fname)

        if not algun_reconocido:
            raise KucoinUserError(
                "wrong_file",
                "Ninguno de los ficheros se reconoce como un export de KuCoin. "
                "Sube los CSV de 'Historial de la cuenta' (Cuenta de trading y/o de "
                "financiación), 'Órdenes fiat' o el 'Historial de depósitos/retiradas'.",
            )

        # Procesar el ledger consolidado (todos los ficheros ledger juntos)
        self._procesar_ledger()

        # Deduplicar Órdenes fiat contra los Fiat Deposit del ledger
        self._procesar_fiat_orders_dedup()

        # Advertencias finales
        self._construir_advertencias()

        return self

    # ── RESUMEN DE FICHEROS LEDGER ─────────────────────────────────────────────

    def _registrar_ledger_en_resumen(self, filas: List[dict], vacio: bool) -> None:
        """Etiqueta el fichero ledger como trading o financiación según sus Type.
        La cabecera de ambos es idéntica; sólo el contenido los distingue."""
        tipos = {(f.get("type") or "").strip().lower() for f in filas}
        es_trading = bool(tipos & {"spot", "convert dust to kcs"})
        es_financ  = bool(tipos & {"fiat deposit", "fiat transactions"})

        # Si tiene Type de trading → trading; si tiene fiat → financiación.
        # Un fichero sólo-Transfer (sin pistas) se cuenta como financiación por defecto.
        if es_trading:
            sec = self._sec_trading
        elif es_financ:
            sec = self._sec_financiacion
        else:
            sec = self._sec_financiacion
        sec.detectado = True
        sec.registros += len(filas)
        if vacio:
            sec.vacio = True

    # ── LEDGER: Spot, Fiat Transactions, Transfer, Fiat Deposit, Convert Dust ──

    def _procesar_ledger(self) -> None:
        # Tipos que requieren reconstrucción agrupando varias filas.
        reconstruibles: Dict[str, List[dict]] = {
            "spot": [], "fiat transactions": [], "convert dust to kcs": [],
        }
        for fila in self._ledger_rows:
            tipo = (fila.get("type") or "").strip()
            tipo_l = tipo.lower()
            fecha = fila.get("time", "")

            if tipo_l == "transfer":
                self._procesar_transfer(fila)
            elif tipo_l == "fiat deposit":
                self._procesar_fiat_deposit(fila)
            elif tipo_l in reconstruibles:
                reconstruibles[tipo_l].append(fila)
            else:
                self.desconocidas.append(OperacionDesconocida(
                    fecha=_parse_fecha(fecha), subtipo=f"Type desconocido: {tipo}",
                    activo=(fila.get("currency") or "?").upper(),
                    cantidad=float(_parse_decimal(fila.get("amount", ""))),
                ))

        # Las patas de una misma operación comparten (casi) el mismo segundo; las
        # agrupamos por ventana temporal en vez de por timestamp exacto, porque
        # Fiat Transactions puede tener las dos patas a 1 segundo de diferencia.
        for tipo_l, filas in reconstruibles.items():
            for cluster in self._clusterizar_por_tiempo(filas):
                fecha = cluster[0].get("time", "")
                if tipo_l == "convert dust to kcs":
                    self._reconstruir_dust(fecha, cluster)
                else:  # spot | fiat transactions
                    self._reconstruir_trade(fecha, cluster, tipo_l)

    @staticmethod
    def _clusterizar_por_tiempo(filas: List[dict]) -> List[List[dict]]:
        """Agrupa filas consecutivas (ordenadas por tiempo) cuyo hueco respecto a la
        anterior es ≤ _GROUP_WINDOW_SEG. Las filas sin fecha válida van en clusters
        propios (acabarán como ambiguas en la reconstrucción)."""
        con_fecha = []
        sin_fecha = []
        for f in filas:
            dt = _to_dt(f.get("time", ""))
            (con_fecha if dt is not None else sin_fecha).append((dt, f))
        con_fecha.sort(key=lambda x: x[0])

        clusters: List[List[dict]] = []
        actual: List[dict] = []
        prev_dt = None
        for dt, f in con_fecha:
            if prev_dt is not None and (dt - prev_dt).total_seconds() > _GROUP_WINDOW_SEG:
                clusters.append(actual)
                actual = []
            actual.append(f)
            prev_dt = dt
        if actual:
            clusters.append(actual)

        for _dt, f in sin_fecha:
            clusters.append([f])
        return clusters

    def _agrupar_lados(self, filas: List[dict]) -> Tuple[dict, dict, dict]:
        """Consolida una lista de filas en recibidos{cur:Decimal}, entregados{cur:Decimal}
        y fees{cur:Decimal}. La fee se atribuye a la moneda de su propia fila."""
        recibidos: Dict[str, Decimal]  = {}
        entregados: Dict[str, Decimal] = {}
        fees: Dict[str, Decimal]       = {}
        for f in filas:
            cur = (f.get("currency") or "").strip().upper()
            amt = _parse_decimal(f.get("amount", ""))
            fee = _parse_decimal(f.get("fee", ""))
            if _es_deposit(f.get("side", "")):
                recibidos[cur] = recibidos.get(cur, Decimal("0")) + amt
            elif _es_withdrawal(f.get("side", "")):
                entregados[cur] = entregados.get(cur, Decimal("0")) + amt
            if fee > 0:
                fees[cur] = fees.get(cur, Decimal("0")) + fee
        return recibidos, entregados, fees

    def _reconstruir_trade(self, fecha: str, filas: List[dict], tipo_l: str) -> None:
        """Spot / Fiat Transactions → COMPRA, VENTA o permuta (swap)."""
        recibidos, entregados, fees = self._agrupar_lados(filas)
        fecha_n = _parse_fecha(fecha)
        etiqueta = "Spot" if tipo_l == "spot" else "Fiat Transactions"

        recibidos  = {k: v for k, v in recibidos.items() if v > 0}
        entregados = {k: v for k, v in entregados.items() if v > 0}

        if len(recibidos) != 1 or len(entregados) != 1:
            # Mezcla ambigua: no inventar.
            self.advertencias.append(
                f"{etiqueta} del {fecha_n[:10]}: no se pudo reconstruir con seguridad "
                f"(recibido: {', '.join(recibidos) or '—'}; entregado: "
                f"{', '.join(entregados) or '—'}). Revísalo manualmente."
            )
            for f in filas:
                self.desconocidas.append(OperacionDesconocida(
                    fecha=fecha_n, subtipo=f"{etiqueta} ambiguo",
                    activo=(f.get("currency") or "?").upper(),
                    cantidad=float(_parse_decimal(f.get("amount", ""))),
                ))
            return

        recv_cur, recv_amt = next(iter(recibidos.items()))
        give_cur, give_amt = next(iter(entregados.items()))

        recv_quote = recv_cur in QUOTE_LIKE
        give_quote = give_cur in QUOTE_LIKE

        # Fee total: preferimos la fee en la moneda quote; si no, la primera disponible.
        def _fee_en(cur: str) -> Tuple[str, float]:
            if cur in fees:
                return cur, float(fees[cur])
            if fees:
                k = next(iter(fees))
                return k, float(fees[k])
            return cur, 0.0

        if recv_quote and not give_quote:
            # Recibo quote, entrego cripto → VENTA de la cripto entregada.
            fee_cur, fee_amt = _fee_en(recv_cur)
            self._marcar_usd(recv_cur)
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha_n, tipo="VENTA", activo=give_cur, cantidad=float(give_amt),
                contraparte=recv_cur, importe=float(recv_amt),
                fee_activo=fee_cur, fee_cantidad=fee_amt,
            ))
        elif give_quote and not recv_quote:
            # Entrego quote, recibo cripto → COMPRA de la cripto recibida.
            fee_cur, fee_amt = _fee_en(give_cur)
            self._marcar_usd(give_cur)
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha_n, tipo="COMPRA", activo=recv_cur, cantidad=float(recv_amt),
                contraparte=give_cur, importe=float(give_amt),
                fee_activo=fee_cur, fee_cantidad=fee_amt,
            ))
        elif not recv_quote and not give_quote:
            # Cripto ↔ cripto → permuta (el motor la trata como venta + compra).
            self.swaps.append(OperacionSwap(
                fecha=fecha_n, activo_entregado=give_cur, cantidad_entregada=float(give_amt),
                activo_recibido=recv_cur, cantidad_recibida=float(recv_amt),
                nota=etiqueta,
            ))
        else:
            # Quote ↔ quote (p.ej. EUR→USDT): COMPRA del recibido pagando con el entregado.
            fee_cur, fee_amt = _fee_en(give_cur)
            self._marcar_usd(recv_cur)
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha_n, tipo="COMPRA", activo=recv_cur, cantidad=float(recv_amt),
                contraparte=give_cur, importe=float(give_amt),
                fee_activo=fee_cur, fee_cantidad=fee_amt,
            ))

    def _reconstruir_dust(self, fecha: str, filas: List[dict]) -> None:
        """Convert Dust to KCS → permuta (transmisión patrimonial)."""
        recibidos, entregados, _fees = self._agrupar_lados(filas)
        fecha_n = _parse_fecha(fecha)

        recibidos  = {k: v for k, v in recibidos.items() if v > 0}
        entregados = {k: v for k, v in entregados.items() if v > 0}

        kcs_amt = recibidos.get(KCS, Decimal("0"))

        if KCS not in recibidos or len(recibidos) != 1 or not entregados:
            self.advertencias.append(
                f"Convert Dust to KCS del {fecha_n[:10]}: no se reconoce KCS recibido "
                f"de forma inequívoca. Revísalo manualmente."
            )
            for cur, amt in entregados.items():
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha_n, subtipo="Convert Dust (revisar)", activo=cur,
                    cantidad=float(amt), observacion="Permuta a KCS pendiente de valoración manual",
                ))
            return

        if len(entregados) == 1:
            give_cur, give_amt = next(iter(entregados.items()))
            self.swaps.append(OperacionSwap(
                fecha=fecha_n, activo_entregado=give_cur, cantidad_entregada=float(give_amt),
                activo_recibido=KCS, cantidad_recibida=float(kcs_amt),
                nota="Convert Dust to KCS",
            ))
        else:
            # Varios activos entregados → no se puede atribuir el KCS por activo sin
            # valoración de mercado. No inventamos el reparto: advertencia + movimientos.
            self.advertencias.append(
                f"Convert Dust to KCS del {fecha_n[:10]}: se convirtieron varios activos "
                f"({', '.join(sorted(entregados))}) a KCS en una sola operación. Cada activo "
                f"es una permuta; valora manualmente el KCS recibido por cada uno."
            )
            for cur, amt in entregados.items():
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha_n, subtipo="Convert Dust (revisar)", activo=cur,
                    cantidad=float(amt), observacion=f"Permuta a {float(kcs_amt):.8g} KCS (reparto manual)",
                ))

    def _procesar_transfer(self, fila: dict) -> None:
        """Movimiento interno entre cuentas → sin impacto fiscal."""
        self.movimientos.append(OperacionMovimiento(
            fecha=_parse_fecha(fila.get("time", "")),
            subtipo="Transfer",
            activo=(fila.get("currency") or "").upper(),
            cantidad=float(_parse_decimal(fila.get("amount", ""))),
            observacion=fila.get("remark", "") or "Movimiento interno entre cuentas",
        ))

    def _procesar_fiat_deposit(self, fila: dict) -> None:
        """Entrada fiat en la cuenta de financiación → movimiento (no transmisión)."""
        mov = OperacionMovimiento(
            fecha=_parse_fecha(fila.get("time", "")),
            subtipo="Fiat Deposit",
            activo=(fila.get("currency") or "").upper(),
            cantidad=float(_parse_decimal(fila.get("amount", ""))),
            observacion=fila.get("remark", "") or "Depósito fiat",
        )
        self.movimientos.append(mov)
        self._depositos_fiat_ledger.append(mov)

    # ── DEPÓSITOS / RETIROS CRIPTO ─────────────────────────────────────────────

    def _procesar_depositos_cripto(self, filas: List[dict]) -> None:
        """Depósitos/retiros cripto → movimiento. NO genera transmisión automática."""
        for f in filas:
            cur = (f.get("coin") or "").upper()
            amt = float(_parse_decimal(f.get("amount", "")))
            if amt <= 0:
                continue
            red = f.get("transfer network", "")
            self.movimientos.append(OperacionMovimiento(
                fecha=_parse_fecha(f.get("time", "")),
                subtipo="Deposito/Retiro cripto",
                activo=cur,
                cantidad=amt,
                observacion=f"Red: {red}" if red else "",
            ))

    # ── ÓRDENES FIAT (con deduplicación) ───────────────────────────────────────

    def _procesar_fiat_orders_dedup(self) -> None:
        """
        La Cuenta de financiación es la fuente contable principal. Las Órdenes fiat
        sólo se añaden como complemento si NO existe un Fiat Deposit equivalente
        (misma moneda, misma fecha YYYY-MM-DD, importe ~igual, status SUCCEEDED).
        """
        for f in self._fiat_orders:
            status = (f.get("status") or "").strip().upper()
            cur    = (f.get("currency (fiat)") or "").strip().upper()
            amt    = _parse_decimal(f.get("fiat amount", ""))
            fecha  = _parse_fecha(f.get("time", ""))

            if status and status != "SUCCEEDED":
                continue
            if amt <= 0:
                continue

            if self._existe_equivalente_ledger(cur, amt, fecha):
                continue  # ya contabilizado por la Cuenta de financiación → no duplicar

            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Fiat Order", activo=cur, cantidad=float(amt),
                observacion=f"Depósito fiat ({f.get('deposit method', '')})".strip(),
            ))

    def _existe_equivalente_ledger(self, cur: str, amt: Decimal, fecha: str) -> bool:
        dia = fecha[:10]
        for mov in self._depositos_fiat_ledger:
            if mov.activo.upper() != cur:
                continue
            if mov.fecha[:10] != dia:
                continue
            # importe neto/bruto: tolerancia del 2 % o 0,01 absoluto.
            base = max(abs(float(amt)), 1e-9)
            if abs(float(amt) - mov.cantidad) <= max(0.02 * base, 0.01):
                return True
        return False

    # ── ADVERTENCIAS Y MARCADORES ──────────────────────────────────────────────

    def _marcar_usd(self, cur: str) -> None:
        if cur in STABLES_USD and cur not in STABLES_EUR:
            self._tiene_pares_usd = True

    def _construir_advertencias(self) -> None:
        if self._tiene_pares_usd:
            self.advertencias.append(
                "Algunas operaciones están valoradas en USDT u otra stablecoin USD. "
                "Para el IRPF aplica el tipo de cambio EUR/USD vigente en la fecha de cada operación."
            )

        # Ficheros vacíos reconocidos → advertencia suave.
        if self._sec_cripto.detectado and self._sec_cripto.vacio:
            self.advertencias.append(
                "El historial de depósitos/retiradas cripto está vacío. Si tuviste "
                "depósitos o retiradas de cripto, expórtalos y súbelos también."
            )

        if self._no_reconocidos:
            self.advertencias.append(
                "Archivos no reconocidos como KuCoin: " + ", ".join(self._no_reconocidos)
            )

        # Productos que no aparecen en estos ficheros: aviso para que no se asuma cobertura total.
        self.advertencias.append(
            "No se han procesado retiradas cripto, staking, earn, lending, margin ni "
            "futuros (no figuran en estos historiales). Si usaste alguno de esos "
            "productos, exporta su historial y súbelo también."
        )

    # ── RESUMEN PARA LA UI ─────────────────────────────────────────────────────

    @property
    def resumen_archivos(self) -> dict:
        def _sec(s: _ResumenSeccion) -> dict:
            return {"detectado": s.detectado, "vacio": s.vacio, "registros": s.registros}
        return {
            "trading":         _sec(self._sec_trading),
            "financiacion":    _sec(self._sec_financiacion),
            "deposito_cripto": _sec(self._sec_cripto),
            "fiat_orders":     _sec(self._sec_fiat_orders),
            "no_reconocidos":  list(self._no_reconocidos),
        }

    def resumen(self) -> dict:
        return {
            "compraventas": len(self.compraventas),
            "swaps":        len(self.swaps),
            "movimientos":  len(self.movimientos),
            "rendimientos": len(self.rendimientos),
            "desconocidas": len(self.desconocidas),
            "advertencias": len(self.advertencias),
        }


# ── EJECUCIÓN DIRECTA ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    rutas = sys.argv[1:]
    if not rutas:
        print("Uso: python clasificador_kucoin.py fichero1.csv [fichero2.csv ...]")
        sys.exit(1)

    c = ClasificadorKuCoin(rutas).clasificar()
    print("=" * 60)
    print("RESUMEN KuCoin")
    print("=" * 60)
    for k, v in c.resumen().items():
        print(f"  {k:<14} {v:>5}")
    print("\n── RESUMEN ARCHIVOS ──")
    for k, v in c.resumen_archivos.items():
        print(f"  {k:<16} {v}")
    print("\n── COMPRAVENTAS ──")
    for op in c.compraventas:
        print(f"  {op.fecha[:10]}  {op.tipo:<6} {op.activo:<6} {op.cantidad:>14.8f}"
              f"  @ {op.importe:.6f} {op.contraparte}  fee {op.fee_cantidad:.8g} {op.fee_activo}")
    print("\n── SWAPS ──")
    for op in c.swaps:
        print(f"  {op.fecha[:10]}  {op.cantidad_entregada:.8g} {op.activo_entregado}"
              f" → {op.cantidad_recibida:.8g} {op.activo_recibido}  ({op.nota})")
    print("\n── MOVIMIENTOS ──")
    for op in c.movimientos:
        print(f"  {op.fecha[:10]}  {op.subtipo:<22} {op.activo:<6} {op.cantidad:.8g}  {op.observacion}")
    print(f"\n── ADVERTENCIAS ({len(c.advertencias)}) ──")
    for a in c.advertencias:
        print(f"  ⚠  {a}")
