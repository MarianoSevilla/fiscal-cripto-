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

import logging
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)

# Columnas obligatorias para construir un timestamp y clasificar operaciones.
_COLS_OBLIGATORIAS = ["Date", "Time", "Type", "Currency", "Amount"]

# Aliases de nombres de columna: clave = nombre canónico, valor = variantes aceptadas.
# El orden dentro de cada lista refleja la preferencia (más específico primero).
_COL_ALIASES: Dict[str, List[str]] = {
    "Date":                     ["Date", "date", "DATE", "Trade Date", "Transaction Date"],
    "Time":                     ["Time", "time", "TIME"],
    "Type":                     ["Type", "type", "TYPE", "Transaction Type"],
    "Currency":                 ["Currency", "currency", "Asset", "Base Currency"],
    "Amount":                   ["Amount", "amount", "Quantity"],
    "Quote Currency":           ["Quote Currency", "Quote currency", "quote_currency"],
    "Quote Price":              ["Quote Price", "Quote price", "Unit Price", "Price"],
    "Received / Paid Currency": ["Received / Paid Currency", "Received/Paid Currency",
                                  "received_paid_currency", "Counter Currency"],
    "Received / Paid Amount":   ["Received / Paid Amount", "Received/Paid Amount",
                                  "received_paid_amount", "Counter Amount"],
    "Fee currency":             ["Fee currency", "Fee Currency", "fee_currency"],
    "Fee amount":               ["Fee amount", "Fee Amount", "fee_amount"],
    "Status":                   ["Status", "status", "STATUS"],
    "Address":                  ["Address", "address", "Wallet Address"],
}


