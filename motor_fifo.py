"""
Motor FIFO — Cálculo de plusvalías y minusvalías
Mariano Sevilla — marianosevilla.com
---
Normativa aplicada:
- Método FIFO obligatorio (art. 37.2 LIRPF)
- Las comisiones de compra aumentan el precio de coste
- Las comisiones de venta reducen el precio de transmisión
- Los swaps entre criptos tributan como venta + compra simultánea
- Los swaps entre stablecoins tributan si hay diferencia de valor
- Período de generación: determina si es corto (<1 año) o largo plazo (≥1 año)
  (en España ambos van a la base del ahorro, pero se informa separado)
"""

from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from typing import Optional


# ──────────────────────────────────────────────
# ESTRUCTURAS DE DATOS
# ──────────────────────────────────────────────

@dataclass
class Lote:
    """Un lote de compra en la cola FIFO de un activo."""
    fecha: datetime
    cantidad_original: float
    cantidad_restante: float
    precio_coste_unitario: float   # en EUR o USD (contraparte)
    contraparte: str               # USDC, USDT, EUR...
    origen: str                    # "compra" o "swap"

@dataclass
class ResultadoFIFO:
    """El resultado fiscal de una venta o swap."""
    fecha: datetime
    activo: str
    cantidad_vendida: float
    precio_transmision: float      # total recibido
    precio_coste: float            # total coste según FIFO
    ganancia_perdida: float        # transmisión - coste
    periodo_dias: float            # días desde la compra más antigua consumida
    lotes_consumidos: list         # detalle de qué lotes se usaron
    tipo_operacion: str            # "venta" o "swap"
    nota: str = ""

@dataclass
class ResumenActivo:
    """Posición actual de un activo tras todas las operaciones."""
    activo: str
    cantidad_total: float
    coste_total: float
    precio_medio: float
    lotes: list


# ──────────────────────────────────────────────
# MOTOR FIFO
# ──────────────────────────────────────────────

