"""
Clasificador del Excel "Historial de operaciones" de Bit2Me
Mariano Sevilla — marianosevilla.com

NO confundir con clasificador_bit2me.py:
  · clasificador_bit2me.py      → CSV "Informe Fiscal" (FIFO ya calculado por Bit2Me)
  · clasificador_bit2me_excel.py → Excel "Historial de operaciones" (transacciones
                                    en bruto que alimentan el MotorFIFO existente)

El Excel es una FUENTE DE DATOS para el motor, igual que MEXC/Binance/Nexo.
Expone la misma interfaz que ClasificadorMEXC (compraventas, swaps, rendimientos,
movimientos, desconocidas, advertencias) para ser compatible con
procesar_con_fifo() sin modificar el MotorFIFO.

Esquema fijo del fichero (11 columnas):
  Tipo de operación · Cantidad de destino · Moneda de destino · Cantidad de origen ·
  Moneda de origen · Comisión de la operación · Moneda de la comisión · Exchange ·
  Grupo · Descripción · Fecha

Convenios:
  · destino = lo que ENTRA, origen = lo que SALE
  · FIAT = solo "EUR"; el resto (incl. stablecoins) es cripto con su propio FIFO
  · El resultado es una ESTIMACIÓN; el CSV Informe Fiscal es la vía oficial.
"""

import logging
import warnings
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── EXCEPCIÓN TIPIFICADA ──────────────────────────────────────────────────────

class Bit2MeExcelError(ValueError):
    """
    Error imputable al usuario: fichero que no es el historial de operaciones de
    Bit2Me, Excel corrupto o vacío. No es un bug del parser.
    """
    def __init__(self, code: str, mensaje_usuario: str):
        super().__init__(mensaje_usuario)
        self.code = code
        self.category = "user_error"


# ── DATACLASSES (misma forma que clasificador.py para compatibilidad FIFO) ─────

@dataclass
class OperacionCompraventa:
    fecha: str
    tipo: str            # "COMPRA" | "VENTA"
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
    cuenta: str          # sin valor_eur: no se valora automáticamente (decisión de producto)

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


# ── CONSTANTES ────────────────────────────────────────────────────────────────

FIAT = {"EUR"}

# Cabeceras obligatorias para reconocer el fichero (normalizadas a minúsculas).
COLUMNAS_REQUERIDAS = {
    "tipo de operación", "cantidad de destino", "moneda de destino",
    "cantidad de origen", "moneda de origen", "fecha",
}

TIPOS_CONOCIDOS = {"trade", "staking", "other income", "deposit", "withdrawal"}

_FECHA_FORMATOS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
)


# ── HELPERS DE PARSING (defensivos) ───────────────────────────────────────────

def _norm(v) -> str:
    """Celda → string limpio ('' si vacío/NaN)."""
    if v is None:
        return ""
    if isinstance(v, float) and v != v:   # NaN
        return ""
    return str(v).strip()


