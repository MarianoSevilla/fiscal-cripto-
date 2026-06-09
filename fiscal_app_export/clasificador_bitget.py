"""
Clasificador fiscal de operaciones Bitget (spot CSV)
Mariano Sevilla — marianosevilla.com

Soporta los exports CSV de Bitget spot:
  · Detalles de órdenes en spot  ← fuente fiscal principal para FIFO
    Headers: Date, Trading pair, Base Asset, Quote Asset, Direction,
             Price, Amount, Total, Fee, Fee Coin
  · Transacciones en spot        ← soportado en fase 2: compraventas,
    Headers: order, Date, Coin, Type, Amount, Fee, Available           rendimientos, swaps, movimientos
    Tipos soportados:
      Buy / Sell                       → compraventas FIFO (emparejadas por timestamp)
      Interest                         → rendimientos del capital mobiliario
      Deposit                          → movimiento (depósito)
      Ordinary Withdrawal              → movimiento (retiro)
      Transfer out                     → movimiento (transferencia interna)
      Financial                        → movimiento (bloqueo earn, neutral fiscal)
      Redemption                       → movimiento (rescate earn, neutral fiscal)
      Exchange income / spending       → swap crypto↔crypto
      Increase / Reduce exchange rate  → swap crypto↔crypto
      Buy with card                    → movimiento informativo (fiat→USDT, sin EUR)
      Fiat                             → movimiento informativo (depósito fiat, sin EUR)
      Transaction fee deduct           → ignorado (importe mínimo)
  · Historial de órdenes en spot ← solo detección; lanza ValueError descriptivo
    Headers: Date, Type, Order Id, Trading pair, …

Riesgos gestionados:
  - UTF-8-SIG (BOM) en los 3 archivos → encoding='utf-8-sig'
  - TAB prefijado en IDs de orden → .strip() en todos los campos
  - Columna vacía None por trailing comma en DETALLES → filtrada en lectura
  - Multi-fill en DETALLES: mismo timestamp y par → operaciones FIFO independientes
  - Multi-sub-fill en TRANSACCIONES: emparejamiento posicional Buy[i]↔Sell[i]
  - Fee en Base Asset (Buy) vs Fee en USDT (Sell)
  - Pares todos X/USDT → advertencia conversión EUR
  - Sin timezone explícito: se asume UTC
  - PI y activos depositados sin coste → inventario insuficiente en FIFO
  - Posible duplicidad si se suben DETALLES y TRANSACCIONES del mismo período
"""

import csv
import logging
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime

logger = logging.getLogger(__name__)

# ── FIRMAS DE DETECCIÓN ────────────────────────────────────────────────────────

BITGET_DETALLES_SIGNATURE = {
    "Date", "Trading pair", "Base Asset", "Quote Asset",
    "Direction", "Price", "Amount", "Total", "Fee", "Fee Coin",
}
BITGET_TRANSACCIONES_SIGNATURE = {
    "order", "Date", "Coin", "Type", "Amount", "Fee", "Available",
}
BITGET_HISTORIAL_SIGNATURE = {
    "Date", "Type", "Order Id", "Trading pair", "Base Asset",
    "Quote Asset", "Direction", "Price", "Order amount",
    "Executed", "Average Price", "Trading volume", "Status",
}

# Firmas textuales para _validar_csv (basta con que aparezca una en las primeras líneas)
BITGET_SIGNATURES = ["Fee Coin", "Available", "Order Id"]

# ── CONSTANTES ────────────────────────────────────────────────────────────────

STABLES_USD = {"USDC", "USDT", "BUSD", "USD", "FDUSD", "DAI"}

# Tipos de swap interno del ledger de transacciones
_TIPOS_SWAP_INTERNO = frozenset({
    "exchange income", "exchange spending",
    "increase exchange rate", "reduce exchange rate",
})


# ── DATACLASSES (misma forma que clasificador_mexc.py para compatibilidad FIFO) ──

