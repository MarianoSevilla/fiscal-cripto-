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
from typing import Dict, List, Optional


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
    inventario_incompleto: bool = False  # True si faltan lotes previos → coste parcial o nulo

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
        self.inventario: Dict[str, List[Lote]] = defaultdict(list)
        # Resultados de ventas/swaps
        self.resultados: List[ResultadoFIFO] = []
        # Operaciones que no se pudieron procesar
        self.advertencias: List[str] = []

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

        if importe < 0 or cantidad_neta <= 0:
            self.advertencias.append(f"{fecha} | COMPRA {activo} — importe o cantidad inválidos")
            return

        # importe == 0 es válido (ej. dust conversions, airdrops sin valor declarado)
        # → el lote entra al inventario con coste base cero
        precio_unitario = importe / cantidad_neta if cantidad_neta > 0 else 0.0

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

        El precio de transmisión del activo entregado —y el coste base del
        activo recibido— se determina así:
          · Stablecoin o EUR entregado → valor EUR ≈ cantidad entregada (1:1).
          · Cripto entregada           → valor EUR = coste FIFO de los lotes
                                         consumidos (mejor aproximación sin
                                         precio de mercado en tiempo real).
          · Sin inventario previo      → valor EUR = 0 + advertencia.

        CORRECCIÓN (bug anterior): antes se usaba `precio_transmision =
        cantidad_recibida`, lo que asignaba las unidades del activo recibido
        como si fueran euros, produciendo costes base absurdos (p.ej. 1 EUR/BTC).
        """
        dt = self._parsear_fecha(fecha)

        # Ignorar swaps donde entregado == recibido (movimiento interno)
        if activo_entregado == activo_recibido:
            self.advertencias.append(
                f"{fecha} | SWAP {activo_entregado}→{activo_recibido} ignorado "
                f"(mismo activo, movimiento interno)"
            )
            return

        # ── Determinar valor EUR del activo entregado ───────────────────────
        if activo_entregado in self.STABLES or activo_entregado == "EUR":
            # Stablecoin o fiat: 1 unidad ≈ 1 EUR (aproximación)
            valor_eur_entregado = cantidad_entregada
        else:
            # Cripto: usar el coste FIFO de los lotes que se van a consumir
            # como mejor aproximación del valor de mercado en EUR.
            valor_eur_entregado = self._coste_fifo_peek(activo_entregado, cantidad_entregada)
            if valor_eur_entregado is None:
                self.advertencias.append(
                    f"{fecha} | SWAP {activo_entregado}→{activo_recibido} — "
                    f"sin inventario previo de {activo_entregado}: el coste base "
                    f"asignado a {activo_recibido} es cero. Requiere valoración manual."
                )
                valor_eur_entregado = 0.0

        # ── 1) Procesar venta del activo entregado ───────────────────────────
        resultado = self._consumir_fifo(
            dt=dt,
            activo=activo_entregado,
            cantidad=cantidad_entregada,
            precio_transmision=valor_eur_entregado,
            tipo="swap",
            nota=nota
        )
        if resultado:
            self.resultados.append(resultado)

        # ── 2) Registrar activo recibido con coste base = valor EUR entregado
        if cantidad_recibida > 0:
            precio_unitario_recibido = (
                valor_eur_entregado / cantidad_recibida
                if valor_eur_entregado > 0 else 0.0
            )
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

    def _coste_fifo_peek(self, activo: str, cantidad: float) -> Optional[float]:
        """
        Estima el coste FIFO total de `cantidad` unidades de `activo`
        SIN modificar el inventario (lectura). Se usa para calcular el
        valor EUR de un activo cripto que se va a entregar en un swap.
        Devuelve None si no existe inventario previo del activo.
        """
        cola = self.inventario.get(activo, [])
        lotes_vivos = [l for l in cola if l.cantidad_restante > 1e-9]
        if not lotes_vivos:
            return None
        pendiente = cantidad
        coste = 0.0
        for lote in lotes_vivos:
            if pendiente <= 0:
                break
            consumir = min(lote.cantidad_restante, pendiente)
            coste += consumir * lote.precio_coste_unitario
            pendiente -= consumir
        return coste

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

        _incompleto = cantidad_pendiente > 0.0001  # True si faltan unidades por inventario insuficiente

        if _incompleto:
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
            nota=nota,
            inventario_incompleto=_incompleto,
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

    def posicion_a_fecha(self, fecha_corte: datetime) -> list[ResumenActivo]:
        """
        Reconstruye la posición de cada activo exactamente a fecha_corte
        mediante un snapshot replay no destructivo del inventario.

        A diferencia de posicion_actual(), que refleja el estado actual
        (tras TODAS las operaciones), este método devuelve la posición a
        fecha_corte exacta:
          · Solo incluye lotes de compra/swap creados en fecha ≤ fecha_corte.
          · Solo aplica ventas/swaps ocurridos en fecha ≤ fecha_corte.
          · No muta ni el inventario ni los resultados del motor original.

        Uso principal: snapshot a 31/12 del ejercicio para el Modelo 721.

        Algoritmo:
          1. Snapshot — copia virtual del inventario: solo lotes ≤ fecha_corte,
             cada uno empezando en su cantidad_original (ignorando las mutaciones
             posteriores sobre cantidad_restante causadas por ventas futuras).
          2. Replay — aplica en orden cronológico todas las ventas/swaps
             ≤ fecha_corte sobre el snapshot (mismo orden FIFO que el motor real).
          3. Output — construye ResumenActivo con nuevos objetos Lote que reflejan
             la cantidad_restante correcta a fecha_corte.
        """
        # ── 1. Snapshot: lotes con fecha ≤ fecha_corte, cantidad = original ──
        snapshot: Dict[str, list] = {}
        for activo, lotes in self.inventario.items():
            for lote in lotes:
                if lote.fecha > fecha_corte:
                    continue
                if activo not in snapshot:
                    snapshot[activo] = []
                snapshot[activo].append({
                    "lote":              lote,
                    "cantidad_restante": lote.cantidad_original,
                })

        # ── 2. Replay de ventas/swaps ≤ fecha_corte en orden cronológico ─────
        # sorted() es estable: si dos resultados tienen la misma fecha exacta,
        # se preserva el orden de inserción original (cronológico por el CSV).
        for resultado in sorted(
            (r for r in self.resultados if r.fecha <= fecha_corte),
            key=lambda r: r.fecha,
        ):
            activo = resultado.activo
            if activo not in snapshot:
                continue
            pendiente = resultado.cantidad_vendida
            for entry in snapshot[activo]:
                if pendiente <= 1e-9:
                    break
                consumir = min(entry["cantidad_restante"], pendiente)
                entry["cantidad_restante"] -= consumir
                pendiente -= consumir

        # ── 3. Construir ResumenActivo con nuevos Lote a fecha_corte ─────────
        # Umbral 1e-9: más preciso que posicion_actual (0.0001) para no perder
        # posiciones pequeñas pero reales (dust a efectos fiscales).
        _UMBRAL = 1e-9
        resultado_final = []
        for activo, entries in snapshot.items():
            vivos = [e for e in entries if e["cantidad_restante"] > _UMBRAL]
            if not vivos:
                continue
            cantidad = sum(e["cantidad_restante"] for e in vivos)
            coste    = sum(
                e["cantidad_restante"] * e["lote"].precio_coste_unitario
                for e in vivos
            )
            # Nuevos objetos Lote con la cantidad_restante correcta a fecha_corte.
            # El motor original no se toca: lote.cantidad_restante permanece intacto.
            lotes_corte = [
                Lote(
                    fecha=e["lote"].fecha,
                    cantidad_original=e["lote"].cantidad_original,
                    cantidad_restante=e["cantidad_restante"],
                    precio_coste_unitario=e["lote"].precio_coste_unitario,
                    contraparte=e["lote"].contraparte,
                    origen=e["lote"].origen,
                )
                for e in vivos
            ]
            resultado_final.append(ResumenActivo(
                activo=activo,
                cantidad_total=cantidad,
                coste_total=coste,
                precio_medio=coste / cantidad if cantidad > 0 else 0,
                lotes=lotes_corte,
            ))
        return resultado_final

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
        texto = fecha.strip()
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y",
            # Exportaciones con milisegundos/microsegundos
            # (str(pandas.Timestamp) y formatos recientes de exchanges)
            "%Y-%m-%d %H:%M:%S.%f",
            "%d/%m/%Y %H:%M:%S.%f",
            # Variantes ISO-8601 con separador 'T'
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                return datetime.strptime(texto, fmt)
            except ValueError:
                continue
        # Último recurso: ISO-8601 con offset horario ("+00:00" o sufijo "Z").
        # El motor trabaja con datetimes naive → se descarta el tzinfo.
        try:
            dt = datetime.fromisoformat(texto.replace("Z", "+00:00"))
            return dt.replace(tzinfo=None)
        except ValueError:
            pass
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
