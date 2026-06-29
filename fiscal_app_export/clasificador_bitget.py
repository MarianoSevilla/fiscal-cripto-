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
  · Withdrawal Records           ← variante alternativa de depósitos/retiros
    Headers: Date, Type, Funding account, Coin, Quantity, Address, TxID, Status
    Se procesa igual que Deposit/Withdrawal History en cuanto a movimientos.
  · Futures order history        ← detectado; no soportado (requiere criterio fiscal específico)
    Headers: Date, Order ID, Direction, Coin, Futures, …, Realized P/L, NetProfits, Status

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
# "Historial de operaciones en spot" (Spot Trading History / Spot Trading Record)
#   ← FUENTE FIFO RECOMENDADA: contiene TODO el histórico de operaciones ejecutadas
#     (compras y ventas con par, precio y comisión), incluido el coste de adquisición.
#   Llega con una fila de TÍTULO previa ("Spot Trading Record") y las fechas como
#   número de serie Excel (p. ej. 44818.0559). Ambos casos se resuelven en lectura.
BITGET_SPOT_TRADING_SIGNATURE = {
    "Order no.", "Trading pair", "Coin", "Action",
    "Executed price", "Quantity", "Transacted amount", "Fee",
}
# "Historial de depósitos y retiros" (Deposit/Withdrawal History)
#   ← OPCIONAL/RECOMENDADO: depósitos y retiros para conciliación y trazabilidad.
#   También llega con fila de título previa.
BITGET_DEPWD_SIGNATURE = {
    "Coin", "Network", "Quantity", "Amount in USDT", "Type", "Status",
}
# "Withdrawal Records" (variante alternativa de depósitos/retiros)
#   ← Ruta de exportación distinta a Deposit/Withdrawal History. Sin fila de título.
#   Sin columna Network ni Amount in USDT; usa Funding account, Address y TxID.
BITGET_WITHDRAWAL_RECORDS_SIGNATURE = {
    "Date", "Type", "Funding account", "Coin", "Quantity", "Address", "TxID", "Status",
}
# "Futures Order History" (historial de órdenes de futuros)
#   ← NO soportado: requiere revisión fiscal específica. Solo se detecta para
#     mostrar un mensaje descriptivo en lugar de "archivo no reconocido".
BITGET_FUTURES_ORDERS_SIGNATURE = {
    "Futures", "Realized P/L", "Order ID",
}
# "Spot Financial Record" (registro financiero granular)
#   ← INFORMATIVO: sólo auditoría/conciliación de saldos. NO se usa para FIFO
#     (sus asientos ORDER_FROZEN/DEALT duplicarían las operaciones del trading history).
BITGET_FINANCIAL_RECORD_SIGNATURE = {
    "Order no.", "Coin", "Type", "Action", "Quantity", "Amount (USDT)",
}

