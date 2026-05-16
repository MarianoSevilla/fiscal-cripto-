"""
Clasificador fiscal de operaciones Uphold
Mariano Sevilla — marianosevilla.com
v1.0

Formato CSV de Uphold (Transaction History):
- Sin filas de metadatos: cabecera en la primera fila
- Columnas: Date, Destination, Destination Amount, Destination Currency,
  Fee Amount, Fee Currency, Id, Origin, Origin Amount, Origin Currency, Status, Type
- Date format: 'Fri Sep 26 2025 23:31:25 GMT+0000' (always UTC)
- Type values: in (compras/recompensas), out (retiradas), transfer (swaps/internos)
- Status values: completed (procesar), failed (IGNORAR)
- Brave Rewards (BAT): Origin=uphold, Type=in, misma moneda origen/destino
"""

import csv
from dataclasses import dataclass
from datetime import datetime


# ── CONSTANTES ────────────────────────────────

# Firma de detección en las primeras líneas del CSV
UPHOLD_SIGNATURES = ["Destination Amount", "Origin Amount", "Fee Currency"]

ORIGINS_COMPRA = {"alternative-payment-method", "credit-card"}


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

class ClasificadorUphold:

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.compraventas:  list[OperacionCompraventa] = []
        self.swaps:         list[OperacionSwap]        = []
        self.rendimientos:  list[OperacionRendimiento] = []
        self.movimientos:   list[OperacionMovimiento]  = []
        self.desconocidas:  list[OperacionDesconocida] = []
        self.advertencias:  list[str]                  = []
        self._total_filas = 0

    def clasificar(self):
        rows = []
        with open(self.filepath, encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Strip whitespace from keys and values
                row = {k.strip(): v.strip() for k, v in row.items()}
                rows.append(row)

        self._total_filas = len(rows)

        # Sort by date (ascending) before processing
        rows.sort(key=lambda r: self._parse_fecha_dt(r.get("Date", "")))

        for row in rows:
            self._clasificar_fila(row)

        return self

    def _clasificar_fila(self, row: dict):
        status      = row.get("Status", "").strip()
        tipo        = row.get("Type", "").strip()
        origin      = row.get("Origin", "").strip()
        origin_cur  = row.get("Origin Currency", "").strip()
        dest_cur    = row.get("Destination Currency", "").strip()
        origin_amt  = self._float(row.get("Origin Amount", "0"))
        dest_amt    = self._float(row.get("Destination Amount", "0"))
        fee_amt     = self._float(row.get("Fee Amount", ""))
        fee_cur     = row.get("Fee Currency", "").strip()
        tx_id       = row.get("Id", "").strip()
        fecha       = self._fmt_fecha(row.get("Date", ""))

        # ── 1. SKIP failed ────────────────────────────────────────────────────
        if status == "failed":
            return

        # Only process completed rows below
        if status != "completed":
            # Unknown status — add as desconocida
            self.advertencias.append(
                f"Estado desconocido «{status}» el {fecha} — se ignora a efectos fiscales."
            )
            self.desconocidas.append(OperacionDesconocida(
                fecha=fecha, subtipo=f"status:{status}",
                activo=origin_cur, cantidad=origin_amt, cuenta="Uphold",
            ))
            return

        fee_qty = fee_amt if fee_amt and fee_amt > 0 else 0.0
        fee_activo = fee_cur if fee_qty > 0 else ""

        # ── 2. COMPRA: Type=in, Origin in compra-origins, OriginCurrency=EUR ──
        if (tipo == "in"
                and origin in ORIGINS_COMPRA
                and origin_cur == "EUR"):
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha, tipo="COMPRA",
                activo=dest_cur, cantidad=dest_amt,
                contraparte="EUR", importe=origin_amt,
                fee_activo=fee_activo, fee_cantidad=fee_qty,
            ))
            return

        # ── 3. VENTA: Type=transfer, OriginCurrency!=EUR, DestCurrency=EUR ───
        if (tipo == "transfer"
                and origin_cur != "EUR"
                and dest_cur == "EUR"):
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha, tipo="VENTA",
                activo=origin_cur, cantidad=origin_amt,
                contraparte="EUR", importe=dest_amt,
                fee_activo=fee_activo, fee_cantidad=fee_qty,
            ))
            return

        # ── 4. SWAP: Type=transfer, distintas monedas, ninguna es EUR ─────────
        if (tipo == "transfer"
                and origin_cur != dest_cur
                and origin_cur != "EUR"
                and dest_cur != "EUR"):
            nota = tx_id
            if fee_qty > 0:
                nota = f"fee: {fee_qty} {fee_cur} | {tx_id}"
            self.advertencias.append(
                f"Swap {origin_cur}→{dest_cur} el {fecha}: Uphold no provee valoración EUR. "
                f"Determina el precio de mercado de {origin_cur} en esa fecha para la declaración."
            )
            self.swaps.append(OperacionSwap(
                fecha=fecha,
                activo_entregado=origin_cur,
                cantidad_entregada=origin_amt,
                activo_recibido=dest_cur,
                cantidad_recibida=dest_amt,
                nota=nota,
                precio_fmv_eur=0.0,
            ))
            return

        # ── 5. RENDIMIENTO (Brave Rewards): Type=in, Origin=uphold, misma moneda
        if (tipo == "in"
                and origin == "uphold"
                and origin_cur == dest_cur):
            self.advertencias.append(
                f"Brave Rewards de {dest_amt} {dest_cur} el {fecha}: Uphold no provee valor EUR. "
                f"Aplica el precio de mercado de esa fecha como rendimiento del capital mobiliario "
                f"(casilla 0033)."
            )
            self.rendimientos.append(OperacionRendimiento(
                fecha=fecha, subtipo="Brave Rewards",
                activo=dest_cur, cantidad=dest_amt,
                cuenta="Uphold",
                valor_eur=0.0,
            ))
            # Entrada al inventario FIFO a coste 0 (para futura venta)
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha, tipo="COMPRA",
                activo=dest_cur, cantidad=dest_amt,
                contraparte="EUR", importe=0.0,
                fee_activo="", fee_cantidad=0.0,
            ))
            return

        # ── 6. MOVIMIENTO (Withdrawal): Type=out ─────────────────────────────
        if tipo == "out":
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Withdrawal",
                activo=origin_cur, cantidad=origin_amt,
                observacion=tx_id,
            ))
            return

        # ── 7. MOVIMIENTO (Internal Transfer): Type=transfer, misma moneda ───
        if tipo == "transfer" and origin_cur == dest_cur:
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Internal Transfer",
                activo=origin_cur, cantidad=origin_amt,
                observacion=tx_id,
            ))
            return

        # ── 8. DESCONOCIDA: todo lo demás completed ───────────────────────────
        self.advertencias.append(
            f"Operación no reconocida: Type={tipo}, Origin={origin}, "
            f"{origin_cur}→{dest_cur} el {fecha} — se ignora a efectos fiscales."
        )
        self.desconocidas.append(OperacionDesconocida(
            fecha=fecha, subtipo=f"{tipo}/{origin}",
            activo=origin_cur, cantidad=origin_amt, cuenta="Uphold",
        ))

    @staticmethod
    def _parse_fecha_dt(date_str: str) -> datetime:
        """Parsea 'Fri Sep 26 2025 23:31:25 GMT+0000' → datetime (UTC)."""
        try:
            # Split: ['Fri', 'Sep', '26', '2025', '23:31:25', 'GMT+0000']
            parts = date_str.strip().split()
            if len(parts) >= 6:
                # Reconstruct without weekday and timezone: 'Sep 26 2025 23:31:25'
                core = " ".join(parts[1:5])
                return datetime.strptime(core, "%b %d %Y %H:%M:%S")
        except Exception:
            pass
        return datetime(2000, 1, 1)

    @staticmethod
    def _fmt_fecha(date_str: str) -> str:
        """Convierte 'Fri Sep 26 2025 23:31:25 GMT+0000' → '2025-09-26 23:31:25'."""
        try:
            parts = date_str.strip().split()
            if len(parts) >= 6:
                core = " ".join(parts[1:5])
                dt = datetime.strptime(core, "%b %d %Y %H:%M:%S")
                return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
        return date_str[:19] if date_str else ""

    @staticmethod
    def _float(val) -> float:
        try:
            s = str(val).strip()
            if not s or s.lower() in ("nan", "-", ""):
                return 0.0
            return float(s)
        except Exception:
            return 0.0

    def resumen(self) -> dict:
        return {
            "total_filas_csv": self._total_filas,
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
    ruta = sys.argv[1] if len(sys.argv) > 1 else "uphold.csv"
    print(f"\nProcesando: {ruta}\n")

    c = ClasificadorUphold(ruta).clasificar()
    r = c.resumen()

    print("=" * 50)
    print("RESUMEN DE CLASIFICACIÓN — UPHOLD")
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
        print(f"  {op.fecha[:10]} | {op.activo_entregado:8} → {op.activo_recibido:8} | "
              f"{op.cantidad_entregada:.6f} → {op.cantidad_recibida:.6f}")

    print("\n── RENDIMIENTOS (primeros 10) ──")
    for op in c.rendimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | "
              f"{op.cantidad:.8f} | valor: {op.valor_eur:.4f}")

    print("\n── MOVIMIENTOS (primeros 10) ──")
    for op in c.movimientos[:10]:
        print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | {op.cantidad:.4f}")

    print(f"\n── ADVERTENCIAS ({len(c.advertencias)}) ──")
    if c.advertencias:
        for adv in c.advertencias[:10]:
            print(f"  !  {adv}")
        if len(c.advertencias) > 10:
            print(f"  ... y {len(c.advertencias) - 10} mas")
    else:
        print("  Ninguna")

    print("\n── DESCONOCIDAS ──")
    if c.desconocidas:
        for op in c.desconocidas:
            print(f"  {op.fecha[:10]} | {op.subtipo:20} | {op.activo:6} | {op.cantidad:.6f}")
    else:
        print("  Ninguna")
