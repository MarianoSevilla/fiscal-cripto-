"""
Clasificador fiscal de operaciones Bitvavo
Mariano Sevilla — marianosevilla.com
v1.0

Formato CSV de Bitvavo:
- Una operación por fila (formato estándar horizontal)
- Columnas: Timezone, Date, Time, Type, Currency, Amount, Quote Currency,
            Quote Price, Received/Paid Currency, Received/Paid Amount,
            Fee currency, Fee amount, Status, Transaction ID, Address

Tipos de operación:
- buy      → COMPRA (Amount positivo = cripto recibida, Received/Paid negativo = EUR pagados)
- sell     → VENTA  (Amount negativo = cripto entregada, Received/Paid positivo = EUR recibidos)
- staking  → RENDIMIENTO
- deposit  → MOVIMIENTO entrada
- withdrawal → MOVIMIENTO salida
- rebate   → RENDIMIENTO (devolución de fees)
- campaign_new_user_incentive → RENDIMIENTO (bonus)
"""

import pandas as pd
from dataclasses import dataclass


# ── CONSTANTES ────────────────────────────────

STABLES = {"EUR", "USDT", "USDC", "BUSD", "DAI", "FDUSD"}

TIPOS_RENDIMIENTO = {
    "staking", "rebate", "campaign_new_user_incentive",
    "affiliate", "cashback", "airdrop"
}

TIPOS_MOVIMIENTO = {"deposit", "withdrawal", "transfer"}


# ── DATACLASSES (compatibles con motor_fifo) ──

@dataclass
class OperacionCompraventa:
    fecha: str
    tipo: str          # COMPRA | VENTA
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

@dataclass
class OperacionRendimiento:
    fecha: str
    subtipo: str
    activo: str
    cantidad: float
    cuenta: str

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

class ClasificadorBitvavo:

    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath)
        self.compraventas:  list[OperacionCompraventa] = []
        self.swaps:         list[OperacionSwap]        = []
        self.rendimientos:  list[OperacionRendimiento] = []
        self.movimientos:   list[OperacionMovimiento]  = []
        self.desconocidas:  list[OperacionDesconocida] = []

    def clasificar(self):
        # Normalizar columnas (quitar espacios)
        self.df.columns = [c.strip() for c in self.df.columns]

        # Construir timestamp
        self.df["fecha"] = (
            self.df["Date"].astype(str) + " " +
            self.df["Time"].astype(str).str.split(".").str[0]  # quitar milisegundos
        )

        # Solo procesar operaciones completadas
        if "Status" in self.df.columns:
            df = self.df[self.df["Status"].isin(["Completed", "Distributed"])].copy()
        else:
            df = self.df.copy()

        for _, fila in df.iterrows():
            self._clasificar_fila(fila)

        return self

    def _clasificar_fila(self, fila):
        tipo     = str(fila.get("Type", "")).strip().lower()
        moneda   = str(fila.get("Currency", "")).strip()
        cantidad = self._float(fila.get("Amount", 0))
        fecha    = str(fila.get("fecha", ""))
        fee_mon  = str(fila.get("Fee currency", "")).strip()
        fee_cant = self._float(fila.get("Fee amount", 0))

        # Received/Paid
        rec_mon  = str(fila.get("Received / Paid Currency", "")).strip()
        rec_cant = self._float(fila.get("Received / Paid Amount", 0))

        if tipo == "buy":
            # Compra: Amount = cripto recibida (+), Received/Paid = EUR pagados (-)
            activo        = moneda
            cant_comprada = abs(cantidad)
            contraparte   = rec_mon if rec_mon and rec_mon != "nan" else "EUR"
            importe       = abs(rec_cant)

            if activo in STABLES:
                # Compra de stable con EUR → movimiento, no hecho imponible
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo="buy_stable",
                    activo=activo, cantidad=cant_comprada,
                    observacion=f"Compra de {activo} con {contraparte}"
                ))
            else:
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="COMPRA",
                    activo=activo, cantidad=cant_comprada,
                    contraparte=contraparte, importe=importe,
                    fee_activo=fee_mon if fee_mon and fee_mon != "nan" else "EUR",
                    fee_cantidad=abs(fee_cant)
                ))

        elif tipo == "sell":
            # Venta: Amount = cripto entregada (-), Received/Paid = EUR recibidos (+)
            activo        = moneda
            cant_vendida  = abs(cantidad)
            contraparte   = rec_mon if rec_mon and rec_mon != "nan" else "EUR"
            importe       = abs(rec_cant)

            if activo in STABLES:
                # Venta de stable → movimiento
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo="sell_stable",
                    activo=activo, cantidad=cant_vendida,
                    observacion=f"Venta de {activo} por {contraparte}"
                ))
            else:
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="VENTA",
                    activo=activo, cantidad=cant_vendida,
                    contraparte=contraparte, importe=importe,
                    fee_activo=fee_mon if fee_mon and fee_mon != "nan" else "EUR",
                    fee_cantidad=abs(fee_cant)
                ))

        elif tipo in TIPOS_RENDIMIENTO:
            self.rendimientos.append(OperacionRendimiento(
                fecha=fecha, subtipo=tipo,
                activo=moneda, cantidad=abs(cantidad),
                cuenta="Bitvavo"
            ))

        elif tipo in TIPOS_MOVIMIENTO:
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo=tipo,
                activo=moneda, cantidad=cantidad,
                observacion=str(fila.get("Address", ""))
            ))

        else:
            if tipo and tipo != "nan":
                self.desconocidas.append(OperacionDesconocida(
                    fecha=fecha, subtipo=tipo,
                    activo=moneda, cantidad=cantidad,
                    cuenta="Bitvavo"
                ))

    @staticmethod
    def _float(val) -> float:
        try:
            return float(val)
        except Exception:
            return 0.0

    def resumen(self) -> dict:
        return {
            "total_filas_csv": len(self.df),
            "compraventas":    len(self.compraventas),
            "swaps":           len(self.swaps),
            "rendimientos":    len(self.rendimientos),
            "movimientos":     len(self.movimientos),
            "desconocidas":    len(self.desconocidas),
        }


# ── EJECUCIÓN DIRECTA ─────────────────────────

if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "bitvavo.csv"
    print(f"\nProcesando: {ruta}\n")

    c = ClasificadorBitvavo(ruta).clasificar()
    r = c.resumen()

    print("=" * 50)
    print("RESUMEN DE CLASIFICACIÓN — BITVAVO")
    print("=" * 50)
    for k, v in r.items():
        print(f"  {k:<25} {v:>6}")

    print("\n── COMPRAVENTAS ──")
    for op in c.compraventas:
        print(f"  {op.fecha[:10]} | {op.tipo:6} | {op.activo:8} | {op.cantidad:.6f} | {op.importe:.4f} {op.contraparte} | fee: {op.fee_cantidad:.4f} {op.fee_activo}")

    print("\n── RENDIMIENTOS ──")
    for op in c.rendimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:30} | {op.activo:6} | {op.cantidad:.6f}")

    print("\n── MOVIMIENTOS ──")
    for op in c.movimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:15} | {op.activo:6} | {op.cantidad:.4f}")

    print("\n── DESCONOCIDAS ──")
    if c.desconocidas:
        for op in c.desconocidas:
            print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | {op.cantidad:.6f}")
    else:
        print("  Ninguna ✓")
