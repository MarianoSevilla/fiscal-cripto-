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
import math
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
    "Advanced Trade Buy",          # se trata aparte si tiene precio EUR
    "Advanced Trade Sell",         # se trata aparte si tiene precio EUR
    "Retail Staking Transfer",     # traspaso interno spot ↔ staking (sin evento fiscal)
    "Retail Unstaking Transfer",   # traspaso interno staking ↔ spot (sin evento fiscal)
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
    fee_eur: float = 0.0  # no calcular IRPF como si no existiera la comisión

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

_COLS_REQUERIDAS = {"Timestamp", "Transaction Type", "Asset", "Quantity Transacted"}
_HEADER_SEARCH_LIMIT = 20  # máximo de filas en que buscamos la cabecera


def _detectar_fila_cabecera(filepath: str) -> int:
    """
    Devuelve el índice (0-based) de la fila que contiene la cabecera del CSV.
    Lanza ValueError si no se encuentra ninguna fila compatible en las primeras
    _HEADER_SEARCH_LIMIT líneas.
    """
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for i, raw_line in enumerate(f):
                if i >= _HEADER_SEARCH_LIMIT:
                    break
                cols = {c.strip().strip('"') for c in raw_line.split(",")}
                if _COLS_REQUERIDAS.issubset(cols):
                    return i
    except OSError:
        pass
    raise ValueError(
        "Este archivo de Coinbase no contiene la cabecera de transacciones esperada. "
        "Es posible que hayas descargado otro tipo de informe o que Coinbase haya "
        "cambiado el formato. Descarga el historial completo de transacciones desde "
        "Coinbase y vuelve a intentarlo."
    )


class ClasificadorCoinbase:

    def __init__(self, filepath: str):
        header_row = _detectar_fila_cabecera(filepath)
        # Keep blank optional fee cells distinct from the literal "NaN" token.
        # Otherwise pandas erases the difference before fiscal validation.
        self.df = pd.read_csv(filepath, skiprows=header_row, keep_default_na=False)
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
            self.df["Timestamp"], utc=True, errors="coerce", format="mixed"
        )
        if self.df["Timestamp"].isna().any():
            raise ValueError(
                "Datos fiscales no seguros: Coinbase contiene una fecha inválida."
            )
        self.df = self.df.sort_values("Timestamp").reset_index(drop=True)

        for _, fila in self.df.iterrows():
            self._clasificar_fila(fila)

        return self

    @staticmethod
    def _validate_fiscal_number(value, field: str, *, zero_allowed: bool = False):
        """A malformed value must never silently become a zero-cost FIFO lot."""
        raw = str(value).strip().replace("€", "").replace(",", "")
        if raw.startswith("$") or raw == "" or raw.lower() in ("nan", "none"):
            raise ValueError(
                f"Datos fiscales no seguros: importe/cantidad Coinbase sin valor EUR válido ({field})."
            )
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ValueError(
                f"Datos fiscales no seguros: número Coinbase no interpretable ({field})."
            ) from None
        if not math.isfinite(number) or (number == 0 and not zero_allowed):
            raise ValueError(
                f"Datos fiscales no seguros: número Coinbase inválido o no finito ({field})."
            )
        return number

    @classmethod
    def _validate_fiscal_optional_numeric(cls, value, field):
        if str(value).strip().lower() in ("nan", "infinity", "-infinity"):
            raise ValueError(f"Datos fiscales no seguros: valor Coinbase inválido ({field}).")
        if not pd.isna(value) and str(value).strip():
            cls._validate_fiscal_number(value, field, zero_allowed=True)

    def _validate_fiscal_row(self, fila):
        kind = str(fila.get("Transaction Type", "")).strip()
        financial = (
            "Buy", "Advanced Trade Buy", "Sell", "Advanced Trade Sell", "Convert"
        )
        if kind not in financial and kind not in TIPOS_RENDIMIENTO:
            return
        currency = str(fila.get("Price Currency", "")).strip().upper()
        if currency != "EUR":
            raise ValueError(
                "Datos fiscales no seguros: Coinbase indica valoración en "
                f"{currency or 'moneda no identificada'} y no en EUR."
            )
        self._validate_fiscal_number(fila.get("Quantity Transacted"), "Quantity Transacted")
        if kind in ("Buy", "Advanced Trade Buy"):
            self._validate_fiscal_number(
                fila.get("Total (inclusive of fees and/or spread)"),
                "Total (inclusive of fees and/or spread)",
            )
            self._validate_fiscal_optional_numeric(
                fila.get("Subtotal"), "Subtotal"
            )
        elif kind in ("Sell", "Advanced Trade Sell"):
            self._validate_fiscal_number(fila.get("Subtotal"), "Subtotal")
            self._validate_fiscal_optional_numeric(
                fila.get("Total (inclusive of fees and/or spread)"),
                "Total (inclusive of fees and/or spread)"
            )
        else:
            total = fila.get("Total (inclusive of fees and/or spread)")
            subtotal = fila.get("Subtotal")
            # Validate each supplied number: a valid subtotal cannot excuse
            # NaN/Infinity in Total later consumed by the parser.
            candidates = (subtotal, total)
            for value in candidates:
                if not pd.isna(value) and str(value).strip():
                    self._validate_fiscal_number(
                        value, "Subtotal/Total EUR", zero_allowed=True
                    )
            if not any(self._valid_positive_optional(v) for v in candidates):
                raise ValueError(
                    "Datos fiscales no seguros: Coinbase no ofrece una "
                    "valoración EUR positiva para esta operación."
                )
        fee = fila.get("Fees and/or Spread", 0)
        if str(fee).strip().lower() in ("nan", "infinity", "-infinity"):
            raise ValueError("Datos fiscales no seguros: comisión Coinbase no finita.")
        if not pd.isna(fee) and str(fee).strip():
            self._validate_fiscal_number(fee, "Fees and/or Spread", zero_allowed=True)

    @classmethod
    def _valid_positive_optional(cls, value):
        try:
            return cls._validate_fiscal_number(value, "valoración EUR") > 0
        except ValueError:
            return False

    def _clasificar_fila(self, fila):
        self._validate_fiscal_row(fila)
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
                    fee_eur=fees,
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
            valor_eur = total if total > 0 else subtotal
            self.rendimientos.append(OperacionRendimiento(
                fecha=fecha, subtipo=tipo,
                activo=activo, cantidad=qty,
                cuenta="Coinbase",
                valor_eur=valor_eur,
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
            received = float(m.group(1))
            if not math.isfinite(received) or received <= 0:
                raise ValueError("Datos fiscales no seguros: cantidad Coinbase Convert recibida inválida.")
            return received, m.group(2).upper()
        return 0.0, ""

    @staticmethod
    def _float_eur(val) -> float:
        """Convierte valores monetarios con símbolo € a float."""
        # Parse exactly the same currency syntax as _validate_fiscal_number.
        # Removing '-' corrupted valid scientific notation: €2e-2 became 200.
        if pd.isna(val) or str(val).strip() == "":
            return 0.0
        return ClasificadorCoinbase._validate_fiscal_number(
            val, "valor monetario Coinbase", zero_allowed=True
        )

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
            return ts.strftime("%Y-%m-%d %H:%M:%S.%f") if ts.microsecond else ts.strftime("%Y-%m-%d %H:%M:%S")
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
