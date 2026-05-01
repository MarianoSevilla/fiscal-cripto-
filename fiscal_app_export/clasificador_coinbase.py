"""
Clasificador fiscal de operaciones Coinbase
Mariano Sevilla — marianosevilla.com
v1.0

Formato CSV de Coinbase (Transaction History):
- 3 filas de metadatos antes de la cabecera (skiprows=3)
- Columnas: ID, Timestamp, Transaction Type, Asset, Quantity Transacted,
  Price Currency, Price at Transaction, Subtotal, Total (inclusive of fees and/or spread),
  Fees and/or Spread, Notes, Sender Address, Recipient Address
- Precios con símbolo €: "€2.64397897689227539608"
- Cantidades negativas para activos entregados (Sell, Convert)
- Convert: notas del tipo "Converted 179.40827296 DOGE to 19.758807 XRP"
"""

import re
import pandas as pd
from dataclasses import dataclass


# ── CONSTANTES ────────────────────────────────

STABLES = {"EUR", "USD", "USDC", "USDT", "BUSD", "DAI", "FDUSD", "USDG"}

TIPOS_RENDIMIENTO = {
    "Rewards Income",
    "Learning Reward",
    "Coinbase Earn",
    "Inflation Reward",
    "Staking Income",
    "Interest Income",
}

TIPOS_MOVIMIENTO = {
    "Withdrawal",
    "Deposit",
    "Send",
    "Receive",
    "Subscription",
    "Advanced Trade Buy",   # se trata aparte si tiene precio EUR
    "Advanced Trade Sell",  # se trata aparte si tiene precio EUR
}

# Firma de detección en las primeras líneas del CSV
COINBASE_SIGNATURES = ["Timestamp", "Transaction Type", "Quantity Transacted"]


# ── DATACLASSES (compatibles con motor_fifo) ──

@dataclass
class OperacionCompraventa:
    fecha: str
    tipo: str
    activo: str
    cantidad: float
    contraparte: str
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
    precio_fmv_eur: float = 0.0

@dataclass
class OperacionRendimiento:
    fecha: str
    subtipo: str
    activo: str
    cantidad: float
    cuenta: str
    valor_eur: float = 0.0

@dataclass
class OperacionMovimiento:
    fecha: str
    subtipo: str
    activo: str
    cantidad: float
    observacion: str

@dataclass
class OperacionDesconocida:
    fecha: str
    subtipo: str
    activo: str
    cantidad: float
    cuenta: str


# ── CLASIFICADOR ──────────────────────────────

