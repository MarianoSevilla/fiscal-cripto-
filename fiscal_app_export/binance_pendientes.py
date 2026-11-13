"""Diagnóstico orientativo para recuperar evidencia faltante de Binance.

No infiere que una fuente no subida contenga operaciones, no deduplica eventos
y NUNCA habilita por sí solo la emisión de informes FIFO.
No expone cantidades, fechas de operaciones ni datos identificativos.
"""

from __future__ import annotations


def diagnosticar_pendientes_binance(clasificador) -> dict:
    """Describe vías de subsanación a partir de incidencias ya detectadas.

    La decisión de aceptación fiscal sigue siendo exclusiva del validador
    existente; esta función no calcula, corrige ni autoriza lotes FIFO.
    """
    markers = set(getattr(clasificador, "fuentes_materiales_no_soportadas", ()) or ())
    incidencias = []

    def add(code: str, tipo: str, titulo: str, descripcion: str, siguiente_paso: str):
        incidencias.append({
            "codigo": code,
            "tipo": tipo,
            "titulo": titulo,
            "descripcion": descripcion,
            "siguiente_paso": siguiente_paso,
        })

    if "spot_orders_ejecutadas_sin_fills_completos" in markers:
        add(
            "spot_fills", "archivo", "Faltan ejecuciones Spot",
            "Hay órdenes Spot ejecutadas sin el detalle completo de sus operaciones.",
            "Descarga el Historial de operaciones Spot (ejecuciones o fills) "
            "de las fechas correspondientes y añádelo a los archivos.",
        )

    earn = getattr(clasificador, "earn_reconciliation", None)
    earn_unmatched = getattr(earn, "ledger_unmatched", 0) if earn is not None else 0
    if earn_unmatched:
        add(
            "earn_cobertura", "archivo", "Historial Simple Earn incompleto",
            "Hay movimientos Simple Earn del historial general que no aparecen "
            "en los archivos específicos aportados.",
            "Descarga las suscripciones, reembolsos y recompensas de Simple Earn "
            "de los períodos anteriores que Binance permita exportar. "
            "Si ya no están disponibles, reúne justificantes históricos.",
        )
    if getattr(clasificador, "earn_events", ()) or any(
        m.startswith("earn_") for m in markers
    ):
        add(
            "earn_lotes", "documentacion", "Lotes y recompensas Simple Earn",
            "Los movimientos internos no son compras nuevas; las recompensas "
            "pueden necesitar fecha y valoración EUR para crear un lote.",
            "Aporta exportaciones y justificantes de las recompensas. "
            "El cálculo seguirá bloqueado hasta verificar su tratamiento fiscal.",
        )

    if "filas_identicas_entre_exportaciones_sin_id_unico" in markers:
        add(
            "solapamiento", "revision", "Exportaciones solapadas",
            "Hay registros indistinguibles entre archivos distintos. "
            "No podemos saber automáticamente si son el mismo evento.",
            "Revisa los rangos de exportación y aporta el identificador "
            "de operación o una exportación sin solapamientos si está disponible.",
        )

    if any(
        getattr(m, "subtipo", "") == "Depósito cripto"
        and getattr(m, "cantidad", 0) > 0
        for m in getattr(clasificador, "movimientos", ())
    ):
        add(
            "depositos_origen", "documentacion", "Origen de depósitos de criptomonedas",
            "El depósito acredita la entrada en Binance, pero no necesariamente "
            "la fecha y el coste de la adquisición original.",
            "Aporta el historial del exchange o monedero de origen. Para una "
            "adquisición aislada, documenta fecha, activo, cantidad, coste EUR, "
            "comisiones y justificante, sin inventar el coste.",
        )

    commission = getattr(clasificador, "commission_evidence_summary", None)
    if getattr(commission, "records", 0):
        add(
            "comisiones_afiliacion", "documentacion", "Ingresos y reembolsos de comisiones",
            "Los movimientos de afiliación y de devolución de comisiones "
            "no pueden clasificarse en bloque como compras.",
            "Aporta información del programa de referidos, ingresos y "
            "reembolsos para determinar su tratamiento y valoración EUR.",
        )

    dust = getattr(clasificador, "dust_evidence_summary", None)
    if getattr(dust, "rows", 0):
        add(
            "conversion_saldos", "documentacion", "Conversión de pequeños saldos a BNB",
            "Los apuntes de conversión requieren identificar ambas patas "
            "y sus valores de mercado antes de actualizar el inventario.",
            "Aporta el detalle de las conversiones y, si se dispone de ellos, "
            "justificantes de sus precios y comisiones.",
        )

    if getattr(clasificador, "valoraciones_pendientes", ()):
        add(
            "valoracion_eur", "documentacion", "Valoraciones en euros pendientes",
            "Hay permutas o rendimientos sin valoración histórica "
            "suficientemente acreditada en euros.",
            "Es necesario documentar el valor en euros en la fecha de cada "
            "operación con una fuente verificable; no se asumirá paridad "
            "entre stablecoins y euros.",
        )

    if getattr(clasificador, "comisiones_pendientes", ()):
        add(
            "comisiones_cripto", "documentacion", "Comisiones pagadas en cripto",
            "Falta acreditar la valoración y el tratamiento de alguna comisión.",
            "Aporta fecha, activo, cantidad, valor en EUR y documento de "
            "la operación a la que corresponde.",
        )

    if getattr(clasificador, "desconocidas", ()) or getattr(
        clasificador, "_unknown_files", 0
    ):
        add(
            "fuente_no_interpretada", "archivo", "Operaciones o archivos no reconocidos",
            "Existe información que el importador todavía no puede interpretar.",
            "Sube la exportación original completa e identifica el tipo de "
            "operación; no suprimas las filas no reconocidas.",
        )

    # No convertir marcadores internos no explicados en un falso visto bueno.
    known = {
        "spot_orders_ejecutadas_sin_fills_completos",
        "filas_identicas_entre_exportaciones_sin_id_unico",
        "earn_fuentes_no_conciliadas",
        "earn_orden_intradia_o_origen_pendiente",
        "earn_recompensas_sin_orden_intradia_acreditado",
        "earn_flexible_requiere_inventario_y_valoracion_fiscal",
        "earn_ledger_sin_lotes_ni_valoracion_acreditados",
        "earn_intereses_ledger_sin_fuente_nativa_suficiente",
        "earn_tipo_recompensa_desconocido",
        "earn_airdrop_destino_no_acreditado",
        "binance_comisiones_sin_valoracion_ni_categoria_fiscal",
        "small_assets_exchange_bnb_sin_permuta_valorada",
        "archivo Binance no reconocido",
    }
    if markers - known:
        add(
            "otras_incidencias", "revision", "Otras operaciones pendientes",
            "Existen inconsistencias adicionales que necesitan "
            "conciliación y revisión antes de calcular el FIFO.",
            "Conserva todos los archivos originales y revisa las "
            "operaciones señaladas; no elimines datos para evitar el bloqueo.",
        )

    return {
        "estado": "pendiente_validacion",
        "validez_fiscal_acreditada": False,
        "incidencias": incidencias,
        "aviso": (
            "Este diagnóstico no verifica que el historial esté completo "
            "desde la primera adquisición ni que el FIFO global sea correcto. "
            "No autoriza la generación del PDF."
        ),
    }
