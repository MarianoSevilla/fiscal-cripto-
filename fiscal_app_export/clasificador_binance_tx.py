"""
Clasificador fiscal de operaciones Binance — Historial de Transacciones
Mariano Sevilla — marianosevilla.com

Soporta el formato exportado desde:
  Binance → Órdenes → Historial de transacciones
  (columnas: ID de usuario, Tiempo, Cuenta, Operación, Moneda, Cambio, Observación)

Operaciones reconocidas:
  Buy Crypto With Fiat  → COMPRA (par EUR) o RENDIMIENTO (bono "Ref" sin par EUR)
  Sell Crypto To Fiat   → VENTA
  Binance Convert       → COMPRA / VENTA / SWAP según contrapartida
  Simple Earn *         → RENDIMIENTO
  Deposit / Withdraw    → MOVIMIENTO
  Fiat Deposit/Withdraw → MOVIMIENTO
  Simple Earn Sub/Red   → MOVIMIENTO
"""

import re
import pandas as pd
from clasificador import (
    OperacionCompraventa, OperacionSwap,
    OperacionRendimiento, OperacionMovimiento,
    OperacionDesconocida, STABLES,
)

_WALLET_RE = re.compile(r"Wallet/(\w+)")


def _wallet_id(obs: str):
    """Extrae el ID de cartera de la columna Observación, o None si no existe."""
    m = _WALLET_RE.search(str(obs))
    return m.group(1) if m else None


# Operaciones que se resuelven fila a fila (sin pareja)
REGLAS_TX = {
    # ── Simple Earn ──────────────────────────────────────────────────────────
    "Simple Earn Flexible Interest":     "RENDIMIENTO",
    "Simple Earn Locked Rewards":        "RENDIMIENTO",
    "Simple Earn Locked Subscription":   "MOVIMIENTO",
    "Simple Earn Locked Redemption":     "MOVIMIENTO",
    "Simple Earn Flexible Subscription": "MOVIMIENTO",
    "Simple Earn Flexible Redemption":   "MOVIMIENTO",
    # ── Depósitos / retiros fiat ─────────────────────────────────────────────
    "Deposit":                           "MOVIMIENTO",
    "Withdraw":                          "MOVIMIENTO",
    "Fiat Withdraw":                     "MOVIMIENTO",
    "Fiat Deposit":                      "MOVIMIENTO",
    # ── Comisiones y referidos (rendimientos del capital) ────────────────────
    # Art. 25.2 LIRPF: comisiones cobradas son rendimiento del capital mobiliario
    "Commission Rebate":                             "RENDIMIENTO",
    "Referrer Commission":                           "RENDIMIENTO",
    # ── Distribuciones de pools y staking (rendimientos del capital) ─────────
    "Pool Distribution":                             "RENDIMIENTO",
    "Launchpool Airdrop - System Distribution":      "RENDIMIENTO",
    "HODLer Airdrops Distribution":                  "RENDIMIENTO",
    "Megadrop Rewards":                              "RENDIMIENTO",
    # ── Airdrops y regalos (rendimiento en especie) ──────────────────────────
    "Airdrop Assets":                                "RENDIMIENTO",
    "Crypto Box":                                    "RENDIMIENTO",
    # ── Distribuciones de token swaps ────────────────────────────────────────
    "Token Swap - Distribution":                     "RENDIMIENTO",
    # ── Transferencias entre cuentas / sin impacto fiscal directo ───────────
    "Small Assets Exchange BNB":                     "MOVIMIENTO",
    "Send":                                          "MOVIMIENTO",
    "Asset Recovery":                                "MOVIMIENTO",
    "Transfer Between Main and Funding Wallet":      "MOVIMIENTO",
    "Transfer Between Spot Account and UM Futures Account": "MOVIMIENTO",
    "Transfer Between Spot Account and CM Futures Account": "MOVIMIENTO",
    "Transfer Between Spot Account and PM Futures Account": "MOVIMIENTO",
    "Transfer Between Main Account/Futures and Margin Account": "MOVIMIENTO",
}


