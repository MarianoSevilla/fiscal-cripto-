"""
Clasificador fiscal de operaciones Binance
Mariano Sevilla — marianosevilla.com
v1.1 — maneja swaps multi-fila y timestamps desfasados 1s
"""

import pandas as pd
from dataclasses import dataclass
from datetime import timedelta
from collections import defaultdict


# ──────────────────────────────────────────────
# REGLAS DE CLASIFICACIÓN
# ──────────────────────────────────────────────

STABLES = {"USDC", "USDT", "BUSD", "EUR", "USD", "FDUSD", "DAI"}

REGLAS = {
    "Transaction Buy":    "COMPRAVENTA",
    "Transaction Spend":  "COMPRAVENTA",
    "Transaction Fee":    "COMPRAVENTA",

    "Binance Convert":    "SWAP",

    "Pool Distribution":                "RENDIMIENTO",
    "Simple Earn Flexible Interest":    "RENDIMIENTO",
    "Savings Interest":                 "RENDIMIENTO",
    "Staking Rewards":                  "RENDIMIENTO",
    "Launchpool Interest":              "RENDIMIENTO",
    "Referrer Commission":              "RENDIMIENTO",
    "Commission Rebate":                "RENDIMIENTO",

    "Deposit":            "MOVIMIENTO",
    "Withdraw":           "MOVIMIENTO",
    "Send":               "MOVIMIENTO",
    "Simple Earn Flexible Subscription":            "MOVIMIENTO",
    "Simple Earn Flexible Redemption":              "MOVIMIENTO",
    "Transfer Between Spot Account and UM Futures Account": "MOVIMIENTO",
    "Transfer Between Main and Funding Wallet":             "MOVIMIENTO",

    "Alpha 2.0 - Asset Freeze": "IGNORAR",
    "Alpha 2.0 - Refund":       "IGNORAR",
}


# ──────────────────────────────────────────────
# DATACLASSES
# ──────────────────────────────────────────────

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
    precio_fmv_eur: float = 0.0   # valor de mercado EUR del activo recibido en el momento del swap

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


# ──────────────────────────────────────────────
# CLASIFICADOR
# ──────────────────────────────────────────────

