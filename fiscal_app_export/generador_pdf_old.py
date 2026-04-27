"""
Generador de informe fiscal PDF
Mariano Sevilla — marianosevilla.com
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen import canvas
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate
from datetime import datetime
import io


# ── PALETA ────────────────────────────────────
BLACK     = colors.HexColor("#0D0D0D")
WHITE     = colors.HexColor("#F0EDE6")
GREEN     = colors.HexColor("#00C896")
RED_C     = colors.HexColor("#E24B4A")
SURFACE   = colors.HexColor("#1A1A1A")
SURFACE2  = colors.HexColor("#111111")
MUTED     = colors.HexColor("#888580")
BORDER    = colors.HexColor("#2A2A2A")


def _build_styles():
    return {
        "title": ParagraphStyle(
            "title", fontName="Helvetica-Bold", fontSize=22,
            textColor=WHITE, leading=28, spaceAfter=6
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName="Helvetica", fontSize=11,
            textColor=MUTED, leading=16, spaceAfter=20
        ),
        "section": ParagraphStyle(
            "section", fontName="Helvetica-Bold", fontSize=13,
            textColor=GREEN, leading=18, spaceBefore=18, spaceAfter=8
        ),
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=9,
            textColor=WHITE, leading=14
        ),
        "body_muted": ParagraphStyle(
            "body_muted", fontName="Helvetica", fontSize=8,
            textColor=MUTED, leading=12
        ),
        "kpi_label": ParagraphStyle(
            "kpi_label", fontName="Helvetica", fontSize=8,
            textColor=MUTED, leading=12, alignment=TA_CENTER
        ),
        "kpi_value": ParagraphStyle(
            "kpi_value", fontName="Helvetica-Bold", fontSize=18,
            textColor=WHITE, leading=22, alignment=TA_CENTER
        ),
        "kpi_value_green": ParagraphStyle(
            "kpi_value_green", fontName="Helvetica-Bold", fontSize=18,
            textColor=GREEN, leading=22, alignment=TA_CENTER
        ),
        "kpi_value_red": ParagraphStyle(
            "kpi_value_red", fontName="Helvetica-Bold", fontSize=18,
            textColor=RED_C, leading=22, alignment=TA_CENTER
        ),
        "warning": ParagraphStyle(
            "warning", fontName="Helvetica", fontSize=8,
            textColor=colors.HexColor("#C8A5A4"), leading=12
        ),
        "disclaimer": ParagraphStyle(
            "disclaimer", fontName="Helvetica-Oblique", fontSize=7.5,
            textColor=MUTED, leading=11
        ),
        "th": ParagraphStyle(
            "th", fontName="Helvetica-Bold", fontSize=7.5,
            textColor=MUTED, leading=10
        ),
        "td": ParagraphStyle(
            "td", fontName="Helvetica", fontSize=8,
            textColor=WHITE, leading=11
        ),
        "td_green": ParagraphStyle(
            "td_green", fontName="Helvetica-Bold", fontSize=8,
            textColor=GREEN, leading=11
        ),
        "td_red": ParagraphStyle(
            "td_red", fontName="Helvetica-Bold", fontSize=8,
            textColor=RED_C, leading=11
        ),
    }


def _header_footer(canvas_obj, doc):
    """Cabecera y pie en cada página."""
    canvas_obj.saveState()
    w, h = A4

    # Fondo negro
    canvas_obj.setFillColor(BLACK)
    canvas_obj.rect(0, 0, w, h, fill=1, stroke=0)

    # Franja superior
    canvas_obj.setFillColor(SURFACE)
    canvas_obj.rect(0, h - 28*mm, w, 28*mm, fill=1, stroke=0)

    # Logo / marca
    canvas_obj.setFont("Helvetica-Bold", 10)
    canvas_obj.setFillColor(WHITE)
    canvas_obj.drawString(18*mm, h - 16*mm, "mariano")
    canvas_obj.setFillColor(GREEN)
    canvas_obj.drawString(18*mm + 46, h - 16*mm, "sevilla")
    canvas_obj.setFillColor(MUTED)
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.drawString(18*mm, h - 22*mm, "Informe Fiscal Cripto — IRPF Base del Ahorro")

    # Fecha generación
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(MUTED)
    fecha_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    canvas_obj.drawRightString(w - 18*mm, h - 16*mm, f"Generado: {fecha_str}")
    canvas_obj.drawRightString(w - 18*mm, h - 22*mm, f"Página {doc.page}")

    # Pie
    canvas_obj.setFillColor(SURFACE)
    canvas_obj.rect(0, 0, w, 14*mm, fill=1, stroke=0)
    canvas_obj.setFont("Helvetica-Oblique", 7)
    canvas_obj.setFillColor(MUTED)
    canvas_obj.drawCentredString(
        w / 2, 5*mm,
        "Este informe es un auxiliar de organización fiscal. No constituye asesoramiento fiscal ni legal. "
        "Consulta siempre con un gestor o asesor autorizado."
    )

    canvas_obj.restoreState()


def _kpi_table(resumen, styles):
    """Tabla de KPIs resumen en la portada."""
    neto = resumen["resultado_neto"]
    neto_style = styles["kpi_value_green"] if neto >= 0 else styles["kpi_value_red"]
    neto_fmt   = f"+{neto:,.2f}" if neto >= 0 else f"{neto:,.2f}"

    data = [
        [
            Paragraph("OPERACIONES CON RESULTADO", styles["kpi_label"]),
            Paragraph("GANANCIAS BRUTAS", styles["kpi_label"]),
            Paragraph("PÉRDIDAS BRUTAS", styles["kpi_label"]),
            Paragraph("RESULTADO NETO", styles["kpi_label"]),
        ],
        [
            Paragraph(str(resumen["operaciones_con_resultado"]), styles["kpi_value"]),
            Paragraph(f"+{resumen['ganancias_brutas']:,.2f}", styles["kpi_value_green"]),
            Paragraph(f"{resumen['perdidas_brutas']:,.2f}", styles["kpi_value_red"]),
            Paragraph(neto_fmt, neto_style),
        ],
    ]
    col_w = [40*mm] * 4
    t = Table(data, colWidths=col_w, rowHeights=[12*mm, 16*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("GRID",       (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [4]),
    ]))
    return t


def _tabla_operaciones(resultados, styles, tipo_filtro=None):
    """Tabla de operaciones con resultado fiscal."""
    fila_cabecera = [
        Paragraph(h, styles["th"]) for h in
        ["FECHA", "TIPO", "ACTIVO", "CANT.", "TRANSMISIÓN", "COSTE FIFO", "G/P", "DÍAS"]
    ]
    rows = [fila_cabecera]

    filtrados = [r for r in resultados if (tipo_filtro is None or r.tipo_operacion == tipo_filtro)]
    for r in filtrados:
        gp = r.ganancia_perdida
        gp_style = styles["td_green"] if gp >= 0 else styles["td_red"]
        gp_str   = f"+{gp:,.4f}" if gp >= 0 else f"{gp:,.4f}"

        rows.append([
            Paragraph(r.fecha.strftime("%d/%m/%Y"), styles["td"]),
            Paragraph(r.tipo_operacion.upper(), styles["td"]),
            Paragraph(r.activo, styles["td"]),
            Paragraph(f"{r.cantidad_vendida:,.4f}", styles["td"]),
            Paragraph(f"{r.precio_transmision:,.4f}", styles["td"]),
            Paragraph(f"{r.precio_coste:,.4f}", styles["td"]),
            Paragraph(gp_str, gp_style),
            Paragraph(str(int(r.periodo_dias)), styles["td"]),
        ])

    col_w = [22*mm, 14*mm, 16*mm, 22*mm, 24*mm, 24*mm, 24*mm, 14*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        # Cabecera
        ("BACKGROUND",    (0, 0), (-1, 0), SURFACE),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, GREEN),
        # Cuerpo
        ("BACKGROUND",    (0, 1), (-1, -1), BLACK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [BLACK, SURFACE2]),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    return t


def _tabla_posicion(posiciones, styles):
    """Tabla de posición actual."""
    fila_cabecera = [
        Paragraph(h, styles["th"]) for h in
        ["ACTIVO", "CANTIDAD ACTUAL", "COSTE MEDIO", "COSTE TOTAL"]
    ]
    rows = [fila_cabecera]
    for pos in posiciones:
        rows.append([
            Paragraph(pos.activo, styles["td"]),
            Paragraph(f"{pos.cantidad_total:,.6f}", styles["td"]),
            Paragraph(f"{pos.precio_medio:,.4f}", styles["td"]),
            Paragraph(f"{pos.coste_total:,.4f}", styles["td"]),
        ])
    col_w = [30*mm, 42*mm, 42*mm, 42*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), SURFACE),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, GREEN),
        ("BACKGROUND",    (0, 1), (-1, -1), BLACK),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [BLACK, SURFACE2]),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    return t


def generar_pdf(motor, nombre_usuario="", ejercicio="") -> bytes:
    """
    Recibe un MotorFIFO ya procesado y devuelve el PDF como bytes.
    """
    styles = _build_styles()
    buf = io.BytesIO()
    resumen = motor.resumen_fiscal()
    posiciones = motor.posicion_actual()

    # Márgenes: deja espacio para cabecera y pie
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=35*mm, bottomMargin=20*mm,
        title="Informe Fiscal Cripto — Mariano Sevilla",
        author="marianosevilla.com"
    )

    story = []

    # ── PORTADA ───────────────────────────────
    story.append(Spacer(1, 8*mm))
    titulo = f"Informe Fiscal Cripto"
    if ejercicio:
        titulo += f" — {ejercicio}"
    story.append(Paragraph(titulo, styles["title"]))
    if nombre_usuario:
        story.append(Paragraph(f"Preparado para: {nombre_usuario}", styles["subtitle"]))
    else:
        story.append(Paragraph("Historial de Binance · Método FIFO · Art. 37.2 LIRPF", styles["subtitle"]))

    story.append(Spacer(1, 4*mm))
    story.append(_kpi_tabla(resumen, styles) if False else _kpi_table(resumen, styles))
    story.append(Spacer(1, 6*mm))

    # Nota metodológica
    story.append(Paragraph(
        "Metodología aplicada: Método FIFO obligatorio (art. 37.2 LIRPF). Las comisiones de compra aumentan el "
        "precio de coste. Las comisiones de venta reducen el precio de transmisión. Los swaps entre criptoactivos "
        "tributan como venta y compra simultánea al valor de mercado. Los movimientos de entrada/salida de exchange "
        "no generan hecho imponible.",
        styles["body_muted"]
    ))

    # ── OPERACIONES CON RESULTADO ─────────────
    if motor.resultados:
        story.append(PageBreak())
        story.append(Paragraph("Operaciones con Resultado Fiscal", styles["section"]))
        story.append(Paragraph(
            f"Total: {len(motor.resultados)} operaciones. "
            f"Ganancias: {resumen['ganancias_brutas']:,.2f} · "
            f"Pérdidas: {resumen['perdidas_brutas']:,.2f} · "
            f"Neto: {resumen['resultado_neto']:,.2f}",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_operaciones(motor.resultados, styles))

    # ── POSICIÓN ACTUAL ───────────────────────
    if posiciones:
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("Posición Actual (Lotes no Vendidos)", styles["section"]))
        story.append(Paragraph(
            "Activos que permanecen en el inventario al cierre del período analizado. "
            "No han generado hecho imponible todavía.",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_posicion(posiciones, styles))

    # ── ADVERTENCIAS ──────────────────────────
    if motor.advertencias:
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("Advertencias del Procesador", styles["section"]))
        story.append(Paragraph(
            "Las siguientes operaciones requieren revisión manual. Pueden indicar datos faltantes en el CSV "
            "o situaciones que el motor no puede resolver automáticamente:",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 2*mm))
        for adv in motor.advertencias:
            story.append(Paragraph(f"⚠ {adv}", styles["warning"]))
            story.append(Spacer(1, 1*mm))

    # ── DISCLAIMER FINAL ──────────────────────
    story.append(Spacer(1, 10*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        "Este documento ha sido generado automáticamente por la herramienta de Mariano Sevilla "
        "(marianosevilla.com) a partir del historial de operaciones exportado por el usuario. "
        "No constituye asesoramiento fiscal ni legal. Los resultados deben ser revisados y validados "
        "por un gestor o asesor fiscal autorizado antes de su presentación a la Agencia Tributaria. "
        "Mariano Sevilla no asume responsabilidad por errores derivados de datos incorrectos o incompletos "
        "en el fichero CSV de origen.",
        styles["disclaimer"]
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