class ClasificadorBinanceTx:
    """
    Clasificador para el Historial de Transacciones de Binance.
    Expone la misma interfaz que ClasificadorBinance para ser compatible
    con _pipeline_motor y procesar_con_fifo.
    """

    def __init__(self, filepath: str):
        self.df = pd.read_csv(filepath)
        self.df.columns = [c.strip() for c in self.df.columns]
        self.df["Tiempo"] = pd.to_datetime(self.df["Tiempo"], format="%y-%m-%d %H:%M:%S")
        self.df = self.df.sort_values("Tiempo").reset_index(drop=True)
        self.df["Cambio"] = pd.to_numeric(self.df["Cambio"], errors="coerce").fillna(0.0)
        if "Observación" not in self.df.columns:
            self.df["Observación"] = ""

        self.compraventas = []
        self.swaps        = []
        self.rendimientos = []
        self.movimientos  = []
        self.desconocidas = []
        self.advertencias = []
        self._procesadas:  set                        = set()

    # ── ENTRADA PÚBLICA ────────────────────────────────────────────────────

    def clasificar(self):
        self._procesar_buy_sell_fiat()
        self._procesar_convert()
        self._procesar_transaction_buy_spend()
        self._procesar_resto()
        if self.desconocidas:
            tipos = {d.subtipo for d in self.desconocidas}
            self.advertencias.append(
                f"{len(self.desconocidas)} operación(es) no reconocida(s): "
                + ", ".join(sorted(tipos))
            )
        return self

    # ── BUY / SELL CRYPTO WITH FIAT ────────────────────────────────────────

    def _procesar_buy_sell_fiat(self):
        """
        Empareja filas Buy/Sell por wallet ID extraído de Observación.
        Desde ~sep-2025 Binance usa 'Deposit EUR -X' (±10s) en lugar del par
        EUR dentro del mismo wallet, así que también buscamos esa variante.
        Las filas sin wallet ID (marcadas 'Ref') son bonos/referrals → RENDIMIENTO.
        """
        mask  = self.df["Operación"].isin(["Buy Crypto With Fiat", "Sell Crypto To Fiat"])
        filas = self.df[mask].copy()
        if filas.empty:
            return

        filas["_wid"] = filas["Observación"].apply(_wallet_id)

        # ── Parejas con wallet ID (formato anterior a sep-2025) ───────────
        con_wid = filas[filas["_wid"].notna()]
        for wid, grupo in con_wid.groupby("_wid"):
            self._procesadas.update(grupo.index.tolist())
            self._resolver_par_fiat(grupo)

        # ── Sin wallet ID → intentar emparejar con Deposit EUR (sep-2025+) ─
        for idx, fila in filas[filas["_wid"].isna()].iterrows():
            if idx in self._procesadas:
                continue
            self._procesadas.add(idx)
            cambio = float(fila["Cambio"])

            if fila["Operación"] == "Buy Crypto With Fiat" and cambio > 0 and fila["Moneda"] not in STABLES:
                coste_eur = self._buscar_deposit_eur(fila["Tiempo"])
                if coste_eur is not None:
                    self.compraventas.append(OperacionCompraventa(
                        fecha=str(fila["Tiempo"]), tipo="COMPRA",
                        activo=fila["Moneda"], cantidad=cambio,
                        contraparte="EUR", importe=coste_eur,
                        fee_activo=fila["Moneda"], fee_cantidad=0.0,
                    ))
                else:
                    # Sin coste conocido → rendimiento con advertencia
                    self.rendimientos.append(OperacionRendimiento(
                        fecha=str(fila["Tiempo"]),
                        subtipo="Buy Crypto With Fiat (Ref)",
                        activo=fila["Moneda"], cantidad=cambio,
                        cuenta=fila["Cuenta"],
                    ))
            else:
                self.desconocidas.append(OperacionDesconocida(
                    fecha=str(fila["Tiempo"]), subtipo=fila["Operación"],
                    activo=fila["Moneda"], cantidad=cambio, cuenta=fila["Cuenta"],
                ))

    def _buscar_deposit_eur(self, timestamp, ventana_s: int = 10):
        """
        Busca un 'Deposit, EUR, negativo' no procesado dentro de los
        `ventana_s` segundos anteriores al timestamp dado.
        Devuelve el importe absoluto en EUR, o None si no lo encuentra.
        Marca la fila encontrada como procesada.
        """
        candidatos = self.df[
            (self.df["Operación"] == "Deposit") &
            (self.df["Moneda"] == "EUR") &
            (self.df["Cambio"] < 0) &
            (self.df["Tiempo"] <= timestamp) &
            (self.df["Tiempo"] >= timestamp - pd.Timedelta(seconds=ventana_s))
        ]
        # Filtrar ya procesados y quedarse con el más cercano en tiempo
        candidatos = candidatos[~candidatos.index.isin(self._procesadas)]
        if candidatos.empty:
            return None
        idx_mas_cercano = (timestamp - candidatos["Tiempo"]).abs().idxmin()
        self._procesadas.add(idx_mas_cercano)
        return abs(float(self.df.loc[idx_mas_cercano, "Cambio"]))

    def _resolver_par_fiat(self, grupo):
        """Construye la operación a partir de un grupo con el mismo wallet ID."""
        fecha   = str(grupo.iloc[0]["Tiempo"])
        op_tipo = grupo.iloc[0]["Operación"]

        filas_eur    = grupo[grupo["Moneda"] == "EUR"]
        filas_crypto = grupo[grupo["Moneda"] != "EUR"]

        if filas_crypto.empty:
            # Solo movimiento de fiat
            for _, fila in filas_eur.iterrows():
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=op_tipo, activo="EUR",
                    cantidad=float(fila["Cambio"]),
                    observacion=str(fila.get("Observación", "")),
                ))
            return

        if filas_eur.empty:
            # Desde sep-2025 Binance usa Deposit EUR -X en lugar de par EUR en el wallet.
            # Buscamos ese Deposit en una ventana de ±10s antes de cada fila crypto.
            for _, fila in filas_crypto.iterrows():
                cambio = float(fila["Cambio"])
                coste_eur = self._buscar_deposit_eur(fila["Tiempo"]) if cambio > 0 else None
                if coste_eur is not None:
                    self.compraventas.append(OperacionCompraventa(
                        fecha=str(fila["Tiempo"]), tipo="COMPRA",
                        activo=fila["Moneda"], cantidad=cambio,
                        contraparte="EUR", importe=coste_eur,
                        fee_activo=fila["Moneda"], fee_cantidad=0.0,
                    ))
                else:
                    self.rendimientos.append(OperacionRendimiento(
                        fecha=str(fila["Tiempo"]), subtipo=f"{op_tipo} (sin par EUR)",
                        activo=fila["Moneda"], cantidad=cambio,
                        cuenta=fila["Cuenta"],
                    ))
            return

        importe_eur = abs(float(filas_eur.iloc[0]["Cambio"]))

        for _, fila_c in filas_crypto.iterrows():
            cambio = float(fila_c["Cambio"])
            activo = fila_c["Moneda"]

            if op_tipo == "Buy Crypto With Fiat" and cambio > 0:
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="COMPRA",
                    activo=activo, cantidad=cambio,
                    contraparte="EUR", importe=importe_eur,
                    fee_activo=activo, fee_cantidad=0.0,
                ))
            elif op_tipo == "Sell Crypto To Fiat" and cambio < 0:
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="VENTA",
                    activo=activo, cantidad=abs(cambio),
                    contraparte="EUR", importe=importe_eur,
                    fee_activo="EUR", fee_cantidad=0.0,
                ))
            else:
                self.desconocidas.append(OperacionDesconocida(
                    fecha=fecha, subtipo=f"{op_tipo} (no resuelto)",
                    activo=activo, cantidad=cambio, cuenta=fila_c["Cuenta"],
                ))

    # ── BINANCE CONVERT ────────────────────────────────────────────────────

    def _procesar_convert(self):
        """
        Agrupa por ventana de ±2 segundos.
        EUR pagado → crypto recibido : COMPRA
        Crypto pagado → EUR recibido : VENTA
        Crypto → crypto              : SWAP
        """
        mask  = self.df["Operación"] == "Binance Convert"
        filas = self.df[mask].copy()
        if filas.empty:
            return

        filas = filas.sort_values("Tiempo").reset_index()
        grupos = []
        grupo_actual = [filas.iloc[0]]

        for i in range(1, len(filas)):
            diff = (filas.iloc[i]["Tiempo"] - filas.iloc[i - 1]["Tiempo"]).total_seconds()
            if diff <= 2:
                grupo_actual.append(filas.iloc[i])
            else:
                grupos.append(grupo_actual)
                grupo_actual = [filas.iloc[i]]
        grupos.append(grupo_actual)

        for grupo_list in grupos:
            grupo = pd.DataFrame(grupo_list)
            self._procesadas.update(grupo["index"].tolist())

            fecha     = str(grupo.iloc[0]["Tiempo"])
            recibido  = grupo[grupo["Cambio"] > 0]
            entregado = grupo[grupo["Cambio"] < 0]

            if recibido.empty or entregado.empty:
                for _, fila in grupo.iterrows():
                    self.desconocidas.append(OperacionDesconocida(
                        fecha=fecha, subtipo="Binance Convert (sin resolver)",
                        activo=fila["Moneda"], cantidad=fila["Cambio"],
                        cuenta=fila["Cuenta"],
                    ))
                continue

            activo_rec = recibido.iloc[0]["Moneda"]
            cant_rec   = float(recibido.iloc[0]["Cambio"])
            activo_ent = entregado.iloc[0]["Moneda"]
            cant_ent   = abs(float(entregado.iloc[0]["Cambio"]))

            if activo_ent == "EUR":
                # EUR → crypto: COMPRA
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="COMPRA",
                    activo=activo_rec, cantidad=cant_rec,
                    contraparte="EUR", importe=cant_ent,
                    fee_activo=activo_rec, fee_cantidad=0.0,
                ))
            elif activo_rec == "EUR":
                # crypto → EUR: VENTA
                self.compraventas.append(OperacionCompraventa(
                    fecha=fecha, tipo="VENTA",
                    activo=activo_ent, cantidad=cant_ent,
                    contraparte="EUR", importe=cant_rec,
                    fee_activo="EUR", fee_cantidad=0.0,
                ))
            else:
                # crypto → crypto: SWAP
                self.swaps.append(OperacionSwap(
                    fecha=fecha,
                    activo_entregado=activo_ent, cantidad_entregada=cant_ent,
                    activo_recibido=activo_rec,  cantidad_recibida=cant_rec,
                ))

    # ── TRANSACTION BUY / SPEND (Binance Pay) ────────────────────────────────

    def _procesar_transaction_buy_spend(self):
        """
        Empareja filas Transaction Buy + Transaction Spend (± Transaction Fee)
        que ocurren en el mismo segundo — son operaciones de Binance Pay:
          Transaction Spend  → activo entregado (negativo)
          Transaction Buy    → activo recibido  (positivo)
          Transaction Fee    → fee en BNB       (negativo, opcional)

        Un mismo segundo puede contener MÚLTIPLES filas del mismo tipo cuando
        Binance ejecuta varias órdenes parciales en el mismo instante (p.ej.
        5 Spend EUR + 5 Buy XRP → agregar en una sola COMPRA por par de monedas).

        Si el activo entregado es EUR → COMPRA con EUR.
        Si el activo recibido  es EUR → VENTA  con EUR.
        En cualquier otro caso        → SWAP crypto→crypto.
        """
        ops_tx = {"Transaction Buy", "Transaction Spend", "Transaction Fee"}
        mask   = self.df["Operación"].isin(ops_tx)
        filas  = self.df[mask].copy().sort_values("Tiempo").reset_index()
        if filas.empty:
            return

        # Agrupar por segundo exacto
        grupos: list = []
        grupo_actual = [filas.iloc[0]]
        for i in range(1, len(filas)):
            diff = (filas.iloc[i]["Tiempo"] - filas.iloc[i - 1]["Tiempo"]).total_seconds()
            if diff == 0:
                grupo_actual.append(filas.iloc[i])
            else:
                grupos.append(grupo_actual)
                grupo_actual = [filas.iloc[i]]
        grupos.append(grupo_actual)

        for grupo_list in grupos:
            grupo = pd.DataFrame(grupo_list)
            self._procesadas.update(grupo["index"].tolist())

            fecha      = str(grupo.iloc[0]["Tiempo"])
            buy_rows   = grupo[grupo["Operación"] == "Transaction Buy"]
            spend_rows = grupo[grupo["Operación"] == "Transaction Spend"]

            # Sin par buy+spend → registrar como movimiento
            if buy_rows.empty or spend_rows.empty:
                for _, fila in grupo.iterrows():
                    self.movimientos.append(OperacionMovimiento(
                        fecha=fecha, subtipo=fila["Operación"],
                        activo=fila["Moneda"], cantidad=float(fila["Cambio"]),
                        observacion=str(fila.get("Observación", "")),
                    ))
                continue

            # ── Sumar totales por moneda (maneja múltiples rows del mismo activo)
            # buy_rows tienen Cambio positivo; spend_rows tienen Cambio negativo
            buys_por_moneda   = buy_rows.groupby("Moneda")["Cambio"].sum()    # positivos
            spends_por_moneda = spend_rows.groupby("Moneda")["Cambio"].sum()  # negativos

            # Caso simple y más común: un activo comprado + un activo pagado
            # (incluso si hay N filas de cada uno, sumamos en una sola operación)
            if len(buys_por_moneda) == 1 and len(spends_por_moneda) == 1:
                activo_rec = buys_por_moneda.index[0]
                cant_rec   = float(buys_por_moneda.iloc[0])
                activo_ent = spends_por_moneda.index[0]
                cant_ent   = abs(float(spends_por_moneda.iloc[0]))
                self._registrar_op_buy_spend(fecha, activo_ent, cant_ent, activo_rec, cant_rec)

            elif len(buys_por_moneda) == 1:
                # Un activo recibido, varios pagados: crear una operación por moneda pagada
                activo_rec = buys_por_moneda.index[0]
                cant_rec   = float(buys_por_moneda.iloc[0])
                for activo_ent, cant_neg in spends_por_moneda.items():
                    self._registrar_op_buy_spend(
                        fecha, activo_ent, abs(float(cant_neg)), activo_rec, cant_rec
                    )

            else:
                # Caso ambiguo con múltiples activos recibidos: marcar como desconocido
                for _, fila in grupo.iterrows():
                    if fila["Operación"] != "Transaction Fee":
                        self.desconocidas.append(OperacionDesconocida(
                            fecha=fecha, subtipo=f"{fila['Operación']} (multi-par sin resolver)",
                            activo=fila["Moneda"], cantidad=float(fila["Cambio"]),
                            cuenta=str(fila.get("Cuenta", "")),
                        ))

    def _registrar_op_buy_spend(
        self,
        fecha: str,
        activo_ent: str, cant_ent: float,
        activo_rec: str, cant_rec: float,
    ) -> None:
        """Crea COMPRA (EUR→crypto), VENTA (crypto→EUR) o SWAP (crypto→crypto)."""
        if activo_ent == "EUR":
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha, tipo="COMPRA",
                activo=activo_rec, cantidad=cant_rec,
                contraparte="EUR", importe=cant_ent,
                fee_activo=activo_rec, fee_cantidad=0.0,
            ))
        elif activo_rec == "EUR":
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha, tipo="VENTA",
                activo=activo_ent, cantidad=cant_ent,
                contraparte="EUR", importe=cant_rec,
                fee_activo="EUR", fee_cantidad=0.0,
            ))
        else:
            # crypto → crypto (p.ej. USDC → XRP via Binance Pay)
            self.swaps.append(OperacionSwap(
                fecha=fecha,
                activo_entregado=activo_ent, cantidad_entregada=cant_ent,
                activo_recibido=activo_rec,  cantidad_recibida=cant_rec,
            ))

    # ── RESTO ─────────────────────────────────────────────────────────────

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
            cat    = REGLAS_TX.get(op)

            if cat == "RENDIMIENTO":
                self.rendimientos.append(OperacionRendimiento(
                    fecha=fecha, subtipo=op, activo=moneda,
                    cantidad=cambio, cuenta=cuenta,
                ))
            elif cat == "MOVIMIENTO":
                self.movimientos.append(OperacionMovimiento(
                    fecha=fecha, subtipo=op, activo=moneda,
                    cantidad=cambio, observacion=obs,
                ))
            else:
                self.desconocidas.append(OperacionDesconocida(
                    fecha=fecha, subtipo=op, activo=moneda,
                    cantidad=cambio, cuenta=cuenta,
                ))

    # ── RESUMEN ────────────────────────────────────────────────────────────

    def resumen(self) -> dict:
        return {
            "total_filas_csv": len(self.df),
            "compraventas":    len(self.compraventas),
            "swaps":           len(self.swaps),
            "rendimientos":    len(self.rendimientos),
            "movimientos":     len(self.movimientos),
            "desconocidas":    len(self.desconocidas),
        }


# ── EJECUCIÓN DIRECTA ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "binance_tx.csv"
    print(f"\nProcesando: {ruta}\n")
    c = ClasificadorBinanceTx(ruta).clasificar()
    r = c.resumen()
    print("=" * 50)
    print("RESUMEN")
    print("=" * 50)
    for k, v in r.items():
        print(f"  {k:<25} {v:>6}")
    print("\n── COMPRAVENTAS ──")
    for op in c.compraventas:
        print(f"  {op.fecha[:10]}  {op.tipo:<6}  {op.activo:<8}  {op.cantidad:>14.6f}  @ {op.importe:.2f} EUR")
    print("\n── RENDIMIENTOS ──")
    for op in c.rendimientos:
        print(f"  {op.fecha[:10]}  {op.subtipo:<40}  {op.activo:<8}  {op.cantidad:>14.6f}")
    print("\n── NO RECONOCIDAS ──")
    for op in c.desconocidas:
        print(f"  {op.fecha[:10]}  {op.subtipo:<40}  {op.activo:<8}  {op.cantidad:>14.6f}")
    if not c.desconocidas:
        print("  Ninguna. ✓")