@dataclass
class OperacionCompraventa:
    fecha: str
    tipo: str           # "COMPRA" | "VENTA"
    activo: str         # moneda base (XRP, ETH, PI…)
    cantidad: float     # cantidad bruta ejecutada (Amount del CSV)
    contraparte: str    # moneda quote (USDT…)
    importe: float      # total en quote (Total del CSV)
    fee_activo: str
    fee_cantidad: float

@dataclass
class OperacionMovimiento:
    fecha: str
    subtipo: str        # "Deposit" | "Withdrawal" | "Transfer"
    activo: str
    cantidad: float
    observacion: str

@dataclass
class OperacionRendimiento:
    fecha: str
    subtipo: str
    activo: str
    cantidad: float
    cuenta: str

@dataclass
class OperacionSwap:
    fecha: str
    activo_entregado: str
    cantidad_entregada: float
    activo_recibido: str
    cantidad_recibida: float
    nota: str = ""

@dataclass
class OperacionDesconocida:
    fecha: str
    subtipo: str
    activo: str
    cantidad: float
    cuenta: str


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _leer_csv(filepath: str) -> tuple:
    """
    Lee CSV UTF-8-SIG (BOM) y devuelve (headers, filas_como_dict).
    Elimina la columna None generada por trailing comma en DETALLES.
    """
    with open(filepath, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])

    # Eliminar clave None (artefacto de trailing comma); normalizar valor None a ""
    # csv.DictReader rellena con None las columnas faltantes en filas cortas (restval=None).
    cleaned = [
        {k: (v if v is not None else "") for k, v in row.items() if k is not None}
        for row in rows
    ]
    return headers, cleaned


def detect_bitget_file_type(filepath: str) -> str:
    """
    Inspecciona las cabeceras del CSV y devuelve el tipo de export de Bitget.
    Retorna: "detalles" | "transacciones" | "historial" | "unknown"
    """
    try:
        headers, _ = _leer_csv(filepath)
    except Exception as e:
        logger.warning("Bitget: no se pudo leer el archivo: %s", e)
        return "unknown"

    headers_set = {h.strip() for h in headers if h}

    # El historial tiene la firma más amplia; comprobar primero para evitar
    # falsos positivos (comparte "Trading pair" con DETALLES).
    if BITGET_HISTORIAL_SIGNATURE.issubset(headers_set):
        return "historial"
    if BITGET_DETALLES_SIGNATURE.issubset(headers_set):
        return "detalles"
    if BITGET_TRANSACCIONES_SIGNATURE.issubset(headers_set):
        return "transacciones"

    return "unknown"


def _parse_decimal(valor: str) -> Decimal:
    """Convierte string a Decimal. Devuelve Decimal('0') si es inválido."""
    try:
        clean = str(valor).strip().replace(",", "")
        if not clean:
            return Decimal("0")
        return Decimal(clean)
    except (InvalidOperation, Exception):
        return Decimal("0")


