"""
Clasificador fiscal de operaciones Crypto.com App
Mariano Sevilla — marianosevilla.com
v1.1

Formato CSV: crypto_transactions_record_*.csv
Columnas: Timestamp (UTC), Transaction Description, Currency, Amount,
          To Currency, To Amount, Native Currency, Native Amount,
          Native Amount (in USD), Transaction Kind, Transaction Hash

Tipos de transacción:
- crypto_purchase / trading.crypto_purchase.google_pay → COMPRA directa
- viban_purchase / trading.limit_order.*purchase_commit → COMPRA vía IBAN/limit order
- crypto_viban_exchange        → VENTA
- crypto_earn_program_created / finance.dpos.staking.*   → MOVIMIENTO
- crypto_earn_program_withdrawn / finance.dpos.unstaking.* → MOVIMIENTO
- trading.limit_order.*.purchase_lock / crypto_withdrawal  → MOVIMIENTO
- crypto_earn_interest_paid / finance.dpos.*interest.*    → RENDIMIENTO
- rewards_platform_deposit_credited / campaign_reward     → RENDIMIENTO
- reward.*                    → RENDIMIENTO (rebates)
- crypto_wallet_swap_* / dust_conversion_* → SWAP (par debit+credit)
"""

import pandas as pd
from dataclasses import dataclass


STABLES = {"EUR", "USD", "USDC", "USDT", "BUSD", "DAI", "FDUSD"}

TIPOS_COMPRA_DIRECTA = {"crypto_purchase", "trading.crypto_purchase.google_pay"}
TIPOS_COMPRA_IBAN    = {"viban_purchase", "trading.limit_order.cash_account.purchase_commit"}
TIPOS_VENTA          = {"crypto_viban_exchange"}
TIPOS_EARN_LOCK      = {
    "crypto_earn_program_created",
    "finance.dpos.staking.crypto_wallet",
}
TIPOS_EARN_UNLOCK    = {
    "crypto_earn_program_withdrawn",
    "finance.dpos.unstaking.crypto_wallet",
}
TIPOS_EARN_INTERES   = {
    "crypto_earn_interest_paid",
    "finance.dpos.non_compound_interest.crypto_wallet",
}
TIPOS_RENDIMIENTO    = {"rewards_platform_deposit_credited", "campaign_reward"}
TIPOS_MOVIMIENTO     = {
    "trading.limit_order.cash_account.purchase_lock",
    "crypto_withdrawal",
}
TIPOS_SWAP_DEBIT     = {"crypto_wallet_swap_debited", "dust_conversion_debited"}
TIPOS_SWAP_CREDIT    = {"crypto_wallet_swap_credited", "dust_conversion_credited"}


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
        self.compraventas = []
        self.swaps        = []
        self.rendimientos = []
        self.movimientos  = []
        self.desconocidas = []
        self.advertencias = []

    def clasificar(self):
        self.df.columns = [c.strip() for c in self.df.columns]
        self.df["Timestamp (UTC)"] = pd.to_datetime(self.df["Timestamp (UTC)"])
        self.df = self.df.sort_values("Timestamp (UTC)").reset_index(drop=True)

        procesadas = self._procesar_swaps()

        for idx, fila in self.df.iterrows():
            if idx in procesadas:
                continue

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

            elif kind in TIPOS_RENDIMIENTO:
                self._procesar_rebate(fecha, moneda, amount, native_moneda, native_amount)

            elif kind in TIPOS_MOVIMIENTO:
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=kind,
                    activo=moneda, cantidad=amount,
                    observacion=""
                ))

            elif kind.startswith("reward."):
                self._procesar_rebate(fecha, moneda, amount, native_moneda, native_amount)

            elif kind and kind not in ("nan", ""):
                self._registrar_desconocida(fecha, kind, moneda, amount)

        return self

    # ── SWAPS ─────────────────────────────────

    def _procesar_swaps(self):
        """
        Empareja filas debited+credited de swap/dust_conversion por timestamp exacto.
        Devuelve el conjunto de índices procesados.
        """
        procesadas = set()
        mask_debit  = self.df["Transaction Kind"].isin(TIPOS_SWAP_DEBIT)
        mask_credit = self.df["Transaction Kind"].isin(TIPOS_SWAP_CREDIT)

        debits  = self.df[mask_debit].copy()
        credits = self.df[mask_credit].copy()

        for ts, grupo_credit in credits.groupby("Timestamp (UTC)"):
            grupo_debit = debits[debits["Timestamp (UTC)"] == ts]
            if grupo_debit.empty:
                continue

            recibido       = grupo_credit.iloc[0]
            cant_recibida  = self._float(recibido["Amount"])
            activo_recibido = str(recibido["Currency"]).strip()

            for _, debit in grupo_debit.iterrows():
                cant_entregada = abs(self._float(debit["Amount"]))
                activo_entregado = str(debit["Currency"]).strip()
                self.swaps.append(OperacionSwap(
                    fecha=str(ts),
                    activo_entregado=activo_entregado,
                    cantidad_entregada=cant_entregada,
                    activo_recibido=activo_recibido,
                    cantidad_recibida=cant_recibida,
                ))
                procesadas.add(debit.name)

            procesadas.update(grupo_credit.index.tolist())

        return procesadas

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