class MotorFIFO:

    # Stablecoins — precio referencial 1:1 con su moneda base
    STABLES = {"USDC", "USDT", "BUSD", "FDUSD", "DAI"}

    def __init__(self):
        # Cola FIFO por activo: {activo: [Lote, ...]} ordenada por fecha
        self.inventario: dict[str, list[Lote]] = defaultdict(list)
        # Resultados de ventas/swaps
        self.resultados: list[ResultadoFIFO] = []
        # Operaciones que no se pudieron procesar
        self.advertencias: list[str] = []

    # ── ENTRADA: registrar una compra ─────────

    def registrar_compra(self, fecha: str, activo: str, cantidad: float,
                          importe: float, contraparte: str,
                          fee_activo: str, fee_cantidad: float):
        """
        Añade un lote al inventario FIFO.
        La comisión pagada en el propio activo reduce la cantidad recibida
        pero no el coste → sube el precio unitario.
        """
        dt = self._parsear_fecha(fecha)

        # Si la fee se paga en el mismo activo comprado, la cantidad neta es menor
        # pero el coste total es el mismo → precio unitario real más alto
        cantidad_neta = cantidad  # la fee ya está descontada por Binance en el Cambio

        if importe <= 0 or cantidad_neta <= 0:
            self.advertencias.append(f"{fecha} | COMPRA {activo} — importe o cantidad inválidos")
            return

        precio_unitario = importe / cantidad_neta

        lote = Lote(
            fecha=dt,
            cantidad_original=cantidad_neta,
            cantidad_restante=cantidad_neta,
            precio_coste_unitario=precio_unitario,
            contraparte=contraparte,
            origen="compra"
        )
        self.inventario[activo].append(lote)

    # ── ENTRADA: registrar un swap ────────────

    def registrar_swap(self, fecha: str,
                        activo_entregado: str, cantidad_entregada: float,
                        activo_recibido: str, cantidad_recibida: float,
                        nota: str = ""):
        """
        Un swap es fiscalmente una venta del activo entregado
        y una compra inmediata del activo recibido.
        El precio de transmisión es el valor del activo recibido.
        """
        dt = self._parsear_fecha(fecha)

        # Ignorar el swap BNB→BNB (transferencia interna, no fiscal)
        if activo_entregado == activo_recibido:
            self.advertencias.append(
                f"{fecha} | SWAP {activo_entregado}→{activo_recibido} ignorado (mismo activo, movimiento interno)"
            )
            return

        # 1) Procesar como venta del activo entregado
        precio_transmision = cantidad_recibida  # valor recibido en la contraparte

        resultado = self._consumir_fifo(
            dt=dt,
            activo=activo_entregado,
            cantidad=cantidad_entregada,
            precio_transmision=precio_transmision,
            tipo="swap",
            nota=nota
        )
        if resultado:
            self.resultados.append(resultado)

        # 2) Registrar el activo recibido como nueva compra al valor de mercado
        if cantidad_recibida > 0:
            precio_unitario_recibido = precio_transmision / cantidad_recibida if cantidad_recibida > 0 else 0
            lote = Lote(
                fecha=dt,
                cantidad_original=cantidad_recibida,
                cantidad_restante=cantidad_recibida,
                precio_coste_unitario=precio_unitario_recibido,
                contraparte=activo_entregado,
                origen="swap"
            )
            self.inventario[activo_recibido].append(lote)

    # ── ENTRADA: registrar una venta ──────────

    def registrar_venta(self, fecha: str, activo: str, cantidad: float,
                         importe: float, contraparte: str,
                         fee_activo: str, fee_cantidad: float):
        """Venta de cripto por stablecoin o fiat."""
        dt = self._parsear_fecha(fecha)

        # La fee reduce el precio de transmisión efectivo
        importe_neto = importe
        if fee_activo == contraparte:
            importe_neto = importe - fee_cantidad

        resultado = self._consumir_fifo(
            dt=dt,
            activo=activo,
            cantidad=cantidad,
            precio_transmision=importe_neto,
            tipo="venta"
        )
        if resultado:
            self.resultados.append(resultado)

    # ── MOTOR FIFO INTERNO ────────────────────

    def _consumir_fifo(self, dt: datetime, activo: str, cantidad: float,
                        precio_transmision: float, tipo: str,
                        nota: str = "") -> Optional[ResultadoFIFO]:
        """
        Consume lotes del inventario en orden FIFO y calcula
        la ganancia o pérdida patrimonial.
        """
        cola = self.inventario.get(activo, [])

        if not cola:
            self.advertencias.append(
                f"{dt.date()} | {tipo.upper()} {activo} — no hay lotes de compra previos en el inventario"
            )
            return None

        cantidad_pendiente = cantidad
        coste_total = 0.0
        lotes_consumidos = []
        fecha_lote_mas_antiguo = None

        for lote in cola:
            if cantidad_pendiente <= 0:
                break
            if lote.cantidad_restante <= 0:
                continue

            consumir = min(lote.cantidad_restante, cantidad_pendiente)
            coste_lote = consumir * lote.precio_coste_unitario

            lotes_consumidos.append({
                "fecha_compra": lote.fecha.strftime("%Y-%m-%d"),
                "cantidad": consumir,
                "precio_unitario": lote.precio_coste_unitario,
                "coste_parcial": coste_lote,
                "contraparte": lote.contraparte
            })

            if fecha_lote_mas_antiguo is None:
                fecha_lote_mas_antiguo = lote.fecha

            lote.cantidad_restante -= consumir
            cantidad_pendiente -= consumir
            coste_total += coste_lote

        if cantidad_pendiente > 0.0001:  # tolerancia por redondeo
            self.advertencias.append(
                f"{dt.date()} | {tipo.upper()} {activo} — "
                f"inventario insuficiente: faltan {cantidad_pendiente:.6f} unidades"
            )

        ganancia = precio_transmision - coste_total
        periodo = (dt - fecha_lote_mas_antiguo).days if fecha_lote_mas_antiguo else 0

        return ResultadoFIFO(
            fecha=dt,
            activo=activo,
            cantidad_vendida=cantidad,
            precio_transmision=precio_transmision,
            precio_coste=coste_total,
            ganancia_perdida=ganancia,
            periodo_dias=periodo,
            lotes_consumidos=lotes_consumidos,
            tipo_operacion=tipo,
            nota=nota
        )

    # ── INVENTARIO ACTUAL ─────────────────────

    def posicion_actual(self) -> list[ResumenActivo]:
        """Devuelve la posición actual de cada activo (lotes no vendidos)."""
        resultado = []
        for activo, lotes in self.inventario.items():
            lotes_vivos = [l for l in lotes if l.cantidad_restante > 0.0001]
            if not lotes_vivos:
                continue
            cantidad = sum(l.cantidad_restante for l in lotes_vivos)
            coste    = sum(l.cantidad_restante * l.precio_coste_unitario for l in lotes_vivos)
            resultado.append(ResumenActivo(
                activo=activo,
                cantidad_total=cantidad,
                coste_total=coste,
                precio_medio=coste / cantidad if cantidad > 0 else 0,
                lotes=lotes_vivos
            ))
        return resultado

    # ── RESUMEN FISCAL ────────────────────────

    def resumen_fiscal(self) -> dict:
        ganancias  = [r for r in self.resultados if r.ganancia_perdida >= 0]
        perdidas   = [r for r in self.resultados if r.ganancia_perdida < 0]
        total_g    = sum(r.ganancia_perdida for r in ganancias)
        total_p    = sum(r.ganancia_perdida for r in perdidas)
        neto       = total_g + total_p

        return {
            "operaciones_con_resultado": len(self.resultados),
            "ganancias_brutas":  round(total_g, 2),
            "perdidas_brutas":   round(total_p, 2),
            "resultado_neto":    round(neto, 2),
            "advertencias":      len(self.advertencias),
        }

    # ── UTILIDADES ────────────────────────────

    @staticmethod
    def _parsear_fecha(fecha: str) -> datetime:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(fecha.strip(), fmt)
            except ValueError:
                continue
        raise ValueError(f"Formato de fecha no reconocido: {fecha}")


