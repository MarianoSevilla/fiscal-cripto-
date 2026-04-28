"""
Clasificador fiscal de operaciones Kraken
Mariano Sevilla — marianosevilla.com
v1.0

Formato CSV de Kraken (Ledgers):
- Columnas: txid, refid, time, type, subtype, aclass, subclass, asset, wallet, amount, fee, balance
- spend + receive agrupados por refid = compra/venta/swap
- fee incluido en la fila spend
"""

import pandas as pd
from dataclasses import dataclass


# ── CONSTANTES ────────────────────────────────

STABLES = {"EUR", "USD", "USDC", "USDT", "BUSD", "DAI", "FDUSD", "USDG"}

TIPOS_RENDIMIENTO = {"earn/reward", "reward/welcomebonus", "earn/bonus"}
TIPOS_MOVIMIENTO  = {
    "deposit", "withdrawal", "transfer",
    "earn/autoallocation", "earn/allocation", "earn/deallocation",
}


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

class ClasificadorKraken:

    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath)
        self.compraventas:  list[OperacionCompraventa] = []
        self.swaps:         list[OperacionSwap]        = []
        self.rendimientos:  list[OperacionRendimiento] = []
        self.movimientos:   list[OperacionMovimiento]  = []
        self.desconocidas:  list[OperacionDesconocida] = []
        self._procesadas:   set = set()

    def clasificar(self):
        self.df.columns = [c.strip() for c in self.df.columns]
        self.df["time"] = pd.to_datetime(self.df["time"])
        self.df = self.df.sort_values("time").reset_index(drop=True)

        self._procesar_trades()
        self._procesar_resto()
        return self

    # ── COMPRAVENTAS Y SWAPS ──────────────────

    def _procesar_trades(self):
        """Agrupa spend+receive por refid para identificar compras/ventas/swaps."""
        mask  = self.df["type"].isin(["spend", "receive"])
        filas = self.df[mask].copy()

        if filas.empty:
            return

        self._procesadas.update(filas.index.tolist())
        grupos = filas.groupby("refid")

        for refid, grupo in grupos:
            spend   = grupo[grupo["type"] == "spend"]
            receive = grupo[grupo["type"] == "receive"]

            if spend.empty or receive.empty:
                for idx, fila in grupo.iterrows():
                    self.desconocidas.append(OperacionDesconocida(
                        fecha=str(fila["time"]), subtipo=fila["type"],
                        activo=fila["asset"], cantidad=float(fila["amount"]), cuenta="Kraken"
                    ))
                continue

            fecha        = str(spend.iloc[0]["time"])
            asset_spent  = spend.iloc[0]["asset"]
            amount_spent = abs(float(spend.iloc[0]["amount"]))
            fee_asset    = asset_spent
            fee_amount   = abs(float(spend.iloc[0]["fee"]))

            asset_recv  = receive.iloc[0]["asset"]
            amount_recv = abs(float(receive.iloc[0]["amount"]))

            spent_fiat = asset_spent in STABLES
            recv_fiat  = asset_recv  in STABLES

            if spent_fiat and not recv_fiat:
                # Fiat → crypto: COMPRA
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="COMPRA",
                    activo=asset_recv, cantidad=amount_recv,
                    contraparte=asset_spent, importe=amount_spent,
                    fee_activo=fee_asset, fee_cantidad=fee_amount
                ))
            elif not spent_fiat and recv_fiat:
                # Crypto → fiat: VENTA
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="VENTA",
                    activo=asset_spent, cantidad=amount_spent,
                    contraparte=asset_recv, importe=amount_recv,
                    fee_activo=fee_asset, fee_cantidad=fee_amount
                ))
            elif not spent_fiat and not recv_fiat:
                # Crypto → crypto: SWAP
                self.swaps.append(OperacionSwap(
                    fecha=fecha,
                    activo_entregado=asset_spent, cantidad_entregada=amount_spent,
                    activo_recibido=asset_recv,   cantidad_recibida=amount_recv
                ))
            else:
                # Fiat → fiat: movimiento
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo="fiat_exchange",
                    activo=asset_recv, cantidad=amount_recv,
                    observacion=f"{asset_spent} → {asset_recv}"
                ))

    # ── RENDIMIENTOS, MOVIMIENTOS Y RESTO ─────

    def _procesar_resto(self):
        for idx, fila in self.df.iterrows():
            if idx in self._procesadas:
                continue

            tipo    = str(fila.get("type", "")).strip()
            subtipo = str(fila.get("subtype", "")).strip()
            clave   = f"{tipo}/{subtipo}" if subtipo and subtipo not in ("", "nan") else tipo
            activo  = str(fila.get("asset", "")).strip()
            cantidad = self._float(fila.get("amount", 0))
            fee      = self._float(fila.get("fee", 0))
            fecha    = str(fila.get("time", ""))
            wallet   = str(fila.get("wallet", "")).strip()

            if clave in TIPOS_RENDIMIENTO:
                cantidad_neta = abs(cantidad) - abs(fee)
                self.rendimientos.append(OperacionRendimiento(
                    fecha=fecha, subtipo=clave,
                    activo=activo, cantidad=round(cantidad_neta, 10),
                    cuenta=wallet
                ))
            elif clave in TIPOS_MOVIMIENTO:
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=clave,
                    activo=activo, cantidad=cantidad,
                    observacion=wallet
                ))
            else:
                if tipo and tipo not in ("nan", ""):
                    self.desconocidas.append(OperacionDesconocida(
                        fecha=fecha, subtipo=clave,
                        activo=activo, cantidad=cantidad,
                        cuenta=wallet
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
    ruta = sys.argv[1] if len(sys.argv) > 1 else "kraken.csv"
    print(f"\nProcesando: {ruta}\n")

    c = ClasificadorKraken(ruta).clasificar()
    r = c.resumen()

    print("=" * 50)
    print("RESUMEN DE CLASIFICACIÓN — KRAKEN")
    print("=" * 50)
    for k, v in r.items():
        print(f"  {k:<25} {v:>6}")

    print("\n── COMPRAVENTAS ──")
    for op in c.compraventas[:10]:
        print(f"  {op.fecha[:10]} | {op.tipo:6} | {op.activo:8} | {op.cantidad:.6f} | {op.importe:.4f} {op.contraparte} | fee: {op.fee_cantidad:.4f} {op.fee_activo}")

    print("\n── RENDIMIENTOS ──")
    for op in c.rendimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:30} | {op.activo:6} | {op.cantidad:.8f}")

    print("\n── MOVIMIENTOS ──")
    for op in c.movimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:25} | {op.activo:6} | {op.cantidad:.4f}")

    print("\n── DESCONOCIDAS ──")
    if c.desconocidas:
        for op in c.desconocidas:
            print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | {op.cantidad:.6f}")
    else:
        print("  Ninguna ✓")
