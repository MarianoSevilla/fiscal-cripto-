"""
Generador PDF para MEXC — Mariano Sevilla — marianosevilla.com

Wrapper sobre generar_pdf() estándar.
Mantiene módulo independiente por exchange (no editar el original compartido).
"""

from generador_pdf import generar_pdf


def generar_pdf_mexc(motor, nombre_usuario: str = "", ejercicio: str = "",
                     rendimientos=None, clasificador_stats=None) -> bytes:
    """
    Genera el informe fiscal PDF para un usuario de MEXC.

    Parámetros:
        motor            — MotorFIFO ya procesado
        nombre_usuario   — nombre para la portada
        ejercicio        — ejercicio(s) fiscal(es), ej. "2024" o "2024,2025"
        rendimientos     — lista de OperacionRendimiento (puede estar vacía)
        clasificador_stats — dict con resumen del clasificador (opcional, para
                             estadísticas adicionales en la portada)

    La nota informativa sobre pares USDT se propaga a través de motor.advertencias,
    que el generador estándar ya muestra en la sección de advertencias del PDF.
    """
    return generar_pdf(
        motor,
        nombre_usuario,
        ejercicio,
        exchange="MEXC",
        rendimientos=rendimientos,
    )