class ClasificadorBinance:

    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath)
        self.df["Tiempo"] = pd.to_datetime(self.df["Tiempo"], format="%y-%m-%d %H:%M:%S")
        self.df = self.df.sort_values("Tiempo").reset_index(drop=True)

        self.compraventas:  list[OperacionCompraventa] = []
        self.swaps:         list[OperacionSwap]        = []
        self.rendimientos:  list[OperacionRendimiento] = []
        self.movimientos:   list[OperacionMovimiento]  = []
        self.desconocidas:  list[OperacionDesconocida] = []
        self._procesadas:   set = set()

    def clasificar(self):
        self._procesar_compraventas()
        # Construir tabla de precios EUR implícitos antes de clasificar swaps
        self._tabla_precios: dict = self._construir_tabla_precios()
        self._procesar_swaps()
        self._procesar_resto()
        return self

    # ── COMPRAVENTAS ──────────────────────────

    def _procesar_compraventas(self):
        mask = self.df["Operación"].isin(["Transaction Buy", "Transaction Spend", "Transaction Fee"])
        filas_cv = self.df[mask]
        grupos = filas_cv.groupby("Tiempo")

        for timestamp, grupo in grupos:
            indices = grupo.index.tolist()
            self._procesadas.update(indices)

            buy   = grupo[grupo["Operación"] == "Transaction Buy"]
            spend = grupo[grupo["Operación"] == "Transaction Spend"]
            fee   = grupo[grupo["Operación"] == "Transaction Fee"]

            if buy.empty or spend.empty:
                for _, fila in grupo.iterrows():
                    self.desconocidas.append(OperacionDesconocida(
                        fecha=str(timestamp), subtipo=fila["Operación"],
                        activo=fila["Moneda"], cantidad=fila["Cambio"], cuenta=fila["Cuenta"]
                    ))
                continue

            activo_comprado   = buy.iloc[0]["Moneda"]
            cantidad_comprada = float(buy.iloc[0]["Cambio"])
            activo_pagado     = spend.iloc[0]["Moneda"]
            importe_pagado    = abs(float(spend.iloc[0]["Cambio"]))
            fee_activo        = fee.iloc[0]["Moneda"] if not fee.empty else activo_comprado
            fee_cantidad      = abs(float(fee.iloc[0]["Cambio"])) if not fee.empty else 0.0

            if activo_comprado in STABLES:
                tipo = "VENTA"
                activo, cantidad = activo_pagado, importe_pagado
                contra, importe  = activo_comprado, cantidad_comprada
            else:
                tipo = "COMPRA"
                activo, cantidad = activo_comprado, cantidad_comprada
                contra, importe  = activo_pagado, importe_pagado

            self.compraventas.append(OperacionCompraventa(
                fecha=str(timestamp), tipo=tipo, activo=activo,
                cantidad=cantidad, contraparte=contra, importe=importe,
                fee_activo=fee_activo, fee_cantidad=fee_cantidad
            ))

    # ── SWAPS ─────────────────────────────────

    def _procesar_swaps(self):
        """
        Agrupa por ventana de 2 segundos para capturar timestamps desfasados.
        Maneja swaps con filas intermedias de transferencia entre cuentas.
        """
        mask = self.df["Operación"] == "Binance Convert"
        filas_swap = self.df[mask].copy()

        if filas_swap.empty:
            return

        # Agrupar con tolerancia de 2 segundos
        filas_swap = filas_swap.sort_values("Tiempo").reset_index()
        grupos = []
        grupo_actual = [filas_swap.iloc[0]]

        for i in range(1, len(filas_swap)):
            diff = (filas_swap.iloc[i]["Tiempo"] - filas_swap.iloc[i-1]["Tiempo"]).total_seconds()
            if diff <= 2:
                grupo_actual.append(filas_swap.iloc[i])
            else:
                grupos.append(grupo_actual)
                grupo_actual = [filas_swap.iloc[i]]
        grupos.append(grupo_actual)

        for grupo_list in grupos:
            grupo = pd.DataFrame(grupo_list)
            indices = grupo["index"].tolist()
            self._procesadas.update(indices)

            fecha = str(grupo.iloc[0]["Tiempo"])

            # Filtrar solo filas de Spot (ignorar movimientos internos entre cuentas)
            spot = grupo[grupo["Cuenta"] == "Spot"]
            if spot.empty:
                spot = grupo  # fallback si no hay cuenta Spot

            entregado = spot[spot["Cambio"] < 0]
            recibido  = spot[spot["Cambio"] > 0]

            if entregado.empty or recibido.empty:
                for _, fila in grupo.iterrows():
                    self.desconocidas.append(OperacionDesconocida(
                        fecha=fecha, subtipo="Binance Convert (sin resolver)",
                        activo=fila["Moneda"], cantidad=fila["Cambio"], cuenta=fila["Cuenta"]
                    ))
                continue

            # Si hay múltiples filas entregadas o recibidas, sumar por moneda
            entregado_total = entregado.groupby("Moneda")["Cambio"].sum()
            recibido_total  = recibido.groupby("Moneda")["Cambio"].sum()

            activo_ent = entregado_total.index[0]
            cant_ent   = abs(float(entregado_total.iloc[0]))
            activo_rec = recibido_total.index[0]
            cant_rec   = float(recibido_total.iloc[0])

            nota = "Múltiples cuentas involucradas" if len(grupo["Cuenta"].unique()) > 1 else ""

            # FMV: precio EUR del activo recibido en el momento del swap
            ts_swap = grupo.iloc[0]["Tiempo"]  # ya es pd.Timestamp desde __init__
            pu_fmv  = self._precio_mas_cercano(activo_rec, ts_swap)
            fmv_eur = round(pu_fmv * cant_rec, 6) if pu_fmv > 0 else 0.0

            self.swaps.append(OperacionSwap(
                fecha=fecha,
                activo_entregado=activo_ent, cantidad_entregada=cant_ent,
                activo_recibido=activo_rec,  cantidad_recibida=cant_rec,
                nota=nota,
                precio_fmv_eur=fmv_eur
            ))

    # ── TABLA DE PRECIOS EUR IMPLÍCITOS ──────────

    def _construir_tabla_precios(self) -> dict:
        """
        Extrae precios EUR/unidad de cada activo a partir de las operaciones
        Transaction Buy/Spend donde uno de los lados es EUR o stable.
        Retorna: {asset: [(timestamp, eur_por_unidad), ...]} ordenado por tiempo.
        """
        tabla: dict = defaultdict(list)
        mask  = self.df["Operación"].isin(["Transaction Buy", "Transaction Spend"])
        filas = self.df[mask]

        for ts, grupo in filas.groupby("Tiempo"):
            buy   = grupo[grupo["Operación"] == "Transaction Buy"]
            spend = grupo[grupo["Operación"] == "Transaction Spend"]
            if buy.empty or spend.empty:
                continue

            a_buy   = buy.iloc[0]["Moneda"]
            c_buy   = float(buy.iloc[0]["Cambio"])          # positivo
            a_spend = spend.iloc[0]["Moneda"]
            c_spend = abs(float(spend.iloc[0]["Cambio"]))   # positivo

            # COMPRA: EUR/stable → cripto
            if a_spend in STABLES and a_buy not in STABLES and c_buy > 0:
                tabla[a_buy].append((ts, c_spend / c_buy))

            # VENTA: cripto → EUR/stable
            elif a_buy in STABLES and a_spend not in STABLES and c_spend > 0:
                tabla[a_spend].append((ts, c_buy / c_spend))

        for asset in tabla:
            tabla[asset].sort(key=lambda x: x[0])
        return tabla

    def _precio_mas_cercano(self, asset: str, ts) -> float:
        """
        Devuelve el precio EUR/unidad más cercano en tiempo para el activo.
        Retorna 0.0 si no hay datos de referencia.
        """
        puntos = self._tabla_precios.get(asset, [])
        if not puntos:
            return 0.0
        mejor = min(puntos, key=lambda x: abs((x[0] - ts).total_seconds()))
        return mejor[1]

    # ── RESTO ─────────────────────────────────

    def _procesar_resto(self):
        for idx, fila in self.df.iterrows():
            if idx in self._procesadas:
                continue

            op     = fila["Operación"]
            moneda = fila["Moneda"]
            cambio = float(fila["Cambio"])
            cuenta = fila["Cuenta"]
            obs    = str(fila.get("Observación", ""))
            fecha  = str(fila["Tiempo"])
            cat    = REGLAS.get(op)

            if cat == "RENDIMIENTO":
                self.rendimientos.append(OperacionRendimiento(
                    fecha=fecha, subtipo=op, activo=moneda, cantidad=cambio, cuenta=cuenta
                ))
            elif cat == "MOVIMIENTO":
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=op, activo=moneda, cantidad=cambio, observacion=obs
                ))
            elif cat == "IGNORAR":
                pass
            else:
                self.desconocidas.append(OperacionDesconocida(
                    fecha=fecha, subtipo=op, activo=moneda, cantidad=cambio, cuenta=cuenta
                ))

    # ── RESUMEN Y EXPORT ──────────────────────

    def resumen(self) -> dict:
        return {
            "total_filas_csv": len(self.df),
            "compraventas":    len(self.compraventas),
            "swaps":           len(self.swaps),
            "rendimientos":    len(self.rendimientos),
            "movimientos":     len(self.movimientos),
            "desconocidas":    len(self.desconocidas),
        }

    def to_dataframes(self) -> dict[str, pd.DataFrame]:
        return {
            "compraventas": pd.DataFrame([vars(o) for o in self.compraventas]),
            "swaps":        pd.DataFrame([vars(o) for o in self.swaps]),
            "rendimientos": pd.DataFrame([vars(o) for o in self.rendimientos]),
            "movimientos":  pd.DataFrame([vars(o) for o in self.movimientos]),
            "desconocidas": pd.DataFrame([vars(o) for o in self.desconocidas]),
        }


