"""
Clasificador fiscal de operaciones Crypto.com App
Mariano Sevilla — marianosevilla.com
v1.0

Formato CSV: crypto_transactions_record_*.csv
Columnas: Timestamp (UTC), Transaction Description, Currency, Amount,
          To Currency, To Amount, Native Currency, Native Amount,
          Native Amount (in USD), Transaction Kind, Transaction Hash

Tipos de transacción:
- crypto_purchase              → COMPRA directa (Currency=coin, NativeAmount=EUR)
- viban_purchase               → COMPRA vía IBAN (ToCurrency=coin, ToAmount=qty)
- crypto_viban_exchange        → VENTA (Currency=coin, Amount<0, NativeAmount=EUR recibido)
- crypto_earn_program_created  → MOVIMIENTO (coins bloqueadas en Earn)
- crypto_earn_program_withdrawn→ MOVIMIENTO (coins devueltas de Earn)
- crypto_earn_interest_paid    → RENDIMIENTO + COMPRA a precio de mercado
- reward.loyalty_program.*     → RENDIMIENTO (rebates en CRO)
"""

import pandas as pd
from dataclasses import dataclass


STABLES = {"EUR", "USD", "USDC", "USDT", "BUSD", "DAI", "FDUSD"}

TIPOS_COMPRA_DIRECTA = {"crypto_purchase"}
TIPOS_COMPRA_IBAN    = {"viban_purchase"}
TIPOS_VENTA          = {"crypto_viban_exchange"}
TIPOS_EARN_LOCK      = {"crypto_earn_program_created"}
TIPOS_EARN_UNLOCK    = {"crypto_earn_program_withdrawn"}
TIPOS_EARN_INTERES   = {"crypto_earn_interest_paid"}


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

