"""Borrador de cobertura Binance: jamás es un cálculo fiscal FIFO.

Este objeto permite devolver un resultado útil cuando faltan datos y el
informe definitivo no puede emitirse. Sin importes, lotes, contrapartes,
identificadores, transacciones individuales o valores EUR inventados.
"""
from __future__ import annotations


def construir_borrador_binance(clasificador, diagnostico: dict, ejercicio: str = "") -> dict:
    if clasificador is None or not isinstance(diagnostico, dict):
        raise ValueError("El borrador requiere clasificación y diagnóstico")

    def contar(nombre):
        grupo = getattr(clasificador, nombre, ()) or ()
        return len(grupo)

    archivos = getattr(clasificador, "resumen_archivos", {}) or {}
    fuentes = []
    for clave, estado in sorted(archivos.items()):
        if not isinstance(estado, dict) or not estado.get("detectado"):
            continue
        n = estado.get("registros", 0)
        fuentes.append({
            "tipo": str(clave)[:64],
            "registros": n if type(n) is int and n >= 0 else None,
            "vacio": bool(estado.get("vacio")),
        })

    comisiones = getattr(clasificador, "commission_evidence_summary", None)
    cantidad_comisiones = getattr(comisiones, "records", 0)
    if type(cantidad_comisiones) is not int or cantidad_comisiones < 0:
        cantidad_comisiones = None

    def grupo_incidencia(codigo: str) -> str:
        # La agrupación solo organiza el diagnóstico; no modifica cálculos.
        label = codigo.lower()
        if any(mark in label for mark in ("earn", "recompensa", "reward", "staking", "lotes")):
            return "earn"
        if any(mark in label for mark in ("comision", "comisiones", "rebate", "referid")):
            return "comisiones"
        return "operaciones"

    incidencias = []
    for item in (diagnostico.get("incidencias") or ())[:50]:
        if not isinstance(item, dict):
            continue
        entry = {
            key: str(item.get(key) or "")[:1600]
            for key in ("codigo", "titulo", "descripcion", "siguiente_paso")
        }
        entry["grupo"] = grupo_incidencia(entry["codigo"])
        incidencias.append(entry)

    return {
        "version": 1,
        "estado": "INCOMPLETO_NO_APTO_PARA_DECLARAR",
        "tipo": "BORRADOR_DOCUMENTAL_NO_FIFO_FISCAL",
        "ejercicio_solicitado": str(ejercicio or "todos")[:40],
        "no_es_informe_fiscal": True,
        "costes_fifo_calculados": False,
        "ganancias_y_perdidas_eur": None,
        "pdf_fiscal_disponible": False,
        "descripcion": (
            "Este documento inventaría fuentes y operaciones detectadas. "
            "NO calcula ganancias, pérdidas ni coste FIFO global. "
            "No debe presentarse a la AEAT ni utilizarse como declaración."
        ),
        "operaciones_detectadas": {
            "compraventas_candidatas": contar("compraventas"),
            "permutas_candidatas": contar("swaps"),
            "rendimientos_candidatos": contar("rendimientos"),
            "movimientos_candidatos": contar("movimientos"),
            "operaciones_no_reconocidas": contar("desconocidas"),
            "comisiones_referidos_analizadas": cantidad_comisiones,
        },
        "fuentes": fuentes,
        "pendientes": incidencias,
        "nota": (
            "Las cantidades de tipos de evento son registros clasificados, "
            "no lotes fiscales, no operaciones únicas entre fuentes ni una "
            "comprobación de cobertura histórica completa."
        ),
    }