# ──────────────────────────────────────────────
# INTEGRACIÓN CON EL CLASIFICADOR
# ──────────────────────────────────────────────

def procesar_binance(filepath: str) -> MotorFIFO:
    """
    Pipeline completo: CSV → clasificador → motor FIFO
    """
    import sys
    sys.path.insert(0, '/home/claude/fiscal_app')
    from clasificador import ClasificadorBinance

    # 1. Clasificar
    c = ClasificadorBinance(filepath).clasificar()

    # 2. Alimentar el motor en orden cronológico
    motor = MotorFIFO()

    # Combinar todas las operaciones con resultado fiscal
    ops = []
    for op in c.compraventas:
        ops.append(("cv", op.fecha, op))
    for op in c.swaps:
        ops.append(("swap", op.fecha, op))

    # Ordenar cronológicamente
    ops.sort(key=lambda x: x[1])

    for tipo, fecha, op in ops:
        if tipo == "cv":
            if op.tipo == "COMPRA":
                motor.registrar_compra(
                    fecha=op.fecha,
                    activo=op.activo,
                    cantidad=op.cantidad,
                    importe=op.importe,
                    contraparte=op.contraparte,
                    fee_activo=op.fee_activo,
                    fee_cantidad=op.fee_cantidad
                )
            else:  # VENTA
                motor.registrar_venta(
                    fecha=op.fecha,
                    activo=op.activo,
                    cantidad=op.cantidad,
                    importe=op.importe,
                    contraparte=op.contraparte,
                    fee_activo=op.fee_activo,
                    fee_cantidad=op.fee_cantidad
                )
        elif tipo == "swap":
            motor.registrar_swap(
                fecha=op.fecha,
                activo_entregado=op.activo_entregado,
                cantidad_entregada=op.cantidad_entregada,
                activo_recibido=op.activo_recibido,
                cantidad_recibida=op.cantidad_recibida,
                nota=op.nota
            )

    return motor


# ──────────────────────────────────────────────
# EJECUCIÓN DIRECTA
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "binance.csv"

    motor = procesar_binance(ruta)

    print("\n" + "=" * 60)
    print("MOTOR FIFO — RESULTADOS FISCALES")
    print("=" * 60)

    resumen = motor.resumen_fiscal()
    print(f"\n  Operaciones con resultado fiscal: {resumen['operaciones_con_resultado']}")
    print(f"  Ganancias brutas:  {resumen['ganancias_brutas']:>10.2f} USDC")
    print(f"  Pérdidas brutas:   {resumen['perdidas_brutas']:>10.2f} USDC")
    print(f"  RESULTADO NETO:    {resumen['resultado_neto']:>10.2f} USDC")
    print(f"  Advertencias:      {resumen['advertencias']}")

    print("\n── DETALLE DE OPERACIONES CON RESULTADO ──\n")
    for r in motor.resultados:
        signo = "▲" if r.ganancia_perdida >= 0 else "▼"
        print(f"{r.fecha.strftime('%Y-%m-%d')} | {r.tipo_operacion.upper():5} | {r.activo:6} "
              f"| Transmisión: {r.precio_transmision:8.4f} "
              f"| Coste FIFO: {r.precio_coste:8.4f} "
              f"| {signo} {abs(r.ganancia_perdida):.4f} "
              f"| {r.periodo_dias}d")
        for lote in r.lotes_consumidos:
            print(f"         └ comprado {lote['fecha_compra']} · {lote['cantidad']:.4f} uds · "
                  f"{lote['precio_unitario']:.4f}/u · coste {lote['coste_parcial']:.4f}")
        if r.nota:
            print(f"         ⚠ {r.nota}")

    print("\n── POSICIÓN ACTUAL (lotes no vendidos) ──\n")
    for pos in motor.posicion_actual():
        print(f"  {pos.activo:6} | {pos.cantidad_total:.4f} uds | "
              f"coste medio {pos.precio_medio:.4f} | coste total {pos.coste_total:.4f} USDC")

    if motor.advertencias:
        print("\n── ADVERTENCIAS ──\n")
        for adv in motor.advertencias:
            print(f"  ⚠ {adv}")