def _normalizar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Renombra columnas del CSV Bitvavo a los nombres canónicos usando _COL_ALIASES.
    Solo renombra lo que existe — columnas sin alias reconocido se dejan tal cual.
    """
    col_map: Dict[str, str] = {}
    df_cols = set(df.columns)
    for canonical, aliases in _COL_ALIASES.items():
        if canonical in df_cols:
            continue  # ya está en forma canónica
        for alias in aliases:
            if alias in df_cols:
                col_map[alias] = canonical
                break
    if col_map:
        logger.debug("Bitvavo: renombrando columnas: %s", col_map)
    return df.rename(columns=col_map)


def _validar_columnas(df: pd.DataFrame) -> None:
    """
    Verifica que las columnas obligatorias estén presentes después de normalizar.
    Lanza ValueError con mensaje orientativo si falta alguna.
    """
    missing = [c for c in _COLS_OBLIGATORIAS if c not in df.columns]
    if missing:
        raise ValueError(
            f"CSV Bitvavo: columnas obligatorias no encontradas tras normalización: {missing}. "
            f"Columnas detectadas en el fichero: {list(df.columns)}. "
            f"Verifica que el fichero sea el export de 'Transaction History' de Bitvavo "
            f"y no otro tipo de descarga (p.ej. estados de cuenta o facturas)."
        )


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

class ClasificadorBitvavo:

    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath)
        self.compraventas:  list[OperacionCompraventa] = []
        self.swaps:         list[OperacionSwap]        = []
        self.rendimientos:  list[OperacionRendimiento] = []
        self.movimientos:   list[OperacionMovimiento]  = []
        self.desconocidas:  list[OperacionDesconocida] = []

    def clasificar(self):
        # Normalizar espacios y aplicar aliases de nombre de columna
        self.df.columns = [c.strip() for c in self.df.columns]
        self.df = _normalizar_columnas(self.df)
        _validar_columnas(self.df)

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
        fecha    = str(fila.get("fecha", ""))
        fee_mon  = str(fila.get("Fee currency", "")).strip()
        fee_cant = self._float(fila.get("Fee amount", 0))

        # Received/Paid
        rec_mon   = str(fila.get("Received / Paid Currency", "")).strip()
        rec_cant  = self._float(fila.get("Received / Paid Amount", 0))

        # Quote Price (EUR por unidad de cripto — separador decimal inglés estándar)
        quote_price = self._float(fila.get("Quote Price", 0))
        import math
        if math.isnan(quote_price):
            quote_price = 0.0

        # El campo Amount usa puntos como separador de miles con escala variable
        # por moneda → derivamos la cantidad desde |Received/Paid| / Quote Price
        # cuando sea posible (buy/sell con precio conocido).
        # Para rendimientos/staking usamos Amount directamente (ya tiene escala legible).
        raw_amount = self._float(fila.get("Amount", 0))

        def _cantidad_desde_precio(importe_eur: float, price: float) -> float:
            """Calcula unidades desde EUR pagados/recibidos y precio unitario."""
            if price and price > 0:
                return round(importe_eur / price, 10)
            return abs(raw_amount)  # fallback si no hay precio

        # El fee en EUR es fiable solo si la cifra es razonable
        def _fee_eur(fee_val: float, importe_ref: float) -> float:
            if fee_mon and fee_mon not in ("nan", "EUR", ""):
                return 0.0   # fee en cripto → ignoramos (coste ya incluido en rec_cant)
            # Si el fee parseado supera el importe de referencia está en unidades base
            if fee_val > importe_ref * 2:
                return 0.0
            return fee_val

        if tipo == "buy":
            # Compra: Received/Paid = EUR pagados (negativo)
            activo        = moneda
            importe       = abs(rec_cant)
            cant_comprada = _cantidad_desde_precio(importe, quote_price)
            contraparte   = rec_mon if rec_mon and rec_mon != "nan" else "EUR"

            if activo in STABLES:
                # Compra de stable con EUR → movimiento, no hecho imponible
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo="buy_stable",
                    activo=activo, cantidad=cant_comprada,
                    observacion=f"Compra de {activo} con {contraparte}"
                ))
            else:
                fee_eur = _fee_eur(abs(fee_cant), importe)
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="COMPRA",
                    activo=activo, cantidad=cant_comprada,
                    contraparte=contraparte, importe=importe,
                    fee_activo="EUR",
                    fee_cantidad=fee_eur,
                ))

        elif tipo == "sell":
            # Venta: Received/Paid = EUR recibidos (+)
            activo       = moneda
            importe      = abs(rec_cant)
            cant_vendida = _cantidad_desde_precio(importe, quote_price)
            contraparte  = rec_mon if rec_mon and rec_mon != "nan" else "EUR"

            if activo in STABLES:
                # Venta de stable → movimiento
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo="sell_stable",
                    activo=activo, cantidad=cant_vendida,
                    observacion=f"Venta de {activo} por {contraparte}"
                ))
            else:
                fee_eur = _fee_eur(abs(fee_cant), importe)
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="VENTA",
                    activo=activo, cantidad=cant_vendida,
                    contraparte=contraparte, importe=importe,
                    fee_activo="EUR",
                    fee_cantidad=fee_eur,
                ))

        elif tipo in TIPOS_RENDIMIENTO:
            activo       = moneda
            cantidad_abs = abs(raw_amount)
            valor_eur    = round(cantidad_abs * quote_price, 4) if quote_price else 0.0
            self.rendimientos.append(OperacionRendimiento(
                fecha=fecha, subtipo=tipo,
                activo=activo, cantidad=cantidad_abs,
                cuenta="Bitvavo", valor_eur=valor_eur
            ))

        elif tipo in TIPOS_MOVIMIENTO:
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo=tipo,
                activo=moneda, cantidad=raw_amount,
                observacion=str(fila.get("Address", ""))
            ))

        else:
            if tipo and tipo != "nan":
                self.desconocidas.append(OperacionDesconocida(
                    fecha=fecha, subtipo=tipo,
                    activo=moneda, cantidad=raw_amount,
                    cuenta="Bitvavo"
                ))

    @staticmethod
    def _float(val) -> float:
        """Parsea un número en formato europeo (punto=miles, coma=decimal).

        Ejemplos de Bitvavo:
          '662.775.631'  → 662775631.0  (puntos como separador de miles)
          '-1018,18'     → -1018.18     (coma como decimal)
          '14.915'       → 14.915       (un solo punto → decimal estándar)
          '2.48'         → 2.48
        """
        try:
            s = str(val).strip()
            if not s or s.lower() in ("nan", "none"):
                return 0.0
            dot_count = s.count(".")
            comma_count = s.count(",")
            if dot_count > 1:
                # Varios puntos → separadores de miles, sin decimal
                s = s.replace(".", "")
            elif dot_count == 1 and comma_count == 1:
                # Punto de miles + coma decimal → '1.234,56'
                s = s.replace(".", "").replace(",", ".")
            elif comma_count >= 1 and dot_count == 0:
                # Solo coma → decimal europeo → '1018,18'
                s = s.replace(",", ".")
            # Si solo hay un punto → decimal estándar inglés: no modificar
            return float(s)
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
