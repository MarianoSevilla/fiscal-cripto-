"""
Clasificador fiscal de operaciones Nexo
Mariano Sevilla — marianosevilla.com
v1.0

Formato CSV de Nexo (Transaction History):
- Sin filas de metadatos: cabecera en la primera fila
- Columnas: Transaction, Type, Input Currency, Input Amount, Output Currency,
  Output Amount, USD Equivalent, Fee, Fee Currency, Details, Date / Time (UTC)
- Input Amount negativo = activo entregado
- Output Amount siempre positivo = activo recibido
- USD Equivalent: valor USD de la operación (formato "$1234.56")
- Fee: "-" si no hay comisión
- EURX = stablecoin EUR de Nexo (1:1 con EUR)
- USDX = stablecoin USD de Nexo
"""

import pandas as pd
from dataclasses import dataclass


# ── CONSTANTES ────────────────────────────────

STABLES_EUR = {"EUR", "EURX"}
STABLES_USD = {"USD", "USDC", "USDT", "USDX"}
STABLES     = STABLES_EUR | STABLES_USD

TIPOS_RENDIMIENTO = {"Interest", "Fixed Term Interest", "Exchange Cashback"}

# Movimientos internos de Nexo (no son eventos fiscales)
TIPOS_MOVIMIENTO_INTERNO = {
    "Locking Term Deposit",
    "Unlocking Term Deposit",
    "Deposit To Exchange",     # EUR/USD → EURX/USDX interno
    "Exchange Deposited On",   # contrapartida del anterior
}

TIPOS_MOVIMIENTO = {"Withdrawal"}

# Firma de detección en las primeras líneas del CSV
NEXO_SIGNATURES = ["Transaction", "Type", "Input Currency", "Output Currency"]


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

