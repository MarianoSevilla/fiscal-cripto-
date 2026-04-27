"""
Generador de informe fiscal PDF
Mariano Sevilla — marianosevilla.com
v2.0 — estructura mejorada inspirada en informes fiscales profesionales
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from datetime import datetime
import io


# ── PALETA ────────────────────────────────────
BLACK     = colors.HexColor("#0D0D0D")
WHITE     = colors.HexColor("#F0EDE6")
GREEN     = colors.HexColor("#00C896")
RED_C     = colors.HexColor("#E24B4A")
AMBER     = colors.HexColor("#F0B90B")
SURFACE   = colors.HexColor("#1A1A1A")
SURFACE2  = colors.HexColor("#111111")
MUTED     = colors.HexColor("#888580")
BORDER    = colors.HexColor("#2A2A2A")


def _build_styles():
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=24, textColor=WHITE, leading=30, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10, textColor=MUTED, leading=15, spaceAfter=4),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=12, textColor=GREEN, leading=16, spaceBefore=14, spaceAfter=6),
        "subsection": ParagraphStyle("subsection", fontName="Helvetica-Bold", fontSize=10, textColor=WHITE, leading=14, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9, textColor=WHITE, leading=14),
        "body_muted": ParagraphStyle("body_muted", fontName="Helvetica", fontSize=8, textColor=MUTED, leading=12),
        "kpi_label": ParagraphStyle("kpi_label", fontName="Helvetica", fontSize=7.5, textColor=MUTED, leading=11, alignment=TA_CENTER),
        "kpi_value": ParagraphStyle("kpi_value", fontName="Helvetica-Bold", fontSize=16, textColor=WHITE, leading=20, alignment=TA_CENTER),
        "kpi_value_green": ParagraphStyle("kpi_value_green", fontName="Helvetica-Bold", fontSize=16, textColor=GREEN, leading=20, alignment=TA_CENTER),
        "kpi_value_red": ParagraphStyle("kpi_value_red", fontName="Helvetica-Bold", fontSize=16, textColor=RED_C, leading=20, alignment=TA_CENTER),
        "resumen_label": ParagraphStyle("resumen_label", fontName="Helvetica", fontSize=9, textColor=MUTED, leading=13),
        "resumen_value": ParagraphStyle("resumen_value", fontName="Helvetica-Bold", fontSize=9, textColor=WHITE, leading=13, alignment=TA_RIGHT),
        "resumen_value_green": ParagraphStyle("resumen_value_green", fontName="Helvetica-Bold", fontSize=9, textColor=GREEN, leading=13, alignment=TA_RIGHT),
        "resumen_value_red": ParagraphStyle("resumen_value_red", fontName="Helvetica-Bold", fontSize=9, textColor=RED_C, leading=13, alignment=TA_RIGHT),
        "warning": ParagraphStyle("warning", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#C8A5A4"), leading=12),
        "disclaimer": ParagraphStyle("disclaimer", fontName="Helvetica-Oblique", fontSize=7.5, textColor=MUTED, leading=11),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7, textColor=MUTED, leading=9),
        "td": ParagraphStyle("td", fontName="Helvetica", fontSize=7.5, textColor=WHITE, leading=10),
        "td_mono": ParagraphStyle("td_mono", fontName="Courier", fontSize=7, textColor=WHITE, leading=10),
        "td_green": ParagraphStyle("td_green", fontName="Helvetica-Bold", fontSize=7.5, textColor=GREEN, leading=10),
        "td_red": ParagraphStyle("td_red", fontName="Helvetica-Bold", fontSize=7.5, textColor=RED_C, leading=10),
        "td_muted": ParagraphStyle("td_muted", fontName="Helvetica", fontSize=7, textColor=MUTED, leading=10),
        "nota_label": ParagraphStyle("nota_label", fontName="Helvetica-Bold", fontSize=8, textColor=AMBER, leading=12),
        "nota_body": ParagraphStyle("nota_body", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#C8B870"), leading=12),
    }


def _header_footer(canvas_obj, doc):
    canvas_obj.saveState()
    w, h = A4
    canvas_obj.setFillColor(BLACK)
    canvas_obj.rect(0, 0, w, h, fill=1, stroke=0)
    canvas_obj.setFillColor(SURFACE)
    canvas_obj.rect(0, h - 26*mm, w, 26*mm, fill=1, stroke=0)
    canvas_obj.setStrokeColor(GREEN)
    canvas_obj.setLineWidth(0.8)
    canvas_obj.line(0, h - 26*mm, w, h - 26*mm)
    canvas_obj.setFont("Helvetica-Bold", 10)
    canvas_obj.setFillColor(WHITE)
    canvas_obj.drawString(18*mm, h - 14*mm, "Mariano")
    canvas_obj.setFillColor(GREEN)
    canvas_obj.drawString(18*mm + 39, h - 14*mm, "Sevilla")
    canvas_obj.setFillColor(MUTED)
    canvas_obj.setFont("Helvetica", 7.5)
    canvas_obj.drawString(18*mm, h - 20*mm, "Informe Fiscal Cripto · IRPF Base del Ahorro · Método FIFO (art. 37.2 LIRPF)")
    canvas_obj.setFont("Helvetica", 7.5)
    canvas_obj.setFillColor(MUTED)
    fecha_str = datetime.now().strftime("%d/%m/%Y")
    canvas_obj.drawRightString(w - 18*mm, h - 14*mm, f"Generado: {fecha_str}")
    canvas_obj.drawRightString(w - 18*mm, h - 20*mm, f"Página {doc.page}")
    canvas_obj.setFillColor(SURFACE)
    canvas_obj.rect(0, 0, w, 12*mm, fill=1, stroke=0)
    canvas_obj.setStrokeColor(BORDER)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(0, 12*mm, w, 12*mm)
    canvas_obj.setFont("Helvetica-Oblique", 6.5)
    canvas_obj.setFillColor(MUTED)
    canvas_obj.drawCentredString(w / 2, 4.5*mm,
        "Documento auxiliar de organización fiscal. No constituye asesoramiento fiscal ni legal. "
        "Consulta siempre con un gestor o asesor fiscal autorizado antes de presentar tu declaración.")
    canvas_obj.restoreState()


def _portada(story, styles, resumen, nombre_usuario, ejercicio, exchange, periodo=None):
    story.append(Spacer(1, 6*mm))
    titulo = "Informe Fiscal Cripto"
    if ejercicio:
        titulo += f"  {ejercicio}"
    story.append(Paragraph(titulo, styles["title"]))

    # Cada campo en su propia línea — nombre siempre en mayúsculas
    if nombre_usuario:
        story.append(Paragraph(f"Preparado para: {nombre_usuario.upper()}", styles["subtitle"]))
    if ejercicio:
        story.append(Paragraph(f"Ejercicio: {ejercicio}", styles["subtitle"]))
    elif periodo and periodo.get("fecha_min"):
        story.append(Paragraph(f"Período analizado: {periodo['fecha_min']} — {periodo['fecha_max']}", styles["subtitle"]))
    if exchange:
        story.append(Paragraph(f"Exchange: {exchange}", styles["subtitle"]))
    story.append(Paragraph("Método FIFO · Art. 37.2 LIRPF", styles["subtitle"]))

    story.append(Spacer(1, 6*mm))

    neto = resumen["resultado_neto"]
    neto_style = styles["kpi_value_green"] if neto >= 0 else styles["kpi_value_red"]
    neto_fmt   = f"+{neto:,.2f} EUR" if neto >= 0 else f"{neto:,.2f} EUR"

    kpi_data = [
        [Paragraph("OPERACIONES", styles["kpi_label"]),
         Paragraph("GANANCIAS BRUTAS", styles["kpi_label"]),
         Paragraph("PÉRDIDAS BRUTAS", styles["kpi_label"]),
         Paragraph("RESULTADO NETO", styles["kpi_label"])],
        [Paragraph(str(resumen["operaciones_con_resultado"]), styles["kpi_value"]),
         Paragraph(f"+{resumen['ganancias_brutas']:,.2f} EUR", styles["kpi_value_green"]),
         Paragraph(f"{resumen['perdidas_brutas']:,.2f} EUR", styles["kpi_value_red"]),
         Paragraph(neto_fmt, neto_style)],
    ]
    t = Table(kpi_data, colWidths=[42*mm]*4, rowHeights=[10*mm, 14*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), SURFACE),
        ("GRID",          (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.5, GREEN),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 5*mm))

    story.append(Paragraph("Determinación de Bases Imponibles", styles["section"]))
    story.append(Paragraph("Desglose de las ganancias y pérdidas según su tratamiento fiscal en el IRPF español.", styles["body_muted"]))
    story.append(Spacer(1, 3*mm))

    ganancias = resumen['ganancias_brutas']
    perdidas  = resumen['perdidas_brutas']
    neto2     = resumen['resultado_neto']

    resumen_data = [
        [Paragraph("BASE DEL AHORRO — Transmisiones de criptoactivos (art. 33 LIRPF)", styles["th"]),
         Paragraph("IMPORTE (EUR)", styles["th"])],
        [Paragraph("Suma de ganancias patrimoniales", styles["resumen_label"]),
         Paragraph(f"+{ganancias:,.2f}", styles["resumen_value_green"])],
        [Paragraph("Suma de pérdidas patrimoniales", styles["resumen_label"]),
         Paragraph(f"{perdidas:,.2f}", styles["resumen_value_red"])],
        [Paragraph("TOTAL GANANCIAS Y PÉRDIDAS PATRIMONIALES NETAS", styles["subsection"]),
         Paragraph(f"+{neto2:,.2f}" if neto2 >= 0 else f"{neto2:,.2f}",
                   styles["resumen_value_green"] if neto2 >= 0 else styles["resumen_value_red"])],
    ]
    t2 = Table(resumen_data, colWidths=[128*mm, 40*mm])
    t2.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  SURFACE),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, GREEN),
        ("BACKGROUND",    (0, 1), (-1, 2),  BLACK),
        ("BACKGROUND",    (0, 3), (-1, 3),  SURFACE2),
        ("LINEABOVE",     (0, 3), (-1, 3),  0.5, BORDER),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(t2)
    story.append(Spacer(1, 5*mm))

    nota_data = [[
        Paragraph("METODOLOGIA", styles["nota_label"]),
        Paragraph(
            "Método FIFO obligatorio (art. 37.2 LIRPF). Las comisiones de compra incrementan el precio de coste "
            "del lote. Las comisiones de venta reducen el valor de transmisión. Los swaps entre criptoactivos "
            "se tratan como venta y compra simultánea a valor de mercado, generando hecho imponible. "
            "Los depósitos y retiradas de exchange no generan hecho imponible.",
            styles["nota_body"])
    ]]
    t3 = Table(nota_data, colWidths=[22*mm, 146*mm])
    t3.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#1A1800")),
        ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#3A3500")),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(t3)


def _tabla_resumen_activos(resultados, styles):
    from collections import defaultdict
    por_activo = defaultdict(lambda: {"ops": 0, "ganancias": 0.0, "perdidas": 0.0})
    for r in resultados:
        gp = r.ganancia_perdida
        por_activo[r.activo]["ops"] += 1
        if gp >= 0:
            por_activo[r.activo]["ganancias"] += gp
        else:
            por_activo[r.activo]["perdidas"] += gp

    cabecera = [Paragraph(h, styles["th"]) for h in ["ACTIVO", "Nº OPS", "GANANCIAS (EUR)", "PERDIDAS (EUR)", "NETO (EUR)"]]
    rows = [cabecera]
    for activo, datos in sorted(por_activo.items()):
        neto = datos["ganancias"] + datos["perdidas"]
        neto_style = styles["td_green"] if neto >= 0 else styles["td_red"]
        rows.append([
            Paragraph(activo, styles["td"]),
            Paragraph(str(datos["ops"]), styles["td_muted"]),
            Paragraph(f"+{datos['ganancias']:,.4f}" if datos["ganancias"] else "-", styles["td_green"]),
            Paragraph(f"{datos['perdidas']:,.4f}" if datos["perdidas"] else "-", styles["td_red"]),
            Paragraph(f"+{neto:,.4f}" if neto >= 0 else f"{neto:,.4f}", neto_style),
        ])
    col_w = [28*mm, 18*mm, 44*mm, 44*mm, 34*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  SURFACE),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, GREEN),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [BLACK, SURFACE2]),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
    ]))
    return t


def _tabla_operaciones(resultados, styles):
    cabecera = [Paragraph(h, styles["th"]) for h in
                ["FECHA", "TIPO", "ACTIVO", "CANTIDAD", "PRECIO TRANSMISION", "COSTE FIFO", "G / P (EUR)", "DIAS"]]
    rows = [cabecera]
    for r in resultados:
        gp = r.ganancia_perdida
        gp_style = styles["td_green"] if gp >= 0 else styles["td_red"]
        gp_str   = f"+{gp:,.4f}" if gp >= 0 else f"{gp:,.4f}"
        rows.append([
            Paragraph(r.fecha.strftime("%d/%m/%Y"), styles["td_muted"]),
            Paragraph(r.tipo_operacion.upper(), styles["td"]),
            Paragraph(r.activo, styles["td"]),
            Paragraph(f"{r.cantidad_vendida:,.6f}", styles["td_mono"]),
            Paragraph(f"{r.precio_transmision:,.4f}", styles["td_mono"]),
            Paragraph(f"{r.precio_coste:,.4f}", styles["td_mono"]),
            Paragraph(gp_str, gp_style),
            Paragraph(str(int(r.periodo_dias)), styles["td_muted"]),
        ])
    col_w = [20*mm, 13*mm, 16*mm, 26*mm, 26*mm, 26*mm, 24*mm, 13*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  SURFACE),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, GREEN),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [BLACK, SURFACE2]),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("ALIGN",         (3, 0), (-1, -1), "RIGHT"),
    ]))
    return t


def _tabla_posicion(posiciones, styles):
    cabecera = [Paragraph(h, styles["th"]) for h in
                ["ACTIVO", "CANTIDAD EN CARTERA", "PRECIO MEDIO ADQUISICION", "COSTE TOTAL"]]
    rows = [cabecera]
    for pos in posiciones:
        rows.append([
            Paragraph(pos.activo, styles["td"]),
            Paragraph(f"{pos.cantidad_total:,.6f}", styles["td_mono"]),
            Paragraph(f"{pos.precio_medio:,.4f} EUR", styles["td_mono"]),
            Paragraph(f"{pos.coste_total:,.4f} EUR", styles["td_mono"]),
        ])
    col_w = [28*mm, 50*mm, 54*mm, 36*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  SURFACE),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, GREEN),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [BLACK, SURFACE2]),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
    ]))
    return t


def _tabla_rendimientos(rendimientos: list, styles) -> object:
    """Tabla de rendimientos (staking, rebates, etc.) para el PDF."""
    from collections import defaultdict

    # Agrupar por activo y subtipo
    agrupado = defaultdict(lambda: {"cantidad": 0.0, "ops": 0, "subtipo": ""})
    for r in rendimientos:
        key = (r.activo, r.subtipo)
        agrupado[key]["cantidad"] += r.cantidad
        agrupado[key]["ops"] += 1
        agrupado[key]["subtipo"] = r.subtipo

    cabecera = [Paragraph(h, styles["th"]) for h in
                ["ACTIVO", "TIPO", "Nº ABONOS", "CANTIDAD TOTAL"]]
    rows = [cabecera]
    for (activo, subtipo), datos in sorted(agrupado.items()):
        rows.append([
            Paragraph(activo, styles["td"]),
            Paragraph(subtipo.replace("_", " ").capitalize(), styles["td_muted"]),
            Paragraph(str(datos["ops"]), styles["td_muted"]),
            Paragraph(f"{datos['cantidad']:,.6f}", styles["td_mono"]),
        ])

    col_w = [28*mm, 60*mm, 28*mm, 52*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  SURFACE),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, GREEN),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [BLACK, SURFACE2]),
        ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (2, 0), (-1, -1), "RIGHT"),
    ]))
    return t


def generar_pdf(motor, nombre_usuario="", ejercicio="", exchange="Binance", rendimientos=None) -> bytes:
    styles = _build_styles()
    buf = io.BytesIO()
    resumen    = motor.resumen_fiscal()
    posiciones = motor.posicion_actual()
    rendimientos = rendimientos or []

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=33*mm, bottomMargin=18*mm,
        title=f"Informe Fiscal Cripto {ejercicio} - Mariano Sevilla",
        author="marianosevilla.com"
    )
    story = []

    # 1. PORTADA
    _portada(story, styles, resumen, nombre_usuario, ejercicio, exchange)

    # 2. RESUMEN POR ACTIVO
    if motor.resultados:
        story.append(PageBreak())
        story.append(Paragraph("Resumen de Ganancias y Pérdidas por Activo", styles["section"]))
        story.append(Paragraph("Resultado agregado por criptoactivo para el período analizado.", styles["body_muted"]))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_resumen_activos(motor.resultados, styles))

    # 3. DETALLE OPERACIONES
    if motor.resultados:
        story.append(PageBreak())
        story.append(Paragraph("Extracto de Operaciones con Resultado Fiscal", styles["section"]))
        story.append(Paragraph(
            f"{len(motor.resultados)} operaciones con hecho imponible · "
            f"Ganancias: +{resumen['ganancias_brutas']:,.2f} EUR · "
            f"Pérdidas: {resumen['perdidas_brutas']:,.2f} EUR · "
            f"Resultado neto: {resumen['resultado_neto']:+,.2f} EUR",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_operaciones(motor.resultados, styles))

    # 4. POSICION ACTUAL
    if posiciones:
        story.append(PageBreak())
        story.append(Paragraph("Visión General de Valores en Cartera", styles["section"]))
        story.append(Paragraph(
            "Activos que permanecen en el inventario al cierre del período analizado. "
            "Estos lotes no han generado hecho imponible y se valorarán cuando se transmitan.",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_posicion(posiciones, styles))

    # 5. RENDIMIENTOS (staking, rebates, etc.)
    if rendimientos:
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("Rendimientos de Capital Mobiliario", styles["section"]))
        story.append(Paragraph(
            "Ingresos por staking, rebates y otros rendimientos recibidos durante el período. "
            "Tributan como rendimientos de capital mobiliario a la tarifa del ahorro (19-28%). "
            "No se incluyen en la base del ahorro por transmisiones — consúltalos con tu gestor.",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_rendimientos(rendimientos, styles))

    # 6. ADVERTENCIAS
    if motor.advertencias:
        story.append(Spacer(1, 8*mm))
        story.append(KeepTogether([
            Paragraph("Advertencias — Operaciones que Requieren Revisión", styles["section"]),
            Paragraph("Las siguientes situaciones requieren comprobación manual.", styles["body_muted"]),
            Spacer(1, 3*mm),
        ]))
        warn_data = [[Paragraph(f"!  {adv}", styles["warning"])] for adv in motor.advertencias]
        t_warn = Table(warn_data, colWidths=[168*mm])
        t_warn.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#1A0A0A")),
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#3A1A1A")),
            ("ROWBACKGROUNDS",(0, 0), (-1, -1), [colors.HexColor("#1A0A0A"), colors.HexColor("#1E0C0C")]),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(t_warn)

    # 6. NOTAS EXPLICATIVAS
    story.append(PageBreak())
    story.append(Paragraph("Notas Explicativas", styles["section"]))

    notas = [
        ("Método FIFO", "art. 37.2 LIRPF",
         "La normativa española establece que cuando existan valores homogéneos, se considerará que los "
         "transmitidos son los adquiridos en primer lugar (First In, First Out). Este método es obligatorio "
         "y no puede sustituirse por LIFO, HIFO ni precio medio."),
        ("Comisiones de compra", "incrementan el coste",
         "Las comisiones pagadas en el momento de adquirir un criptoactivo forman parte del precio de "
         "adquisición y se suman al coste del lote correspondiente. Esto reduce la ganancia futura o "
         "aumenta la pérdida cuando se venda dicho lote."),
        ("Comisiones de venta", "reducen el valor de transmisión",
         "Las comisiones pagadas al vender un criptoactivo reducen el valor de transmisión declarado. "
         "Esto reduce la ganancia o aumenta la pérdida resultante de la operación."),
        ("Swaps entre criptoactivos", "hecho imponible",
         "El intercambio directo entre dos criptoactivos distintos se considera una transmisión a efectos "
         "del IRPF. Genera una ganancia o pérdida patrimonial calculada como la diferencia entre el valor "
         "de mercado del activo recibido y el coste FIFO del activo entregado."),
        ("Depósitos y retiradas", "no generan hecho imponible",
         "Los movimientos de criptoactivos entre wallets propias o entre exchanges no constituyen "
         "transmisión patrimonial. Sin embargo, es importante conservar los registros para acreditar "
         "que se trata del mismo titular."),
        ("Staking y rendimientos", "rendimiento de capital mobiliario",
         "Los ingresos por staking, intereses de lending o comisiones de referido se califican "
         "generalmente como rendimientos de capital mobiliario y tributan a la tarifa del ahorro (19-28%). "
         "Esta herramienta los clasifica pero no los incluye en el cálculo de la base del ahorro por transmisiones."),
    ]

    for titulo_nota, subtitulo, texto in notas:
        nota_data = [[
            Paragraph(f"{titulo_nota}\n{subtitulo}", styles["nota_label"]),
            Paragraph(texto, styles["nota_body"])
        ]]
        t_nota = Table(nota_data, colWidths=[38*mm, 130*mm])
        t_nota.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#0E0E00")),
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#2A2A00")),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(KeepTogether([t_nota, Spacer(1, 3*mm)]))

    # DISCLAIMER
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        "Este documento ha sido generado automáticamente por la herramienta de Mariano Sevilla "
        "(marianosevilla.com) a partir del historial de operaciones exportado por el usuario. "
        "No constituye asesoramiento fiscal ni legal. Los resultados deben ser revisados y validados "
        "por un gestor o asesor fiscal autorizado antes de su presentación a la Agencia Tributaria. "
        "Mariano Sevilla no asume responsabilidad alguna por errores derivados de datos incorrectos "
        "o incompletos en el fichero CSV de origen.",
        styles["disclaimer"]
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()


def generar_pdf_bit2me(clasificador, nombre_usuario="", ejercicio="") -> bytes:
    """Genera el PDF para informes de Bit2Me usando los resultados ya calculados por el exchange."""
    styles = _build_styles()
    buf = io.BytesIO()
    resumen = clasificador.resumen_fiscal()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=33*mm, bottomMargin=18*mm,
        title=f"Informe Fiscal Cripto {ejercicio} - Bit2Me - Mariano Sevilla",
        author="marianosevilla.com"
    )
    story = []

    # Portada
    _portada(story, styles, resumen, nombre_usuario, ejercicio, "Bit2Me")

    # Operaciones con resultado
    if clasificador.resultados:
        story.append(PageBreak())
        story.append(Paragraph("Extracto de Operaciones con Resultado Fiscal", styles["section"]))
        story.append(Paragraph(
            f"{len(clasificador.resultados)} operaciones · "
            f"Ganancias: +{resumen['ganancias_brutas']:,.2f} EUR · "
            f"Pérdidas: {resumen['perdidas_brutas']:,.2f} EUR · "
            f"Resultado neto: {resumen['resultado_neto']:+,.2f} EUR",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))

        cabecera = [Paragraph(h, styles["th"]) for h in
                    ["FECHA", "TIPO", "ACTIVO", "CANTIDAD", "PRECIO TRANSMISIÓN", "COSTE ADQUISICIÓN", "G / P (EUR)"]]
        rows = [cabecera]
        for r in clasificador.resultados:
            gp = r.ganancia_perdida
            gp_s = styles["td_green"] if gp >= 0 else styles["td_red"]
            rows.append([
                Paragraph(r.fecha_venta[:10], styles["td_muted"]),
                Paragraph(r.tipo_op.upper(), styles["td"]),
                Paragraph(r.activo, styles["td"]),
                Paragraph(f"{r.cantidad:,.6f}", styles["td_mono"]),
                Paragraph(f"{r.precio_transmision:,.4f}", styles["td_mono"]),
                Paragraph(f"{r.precio_coste:,.4f}", styles["td_mono"]),
                Paragraph(f"+{gp:,.4f}" if gp >= 0 else f"{gp:,.4f}", gp_s),
            ])
        col_w = [22*mm, 14*mm, 18*mm, 28*mm, 32*mm, 32*mm, 22*mm]
        t = Table(rows, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  SURFACE),
            ("LINEBELOW",     (0, 0), (-1, 0),  1, GREEN),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [BLACK, SURFACE2]),
            ("GRID",          (0, 0), (-1, -1), 0.3, BORDER),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ("ALIGN",         (3, 0), (-1, -1), "RIGHT"),
        ]))
        story.append(t)

    # Rendimientos
    if clasificador.rendimientos:
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("Rendimientos de Capital Mobiliario", styles["section"]))
        story.append(Paragraph(
            "Ingresos por staking y otros rendimientos. Tributan como rendimientos de capital mobiliario.",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_rendimientos(clasificador.rendimientos, styles))

    # Advertencias
    if clasificador.advertencias:
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("Advertencias", styles["section"]))
        for adv in clasificador.advertencias:
            story.append(Paragraph(f"! {adv}", styles["warning"]))
            story.append(Spacer(1, 2*mm))

    # Disclaimer
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        "Los resultados de este informe provienen de los datos calculados por Bit2Me en su informe fiscal oficial. "
        "Este documento complementa, no sustituye, el informe oficial de tu exchange. "
        "Preséntalo siempre junto al historial oficial. "
        "Consulta siempre con un gestor o asesor fiscal autorizado.",
        styles["disclaimer"]
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
