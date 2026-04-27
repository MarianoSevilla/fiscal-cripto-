"""
Clasificador fiscal de operaciones Bit2Me
Mariano Sevilla — marianosevilla.com
v4.0 — parser robusto basado en búsqueda inversa desde Yes

Bit2Me exporta el informe fiscal en CSV vertical (un dato por línea).
Las filas con resultado fiscal están marcadas con "Yes" al final.
Leemos directamente esos resultados en lugar de recalcular con FIFO propio.

Estructura de una fila de detalle FIFO (Buy + Yes):
  [ID] → Fecha → Buy → Cant → Activo → Cant2 → Activo2 → Cuota → CosteAdq → VentasIng → GanCap → Yes

Los tickers con números (API3, B2M) aparecen partidos en dos valores en el CSV.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


FECHA_RE = re.compile(r'^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}$')
TIPOS_OP = {"Buy", "Sell", "Fee", "Staking", "Airdrop", "Deposit",
            "Withdrawal", "Transfer", "Mining", "Lending", "Cashback"}
STABLES  = {"EUR", "USDT", "USDC", "BUSD", "EURC", "EURR", "EURT", "DAI", "FDUSD"}


@dataclass
class ResultadoFiscal:
    fecha_venta:        str
    fecha_compra:       str
    tipo_op:            str
    activo:             str
    activo_contraparte: str
    cantidad:           float
    precio_transmision: float
    precio_coste:       float
    ganancia_perdida:   float

@dataclass
class OperacionRendimiento:
    fecha:     str
    subtipo:   str
    activo:    str
    cantidad:  float
    valor_eur: float

@dataclass
class OperacionMovimiento:
    fecha:    str
    subtipo:  str
    activo:   str
    cantidad: float


def _parse_fecha(s: str) -> str:
    try:
        return datetime.strptime(s, "%d.%m.%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return s

def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(".", "").replace(",", "."))
    except Exception:
        return None

def _es_numero(s: str) -> bool:
    return _to_float(s) is not None

def _es_fecha(s: str) -> bool:
    return bool(FECHA_RE.match(s))


class ClasificadorBit2Me:

    def __init__(self, filepath: str):
        self.filepath      = filepath
        self.resultados:   list[ResultadoFiscal]      = []
        self.rendimientos: list[OperacionRendimiento] = []
        self.movimientos:  list[OperacionMovimiento]  = []
        self.advertencias: list[str] = []

    def clasificar(self):
        valores = self._extraer_valores()
        self._parsear_desde_yes(valores)
        return self

    def _extraer_valores(self) -> list[str]:
        """Lee el CSV y extrae el contenido de cada celda, línea a línea."""
        valores = []
        with open(self.filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line in ('""', '","'):
                    continue
                partes = re.findall(r'"([^"]*)"', line)
                for p in partes:
                    p = p.strip()
                    if p:
                        valores.append(p)
        return valores

    def _reconstruir_bloque(self, valores: list[str], yes_idx: int) -> Optional[dict]:
        """
        Busca hacia atrás desde yes_idx el bloque de operación.
        Maneja tickers partidos (API3 → "API","3"; B2M → "B","2M").
        Busca la fecha más cercana hacia atrás en un rango de 7-18 posiciones.
        """
        n = len(valores)

        for dist in range(6, 26):  # hasta 25 para cubrir cabeceras de página
            fecha_idx = yes_idx - dist
            if fecha_idx < 1:
                break

            fecha_val = valores[fecha_idx]
            if not _es_fecha(fecha_val):
                continue

            # Comprobar que hay un tipo de operación justo después de la fecha
            tipo_idx = fecha_idx + 1
            if tipo_idx >= yes_idx:
                continue
            tipo = valores[tipo_idx]
            if tipo not in TIPOS_OP:
                continue

            # Leer campos desde tipo_idx+1 hasta yes_idx-1
            campos = valores[tipo_idx + 1: yes_idx]

            # Parsear campos con soporte para tickers partidos
            # Estructura esperada: cant_e, activo_e, cant_s, activo_s, [cuota,] coste, ventas, gan
            resultado = self._parsear_campos(campos, tipo, fecha_val)
            if resultado:
                return resultado

        return None

    def _parsear_campos(self, campos: list[str], tipo: str, fecha: str) -> Optional[dict]:
        """
        Parsea la lista de campos entre el tipo y el Yes.
        Los tickers pueden estar partidos en 2 tokens.
        """
        if len(campos) < 6:
            return None

        j = 0

        def leer_numero() -> Optional[float]:
            nonlocal j
            if j >= len(campos):
                return None
            v = _to_float(campos[j])
            if v is not None:
                j += 1
                return v
            return None

        def leer_activo() -> str:
            nonlocal j
            if j >= len(campos):
                return ""
            activo = campos[j]; j += 1
            # Si lo siguiente NO es número, es parte del ticker
            if (j < len(campos) and
                    not _es_numero(campos[j]) and
                    not _es_fecha(campos[j]) and
                    campos[j] != "Yes"):
                activo += campos[j]; j += 1
            return activo

        # Leer: cant_entrada, activo_entrada, cant_salida, activo_salida
        cant_e = leer_numero()
        if cant_e is None:
            return None
        activo_e = leer_activo()

        cant_s = leer_numero()
        if cant_s is None:
            return None
        activo_s = leer_activo()

        # Quedan entre 3 y 4 números: [cuota,] coste, ventas, gan_cap
        nums_restantes = []
        while j < len(campos):
            v = _to_float(campos[j])
            if v is not None:
                nums_restantes.append(v)
                j += 1
            else:
                break  # texto inesperado → no es un bloque válido

        if len(nums_restantes) == 3:
            coste, ventas, gan = nums_restantes
        elif len(nums_restantes) == 4:
            _, coste, ventas, gan = nums_restantes  # cuota, coste, ventas, gan
        else:
            return None

        return {
            "fecha": fecha,
            "tipo": tipo,
            "activo_e": activo_e,
            "cant_e": cant_e,
            "activo_s": activo_s,
            "cant_s": cant_s,
            "coste": coste,
            "ventas": ventas,
            "gan": gan,
        }

    def _parsear_desde_yes(self, valores: list[str]):
        """Procesa todos los bloques con Yes buscando hacia atrás."""
        yes_indices = [i for i, v in enumerate(valores) if v == "Yes"]
        fallidos = 0

        for idx in yes_indices:
            bloque = self._reconstruir_bloque(valores, idx)
            if not bloque:
                fallidos += 1
                continue

            tipo     = bloque["tipo"]
            fecha    = _parse_fecha(bloque["fecha"])
            activo_e = bloque["activo_e"]
            activo_s = bloque["activo_s"]
            cant_e   = bloque["cant_e"]
            cant_s   = bloque["cant_s"]
            coste    = bloque["coste"]
            ventas   = bloque["ventas"]
            gan      = bloque["gan"]

            if tipo == "Buy":
                # activo_e = cripto comprado, activo_s = con qué se pagó
                activo = activo_e
                contra = activo_s or "EUR"
                t_op = "swap" if (contra not in STABLES and contra) else "venta"
                self.resultados.append(ResultadoFiscal(
                    fecha_venta=fecha,
                    fecha_compra=fecha,
                    tipo_op=t_op,
                    activo=activo,
                    activo_contraparte=contra,
                    cantidad=cant_e,
                    precio_transmision=ventas,
                    precio_coste=coste,
                    ganancia_perdida=gan
                ))

            elif tipo == "Staking":
                activo   = activo_e or activo_s
                cantidad = cant_e or cant_s
                self.rendimientos.append(OperacionRendimiento(
                    fecha=fecha, subtipo="Staking",
                    activo=activo, cantidad=cantidad,
                    valor_eur=coste
                ))

        # Deduplicar bloques capturados múltiples veces
        vistos: set = set()
        dedup = []
        for r in self.resultados:
            key = (r.fecha_venta, r.activo, round(r.cantidad, 6),
                   round(r.precio_coste, 4), round(r.precio_transmision, 4),
                   round(r.ganancia_perdida, 4))
            if key not in vistos:
                vistos.add(key)
                dedup.append(r)
        self.resultados = dedup

        if fallidos > 0:
            self.advertencias.append(
                f"{fallidos} operaciones de Bit2Me no pudieron parsearse "
                f"(pueden ser movimientos internos sin impacto fiscal)."
            )

    def resumen_fiscal(self) -> dict:
        ganancias = sum(r.ganancia_perdida for r in self.resultados if r.ganancia_perdida > 0)
        perdidas  = sum(r.ganancia_perdida for r in self.resultados if r.ganancia_perdida < 0)
        neto      = ganancias + perdidas
        return {
            "operaciones_con_resultado": len(self.resultados),
            "ganancias_brutas":          round(ganancias, 2),
            "perdidas_brutas":           round(perdidas, 2),
            "resultado_neto":            round(neto, 2),
        }

    def resumen(self) -> dict:
        r = self.resumen_fiscal()
        r["rendimientos"] = len(self.rendimientos)
        r["movimientos"]  = len(self.movimientos)
        return r


if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "bit2me.csv"
    print(f"\nProcesando: {ruta}\n")

    c = ClasificadorBit2Me(ruta).clasificar()
    r = c.resumen_fiscal()

    print("=" * 55)
    print("RESUMEN FISCAL — BIT2ME")
    print("=" * 55)
    print(f"  Operaciones con resultado: {r['operaciones_con_resultado']:>8}")
    print(f"  Ganancias brutas:          {r['ganancias_brutas']:>10.2f} EUR")
    print(f"  Perdidas brutas:           {r['perdidas_brutas']:>10.2f} EUR")
    print(f"  Resultado neto:            {r['resultado_neto']:>10.2f} EUR")
    print(f"  Rendimientos (Staking):    {len(c.rendimientos):>8}")
    if c.advertencias:
        print()
        for adv in c.advertencias:
            print(f"  ⚠  {adv}")
    print()
    print("INFORME OFICIAL BIT2ME:")
    print(f"  Ganancias brutas:          {271.77:>10.2f} EUR")
    print(f"  Perdidas brutas:           {-2345.49:>10.2f} EUR")
    print(f"  Resultado neto:            {-2073.72:>10.2f} EUR")
    print()
    dif_gan = r['ganancias_brutas'] - 271.77
    dif_per = r['perdidas_brutas'] - (-2345.49)
    dif_net = r['resultado_neto'] - (-2073.72)
    estado  = lambda d: 'OK ✓' if abs(d) < 2 else 'REVISAR'
    print("DIFERENCIAS:")
    print(f"  Ganancias: {dif_gan:>+10.2f} EUR  {estado(dif_gan)}")
    print(f"  Perdidas:  {dif_per:>+10.2f} EUR  {estado(dif_per)}")
    print(f"  Neto:      {dif_net:>+10.2f} EUR  {estado(dif_net)}")