# Firmas textuales para _validar_csv (basta con que aparezca una en las primeras líneas).
# Se amplían para reconocer los nuevos exports y dejar de ser demasiado restrictiva.
BITGET_SIGNATURES = [
    "Fee Coin", "Available", "Order Id",          # detalles · transacciones · historial
    "Spot Trading Record", "Transacted amount",   # spot trading history
    "Deposit/Withdrawal History", "Amount in USDT",  # deposits & withdrawals (UID)
    "Spot Financial Record",                       # financial record (informativo)
    "Funding account",                             # withdrawal records (variante)
    "Realized P/L",                               # futures order history (no soportado)
]

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
    order_id: str = ""  # identificador nativo de Bitget (Order no.) cuando exista;
                        # se usa para deduplicar el mismo Spot Trading History subido
                        # dos veces o con rangos solapados. Vacío en detalles/transacciones.

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

    Robusto frente a las variantes de export de Bitget:
      · Fila de TÍTULO previa (p. ej. "Deposit/Withdrawal History,,,," o
        "Spot Trading Record,,,") → se localiza la cabecera real como la primera
        fila con ≥3 celdas no vacías (las de título tienen una sola).
      · Trailing comma en DETALLES → la columna de cabecera vacía se descarta.
      · Filas totalmente vacías → ignoradas.
    Para los exports clásicos (detalles/transacciones) la cabecera está en la
    fila 0 y el comportamiento es idéntico al anterior.
    """
    with open(filepath, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))

    if not rows:
        return [], []

    # Localizar la fila de cabecera: primera (de las 5 primeras) con ≥3 celdas
    # no vacías. Las filas de título de Bitget tienen una sola celda con texto.
    header_idx = 0
    for i, row in enumerate(rows[:5]):
        if sum(1 for c in row if (c or "").strip()) >= 3:
            header_idx = i
            break

    headers = [(h or "").strip() for h in rows[header_idx]]

    cleaned = []
    for row in rows[header_idx + 1:]:
        if not any((c or "").strip() for c in row):
            continue
        d = {}
        for j, key in enumerate(headers):
            if not key:                      # columna vacía (trailing comma) → descartar
                continue
            d[key] = row[j] if j < len(row) and row[j] is not None else ""
        cleaned.append(d)

    return headers, cleaned


def detect_bitget_file_type(filepath: str) -> str:
    """
    Inspecciona las cabeceras del CSV y devuelve el tipo de export de Bitget.

    Retorna:
        "detalles"           – Detalles de órdenes en spot
        "transacciones"      – Transacciones en spot (ledger)
        "historial"          – Historial de órdenes en spot (incluye canceladas; rechazado)
        "spot_trading"       – Spot Trading History / Historial de operaciones en spot
        "deposit_withdrawal" – Deposit/Withdrawal History (export UID con título)
        "withdrawal_records" – Withdrawal Records (variante sin título, columnas distintas)
        "financial_record"   – Spot Financial Record (auditoría; rechazado)
        "futures_orders"     – Futures Order History (no soportado; requiere criterio fiscal)
        "unknown"            – No reconocido como export de Bitget
    """
    try:
        headers, _ = _leer_csv(filepath)
    except Exception as e:
        logger.warning("Bitget: no se pudo leer el archivo: %s", e)
        return "unknown"

    headers_set = {h.strip() for h in headers if h}

    # Futuros: firma distintiva (Futures + Realized P/L + Order ID). Comprobar antes
    # que historial para evitar coincidencias parciales en archivos futuros/spot mixtos.
    if BITGET_FUTURES_ORDERS_SIGNATURE.issubset(headers_set):
        return "futures_orders"
    # El historial de órdenes spot tiene la firma más amplia; comprobar antes de
    # detalles para evitar falsos positivos (comparte "Trading pair" y más columnas).
    if BITGET_HISTORIAL_SIGNATURE.issubset(headers_set):
        return "historial"
    # Exports UID (con fila de título previa): los más distintivos primero.
    if BITGET_SPOT_TRADING_SIGNATURE.issubset(headers_set):
        return "spot_trading"
    if BITGET_FINANCIAL_RECORD_SIGNATURE.issubset(headers_set):
        return "financial_record"
    if BITGET_DEPWD_SIGNATURE.issubset(headers_set):
        return "deposit_withdrawal"
    # Variante alternativa de depósitos/retiros (sin fila de título, columnas distintas).
    if BITGET_WITHDRAWAL_RECORDS_SIGNATURE.issubset(headers_set):
        return "withdrawal_records"
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


# Epoch del número de serie de Excel (los exports UID de Bitget exportan las
# fechas como serial, p. ej. 44818.0559 → 2022-09-14 01:20). Excel cuenta desde
# 1899-12-30 por su bug histórico del año bisiesto 1900.
_EXCEL_EPOCH = datetime(1899, 12, 30)


def _excel_serial_a_fecha(valor: str):
    """Convierte un número de serie Excel a datetime. None si no aplica.
    Sólo acepta el rango ~2009-2064 para no confundir un número con una fecha."""
    try:
        num = float(str(valor).strip())
    except (ValueError, TypeError):
        return None
    if 30000 <= num <= 80000:        # 30000 ≈ 1982, 80000 ≈ 2119: margen amplio y seguro
        from datetime import timedelta
        return _EXCEL_EPOCH + timedelta(days=num)
    return None


def _parse_fecha(valor: str) -> str:
    """Parsea 'YYYY-MM-DD HH:MM:SS' con variantes, o un número de serie Excel.
    Devuelve ISO normalizado. Nota: los exports UID vienen en UTC+8; se conserva
    la fecha tal cual (naive), igual que el resto de exports de Bitget."""
    valor = str(valor).strip()
    if not valor:
        return valor
    serial = _excel_serial_a_fecha(valor)
    if serial is not None:
        return serial.strftime("%Y-%m-%d %H:%M:%S")
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
                "Este archivo contiene órdenes, incluidas órdenes canceladas, y no "
                "sirve para calcular FIFO. Descarga Spot Trading History / "
                "Historial de operaciones en spot."
            )
        if tipo == "futures_orders":
            raise ValueError(
                "Los futuros de Bitget no están soportados todavía. "
                "Requieren revisión fiscal específica."
            )
        if tipo == "financial_record":
            raise ValueError(
                "El «Spot Financial Record» es un fichero de auditoría y "
                "conciliación de saldos; no se usa para el cálculo FIFO. Sube el "
                "«Historial de operaciones en spot» (Spot Trading History)."
            )
        if tipo == "detalles":
            self._clasificar_detalles()
        elif tipo == "spot_trading":
            self._clasificar_spot_trading()
        elif tipo == "deposit_withdrawal":
            self._clasificar_deposit_withdrawal()
        elif tipo == "withdrawal_records":
            self._clasificar_withdrawal_records()
        elif tipo == "transacciones":
            self._clasificar_transacciones()
            self._generar_advertencias_transacciones()
        else:
            raise ValueError(
                "El archivo no se reconoce como un export de Bitget. "
                "Sube el «Historial de operaciones en spot» (recomendado) y, "
                "si lo tienes, el «Historial de depósitos y retiros»."
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

    # ── HISTORIAL DE OPERACIONES EN SPOT (Spot Trading History) ───────────────
    # Fuente FIFO recomendada: una fila por operación ejecutada, con par, precio,
    # cantidad y comisión, y con TODO el histórico (incluido el coste de adquisición).

    @staticmethod
    def _fecha_de_fila(fila: dict, prefiere: str = "creat") -> str:
        """Devuelve el valor de la columna de fecha de un export UID.
        La cabecera de estos ficheros trae saltos de línea ("Timestamp(UTC+8)\\n
        （created）"), así que buscamos por subcadena en vez de por clave exacta.
        Prioriza la columna de creación; si no, la primera de tipo timestamp/date."""
        for k, v in fila.items():
            kl = (k or "").lower()
            if "timestamp" in kl and prefiere in kl:
                return v
        for k, v in fila.items():
            kl = (k or "").lower()
            if "timestamp" in kl or kl == "date":
                return v
        return fila.get("Date", "")

    def _clasificar_spot_trading(self) -> None:
        _, rows = _leer_csv(self.filepath)
        for fila in rows:
            self._procesar_fila_spot_trading(fila)

    def _procesar_fila_spot_trading(self, fila: dict) -> None:
        coin   = fila.get("Coin", "").strip().upper()
        par    = fila.get("Trading pair", "").strip().upper()      # p. ej. BGBUSDT
        action = fila.get("Action", "").strip().lower()
        qty    = _parse_decimal(fila.get("Quantity", "0"))
        total  = _parse_decimal(fila.get("Transacted amount", "0"))
        fee    = _parse_decimal(fila.get("Fee", "0"))
        fee_coin = fila.get("Fee deducted in", "").strip().upper()
        fecha  = _parse_fecha(self._fecha_de_fila(fila))
        # Order no. nativo de Bitget (con apóstrofo/TAB de antifórmula) para dedup intra-fuente.
        order_id = fila.get("Order no.", "").strip().lstrip("'").lstrip("\t").strip()

        # quote = par sin la base (BGBUSDT − BGB → USDT). Fallback: stable al final.
        quote = ""
        if par.startswith(coin) and len(par) > len(coin):
            quote = par[len(coin):]
        if not quote:
            for st in STABLES_USD:
                if par.endswith(st):
                    quote = st
                    break

        if not coin or not quote or action not in ("buy", "sell"):
            self.desconocidas.append(OperacionDesconocida(
                fecha=fecha, subtipo=f"operación spot no reconocida ({action or '—'})",
                activo=coin or par, cantidad=float(qty), cuenta="Bitget",
            ))
            return

        if qty <= 0 or total <= 0:
            self.desconocidas.append(OperacionDesconocida(
                fecha=fecha, subtipo=f"cantidad/importe inválido ({action})",
                activo=coin, cantidad=float(qty), cuenta="Bitget",
            ))
            return

        if quote in STABLES_USD:
            self._tiene_pares_usdt = True

        self.compraventas.append(OperacionCompraventa(
            fecha        = fecha,
            tipo         = "COMPRA" if action == "buy" else "VENTA",
            activo       = coin,
            cantidad     = float(qty),
            contraparte  = quote,
            importe      = float(total),
            fee_activo   = fee_coin if fee_coin else quote,
            fee_cantidad = float(fee),
            order_id     = order_id,
        ))

    # ── HISTORIAL DE DEPÓSITOS Y RETIROS (Deposit/Withdrawal History) ─────────
    # Opcional/recomendado: movimientos para conciliación y trazabilidad.
    # NO generan FIFO (no son transmisiones patrimoniales).

    def _clasificar_deposit_withdrawal(self) -> None:
        _, rows = _leer_csv(self.filepath)
        for fila in rows:
            self._procesar_fila_depwd(fila)

    def _procesar_fila_depwd(self, fila: dict) -> None:
        coin     = fila.get("Coin", "").strip().upper()
        tipo_raw = fila.get("Type", "").strip().lower()
        qty      = abs(_parse_decimal(fila.get("Quantity", "0")))
        fee      = _parse_decimal(fila.get("fee", "0"))
        status   = fila.get("Status", "").strip().lower()
        fecha    = _parse_fecha(self._fecha_de_fila(fila, prefiere="complet"))

        # Sólo movimientos completados; ignorar fallidos/pendientes/cancelados.
        if status and status not in ("successful", "success", "completed", "finished"):
            return
        if not coin or qty <= 0:
            return

        if tipo_raw == "deposit":
            subtipo, obs = "Deposit", f"Depósito {coin}"
        elif tipo_raw in ("withdrawal", "withdraw"):
            subtipo, obs = "Withdrawal", f"Retiro {coin}"
        else:
            return

        red = fila.get("Network", "").strip()
        if red and red != "-":
            obs += f" | Red: {red}"
        if fee and fee != 0:
            obs += f" | Fee: {float(abs(fee)):.8g} {coin}"

        self.movimientos.append(OperacionMovimiento(
            fecha=fecha, subtipo=subtipo, activo=coin,
            cantidad=float(qty), observacion=obs,
        ))

    # ── WITHDRAWAL RECORDS (variante alternativa de depósitos/retiros) ───────────
    # Ruta de exportación distinta a Deposit/Withdrawal History. Sin fila de título.
    # Columnas: Date, Type, Funding account, Coin, Quantity, Address, TxID, Status.
    # TxID lleva TAB de antifórmula en transferencias internas → se limpia con strip.

    def _clasificar_withdrawal_records(self) -> None:
        _, rows = _leer_csv(self.filepath)
        for fila in rows:
            self._procesar_fila_withdrawal_records(fila)

    def _procesar_fila_withdrawal_records(self, fila: dict) -> None:
        coin     = fila.get("Coin", "").strip().upper()
        tipo_raw = fila.get("Type", "").strip().lower()
        qty      = abs(_parse_decimal(fila.get("Quantity", "0")))
        status   = fila.get("Status", "").strip().lower()
        fecha    = _parse_fecha(fila.get("Date", "").strip())

        if status and status not in ("successful", "success", "completed", "finished"):
            return
        if not coin or qty <= 0:
            return

        if tipo_raw == "deposit":
            subtipo, obs = "Deposit", f"Depósito {coin}"
        elif tipo_raw in ("withdrawal", "withdraw"):
            subtipo, obs = "Withdrawal", f"Retiro {coin}"
        else:
            return

        cuenta = fila.get("Funding account", "").strip()
        if cuenta and cuenta != "-":
            obs += f" | Cuenta: {cuenta}"

        address_type = fila.get("Address", "").strip()
        if address_type and address_type != "-":
            obs += f" | {address_type}"

        self.movimientos.append(OperacionMovimiento(
            fecha=fecha, subtipo=subtipo, activo=coin,
            cantidad=float(qty), observacion=obs,
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


# ── MULTIARCHIVO ──────────────────────────────────────────────────────────────

class BitgetUserError(ValueError):
    """Error imputable al usuario (ningún fichero reconocido, etc.), no un bug.
    Mismo contrato que KucoinUserError para que el endpoint lo interprete igual."""
    def __init__(self, code: str, mensaje_usuario: str):
        super().__init__(mensaje_usuario)
        self.code     = code
        self.category = "user_error"


@dataclass
class _ResumenSeccion:
    detectado: bool = False
    vacio: bool = False
    registros: int = 0


# Confianza para la deduplicación: el trading history es la fuente autorizada
# (histórico completo con coste de adquisición); detalles y transacciones se
# deduplican contra él. Menor número = mayor prioridad.
_PRIORIDAD_FUENTE = {"spot_trading": 0, "detalles": 1, "transacciones": 2}


def _dedup_key(op: "OperacionCompraventa") -> tuple:
    """Clave de deduplicación tolerante a zona horaria y redondeo.

    Los exports difieren en la fecha (Detalles usa la hora local del navegador,
    el Trading History usa UTC+8) y en el redondeo del importe, así que NO se usa
    la fecha. Cantidad e identidad del activo coinciden exactamente entre exports;
    el importe se redondea a 2 decimales para absorber el redondeo de Bitget.
    """
    return (op.activo, op.tipo, round(op.cantidad, 6), round(op.importe, 2))


class ClasificadorBitgetMulti:
    """
    Clasificador fiscal MULTIARCHIVO para Bitget (patrón ClasificadorKuCoin).

    El usuario sube uno o varios CSV; el sistema detecta el tipo de cada uno por
    su cabecera y consolida las operaciones, deduplicando los solapamientos entre
    «Detalles de órdenes» y «Historial de operaciones en spot».

    Expone el contrato FIFO (compraventas · swaps · movimientos · rendimientos ·
    desconocidas · advertencias) y `resumen_archivos` para la UI.
    """

    def __init__(self, filepaths, filenames=None):
        self.filepaths = list(filepaths)
        self.filenames = list(filenames) if filenames else [self._basename(p) for p in self.filepaths]

        self.compraventas: list = []
        self.swaps:        list = []
        self.movimientos:  list = []
        self.rendimientos: list = []
        self.desconocidas: list = []
        self.advertencias: list = []

        # Buffers de compraventas por fuente (para deduplicar tras leer todo)
        self._cv_por_fuente = {"spot_trading": [], "detalles": [], "transacciones": []}
        self._no_reconocidos: list = []
        self._tiene_pares_usdt = False

        self._sec = {
            "spot_trading":       _ResumenSeccion(),
            "deposit_withdrawal": _ResumenSeccion(),
            "detalles":           _ResumenSeccion(),
            "transacciones":      _ResumenSeccion(),
            "financial_record":   _ResumenSeccion(),
        }

    @staticmethod
    def _basename(p: str) -> str:
        import os
        return os.path.basename(p)

    # ── ENTRADA PÚBLICA ────────────────────────────────────────────────────────

    def clasificar(self) -> "ClasificadorBitgetMulti":
        if not self.filepaths:
            raise BitgetUserError("no_files", "No se recibió ningún fichero de Bitget.")

        algun_reconocido = False

        for fp, fname in zip(self.filepaths, self.filenames):
            try:
                tipo = detect_bitget_file_type(fp)
            except Exception as e:                       # pragma: no cover
                logger.warning("Bitget: no se pudo leer %s: %s", fname, e)
                self._no_reconocidos.append(fname)
                continue

            if tipo == "historial":
                algun_reconocido = True   # es un fichero de Bitget, sólo que no sirve
                self.advertencias.append(
                    f"«{fname}» contiene órdenes, incluidas órdenes canceladas, y no "
                    "sirve para calcular FIFO. Descarga el Spot Trading History / "
                    "Historial de operaciones en spot. Se ha ignorado."
                )
                continue

            if tipo == "futures_orders":
                algun_reconocido = True   # es un fichero de Bitget, pero futuros no soportados
                self.advertencias.append(
                    f"«{fname}»: Los futuros de Bitget no están soportados todavía. "
                    "Requieren revisión fiscal específica. Se ha ignorado."
                )
                continue

            if tipo == "financial_record":
                algun_reconocido = True
                self._sec["financial_record"].detectado = True
                self.advertencias.append(
                    f"«{fname}» es el Spot Financial Record (auditoría/conciliación "
                    "de saldos). No se usa para FIFO; se ha ignorado para no duplicar "
                    "operaciones."
                )
                continue

            if tipo == "unknown":
                self._no_reconocidos.append(fname)
                continue

            # detalles · transacciones · spot_trading · deposit_withdrawal
            try:
                c = ClasificadorBitget(fp).clasificar()
            except ValueError as e:
                self.advertencias.append(f"«{fname}»: {e}")
                continue

            algun_reconocido = True
            self._absorber(tipo, c)

        if not algun_reconocido:
            raise BitgetUserError(
                "wrong_file",
                "Ninguno de los ficheros se reconoce como un export de Bitget. "
                "Sube el «Historial de operaciones en spot» (recomendado) y, si lo "
                "tienes, el «Historial de depósitos y retiros».",
            )

        self._consolidar_compraventas()
        self._dedup_movimientos()
        self._construir_advertencias()
        return self

    # ── ABSORCIÓN POR FICHERO ──────────────────────────────────────────────────

    def _absorber(self, tipo: str, c: "ClasificadorBitget") -> None:
        """Vuelca las operaciones de un clasificador single-file en los buffers."""
        if tipo in self._cv_por_fuente:
            self._cv_por_fuente[tipo].extend(c.compraventas)
        else:                                            # spot_trading no está en el dict de fuentes CV
            self._cv_por_fuente.setdefault(tipo, []).extend(c.compraventas)

        self.swaps.extend(c.swaps)
        self.movimientos.extend(c.movimientos)
        self.rendimientos.extend(c.rendimientos)
        self.desconocidas.extend(c.desconocidas)
        if getattr(c, "_tiene_pares_usdt", False):
            self._tiene_pares_usdt = True

        _es_depositos = tipo in ("deposit_withdrawal", "withdrawal_records")
        sec_key = "deposit_withdrawal" if _es_depositos else tipo
        sec = self._sec.get(sec_key)
        if sec is not None:
            sec.detectado = True
            n = len(c.movimientos) if _es_depositos else len(c.compraventas)
            sec.registros += n
            if n == 0:
                sec.vacio = True

    # ── DEDUPLICACIÓN ──────────────────────────────────────────────────────────

    def _dedup_intra_spot_trading(self, ops: list) -> list:
        """Deduplica el Spot Trading History contra sí mismo.

        Protege frente a subir el mismo Trading History dos veces o varios con
        rangos de fechas solapados. Usa el «Order no.» nativo de Bitget como
        identidad (único y persistente dentro de este formato); si una fila no lo
        trae (caso degenerado: en los exports reales siempre está presente), cae
        a la clave por valor. Conserva la primera aparición de cada identidad.
        """
        self._n_dedup_intra = 0
        vistos = set()
        unicos = []
        for op in ops:
            oid = (getattr(op, "order_id", "") or "").strip()
            identidad = ("ID", oid) if oid else ("VAL",) + _dedup_key(op)
            if identidad in vistos:
                self._n_dedup_intra += 1
                continue
            vistos.add(identidad)
            unicos.append(op)
        return unicos

    def _consolidar_compraventas(self) -> None:
        """Funde las compraventas de todas las fuentes deduplicando solapamientos.

        Dos niveles de deduplicación:
          1. INTRA Spot Trading History (por «Order no.»): mismo fichero subido dos
             veces o exports con rangos solapados → una sola copia.
          2. CRUCE Detalles/Transacciones ↔ Spot Trading History (por valor, ya que
             el Detalles no trae ningún identificador): el Trading History es
             autoritativo y cada operación absorbe como máximo una equivalente.
        """
        from collections import Counter

        prioritarias = self._dedup_intra_spot_trading(
            self._cv_por_fuente.get("spot_trading", [])
        )
        presupuesto = Counter(_dedup_key(op) for op in prioritarias)

        consolidadas = list(prioritarias)
        self._n_dedup = 0

        otras = []
        for fuente in sorted(self._cv_por_fuente):
            if fuente == "spot_trading":
                continue
            otras.extend(self._cv_por_fuente[fuente])

        for op in otras:
            k = _dedup_key(op)
            if presupuesto.get(k, 0) > 0:
                presupuesto[k] -= 1
                self._n_dedup += 1
            else:
                consolidadas.append(op)

        self.compraventas = consolidadas

    def _dedup_movimientos(self) -> None:
        """Deduplica movimientos idénticos (mismo subtipo/activo/cantidad/día) por si
        se suben dos exports de depósitos/retiros solapados."""
        vistos = set()
        unicos = []
        for m in self.movimientos:
            k = (m.subtipo, m.activo, round(m.cantidad, 8), (m.fecha or "")[:10])
            if k in vistos:
                continue
            vistos.add(k)
            unicos.append(m)
        self.movimientos = unicos

    # ── ADVERTENCIAS Y RESUMEN ─────────────────────────────────────────────────

    def _construir_advertencias(self) -> None:
        if getattr(self, "_n_dedup_intra", 0) > 0:
            n = self._n_dedup_intra
            self.advertencias.insert(0,
                f"Se {'ha' if n == 1 else 'han'} descartado {n} "
                f"{'operación repetida' if n == 1 else 'operaciones repetidas'} "
                "dentro del «Historial de operaciones en spot» (mismo fichero subido "
                "dos veces o exports con fechas solapadas)."
            )

        if getattr(self, "_n_dedup", 0) > 0:
            n = self._n_dedup
            self.advertencias.insert(0,
                f"Se {'ha' if n == 1 else 'han'} descartado {n} "
                f"{'operación duplicada' if n == 1 else 'operaciones duplicadas'} "
                "entre el «Detalles de órdenes» y el «Historial de operaciones en "
                "spot» (mismo período). El cálculo usa el historial de operaciones."
            )

        # Compraventas sólo desde Detalles, sin Trading History: avisar del riesgo
        # de que falte el coste de adquisición histórico.
        if (self._sec["detalles"].detectado and self._sec["detalles"].registros > 0
                and not self._sec["spot_trading"].detectado):
            self.advertencias.append(
                "Has subido el «Detalles de órdenes en spot» pero no el «Historial "
                "de operaciones en spot». Si tus compras más antiguas no están en "
                "este fichero, el coste de adquisición puede salir incompleto. "
                "Recomendamos subir el Historial de operaciones en spot."
            )

        if self._tiene_pares_usdt:
            self.advertencias.append(
                "Las operaciones están valoradas en USDT u otra stablecoin. "
                "Para la declaración del IRPF aplica el tipo de cambio EUR/USD "
                "vigente en la fecha de cada operación."
            )

        if self.desconocidas:
            tipos = sorted({d.subtipo for d in self.desconocidas})
            self.advertencias.append(
                f"{len(self.desconocidas)} operación(es) no reconocida(s): "
                + ", ".join(tipos)
            )

        if self._no_reconocidos:
            self.advertencias.append(
                "Archivos no reconocidos como Bitget: " + ", ".join(self._no_reconocidos)
            )

    @property
    def resumen_archivos(self) -> dict:
        def _sec(s: _ResumenSeccion) -> dict:
            return {"detectado": s.detectado, "vacio": s.vacio, "registros": s.registros}
        return {
            "spot_trading":       _sec(self._sec["spot_trading"]),
            "deposit_withdrawal": _sec(self._sec["deposit_withdrawal"]),
            "detalles":           _sec(self._sec["detalles"]),
            "transacciones":      _sec(self._sec["transacciones"]),
            "financial_record":   _sec(self._sec["financial_record"]),
            "no_reconocidos":     list(self._no_reconocidos),
        }

    def resumen(self) -> dict:
        return {
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
    if len(sys.argv) > 2:
        # Varios ficheros → flujo multiarchivo
        c = ClasificadorBitgetMulti(sys.argv[1:]).clasificar()
        print("=" * 60)
        print("RESUMEN Bitget MULTIARCHIVO")
        print("=" * 60)
        for k, v in c.resumen().items():
            print(f"  {k:<20} {v:>6}")
        print("\n── RESUMEN ARCHIVOS ──")
        for k, v in c.resumen_archivos.items():
            print(f"  {k:<20} {v}")
        print("\n── COMPRAVENTAS ──")
        for op in c.compraventas:
            print(f"  {op.fecha[:10]}  {op.tipo:<6}  {op.activo:<8}"
                  f"  {op.cantidad:>14.8f}  @ {op.importe:.6f} {op.contraparte}")
        print(f"\n── ADVERTENCIAS ({len(c.advertencias)}) ──")
        for adv in c.advertencias:
            print(f"  ⚠  {adv}")
        sys.exit(0)

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