# ── EJECUCIÓN DIRECTA ─────────────────────────

if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "binance.csv"
    print(f"\nProcesando: {ruta}\n")

    c = ClasificadorBinance(ruta).clasificar()
    r = c.resumen()

    print("=" * 50)
    print("RESUMEN DE CLASIFICACIÓN")
    print("=" * 50)
    for k, v in r.items():
        print(f"  {k:<25} {v:>6}")

    dfs = c.to_dataframes()

    print("\n── COMPRAVENTAS ──")
    if not dfs["compraventas"].empty:
        print(dfs["compraventas"][["fecha","tipo","activo","cantidad","contraparte","importe"]].to_string())

    print("\n── SWAPS ──")
    if not dfs["swaps"].empty:
        print(dfs["swaps"][["fecha","activo_entregado","cantidad_entregada","activo_recibido","cantidad_recibida","nota"]].to_string())

    print("\n── RENDIMIENTOS por tipo ──")
    if not dfs["rendimientos"].empty:
        print(dfs["rendimientos"].groupby("subtipo")["cantidad"].agg(["count","sum"]))

    print("\n── OPERACIONES NO RECONOCIDAS ──")
    if not dfs["desconocidas"].empty:
        print(dfs["desconocidas"][["fecha","subtipo","activo","cantidad"]].to_string())
    else:
        print("  Ninguna. ✓")