def _parse_fecha(valor: str) -> str:
    """Parsea 'YYYY-MM-DD HH:MM:SS' con variantes. Devuelve ISO normalizado."""
    valor = str(valor).strip()
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
        try:
            return datetime.strptime(valor, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    logger.warning("Bitget: fecha no reconocida: %r", valor)
    return valor


def _contar_filas_csv_bitget(filepath: str) -> int:
    """Cuenta las filas de datos del CSV (sin contar la cabecera)."""
    try:
        _, rows = _leer_csv(filepath)
        return len(rows)
    except Exception:
        return 0


# ── CLASIFICADOR ──────────────────────────────────────────────────────────────

class ClasificadorBitget:
    """
    Clasificador fiscal para exports CSV de Bitget spot.

    Fuente fiscal principal: CSV de "Detalles de órdenes en spot"
    Fuente alternativa:      CSV de "Transacciones en spot" (fase 2 — ver docstring del módulo)
    No procesado:            CSV de "Historial de órdenes en spot" → ValueError descriptivo

    Expone la misma interfaz que ClasificadorMEXC para compatibilidad con
    _pipeline_motor y procesar_con_fifo.

    Atributos públicos:
        compraventas  — BUY/SELL spot como OperacionCompraventa
        movimientos   — depósitos/retiros/transfers como OperacionMovimiento
        rendimientos  — Interest (staking/earn) como OperacionRendimiento
        swaps         — conversiones crypto↔crypto como OperacionSwap
        desconocidas  — operaciones no reconocidas
        advertencias  — warnings (duplicidad, USDT, inventario…)
        tipo_export   — "detalles" | "transacciones" (informativo)
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.tipo_export: str = ""

        self.compraventas:  list = []  # OperacionCompraventa
        self.movimientos:   list = []  # OperacionMovimiento
        self.rendimientos:  list = []  # OperacionRendimiento
        self.swaps:         list = []  # OperacionSwap
        self.desconocidas:  list = []  # OperacionDesconocida
        self.advertencias:  list = []  # str

        self._tiene_pares_usdt: bool = False

    # ── ENTRADA PÚBLICA ────────────────────────────────────────────────────────

    def clasificar(self) -> "ClasificadorBitget":
        tipo = detect_bitget_file_type(self.filepath)
        self.tipo_export = tipo

        if tipo == "historial":
            raise ValueError(
                "El archivo de historial de órdenes de Bitget contiene órdenes "
                "agregadas y canceladas. Para calcular FIFO necesitas subir el "
                "archivo de detalles de órdenes en spot."
            )
        if tipo == "detalles":
            self._clasificar_detalles()
        elif tipo == "transacciones":
            self._clasificar_transacciones()
            self._generar_advertencias_transacciones()
        else:
            raise ValueError(
                "El archivo no se reconoce como un export de Bitget. "
                "Asegúrate de exportar el CSV de detalles de órdenes en spot "
                "o el CSV de transacciones desde tu cuenta de Bitget."
            )

        if self._tiene_pares_usdt:
            self.advertencias.append(
                "Las operaciones están valoradas en USDT. "
                "Para la declaración del IRPF aplica el tipo de cambio EUR/USDT "
                "vigente en la fecha de cada operación."
            )

        if self.desconocidas:
            tipos = {d.subtipo for d in self.desconocidas}
            self.advertencias.append(
                f"{len(self.desconocidas)} operación(es) no reconocida(s): "
                + ", ".join(sorted(tipos))
            )

        return self

    # ── DETALLES DE ÓRDENES (fuente fiscal principal) ─────────────────────────

    def _clasificar_detalles(self) -> None:
        _, rows = _leer_csv(self.filepath)
        for fila in rows:
            self._procesar_fila_detalles(fila)

    def _procesar_fila_detalles(self, fila: dict) -> None:
        fecha_raw  = fila.get("Date", "").strip()
        fecha      = _parse_fecha(fecha_raw)

        base       = fila.get("Base Asset",  "").strip().upper()
        quote      = fila.get("Quote Asset", "").strip().upper()
        direction  = fila.get("Direction",   "").strip()
        amount_raw = fila.get("Amount", "0").strip()
        total_raw  = fila.get("Total",  "0").strip()
        fee_raw    = fila.get("Fee",    "0").strip()
        fee_coin   = fila.get("Fee Coin", "").strip().upper()

        amount = _parse_decimal(amount_raw)
        total  = _parse_decimal(total_raw)
        fee    = _parse_decimal(fee_raw)

        if not base or not quote or not direction:
            self.desconocidas.append(OperacionDesconocida(
                fecha=fecha, subtipo="fila incompleta",
                activo=base or fila.get("Trading pair", ""),
                cantidad=float(amount), cuenta="Bitget",
            ))
            return

        if amount <= 0 or total <= 0:
            self.desconocidas.append(OperacionDesconocida(
                fecha=fecha, subtipo=f"amount/total inválido ({direction})",
                activo=base, cantidad=float(amount), cuenta="Bitget",
            ))
            return

        if quote in STABLES_USD:
            self._tiene_pares_usdt = True

        dir_upper = direction.upper()
        if dir_upper == "BUY":
            tipo = "COMPRA"
        elif dir_upper == "SELL":
            tipo = "VENTA"
        else:
            self.desconocidas.append(OperacionDesconocida(
                fecha=fecha, subtipo=f"direction desconocida: {direction!r}",
                activo=base, cantidad=float(amount), cuenta="Bitget",
            ))
            return

        # Fee:
        #   Buy  → Fee Coin = Base Asset → fee reduce la cantidad neta recibida.
        #   Sell → Fee Coin = USDT       → fee reduce el ingreso neto.
        self.compraventas.append(OperacionCompraventa(
            fecha        = fecha,
            tipo         = tipo,
            activo       = base,
            cantidad     = float(amount),
            contraparte  = quote,
            importe      = float(total),
            fee_activo   = fee_coin if fee_coin else quote,
            fee_cantidad = float(fee),
        ))

    # ── TRANSACCIONES EN SPOT (fase 2) ────────────────────────────────────────

    def _clasificar_transacciones(self) -> None:
        """
        Procesa el ledger de transacciones Bitget en dos pasos:
          1. Agrupa Buy/Sell y swaps internos por timestamp.
          2. Procesa el resto tipo a tipo.
        """
        _, rows = _leer_csv(self.filepath)

        # Acumuladores por timestamp para tipos que requieren emparejamiento
        buy_sell_por_ts = defaultdict(lambda: {"buy": [], "sell": []})
        swap_interno_por_ts = defaultdict(list)
        otras_filas = []

        for fila in rows:
            tipo_lower = (fila.get("Type") or "").strip().lower()
            ts         = (fila.get("Date") or "").strip()

            if tipo_lower == "buy":
                buy_sell_por_ts[ts]["buy"].append(fila)
            elif tipo_lower == "sell":
                buy_sell_por_ts[ts]["sell"].append(fila)
            elif tipo_lower in _TIPOS_SWAP_INTERNO:
                swap_interno_por_ts[ts].append(fila)
            else:
                otras_filas.append(fila)

        # Procesar en orden cronológico
        for ts in sorted(buy_sell_por_ts):
            g = buy_sell_por_ts[ts]
            self._procesar_pares_buy_sell(ts, g["buy"], g["sell"])

        for ts in sorted(swap_interno_por_ts):
            self._procesar_swap_interno(ts, swap_interno_por_ts[ts])

        for fila in otras_filas:
            self._procesar_otros_tipos(fila)

    def _procesar_pares_buy_sell(self, ts: str, buys: list, sells: list) -> None:
        """
        Empareja Buy+Sell del ledger por timestamp y genera OperacionCompraventa.

        Estrategia posicional: Buy[i] ↔ Sell[i].
        Esto funciona porque Bitget emite los sub-fills de una orden en el mismo
        orden en ambas listas. Si los conteos no coinciden, las filas se marcan
        como no reconocidas con advertencia.
        """
        fecha = _parse_fecha(ts)

        if not buys or not sells:
            for f in buys + sells:
                self._add_desconocida(f, fecha)
            return

        if len(buys) != len(sells):
            self.advertencias.append(
                f"Emparejamiento Buy/Sell incompleto en {ts}: "
                f"{len(buys)} entrada(s) Buy, {len(sells)} entrada(s) Sell. "
                "Las filas afectadas se han marcado como no reconocidas."
            )
            for f in buys + sells:
                self._add_desconocida(f, fecha)
            return

        for buy_fila, sell_fila in zip(buys, sells):
            self._reconstruir_compraventa(fecha, buy_fila, sell_fila)

    def _reconstruir_compraventa(self, fecha: str, buy_fila: dict, sell_fila: dict) -> None:
        """
        Clasifica un par Buy/Sell como COMPRA, VENTA o swap crypto↔crypto.

        En el ledger de transacciones Bitget:
          Buy  = coin recibida (cantidad positiva, fee negativa en esa misma coin)
          Sell = coin entregada (cantidad negativa, fee normalmente 0)

        Para COMPRA (ej. XRP←USDT):
          buy_coin=XRP, sell_coin=USDT
          cantidad=buy_amt, importe=sell_amt, fee_activo=XRP, fee_cantidad=buy_fee

        Para VENTA (ej. XRP→USDT):
          buy_coin=USDT, sell_coin=XRP
          cantidad=sell_amt, importe=buy_amt (neto), fee_activo=USDT, fee_cantidad=0
          Nota: el importe es neto porque la fee de venta ya está descontada del USDT
          recibido. El motor FIFO acepta importe neto con fee=0 correctamente.
        """
        buy_coin  = buy_fila.get("Coin", "").strip().upper()
        sell_coin = sell_fila.get("Coin", "").strip().upper()
        buy_amt   = abs(_parse_decimal(buy_fila.get("Amount", "0")))
        sell_amt  = abs(_parse_decimal(sell_fila.get("Amount", "0")))
        buy_fee   = abs(_parse_decimal(buy_fila.get("Fee", "0")))
        sell_fee  = abs(_parse_decimal(sell_fila.get("Fee", "0")))

        if buy_amt == 0 or sell_amt == 0:
            return

        if sell_coin in STABLES_USD and buy_coin not in STABLES_USD:
            # COMPRA: cripto ← stablecoin
            self._tiene_pares_usdt = True
            self.compraventas.append(OperacionCompraventa(
                fecha        = fecha,
                tipo         = "COMPRA",
                activo       = buy_coin,
                cantidad     = float(buy_amt),
                contraparte  = sell_coin,
                importe      = float(sell_amt),
                fee_activo   = buy_coin,
                fee_cantidad = float(buy_fee),
            ))

        elif buy_coin in STABLES_USD and sell_coin not in STABLES_USD:
            # VENTA: cripto → stablecoin
            self._tiene_pares_usdt = True
            self.compraventas.append(OperacionCompraventa(
                fecha        = fecha,
                tipo         = "VENTA",
                activo       = sell_coin,
                cantidad     = float(sell_amt),
                contraparte  = buy_coin,
                importe      = float(buy_amt),   # importe neto (fee ya descontada del USDT)
                fee_activo   = buy_coin,
                fee_cantidad = float(sell_fee),  # normalmente 0 en VENTA del ledger
            ))

        elif buy_coin in STABLES_USD and sell_coin in STABLES_USD:
            # Stablecoin↔Stablecoin: conversión sin impacto fiscal relevante
            self.movimientos.append(OperacionMovimiento(
                fecha       = fecha,
                subtipo     = "Transfer",
                activo      = buy_coin,
                cantidad    = float(buy_amt),
                observacion = f"Conversión stablecoin: {sell_coin}→{buy_coin}",
            ))

        else:
            # Crypto↔Crypto sin stablecoin: swap con valoración manual requerida
            self.swaps.append(OperacionSwap(
                fecha              = fecha,
                activo_entregado   = sell_coin,
                cantidad_entregada = float(sell_amt),
                activo_recibido    = buy_coin,
                cantidad_recibida  = float(buy_amt),
                nota               = f"Swap ledger Bitget: {sell_coin}→{buy_coin}",
            ))

    def _procesar_swap_interno(self, ts: str, filas: list) -> None:
        """
        Procesa pares Exchange income/spending e Increase/Reduce exchange rate
        como swap crypto↔crypto.

        Bitget registra dos filas sincrónicas (mismo timestamp):
          spending / reduce  = activo entregado (salida)
          income / increase  = activo recibido (entrada)
        """
        fecha = _parse_fecha(ts)

        salidas  = [f for f in filas if f.get("Type", "").strip().lower()
                    in ("exchange spending", "reduce exchange rate")]
        entradas = [f for f in filas if f.get("Type", "").strip().lower()
                    in ("exchange income", "increase exchange rate")]

        if len(salidas) != 1 or len(entradas) != 1:
            # Patrón inesperado: marcar todo como desconocido
            for f in filas:
                self._add_desconocida(f, fecha)
            return

        sal = salidas[0]
        ent = entradas[0]

        coin_sal = sal.get("Coin", "").strip().upper()
        coin_ent = ent.get("Coin", "").strip().upper()
        amt_sal  = abs(_parse_decimal(sal.get("Amount", "0")))
        amt_ent  = abs(_parse_decimal(ent.get("Amount", "0")))

        if coin_sal in STABLES_USD or coin_ent in STABLES_USD:
            self._tiene_pares_usdt = True

        self.swaps.append(OperacionSwap(
            fecha              = fecha,
            activo_entregado   = coin_sal,
            cantidad_entregada = float(amt_sal),
            activo_recibido    = coin_ent,
            cantidad_recibida  = float(amt_ent),
            nota               = f"Conversión interna Bitget: {coin_sal}→{coin_ent}",
        ))

    def _procesar_otros_tipos(self, fila: dict) -> None:
        """
        Procesa los tipos de transacción distintos de Buy/Sell y swaps internos.
        Cubre: Deposit, Ordinary Withdrawal, Transfer out, Interest, Financial,
        Redemption, Buy with card, Fiat, Transaction fee deduct, y desconocidos.
        """
        fecha_raw  = fila.get("Date", "").strip()
        fecha      = _parse_fecha(fecha_raw)
        coin       = fila.get("Coin", "").strip().upper()
        tipo_raw   = fila.get("Type", "").strip()
        amount_raw = fila.get("Amount", "0").strip()
        fee_raw    = fila.get("Fee", "0").strip()

        amount     = _parse_decimal(amount_raw)
        fee        = _parse_decimal(fee_raw)
        tipo_lower = tipo_raw.lower()

        # ── Depósito ──────────────────────────────────────────────────────────
        if tipo_lower == "deposit":
            if not coin:
                return
            obs = f"Depósito {coin}"
            if fee != 0:
                obs += f" | Fee: {float(abs(fee)):.8g} {coin}"
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Deposit", activo=coin,
                cantidad=float(abs(amount)), observacion=obs,
            ))

        # ── Retiro ────────────────────────────────────────────────────────────
        elif tipo_lower == "ordinary withdrawal":
            if not coin:
                return
            obs = f"Retiro {coin}"
            if fee != 0:
                obs += f" | Fee: {float(abs(fee)):.8g} {coin}"
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Withdrawal", activo=coin,
                cantidad=float(abs(amount)), observacion=obs,
            ))

        # ── Transferencia interna ─────────────────────────────────────────────
        elif tipo_lower == "transfer out":
            if not coin:
                return
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Transfer", activo=coin,
                cantidad=float(abs(amount)),
                observacion="Transferencia interna Bitget (spot → otro producto)",
            ))

        # ── Rendimiento (staking / earn) ──────────────────────────────────────
        elif tipo_lower == "interest":
            if not coin or amount <= 0:
                return
            self.rendimientos.append(OperacionRendimiento(
                fecha=fecha, subtipo="Staking/Earn",
                activo=coin, cantidad=float(amount), cuenta="Bitget",
            ))

        # ── Bloqueo en producto Earn (neutral fiscal) ─────────────────────────
        elif tipo_lower == "financial":
            if not coin:
                return
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Transfer", activo=coin,
                cantidad=float(abs(amount)),
                observacion=f"Entrada en producto Earn Bitget: {coin}",
            ))

        # ── Rescate de producto Earn (neutral fiscal) ─────────────────────────
        elif tipo_lower == "redemption":
            if not coin:
                return
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Deposit", activo=coin,
                cantidad=float(abs(amount)),
                observacion=f"Rescate de producto Earn Bitget: {coin}",
            ))

        # ── Compra con tarjeta (fiat → USDT/cripto) ───────────────────────────
        # Tipo conocido pero sin valoración EUR disponible en el CSV.
        # Se registra como depósito informativo; no genera FIFO en esta versión.
        elif tipo_lower == "buy with card":
            if not coin:
                return
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Deposit", activo=coin,
                cantidad=float(abs(amount)),
                observacion=(
                    f"Compra con tarjeta (fiat→{coin}): "
                    "valoración EUR no disponible en CSV"
                ),
            ))

        # ── Depósito fiat (p. ej. EUR→USDT) ──────────────────────────────────
        # Dos filas sincrónicas: EUR sale (amount < 0) y USDT entra (amount > 0).
        # Solo registramos la entrada de USDT como depósito informativo.
        elif tipo_lower == "fiat":
            if not coin:
                return
            if amount > 0:
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo="Deposit", activo=coin,
                    cantidad=float(amount),
                    observacion=f"Depósito fiat ({coin}): valoración EUR no disponible",
                ))
            # amount < 0 → moneda fiat saliente (EUR/USD), ignorar

        # ── Comisión de plataforma en BGB ─────────────────────────────────────
        # Amount típicamente 0; Fee = −x BGB. Importe mínimo, ignorar.
        elif tipo_lower == "transaction fee deduct":
            pass

        # ── Tipo no reconocido ────────────────────────────────────────────────
        else:
            self.desconocidas.append(OperacionDesconocida(
                fecha=fecha, subtipo=tipo_raw,
                activo=coin, cantidad=float(abs(amount)), cuenta="Bitget",
            ))

    def _add_desconocida(self, fila: dict, fecha: str) -> None:
        """Añade una fila a la lista de desconocidas."""
        coin = fila.get("Coin", "").strip().upper()
        tipo = fila.get("Type", "").strip()
        amt  = abs(_parse_decimal(fila.get("Amount", "0")))
        self.desconocidas.append(OperacionDesconocida(
            fecha=fecha, subtipo=tipo, activo=coin,
            cantidad=float(amt), cuenta="Bitget",
        ))

    def _generar_advertencias_transacciones(self) -> None:
        """
        Genera las advertencias específicas para el export de transacciones.
        Se llama una vez terminada la clasificación.
        """
        # ── Primera advertencia: estado de las compraventas ───────────────────
        if not self.compraventas:
            # Sin compraventas: guiar al usuario al CSV de detalles
            depositos = sum(1 for m in self.movimientos if m.subtipo == "Deposit")
            retiros   = sum(1 for m in self.movimientos if m.subtipo == "Withdrawal")
            transfers = sum(1 for m in self.movimientos if m.subtipo == "Transfer")
            partes = []
            if depositos:
                partes.append(f"{depositos} depósito{'s' if depositos != 1 else ''}")
            if retiros:
                partes.append(f"{retiros} retiro{'s' if retiros != 1 else ''}")
            if transfers:
                partes.append(f"{transfers} transferencia{'s' if transfers != 1 else ''}")
            movs_str = ", ".join(partes) if partes else "movimientos"
            self.advertencias.insert(0,
                f"Este archivo contiene movimientos de cuenta de Bitget ({movs_str}), "
                "pero no operaciones de compraventa. "
                "Para calcular el FIFO necesitas subir el CSV de detalles de "
                "órdenes en spot."
            )
        else:
            # Con compraventas: advertir posible duplicidad con CSV de detalles
            n = len(self.compraventas)
            self.advertencias.insert(0,
                f"Este archivo ha reconstruido {n} "
                f"{'operación' if n == 1 else 'operaciones'} "
                "de compraventa desde el ledger de transacciones Bitget. "
                "Si también tienes el CSV de detalles de órdenes en spot del "
                "mismo período, no subas ambos archivos: podrías duplicar "
                "operaciones en el cálculo FIFO."
            )

        # ── Rendimientos detectados ───────────────────────────────────────────
        if self.rendimientos:
            coins_rend = sorted({r.activo for r in self.rendimientos})
            n = len(self.rendimientos)
            self.advertencias.append(
                f"Se {'ha' if n == 1 else 'han'} detectado {n} "
                f"{'rendimiento' if n == 1 else 'rendimientos'} en {', '.join(coins_rend)}. "
                "Deben valorarse al precio de mercado en la fecha de cada cobro "
                "como rendimiento del capital mobiliario (art. 25.2 LIRPF). "
                "El CSV no contiene la valoración en euros."
            )

        # ── Swaps detectados ──────────────────────────────────────────────────
        if self.swaps:
            n = len(self.swaps)
            self.advertencias.append(
                f"Se {'ha' if n == 1 else 'han'} detectado {n} "
                f"{'conversión' if n == 1 else 'conversiones'} entre criptos (swap). "
                "Requieren valoración manual en euros en la fecha de cada "
                "operación para calcular la ganancia o pérdida patrimonial."
            )

    # ── RESUMEN ────────────────────────────────────────────────────────────────

    def resumen(self) -> dict:
        return {
            "tipo_export":  self.tipo_export,
            "compraventas": len(self.compraventas),
            "movimientos":  len(self.movimientos),
            "rendimientos": len(self.rendimientos),
            "swaps":        len(self.swaps),
            "desconocidas": len(self.desconocidas),
            "advertencias": len(self.advertencias),
        }


# ── EJECUCIÓN DIRECTA ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "bitget.csv"
    print(f"\nProcesando: {ruta}\n")

    c = ClasificadorBitget(ruta).clasificar()
    r = c.resumen()

    print("=" * 60)
    print(f"RESUMEN Bitget  —  tipo={c.tipo_export}")
    print("=" * 60)
    for k, v in r.items():
        print(f"  {k:<20} {v:>6}")

    print("\n── COMPRAVENTAS ──")
    for op in c.compraventas:
        print(f"  {op.fecha[:10]}  {op.tipo:<6}  {op.activo:<8}"
              f"  {op.cantidad:>14.8f}  @ {op.importe:.6f} {op.contraparte}"
              f"  fee: {op.fee_cantidad:.8g} {op.fee_activo}")

    print("\n── RENDIMIENTOS ──")
    for op in c.rendimientos:
        print(f"  {op.fecha[:10]}  {op.subtipo:<20}  {op.activo:<8}"
              f"  {op.cantidad:>12.8f}")
    if not c.rendimientos:
        print("  Ninguno ✓")

    print("\n── SWAPS ──")
    for op in c.swaps:
        print(f"  {op.fecha[:10]}  {op.activo_entregado}→{op.activo_recibido}"
              f"  {op.cantidad_entregada:.8g}→{op.cantidad_recibida:.8g}"
              f"  [{op.nota}]")
    if not c.swaps:
        print("  Ninguno ✓")

    print("\n── MOVIMIENTOS ──")
    for op in c.movimientos:
        print(f"  {op.fecha[:10]}  {op.subtipo:<15}  {op.activo:<6}"
              f"  {op.cantidad:>14.8f}  |  {op.observacion}")

    print(f"\n── ADVERTENCIAS ({len(c.advertencias)}) ──")
    for adv in c.advertencias:
        print(f"  ⚠  {adv}")
    if not c.advertencias:
        print("  Ninguna ✓")

    print("\n── DESCONOCIDAS ──")
    for op in c.desconocidas:
        print(f"  {op.fecha[:10]}  {op.subtipo:<30}  {op.activo:<8}  {op.cantidad:.6f}")
    if not c.desconocidas:
        print("  Ninguna ✓")
