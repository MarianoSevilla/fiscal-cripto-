"""
Generador PDF para Bitget — Mariano Sevilla — marianosevilla.com

Wrapper sobre generar_pdf() estándar.
Mantiene módulo independiente por exchange (no editar el original compartido).
"""

from generador_pdf import generar_pdf


def generar_pdf_bitget(motor, nombre_usuario: str = "", ejercicio: str = "",
                       rendimientos=None, clasificador_stats=None) -> bytes:
    """
    Genera el informe fiscal PDF para un usuario de Bitget.

    Parámetros:
        motor            — MotorFIFO ya procesado
        nombre_usuario   — nombre para la portada
        ejercicio        — ejercicio(s) fiscal(es), ej. "2024" o "2024,2025"
        rendimientos     — lista de OperacionRendimiento (vacía en fase 1)
        clasificador_stats — dict con resumen del clasificador (opcional)

    La advertencia sobre pares USDT se propaga a través de motor.advertencias,
    que el generador estándar muestra en la sección de advertencias del PDF.
    """
    return generar_pdf(
        motor,
        nombre_usuario,
        ejercicio,
        exchange="Bitget",
        rendimientos=rendimientos,
    )