class ClasificadorCryptoCom:

    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath)
        self.compraventas: list[OperacionCompraventa] = []
        self.swaps:        list                       = []
        self.rendimientos: list[OperacionRendimiento] = []
        self.movimientos:  list[OperacionMovimiento]  = []
        self.desconocidas: list[OperacionDesconocida] = []
        self.advertencias: list[str] = []

    def clasificar(self):
        self.df.columns = [c.strip() for c in self.df.columns]
        self.df["Timestamp (UTC)"] = pd.to_datetime(self.df["Timestamp (UTC)"])
        self.df = self.df.sort_values("Timestamp (UTC)").reset_index(drop=True)

        for _, fila in self.df.iterrows():
            kind          = str(fila.get("Transaction Kind", "")).strip()
            fecha         = str(fila["Timestamp (UTC)"])
            moneda        = str(fila.get("Currency", "")).strip()
            amount        = self._float(fila.get("Amount", 0))
            to_moneda     = str(fila.get("To Currency", "")).strip()
            to_amount     = self._float(fila.get("To Amount", 0))
            native_moneda = str(fila.get("Native Currency", "")).strip()
            native_amount = self._float(fila.get("Native Amount", 0))

            if kind in TIPOS_COMPRA_DIRECTA:
                self._procesar_compra_directa(fecha, moneda, amount, native_moneda, native_amount, kind, fila)

            elif kind in TIPOS_COMPRA_IBAN:
                self._procesar_compra_iban(fecha, moneda, amount, to_moneda, to_amount, native_moneda, native_amount, kind, fila)

            elif kind in TIPOS_VENTA:
                self._procesar_venta(fecha, moneda, amount, native_moneda, native_amount, kind, fila)

            elif kind in TIPOS_EARN_LOCK:
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo="earn_allocation",
                    activo=moneda, cantidad=amount,
                    observacion="Bloqueado en Crypto Earn"
                ))

            elif kind in TIPOS_EARN_UNLOCK:
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo="earn_withdrawal",
                    activo=moneda, cantidad=amount,
                    observacion="Retirado de Crypto Earn"
                ))

            elif kind in TIPOS_EARN_INTERES:
                self._procesar_earn_interes(fecha, moneda, amount, native_moneda, native_amount, kind, fila)

            elif kind.startswith("reward."):
                self._procesar_rebate(fecha, moneda, amount, native_moneda, native_amount)

            elif kind and kind not in ("nan", ""):
                self._registrar_desconocida(fecha, kind, moneda, amount)

        return self

    # ── COMPRAS ───────────────────────────────

    def _procesar_compra_directa(self, fecha, moneda, amount, native_moneda, native_amount, kind, fila):
        """crypto_purchase: Currency=coin, Amount=qty, NativeAmount=EUR gastado."""
        if moneda in STABLES or amount <= 0 or native_moneda != "EUR":
            self._registrar_desconocida(fecha, kind, moneda, amount)
            return
        self.compraventas.append(OperacionCompraventa(
            fecha=fecha, tipo="COMPRA",
            activo=moneda, cantidad=amount,
            contraparte="EUR", importe=native_amount,
            fee_activo="EUR", fee_cantidad=0.0
        ))

    def _procesar_compra_iban(self, fecha, moneda, amount, to_moneda, to_amount, native_moneda, native_amount, kind, fila):
        """viban_purchase: Currency=EUR (Amount<0), ToCurrency=coin, ToAmount=qty."""
        if not to_moneda or to_moneda in STABLES or to_amount <= 0:
            self._registrar_desconocida(fecha, kind, moneda, amount)
            return
        eur_gastado = abs(amount) if moneda == "EUR" else abs(native_amount)
        self.compraventas.append(OperacionCompraventa(
            fecha=fecha, tipo="COMPRA",
            activo=to_moneda, cantidad=to_amount,
            contraparte="EUR", importe=eur_gastado,
            fee_activo="EUR", fee_cantidad=0.0
        ))

    # ── VENTAS ────────────────────────────────

    def _procesar_venta(self, fecha, moneda, amount, native_moneda, native_amount, kind, fila):
        """crypto_viban_exchange: Currency=coin, Amount<0 (qty vendida), NativeAmount=EUR recibido."""
        if moneda in STABLES or amount >= 0 or native_moneda != "EUR":
            self._registrar_desconocida(fecha, kind, moneda, amount)
            return
        self.compraventas.append(OperacionCompraventa(
            fecha=fecha, tipo="VENTA",
            activo=moneda, cantidad=abs(amount),
            contraparte="EUR", importe=native_amount,
            fee_activo="EUR", fee_cantidad=0.0
        ))

    # ── EARN INTERÉS ──────────────────────────

    def _procesar_earn_interes(self, fecha, moneda, amount, native_moneda, native_amount, kind, fila):
        """
        Interés de Crypto Earn: rendimiento del capital mobiliario.
        Los coins recibidos entran al inventario FIFO con coste = valor de mercado.
        """
        if amount <= 0:
            self._registrar_desconocida(fecha, kind, moneda, amount)
            return

        valor_eur = native_amount if native_moneda == "EUR" else 0.0

        self.rendimientos.append(OperacionRendimiento(
            fecha=fecha, subtipo="earn_interest",
            activo=moneda, cantidad=amount,
            cuenta="Crypto.com Earn",
            valor_eur=valor_eur
        ))
        # Entra en FIFO con coste base = valor de mercado en el momento del cobro
        self.compraventas.append(OperacionCompraventa(
            fecha=fecha, tipo="COMPRA",
            activo=moneda, cantidad=amount,
            contraparte="EUR", importe=valor_eur,
            fee_activo="EUR", fee_cantidad=0.0
        ))

    # ── REBATES ───────────────────────────────

    def _procesar_rebate(self, fecha, moneda, amount, native_moneda, native_amount):
        """Rebates en CRO. NativeCurrency suele ser USD — se registra como rendimiento sin valor EUR."""
        valor_eur = native_amount if native_moneda == "EUR" else 0.0
        if native_moneda != "EUR":
            self.advertencias.append(
                f"{fecha[:10]} | REBATE {moneda} — importe en {native_moneda}, sin conversión EUR. "
                "Rendimiento declarado sin valor monetario. Consigna manualmente el contravalor en EUR."
            )
        self.rendimientos.append(OperacionRendimiento(
            fecha=fecha, subtipo="trading_rebate",
            activo=moneda, cantidad=amount,
            cuenta="Crypto.com",
            valor_eur=valor_eur
        ))

    # ── UTILIDADES ────────────────────────────

    def _registrar_desconocida(self, fecha, kind, moneda, amount):
        self.desconocidas.append(OperacionDesconocida(
            fecha=fecha, subtipo=kind,
            activo=moneda, cantidad=amount,
            cuenta="Crypto.com"
        ))

    @staticmethod
    def _float(val) -> float:
        try:
            v = float(val)
            return v if v == v else 0.0  # NaN != NaN → devuelve 0.0
        except Exception:
            return 0.0

    def resumen(self) -> dict:
        compras = sum(1 for op in self.compraventas if op.tipo == "COMPRA")
        ventas  = sum(1 for op in self.compraventas if op.tipo == "VENTA")
        return {
            "total_filas_csv": len(self.df),
            "compras":         compras,
            "ventas":          ventas,
            "rendimientos":    len(self.rendimientos),
            "movimientos":     len(self.movimientos),
            "desconocidas":    len(self.desconocidas),
            "advertencias":    len(self.advertencias),
        }


# ── EJECUCIÓN DIRECTA ─────────────────────────

if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "crypto_transactions.csv"
    print(f"\nProcesando: {ruta}\n")

    c = ClasificadorCryptoCom(ruta).clasificar()
    r = c.resumen()

    print("=" * 55)
    print("RESUMEN DE CLASIFICACIÓN — CRYPTO.COM")
    print("=" * 55)
    for k, v in r.items():
        print(f"  {k:<25} {v:>6}")

    print("\n── COMPRAVENTAS ──")
    for op in c.compraventas[:15]:
        print(f"  {op.fecha[:10]} | {op.tipo:6} | {op.activo:8} | {op.cantidad:.6f} | {op.importe:.4f} {op.contraparte}")

    print("\n── RENDIMIENTOS ──")
    for op in c.rendimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | {op.cantidad:.8f} | {op.valor_eur:.6f} EUR")

    print("\n── MOVIMIENTOS ──")
    for op in c.movimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | {op.cantidad:.4f}")

    if c.advertencias:
        print("\n── ADVERTENCIAS ──")
        for adv in c.advertencias:
            print(f"  ⚠ {adv}")

    print("\n── DESCONOCIDAS ──")
    if c.desconocidas:
        for op in c.desconocidas:
            print(f"  {op.fecha[:10]} | {op.subtipo:45} | {op.activo:6} | {op.cantidad:.6f}")
    else:
        print("  Ninguna ✓")
