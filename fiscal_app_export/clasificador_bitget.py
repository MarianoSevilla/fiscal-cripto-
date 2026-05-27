"""
Clasificador fiscal de operaciones Bitget (spot CSV)
Mariano Sevilla — marianosevilla.com

Soporta los exports CSV de Bitget spot:
  · Detalles de órdenes en spot  ← fuente fiscal principal para FIFO
    Headers: Date, Trading pair, Base Asset, Quote Asset, Direction,
             Price, Amount, Total, Fee, Fee Coin
  · Transacciones en spot        ← complementario: depósitos, retiros, transfers
    Headers: order, Date, Coin, Type, Amount, Fee, Available
  · Historial de órdenes en spot ← solo detección, no procesado en fase 1
    Headers: Date, Type, Order Id, Trading pair, …

Riesgos gestionados:
  - UTF-8-SIG (BOM) en los 3 archivos → encoding='utf-8-sig'
  - TAB prefijado en IDs de orden → .strip() en todos los campos
  - Columna vacía None por trailing comma en DETALLES → filtrada en lectura
  - Multi-fill: mismo timestamp y par → operaciones FIFO independientes
  - Fee en Base Asset (Buy) vs Fee en USDT (Sell)
  - Pares todos X/USDT → advertencia conversión EUR
  - Sin timezone explícito: se asume UTC
  - PI y activos depositados sin coste → inventario insuficiente en FIFO

NO soportado en fase 1:
  · Historial de órdenes en spot (agregados + canceladas → no adecuado para FIFO)
  · Futuros, earn, staking, copy trading
"""

import csv
import logging
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

def _leer_csv(filepath: str) -> tuple[list[str], list[dict]]:
    """
    Lee CSV UTF-8-SIG (BOM) y devuelve (headers, filas_como_dict).
    Elimina la columna None generada por trailing comma en DETALLES.
    """
    with open(filepath, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])

    # Eliminar clave None (artefacto de trailing comma)
    cleaned = [{k: v for k, v in row.items() if k is not None} for row in rows]
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

    # El historial tiene la firma más amplia, comprobar primero para evitar
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

    Fuente fiscal: CSV de "Detalles de órdenes en spot"
    Movimientos:   CSV de "Transacciones en spot"
    No procesado:  CSV de "Historial de órdenes en spot" → ValueError descriptivo

    Expone la misma interfaz que ClasificadorMEXC para compatibilidad con
    _pipeline_motor y procesar_con_fifo.

    Atributos públicos:
        compraventas  — BUY/SELL spot como OperacionCompraventa
        movimientos   — depósitos/retiros/transfers como OperacionMovimiento
        rendimientos  — vacío en fase 1
        swaps         — vacío en fase 1
        desconocidas  — operaciones no reconocidas
        advertencias  — warnings (pares USDT, inventario insuficiente…)
        tipo_export   — "detalles" | "transacciones" (informativo)
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.tipo_export: str = ""

        self.compraventas:  list[OperacionCompraventa]  = []
        self.movimientos:   list[OperacionMovimiento]   = []
        self.rendimientos:  list[OperacionRendimiento]  = []
        self.swaps:         list[OperacionSwap]         = []
        self.desconocidas:  list[OperacionDesconocida]  = []
        self.advertencias:  list[str]                   = []

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

    # ── DETALLES DE ÓRDENES (fuente fiscal) ───────────────────────────────────

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
        #          El motor FIFO lo contabiliza como coste adicional.
        #   Sell → Fee Coin = USDT       → fee reduce el ingreso neto.
        # Se pasa la fee bruta al motor; este ajusta precio_coste / precio_transmision.
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

    # ── TRANSACCIONES EN SPOT (movimientos) ───────────────────────────────────

    def _clasificar_transacciones(self) -> None:
        _, rows = _leer_csv(self.filepath)
        for fila in rows:
            self._procesar_fila_transacciones(fila)

    def _procesar_fila_transacciones(self, fila: dict) -> None:
        fecha_raw  = fila.get("Date", "").strip()
        fecha      = _parse_fecha(fecha_raw)

        coin       = fila.get("Coin", "").strip().upper()
        tipo_raw   = fila.get("Type", "").strip()
        amount_raw = fila.get("Amount", "0").strip()
        fee_raw    = fila.get("Fee",    "0").strip()

        amount = _parse_decimal(amount_raw)
        fee    = _parse_decimal(fee_raw)

        tipo_lower = tipo_raw.lower()

        if tipo_lower == "deposit":
            if not coin:
                return
            obs = f"Depósito {coin}"
            if fee != 0:
                obs += f" | Fee: {float(abs(fee)):.8g} {coin}"
            self.movimientos.append(OperacionMovimiento(
                fecha       = fecha,
                subtipo     = "Deposit",
                activo      = coin,
                cantidad    = float(abs(amount)),
                observacion = obs,
            ))

        elif tipo_lower == "ordinary withdrawal":
            if not coin:
                return
            obs = f"Retiro {coin}"
            if fee != 0:
                obs += f" | Fee: {float(abs(fee)):.8g} {coin}"
            self.movimientos.append(OperacionMovimiento(
                fecha       = fecha,
                subtipo     = "Withdrawal",
                activo      = coin,
                cantidad    = float(abs(amount)),
                observacion = obs,
            ))

        elif tipo_lower == "transfer out":
            if not coin:
                return
            self.movimientos.append(OperacionMovimiento(
                fecha       = fecha,
                subtipo     = "Transfer",
                activo      = coin,
                cantidad    = float(abs(amount)),
                observacion = "Transferencia interna Bitget (spot → otro producto)",
            ))

        elif tipo_lower in ("buy", "sell"):
            # Entradas del ledger de trades — ignorar (datos en DETALLES)
            pass

        else:
            self.desconocidas.append(OperacionDesconocida(
                fecha=fecha, subtipo=tipo_raw,
                activo=coin, cantidad=float(abs(amount)), cuenta="Bitget",
            ))

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

    print("=" * 55)
    print(f"RESUMEN Bitget  —  tipo={c.tipo_export}")
    print("=" * 55)
    for k, v in r.items():
        print(f"  {k:<20} {v:>6}")

    print("\n── COMPRAVENTAS ──")
    for op in c.compraventas:
        print(f"  {op.fecha[:10]}  {op.tipo:<6}  {op.activo:<8}"
              f"  {op.cantidad:>14.8f}  @ {op.importe:.6f} {op.contraparte}"
              f"  fee: {op.fee_cantidad:.8g} {op.fee_activo}")

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