class ClasificadorNexo:

    def __init__(self, filepath: str):
        # Sin filas de metadatos: cabecera en la primera fila
        self.df = pd.read_csv(filepath)
        self.compraventas:  list[OperacionCompraventa] = []
        self.swaps:         list[OperacionSwap]        = []
        self.rendimientos:  list[OperacionRendimiento] = []
        self.movimientos:   list[OperacionMovimiento]  = []
        self.desconocidas:  list[OperacionDesconocida] = []
        self.advertencias:  list[str]                  = []

    def clasificar(self):
        self.df.columns = [c.strip() for c in self.df.columns]

        # Normalizar timestamp
        self.df["Date / Time (UTC)"] = pd.to_datetime(
            self.df["Date / Time (UTC)"], utc=True, errors="coerce"
        )
        self.df = self.df.sort_values("Date / Time (UTC)").reset_index(drop=True)

        for _, fila in self.df.iterrows():
            self._clasificar_fila(fila)

        return self

    def _clasificar_fila(self, fila):
        tipo         = str(fila.get("Type", "")).strip()
        input_cur    = str(fila.get("Input Currency", "")).strip()
        output_cur   = str(fila.get("Output Currency", "")).strip()
        input_amt    = self._float(fila.get("Input Amount", 0))   # puede ser negativo
        output_amt   = self._float(fila.get("Output Amount", 0))  # siempre positivo
        usd_equiv    = self._float_usd(fila.get("USD Equivalent", 0))
        fee_amt      = self._float(fila.get("Fee", 0))
        fee_cur      = str(fila.get("Fee Currency", "")).strip()
        detalles     = str(fila.get("Details", "")).strip()
        fecha        = self._fmt_fecha(fila.get("Date / Time (UTC)"))

        # Cantidades absolutas para usar en operaciones
        qty_in  = abs(input_amt)
        qty_out = abs(output_amt)
        fee_qty = abs(fee_amt) if fee_amt and str(fee_amt) not in ("-", "nan") else 0.0
        fee_activo = fee_cur if fee_qty > 0 else ""

        # ── RENDIMIENTOS ──────────────────────────────────────────────────────
        if tipo in TIPOS_RENDIMIENTO:
            # Si el activo es EURX, el valor en EUR = cantidad (1:1)
            if input_cur in STABLES_EUR:
                valor_eur = qty_in
            else:
                # USD Equivalent → aproximación en USD, advertir al usuario
                valor_eur = usd_equiv
                if usd_equiv > 0:
                    self.advertencias.append(
                        f"Rendimiento de {input_cur} el {fecha}: valor almacenado en USD "
                        f"({usd_equiv:.4f} USD). Convierte manualmente a EUR para la declaración."
                    )
            self.rendimientos.append(OperacionRendimiento(
                fecha=fecha, subtipo=tipo,
                activo=input_cur, cantidad=qty_in,
                cuenta="Nexo",
                valor_eur=round(valor_eur, 6),
            ))

        # ── MOVIMIENTOS INTERNOS ──────────────────────────────────────────────
        elif tipo in TIPOS_MOVIMIENTO_INTERNO:
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo=tipo,
                activo=input_cur, cantidad=qty_in,
                observacion=detalles,
            ))

        # ── RETIROS ───────────────────────────────────────────────────────────
        elif tipo in TIPOS_MOVIMIENTO:
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo=tipo,
                activo=input_cur, cantidad=qty_in,
                observacion=detalles,
            ))

        # ── EXCHANGE ──────────────────────────────────────────────────────────
        elif tipo == "Exchange":
            in_stable  = input_cur  in STABLES
            out_stable = output_cur in STABLES

            if in_stable and out_stable:
                # Stablecoin ↔ stablecoin (p.ej. EURX → USDC): movimiento
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo="Exchange (stables)",
                    activo=input_cur, cantidad=qty_in,
                    observacion=detalles,
                ))

            elif in_stable and not out_stable:
                # COMPRA: pagamos stable, recibimos cripto
                importe, moneda_importe = self._importe_eur(input_cur, qty_in, usd_equiv, fecha)
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="COMPRA",
                    activo=output_cur, cantidad=qty_out,
                    contraparte=moneda_importe, importe=importe,
                    fee_activo=fee_activo, fee_cantidad=fee_qty,
                ))

            elif not in_stable and out_stable:
                # VENTA: entregamos cripto, recibimos stable
                importe, moneda_importe = self._importe_eur(output_cur, qty_out, usd_equiv, fecha)
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="VENTA",
                    activo=input_cur, cantidad=qty_in,
                    contraparte=moneda_importe, importe=importe,
                    fee_activo=fee_activo, fee_cantidad=fee_qty,
                ))

            else:
                # SWAP: ambos son cripto no-stable
                # FMV del activo entregado en EUR (usando USD Equivalent como aproximación)
                fmv_eur = usd_equiv
                if usd_equiv > 0:
                    self.advertencias.append(
                        f"Swap {input_cur}→{output_cur} el {fecha}: FMV almacenado en USD "
                        f"({usd_equiv:.4f} USD). Convierte manualmente a EUR para la declaración."
                    )
                self.swaps.append(OperacionSwap(
                    fecha=fecha,
                    activo_entregado=input_cur,
                    cantidad_entregada=qty_in,
                    activo_recibido=output_cur,
                    cantidad_recibida=qty_out,
                    nota=detalles,
                    precio_fmv_eur=round(fmv_eur, 6),
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
                    activo=input_cur, cantidad=qty_in, cuenta="Nexo",
                ))

    def _importe_eur(self, moneda: str, cantidad: float,
                     usd_equiv: float, fecha: str) -> tuple[float, str]:
        """
        Devuelve (importe, moneda_contraparte).
        Si la moneda es EUR/EURX → importe directo en EUR.
        Si es USD/USDC/USDT/USDX → usa el USD Equivalent y advierte al usuario.
        """
        if moneda in STABLES_EUR:
            return round(cantidad, 6), "EUR"
        else:
            # USD-denominated: almacenamos USD Equivalent y avisamos
            self.advertencias.append(
                f"Compraventa en {moneda} el {fecha}: importe almacenado en USD "
                f"({usd_equiv:.4f} USD). Convierte manualmente a EUR para la declaración."
            )
            return round(usd_equiv, 6), "USD"

    @staticmethod
    def _float_usd(val) -> float:
        """Parsea valores USD del tipo '$1234.56'."""
        try:
            s = str(val).strip().replace("$", "").replace(",", "").strip()
            return float(s) if s and s.lower() not in ("", "nan", "-") else 0.0
        except Exception:
            return 0.0

    @staticmethod
    def _float(val) -> float:
        try:
            s = str(val).strip().replace("-", "") if str(val).strip() == "-" else str(val).strip()
            return float(s)
        except Exception:
            return 0.0

    @staticmethod
    def _fmt_fecha(ts) -> str:
        """Convierte timestamp pandas a string YYYY-MM-DD HH:MM:SS (sin timezone)."""
        try:
            if pd.isna(ts):
                return ""
            if hasattr(ts, 'tz_convert'):
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
    ruta = sys.argv[1] if len(sys.argv) > 1 else "nexo_transactions.csv"
    print(f"\nProcesando: {ruta}\n")

    c = ClasificadorNexo(ruta).clasificar()
    r = c.resumen()

    print("=" * 50)
    print("RESUMEN DE CLASIFICACIÓN — NEXO")
    print("=" * 50)
    for k, v in r.items():
        print(f"  {k:<25} {v:>6}")

    print("\n── COMPRAVENTAS (primeras 10) ──")
    for op in c.compraventas[:10]:
        print(f"  {op.fecha[:10]} | {op.tipo:6} | {op.activo:8} | "
              f"{op.cantidad:.6f} | {op.importe:.4f} {op.contraparte} | "
              f"fee: {op.fee_cantidad:.4f} {op.fee_activo}")

    print("\n── SWAPS (primeros 10) ──")
    for op in c.swaps[:10]:
        print(f"  {op.fecha[:10]} | {op.activo_entregado:6} → {op.activo_recibido:6} | "
              f"{op.cantidad_entregada:.6f} → {op.cantidad_recibida:.6f} | "
              f"FMV: {op.precio_fmv_eur:.4f} USD")

    print("\n── RENDIMIENTOS (primeros 10) ──")
    for op in c.rendimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:25} | {op.activo:6} | "
              f"{op.cantidad:.8f} | valor: {op.valor_eur:.4f}")

    print("\n── MOVIMIENTOS (primeros 10) ──")
    for op in c.movimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:30} | {op.activo:6} | {op.cantidad:.4f}")

    print(f"\n── ADVERTENCIAS ({len(c.advertencias)}) ──")
    if c.advertencias:
        for adv in c.advertencias[:10]:
            print(f"  ⚠  {adv}")
        if len(c.advertencias) > 10:
            print(f"  ... y {len(c.advertencias) - 10} más")
    else:
        print("  Ninguna ✓")

    print("\n── DESCONOCIDAS ──")
    if c.desconocidas:
        for op in c.desconocidas:
            print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | {op.cantidad:.6f}")
    else:
        print("  Ninguna ✓")
