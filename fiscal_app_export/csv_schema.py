"""
Infraestructura común de lectura, normalización y validación de cabeceras CSV.

Generaliza el patrón que introdujo clasificador_bitvavo.py (_COL_ALIASES,
_normalizar_columnas, _validar_columnas) para que cualquier clasificador pueda
reutilizarlo. Bitvavo no se migra en este cambio: su lector combina esta lógica
con reintentos propios de separador × encoding (ver _leer_csv_bitvavo).

Primer consumidor: los clasificadores de Binance (clasificador.py y
clasificador_binance_tx.py).
"""

from __future__ import annotations

import io
import logging
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)


class CsvUserError(ValueError):
    """
    Error de procesamiento de CSV con mensaje listo para mostrar al usuario.

    app.py lee `category` y `code` vía hasattr() en el handler genérico de
    /api/analizar para categorizar la observabilidad, igual que hace con
    BinanceUserError y MexcUserError. El mensaje (str(exc)) se muestra tal
    cual al usuario vía _error_amigable, por lo que nunca debe contener
    tracebacks, nombres de clases ni detalles internos.

    category: "user_error" (archivo imputable al usuario, no accionable)
              o "parser_error" (posible formato nuevo, accionable).
    """

    def __init__(self, code: str, mensaje_usuario: str, category: str = "user_error"):
        super().__init__(mensaje_usuario)
        self.code = code
        self.category = category


def normalizar_cabeceras(columnas) -> List[str]:
    """
    Normaliza nombres de columna: BOM, espacios laterales y espacios múltiples
    internos. Deliberadamente sin case-folding ni cambios de puntuación: dos
    columnas distintas nunca deben poder confundirse por la normalización.
    """
    out = []
    for c in columnas:
        c = str(c).lstrip("\ufeff").strip()
        c = " ".join(c.split())
        out.append(c)
    return out


def resolver_alias(df: pd.DataFrame, aliases: Dict[str, List[str]]) -> pd.DataFrame:
    """
    Renombra columnas a su nombre canónico usando alias explícitos.
    Mismo comportamiento que _normalizar_columnas de clasificador_bitvavo.py:
    solo renombra lo que existe, primer alias que hace match gana, y una
    columna ya canónica nunca se toca.
    """
    col_map: Dict[str, str] = {}
    df_cols = set(df.columns)
    for canonical, variantes in aliases.items():
        if canonical in df_cols:
            continue
        for v in variantes:
            if v in df_cols:
                col_map[v] = canonical
                break
    return df.rename(columns=col_map) if col_map else df


def columnas_ausentes(df: pd.DataFrame, obligatorias: List[str]) -> List[str]:
    """Devuelve las columnas obligatorias que faltan tras la normalización."""
    return [c for c in obligatorias if c not in df.columns]


def leer_csv_texto(filepath: str, **read_kwargs) -> pd.DataFrame | None:
    """
    pd.read_csv con dos protecciones sobre el comportamiento por defecto:

    1. EmptyDataError (archivo sin contenido parseable) → devuelve None en
       lugar de propagar la excepción de pandas; el llamador decide el mensaje.
    2. Repara CSV cuyas líneas completas vienen envueltas en un único par de
       comillas — `"col1,col2,col3"` — que pandas colapsa en una sola columna.
       Variante observada en exports reales de Binance (incidente 6b73e4de).
       La reparación solo se acepta si produce más de una columna; en caso
       contrario se devuelve el DataFrame original sin modificar.
    """
    try:
        df = pd.read_csv(filepath, **read_kwargs)
    except pd.errors.EmptyDataError:
        return None

    if df.shape[1] == 1 and "," in str(df.columns[0]):
        reparado = _reparar_lineas_entrecomilladas(filepath, **read_kwargs)
        if reparado is not None:
            logger.info(
                "csv_schema: CSV con líneas entrecomilladas reparado (%d columnas)",
                reparado.shape[1],
            )
            return reparado
    return df


def _reparar_lineas_entrecomilladas(filepath: str, **read_kwargs) -> pd.DataFrame | None:
    """
    Quita el par de comillas envolvente de cada línea y reintenta el parseo.
    Devuelve None si la reparación no produce un CSV multi-columna.
    """
    try:
        with open(filepath, encoding="utf-8-sig", errors="replace") as f:
            lineas = f.read().splitlines()
        desenvueltas = []
        for linea in lineas:
            linea = linea.strip()
            if len(linea) >= 2 and linea.startswith('"') and linea.endswith('"'):
                linea = linea[1:-1]
            desenvueltas.append(linea)
        read_kwargs.pop("encoding", None)  # el texto ya está decodificado
        df = pd.read_csv(io.StringIO("\n".join(desenvueltas)), **read_kwargs)
        return df if df.shape[1] > 1 else None
    except Exception:
        return None