class ClasificadorCoinbase:

    def __init__(self, filepath: str):
        # Las primeras 3 filas son metadatos: vacía, "Transactions", usuario
        self.df = pd.read_csv(filepath, skiprows=3)
        self.compraventas:  list[OperacionCompraventa] = []
        self.swaps:         list[OperacionSwap]        = []
        self.rendimientos:  list[OperacionRendimiento] = []
        self.movimientos:   list[OperacionMovimiento]  = []
        self.desconocidas:  list[OperacionDesconocida] = []
        self.advertencias:  list[str]                  = []

    def clasificar(self):
        self.df.columns = [c.strip() for c in self.df.columns]

        # Normalizar timestamp
        self.df["Timestamp"] = pd.to_datetime(
            self.df["Timestamp"], utc=True, errors="coerce"
        )
        self.df = self.df.sort_values("Timestamp").reset_index(drop=True)

        for _, fila in self.df.iterrows():
            self._clasificar_fila(fila)

        return self

    def _clasificar_fila(self, fila):
        tipo     = str(fila.get("Transaction Type", "")).strip()
        activo   = str(fila.get("Asset", "")).strip()
        qty      = abs(self._float(fila.get("Quantity Transacted", 0)))
        subtotal = abs(self._float_eur(fila.get("Subtotal", 0)))
        total    = abs(self._float_eur(fila.get("Total (inclusive of fees and/or spread)", 0)))
        fees     = abs(self._float_eur(fila.get("Fees and/or Spread", 0)))
        notas    = str(fila.get("Notes", "")).strip()
        moneda   = str(fila.get("Price Currency", "EUR")).strip()
        fecha    = self._fmt_fecha(fila.get("Timestamp"))

        # ── COMPRA (Buy, Advanced Trade Buy) ──────────────────────────────────
        if tipo in ("Buy", "Advanced Trade Buy"):
            if activo not in STABLES:
                # importe pagado = total (incluye fees)
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="COMPRA",
                    activo=activo, cantidad=qty,
                    contraparte=moneda, importe=total,
                    fee_activo=moneda, fee_cantidad=fees,
                ))
            else:
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=tipo,
                    activo=activo, cantidad=qty,
                    observacion=notas,
                ))

        # ── VENTA (Sell, Advanced Trade Sell) ─────────────────────────────────
        elif tipo in ("Sell", "Advanced Trade Sell"):
            if activo not in STABLES:
                # importe recibido = subtotal (antes de fees)
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="VENTA",
                    activo=activo, cantidad=qty,
                    contraparte=moneda, importe=subtotal,
                    fee_activo=moneda, fee_cantidad=fees,
                ))
            else:
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=tipo,
                    activo=activo, cantidad=qty,
                    observacion=notas,
                ))

        # ── SWAP (Convert) ────────────────────────────────────────────────────
        elif tipo == "Convert":
            recibida_qty, activo_recibido = self._parse_convert_notas(notas, activo)
            if recibida_qty > 0 and activo_recibido:
                # FMV del activo recibido = valor del subtotal entregado
                fmv_eur = subtotal if subtotal > 0 else total
                self.swaps.append(OperacionSwap(
                    fecha=fecha,
                    activo_entregado=activo,
                    cantidad_entregada=qty,
                    activo_recibido=activo_recibido,
                    cantidad_recibida=recibida_qty,
                    nota=notas,
                    precio_fmv_eur=round(fmv_eur, 6),
                ))
            else:
                # No se pudo parsear la nota
                self.advertencias.append(
                    f"Convert sin nota reconocible el {fecha}: {notas!r}. "
                    f"Operación añadida como desconocida."
                )
                self.desconocidas.append(OperacionDesconocida(
                    fecha=fecha, subtipo="Convert",
                    activo=activo, cantidad=qty, cuenta="Coinbase",
                ))

        # ── RENDIMIENTOS ──────────────────────────────────────────────────────
        elif tipo in TIPOS_RENDIMIENTO:
            self.rendimientos.append(OperacionRendimiento(
                fecha=fecha, subtipo=tipo,
                activo=activo, cantidad=qty,
                cuenta="Coinbase",
                valor_eur=total,
            ))

        # ── MOVIMIENTOS ───────────────────────────────────────────────────────
        elif tipo in TIPOS_MOVIMIENTO or tipo in ("Withdrawal", "Deposit", "Send", "Receive"):
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo=tipo,
                activo=activo, cantidad=qty,
                observacion=notas,
            ))

        # ── DESCONOCIDO ───────────────────────────────────────────────────────
        else:
            if tipo and tipo not in ("nan", ""):
                self.advertencias.append(
                    f"Tipo de operación no reconocido: «{tipo}» el {fecha} — "
                    f"se ignora a efectos fiscales."
                )
                self.desconocidas.append(OperacionDesconocida(
                    fecha=fecha, subtipo=tipo,
                    activo=activo, cantidad=qty, cuenta="Coinbase",
                ))

    def _parse_convert_notas(self, nota: str, activo_fallback: str) -> tuple[float, str]:
        """
        Parsea notas como "Converted 179.40827296 DOGE to 19.758807 XRP".
        Devuelve (cantidad_recibida, activo_recibido).
        """
        m = re.search(
            r"Converted\s+[\d.]+\s+\S+\s+to\s+([\d.]+)\s+(\w+)",
            nota, re.IGNORECASE
        )
        if m:
            return float(m.group(1)), m.group(2).upper()
        return 0.0, ""

    @staticmethod
    def _float_eur(val) -> float:
        """Convierte valores monetarios con símbolo € a float."""
        try:
            s = str(val).strip().replace("€", "").replace(",", "").replace("-", "").strip()
            return float(s) if s and s.lower() not in ("", "nan") else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _float(val) -> float:
        try:
            return float(str(val).strip())
        except Exception:
            return 0.0

    @staticmethod
    def _fmt_fecha(ts) -> str:
        """Convierte timestamp pandas a string YYYY-MM-DD HH:MM:SS (sin timezone)."""
        try:
            if pd.isna(ts):
                return ""
            # Convertir a naive UTC para compatibilidad con motor_fifo
            if hasattr(ts, 'tz_localize'):
                # pandas Timestamp con timezone → normalizar a naive
                ts = ts.tz_convert(None)
            return ts.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts)[:19]

    def resumen(self) -> dict:
        return {
            "total_filas_csv": len(self.df),
            "compraventas":    len(self.compraventas),
            "swaps":           len(self.swaps),
            "rendimientos":    len(self.rendimientos),
            "movimientos":     len(self.movimientos),
            "desconocidas":    len(self.desconocidas),
            "advertencias":    len(self.advertencias),
        }


# ── EJECUCIÓN DIRECTA ─────────────────────────

if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "coinbase.csv"
    print(f"\nProcesando: {ruta}\n")

    c = ClasificadorCoinbase(ruta).clasificar()
    r = c.resumen()

    print("=" * 50)
    print("RESUMEN DE CLASIFICACIÓN — COINBASE")
    print("=" * 50)
    for k, v in r.items():
        print(f"  {k:<25} {v:>6}")

    print("\n── COMPRAVENTAS ──")
    for op in c.compraventas[:10]:
        print(f"  {op.fecha[:10]} | {op.tipo:6} | {op.activo:8} | "
              f"{op.cantidad:.6f} | {op.importe:.4f} {op.contraparte} | "
              f"fee: {op.fee_cantidad:.4f} {op.fee_activo}")

    print("\n── SWAPS ──")
    for op in c.swaps[:10]:
        print(f"  {op.fecha[:10]} | {op.activo_entregado:6} → {op.activo_recibido:6} | "
              f"{op.cantidad_entregada:.6f} → {op.cantidad_recibida:.6f} | "
              f"FMV: {op.precio_fmv_eur:.4f} EUR")

    print("\n── RENDIMIENTOS ──")
    for op in c.rendimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:25} | {op.activo:6} | {op.cantidad:.8f} | "
              f"valor: {op.valor_eur:.4f} EUR")

    print("\n── MOVIMIENTOS ──")
    for op in c.movimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | {op.cantidad:.4f}")

    print("\n── ADVERTENCIAS ──")
    if c.advertencias:
        for adv in c.advertencias:
            print(f"  ⚠  {adv}")
    else:
        print("  Ninguna ✓")

    print("\n── DESCONOCIDAS ──")
    if c.desconocidas:
        for op in c.desconocidas:
            print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | {op.cantidad:.6f}")
    else:
        print("  Ninguna ✓")