def _parse_fecha(v) -> Optional[str]:
    """Devuelve 'YYYY-MM-DD HH:MM:SS' o None si no se reconoce."""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    s = _norm(v)
    if not s or s.lower() == "nan":
        return None
    for fmt in _FECHA_FORMATOS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _parse_decimal(v) -> Optional[Decimal]:
    """
    Convierte a Decimal de forma defensiva. Devuelve None si es irrecuperable
    (p.ej. fees malformados tipo '0.99500.46554750').
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        if v != v:   # NaN
            return None
        return Decimal(str(v))
    s = str(v).strip()
    if not s:
        return None
    try:
        if "," in s:
            # Formato europeo: puntos = miles, coma = decimal.
            s2 = s.replace(".", "").replace(",", ".")
            return Decimal(s2)
        # Punto como decimal: más de un punto ⇒ malformado.
        if s.count(".") > 1:
            return None
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _es_fiat(moneda: str) -> bool:
    return moneda.upper() in FIAT


# ── LECTURA DEL FICHERO (xlsx vía openpyxl, xls vía xlrd, ambos por pandas) ────

def _leer_grid(filepath: str) -> list:
    """Lee la primera hoja como lista de filas (valores nativos)."""
    import pandas as pd
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(filepath, sheet_name=0, header=None, dtype=object)
    return df.values.tolist()


def _localizar_cabecera(grid: list) -> Tuple[int, Dict]:
    """
    Busca la fila de cabecera (la que contiene 'Tipo de operación') y devuelve
    (índice_fila, {nombre_columna_normalizado: índice}).
    """
    for i, fila in enumerate(grid[:15]):   # la cabecera está en las primeras filas
        celdas = {_norm(c).lower(): j for j, c in enumerate(fila) if _norm(c)}
        if "tipo de operación" in celdas:
            return i, celdas
    raise Bit2MeExcelError(
        "wrong_file",
        "El archivo no parece el historial de operaciones de Bit2Me. "
        "Asegúrate de exportarlo desde Mi cuenta → Historial de operaciones.",
    )


def validar_columnas_bit2me_excel(filepath: str) -> Tuple[bool, str]:
    """Validación ligera para la capa HTTP: ¿es el historial de operaciones?"""
    try:
        grid = _leer_grid(filepath)
    except Bit2MeExcelError as e:
        return False, str(e)
    except Exception:
        return False, ("No hemos podido leer el archivo Excel de Bit2Me. "
                       "Descárgalo de nuevo desde tu cuenta sin abrirlo con Excel.")
    if not grid:
        return False, "El archivo Excel está vacío."
    try:
        _, cols = _localizar_cabecera(grid)
    except Bit2MeExcelError as e:
        return False, str(e)
    faltan = COLUMNAS_REQUERIDAS - set(cols)
    if faltan:
        return False, ("El historial de Bit2Me no tiene las columnas esperadas "
                       f"(faltan: {', '.join(sorted(faltan))}).")
    return True, ""


# ── CLASIFICADOR ──────────────────────────────────────────────────────────────

class ClasificadorBit2MeExcel:
    """Historial de operaciones XLS/XLSX de Bit2Me → dataclasses del pipeline."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.compraventas: List[OperacionCompraventa] = []
        self.swaps:        List[OperacionSwap]        = []
        self.rendimientos: List[OperacionRendimiento] = []
        self.movimientos:  List[OperacionMovimiento]  = []
        self.desconocidas: List[OperacionDesconocida] = []
        self.advertencias: List[str] = []

        # Acumuladores para advertencias
        self._depositos_cripto: List[str]       = []   # activos depositados sin coste
        self._rend_por_activo:  Dict[str, float] = {}   # staking/other income sin valor
        self._fees_malformados: int             = 0
        self._withdrawals_cripto: int           = 0
        self._fecha_min:        Optional[str]    = None

    # ── ENTRADA PÚBLICA ─────────────────────────────────────────────────────

    def clasificar(self) -> "ClasificadorBit2MeExcel":
        grid = _leer_grid(self.filepath)
        if not grid:
            raise Bit2MeExcelError("empty_file", "El archivo Excel está vacío.")

        hdr_idx, cols = _localizar_cabecera(grid)
        faltan = COLUMNAS_REQUERIDAS - set(cols)
        if faltan:
            raise Bit2MeExcelError(
                "wrong_file",
                "El historial de Bit2Me no tiene las columnas esperadas "
                f"(faltan: {', '.join(sorted(faltan))}).",
            )

        for fila in grid[hdr_idx + 1:]:
            self._procesar_fila(fila, cols)

        self._construir_advertencias()
        return self

    # ── PROCESADO DE UNA FILA ───────────────────────────────────────────────

    def _get(self, fila, cols, nombre):
        idx = cols.get(nombre)
        if idx is None or idx >= len(fila):
            return None
        return fila[idx]

    def _procesar_fila(self, fila, cols) -> None:
        tipo_raw = _norm(self._get(fila, cols, "tipo de operación"))
        if not tipo_raw:
            return   # fila en blanco

        fecha = _parse_fecha(self._get(fila, cols, "fecha"))
        cant_dst = _parse_decimal(self._get(fila, cols, "cantidad de destino"))
        mon_dst  = _norm(self._get(fila, cols, "moneda de destino")).upper()
        cant_org = _parse_decimal(self._get(fila, cols, "cantidad de origen"))
        mon_org  = _norm(self._get(fila, cols, "moneda de origen")).upper()
        fee_raw  = self._get(fila, cols, "comisión de la operación")
        grupo    = _norm(self._get(fila, cols, "grupo"))
        desc     = _norm(self._get(fila, cols, "descripción"))

        if fecha is None:
            self._desconocida("", "fecha_invalida", mon_dst or mon_org, cant_dst)
            return
        if self._fecha_min is None or fecha < self._fecha_min:
            self._fecha_min = fecha

        # Fee (siempre en EUR). Si no se puede interpretar pero había algo → malformado.
        fee = _parse_decimal(fee_raw)
        if fee is None and _norm(fee_raw) not in ("", "0"):
            self._fees_malformados += 1
            fee = Decimal(0)
        elif fee is None:
            fee = Decimal(0)

        tipo = tipo_raw.lower()
        if tipo == "trade":
            self._trade(fecha, cant_dst, mon_dst, cant_org, mon_org, fee, tipo_raw)
        elif tipo in ("staking", "other income"):
            self._rendimiento(fecha, tipo_raw, cant_dst, mon_dst)
        elif tipo == "deposit":
            self._deposit(fecha, cant_dst, mon_dst, grupo)
        elif tipo == "withdrawal":
            self._withdrawal(fecha, cant_dst, mon_dst, desc, grupo)
        else:
            self._desconocida(fecha, f"tipo:{tipo_raw}", mon_dst or mon_org, cant_dst)

    # ── MAPEOS POR TIPO ─────────────────────────────────────────────────────

    def _trade(self, fecha, cant_dst, mon_dst, cant_org, mon_org, fee, tipo_raw) -> None:
        if not mon_dst or not mon_org or cant_dst is None or cant_org is None \
                or cant_dst <= 0 or cant_org <= 0:
            self._desconocida(fecha, "trade_no_clasificable", mon_dst or mon_org, cant_dst)
            return

        dst_fiat, org_fiat = _es_fiat(mon_dst), _es_fiat(mon_org)

        if org_fiat and not dst_fiat:
            # EUR → cripto = COMPRA
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha, tipo="COMPRA", activo=mon_dst, cantidad=float(cant_dst),
                contraparte="EUR", importe=float(cant_org),
                fee_activo="EUR", fee_cantidad=float(fee)))
        elif dst_fiat and not org_fiat:
            # cripto → EUR = VENTA
            self.compraventas.append(OperacionCompraventa(
                fecha=fecha, tipo="VENTA", activo=mon_org, cantidad=float(cant_org),
                contraparte="EUR", importe=float(cant_dst),
                fee_activo="EUR", fee_cantidad=float(fee)))
        elif not dst_fiat and not org_fiat:
            # cripto ↔ cripto = PERMUTA (swap). El motor valora por coste FIFO.
            self.swaps.append(OperacionSwap(
                fecha=fecha, activo_entregado=mon_org, cantidad_entregada=float(cant_org),
                activo_recibido=mon_dst, cantidad_recibida=float(cant_dst),
                nota=f"permuta Bit2Me; fee {float(fee)} EUR"))
        else:
            # EUR ↔ EUR u otro caso no esperado
            self._desconocida(fecha, "trade_no_clasificable", mon_dst, cant_dst)

    def _rendimiento(self, fecha, tipo_raw, cant_dst, mon_dst) -> None:
        if cant_dst is None or cant_dst <= 0 or not mon_dst:
            self._desconocida(fecha, f"rendimiento_invalido:{tipo_raw}", mon_dst, cant_dst)
            return
        self.rendimientos.append(OperacionRendimiento(
            fecha=fecha, subtipo=tipo_raw, activo=mon_dst,
            cantidad=float(cant_dst), cuenta="Bit2Me"))
        self._rend_por_activo[mon_dst] = self._rend_por_activo.get(mon_dst, 0.0) + float(cant_dst)

    def _deposit(self, fecha, cant_dst, mon_dst, grupo) -> None:
        if cant_dst is None or cant_dst <= 0 or not mon_dst:
            self._desconocida(fecha, "deposit_invalido", mon_dst, cant_dst)
            return
        if _es_fiat(mon_dst):
            # Depósito de EUR: movimiento, sin impacto FIFO.
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Deposit EUR", activo="EUR",
                cantidad=float(cant_dst), observacion=grupo or "Depósito EUR"))
            return
        # Depósito de cripto externa: COMPRA con importe=0 (coste desconocido) +
        # advertencia. Conserva inventario/posición; nunca en silencio (decisión §6).
        self.compraventas.append(OperacionCompraventa(
            fecha=fecha, tipo="COMPRA", activo=mon_dst, cantidad=float(cant_dst),
            contraparte="EUR", importe=0.0, fee_activo="EUR", fee_cantidad=0.0))
        self._depositos_cripto.append(mon_dst)

    def _withdrawal(self, fecha, cant_dst, mon_dst, desc, grupo) -> None:
        if cant_dst is None or cant_dst <= 0 or not mon_dst:
            self._desconocida(fecha, "withdrawal_invalido", mon_dst, cant_dst)
            return
        if _es_fiat(mon_dst):
            self.movimientos.append(OperacionMovimiento(
                fecha=fecha, subtipo="Withdrawal EUR", activo="EUR",
                cantidad=float(cant_dst), observacion=grupo or "Retiro EUR"))
            return
        obs = desc[:80] if desc else (grupo or "Retiro")
        self.movimientos.append(OperacionMovimiento(
            fecha=fecha, subtipo="Withdrawal", activo=mon_dst,
            cantidad=float(cant_dst), observacion=obs))
        self._withdrawals_cripto += 1

    def _desconocida(self, fecha, subtipo, activo, cantidad) -> None:
        self.desconocidas.append(OperacionDesconocida(
            fecha=fecha or "", subtipo=subtipo, activo=activo or "?",
            cantidad=float(cantidad) if cantidad is not None else 0.0, cuenta="Bit2Me"))

    # ── ADVERTENCIAS ────────────────────────────────────────────────────────

    def _construir_advertencias(self) -> None:
        if self._depositos_cripto:
            coins = ", ".join(sorted(set(self._depositos_cripto)))
            self.advertencias.append(
                f"Detectados {len(self._depositos_cripto)} depósitos de criptomonedas "
                f"({coins}) sin coste de adquisición conocido. Se han registrado con "
                f"coste 0, por lo que su ganancia al venderlas puede estar sobreestimada. "
                f"Revisa su origen y coste real.")
        if self._rend_por_activo:
            total = sum(self._rend_por_activo.values())
            coins = ", ".join(f"{round(v, 8)} {k}" for k, v in sorted(self._rend_por_activo.items()))
            self.advertencias.append(
                f"Detectadas recompensas (Staking / Other Income) sin valoración en EUR: "
                f"{coins}. Debes asignarles el valor de mercado en su fecha de cobro "
                f"para tu declaración (no se han valorado automáticamente).")
        if self._fees_malformados:
            self.advertencias.append(
                f"{self._fees_malformados} comisión(es) no se pudieron interpretar y se "
                f"han tratado como 0. Verifica los importes de comisión.")
        if self._fecha_min:
            self.advertencias.append(
                f"El cálculo FIFO es acumulativo. Si operaste con estos activos antes de "
                f"la primera fecha del fichero ({self._fecha_min[:10]}), el coste de "
                f"adquisición puede estar incompleto.")
        if self._withdrawals_cripto:
            self.advertencias.append(
                f"Detectadas {self._withdrawals_cripto} retiradas de cripto. Se tratan como "
                f"salidas sin ganancia/pérdida y no reducen el inventario FIFO. Si alguna "
                f"fue una venta, decláralas aparte.")
        if self.desconocidas:
            subtipos = ", ".join(sorted({d.subtipo for d in self.desconocidas}))
            self.advertencias.append(
                f"{len(self.desconocidas)} operación(es) no se pudieron clasificar "
                f"({subtipos}) y no se han incluido en el cálculo.")

    # ── RESUMEN (informativo) ───────────────────────────────────────────────

    def resumen(self) -> dict:
        return {
            "compraventas": len(self.compraventas),
            "swaps":        len(self.swaps),
            "rendimientos": len(self.rendimientos),
            "movimientos":  len(self.movimientos),
            "desconocidas": len(self.desconocidas),
            "advertencias": len(self.advertencias),
        }


if __name__ == "__main__":
    import sys
    ruta = sys.argv[1] if len(sys.argv) > 1 else "bit2me.xlsx"
    c = ClasificadorBit2MeExcel(ruta).clasificar()
    print("RESUMEN:", c.resumen())
    for a in c.advertencias:
        print("  ⚠", a)
