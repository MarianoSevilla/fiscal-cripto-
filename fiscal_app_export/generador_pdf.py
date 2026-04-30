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
        "kpi_value": ParagraphStyle("kpi_value", fontName="Helvetica-Bold", fontSize=14, textColor=WHITE, leading=18, alignment=TA_CENTER),
        "kpi_value_green": ParagraphStyle("kpi_value_green", fontName="Helvetica-Bold", fontSize=14, textColor=GREEN, leading=18, alignment=TA_CENTER),
        "kpi_value_red": ParagraphStyle("kpi_value_red", fontName="Helvetica-Bold", fontSize=14, textColor=RED_C, leading=18, alignment=TA_CENTER),
        "resumen_label": ParagraphStyle("resumen_label", fontName="Helvetica", fontSize=9, textColor=MUTED, leading=13),
        "resumen_value": ParagraphStyle("resumen_value", fontName="Helvetica-Bold", fontSize=9, textColor=WHITE, leading=13, alignment=TA_RIGHT),
        "resumen_value_green": ParagraphStyle("resumen_value_green", fontName="Helvetica-Bold", fontSize=9, textColor=GREEN, leading=13, alignment=TA_RIGHT),
        "resumen_value_red": ParagraphStyle("resumen_value_red", fontName="Helvetica-Bold", fontSize=9, textColor=RED_C, leading=13, alignment=TA_RIGHT),
        "warning": ParagraphStyle("warning", fontName="Helvetica", fontSize=8, textColor=colors.HexColor("#C8A5A4"), leading=12),
        "disclaimer": ParagraphStyle("disclaimer", fontName="Helvetica-Oblique", fontSize=7.5, textColor=MUTED, leading=11),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=7, textColor=MUTED, leading=9),
        "th_right": ParagraphStyle("th_right", fontName="Helvetica-Bold", fontSize=7, textColor=MUTED, leading=9, alignment=TA_RIGHT),
        "td": ParagraphStyle("td", fontName="Helvetica", fontSize=7.5, textColor=WHITE, leading=10),
        "td_mono": ParagraphStyle("td_mono", fontName="Courier", fontSize=7, textColor=WHITE, leading=10, alignment=TA_RIGHT),
        "td_green": ParagraphStyle("td_green", fontName="Helvetica-Bold", fontSize=7.5, textColor=GREEN, leading=10, alignment=TA_RIGHT),
        "td_red": ParagraphStyle("td_red", fontName="Helvetica-Bold", fontSize=7.5, textColor=RED_C, leading=10, alignment=TA_RIGHT),
        "td_muted": ParagraphStyle("td_muted", fontName="Helvetica", fontSize=7, textColor=MUTED, leading=10),
        "td_muted_right": ParagraphStyle("td_muted_right", fontName="Helvetica", fontSize=7, textColor=MUTED, leading=10, alignment=TA_RIGHT),
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
         Paragraph("IMPORTE (EUR)", styles["th_right"])],
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
        Paragraph("METODOLOGÍA", styles["nota_label"]),
        Paragraph(
            "Método FIFO obligatorio (art. 37.2 LIRPF). Las comisiones de compra incrementan el precio de coste "
            "del lote. Las comisiones de venta reducen el valor de transmisión. Los swaps entre criptoactivos "
            "se tratan como venta y compra simultánea a valor de mercado, generando hecho imponible. "
            "Los depósitos y retiradas de exchange no generan hecho imponible.",
            styles["nota_body"])
    ]]
    t3 = Table(nota_data, colWidths=[30*mm, 138*mm])
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


def _grafico_gp_activos(resultados, width_mm=168):
    """
    Gráfico de barras horizontal G/P neta por activo.
    Devuelve un flowable Image de ReportLab o None si matplotlib no está disponible.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker
    except ImportError:
        return None

    from collections import defaultdict
    por_activo = defaultdict(float)
    for r in resultados:
        por_activo[r.activo] += r.ganancia_perdida
    if not por_activo:
        return None

    # Ordenar: pérdidas abajo, ganancias arriba
    items   = sorted(por_activo.items(), key=lambda x: x[1])
    activos = [i[0] for i in items]
    valores = [i[1] for i in items]
    colores = ["#E24B4A" if v < 0 else "#00C896" for v in valores]

    n          = len(activos)
    fig_w_in   = 7.2
    fig_h_in   = max(2.4, n * 0.44 + 0.7)

    fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in))
    fig.patch.set_facecolor("#1A1A1A")
    ax.set_facecolor("#111111")

    bars = ax.barh(activos, valores, color=colores, height=0.60,
                   edgecolor="none", zorder=3)
    ax.axvline(0, color="#555555", linewidth=0.7, zorder=2)

    # Etiquetas de valor: dentro de la barra si es ancha (>30 % del eje),
    # fuera si es estrecha — evita que las etiquetas se salgan del área.
    max_abs = max(abs(v) for v in valores) if valores else 1.0
    if max_abs == 0:
        max_abs = 1.0          # evitar división por cero si todos los valores son 0
    pad     = max_abs * 0.025
    for bar, val in zip(bars, valores):
        x         = bar.get_width()
        bar_ratio = abs(x) / max_abs
        inside    = bar_ratio > 0.30
        lbl       = f"+{val:,.2f} €" if val >= 0 else f"{val:,.2f} €"
        if val >= 0:
            ha   = "right" if inside else "left"
            xpos = x - pad  if inside else x + pad
            col  = "#111111" if inside else "#00C896"
        else:
            ha   = "left"  if inside else "right"
            xpos = x + pad  if inside else x - pad
            col  = "#F0EDE6" if inside else "#E24B4A"
        ax.text(xpos, bar.get_y() + bar.get_height() / 2, lbl,
                va="center", ha=ha, fontsize=6.5, color=col, fontweight="bold")

    # Estilo dark
    for spine in ax.spines.values():
        spine.set_color("#2A2A2A")
    ax.tick_params(colors="#888580", labelsize=7.5)
    ax.xaxis.grid(True, color="#222222", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.set_xlabel("EUR", fontsize=7, color="#888580", labelpad=4)

    plt.tight_layout(pad=0.6)

    img_buf = io.BytesIO()
    plt.savefig(img_buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="#1A1A1A", edgecolor="none")
    plt.close(fig)
    img_buf.seek(0)

    from reportlab.platypus import Image as RLImage
    pdf_w = width_mm * mm
    pdf_h = pdf_w * (fig_h_in / fig_w_in)
    return RLImage(img_buf, width=pdf_w, height=pdf_h)


def _bloque_compensaciones(ganancias, perdidas, neto, rendimientos_list, styles):
    """
    Bloque de compensaciones fiscales (art. 49 LIRPF).
    Devuelve lista de flowables.
    """
    flowables = []
    rcm_total = sum(getattr(r, "valor_eur", 0.0) for r in rendimientos_list) if rendimientos_list else 0.0

    flowables.append(Spacer(1, 5*mm))
    flowables.append(Paragraph("Compensaciones Fiscales Aplicables", styles["section"]))
    flowables.append(Paragraph(
        "Integración y compensación de rentas del ahorro según art. 49 LIRPF.",
        styles["body_muted"]
    ))
    flowables.append(Spacer(1, 3*mm))

    rows = [
        [Paragraph("BASE DEL AHORRO — Integración y compensación (art. 49 LIRPF)", styles["th"]),
         Paragraph("IMPORTE (EUR)", styles["th_right"])],
        [Paragraph("Suma de ganancias patrimoniales (transmisiones)", styles["resumen_label"]),
         Paragraph(f"+{ganancias:,.2f}", styles["resumen_value_green"])],
        [Paragraph("Suma de pérdidas patrimoniales (transmisiones)", styles["resumen_label"]),
         Paragraph(f"{perdidas:,.2f}", styles["resumen_value_red"])],
        [Paragraph("SALDO NETO DE TRANSMISIONES", styles["subsection"]),
         Paragraph(f"{neto:+,.2f}",
                   styles["resumen_value_green"] if neto >= 0 else styles["resumen_value_red"])],
    ]

    if rcm_total > 0:
        rows.append([
            Paragraph("Rendimientos de capital mobiliario (staking / rewards)", styles["resumen_label"]),
            Paragraph(f"+{rcm_total:,.2f}", styles["resumen_value_green"])
        ])

    if neto < 0:
        if rcm_total > 0:
            limite_25  = rcm_total * 0.25
            comp_rcm   = min(abs(neto), limite_25)
            pendiente  = abs(neto) - comp_rcm
            rows.append([
                Paragraph(
                    f"Compensación aplicable con RCM (límite 25% del RCM = {limite_25:,.2f} EUR)",
                    styles["resumen_label"]),
                Paragraph(f"-{comp_rcm:,.2f}", styles["resumen_value_red"])
            ])
            if pendiente > 0.005:
                rows.append([
                    Paragraph(
                        "Pérdida pendiente · compensable con ganancias de los 4 ejercicios siguientes",
                        styles["resumen_label"]),
                    Paragraph(f"-{pendiente:,.2f}", styles["resumen_value_red"])
                ])
        else:
            rows.append([
                Paragraph(
                    "Pérdida patrimonial · compensable con ganancias de los 4 ejercicios siguientes (art. 49.1)",
                    styles["resumen_label"]),
                Paragraph(f"{neto:,.2f}", styles["resumen_value_red"])
            ])
    else:
        rows.append([
            Paragraph("Sin pérdidas pendientes de compensar en ejercicios futuros", styles["resumen_label"]),
            Paragraph("—", styles["resumen_value"])
        ])

    highlight_row = 3  # fila SALDO NETO
    t = Table(rows, colWidths=[128*mm, 40*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),                SURFACE),
        ("LINEBELOW",     (0, 0), (-1, 0),                1, GREEN),
        ("BACKGROUND",    (0, 1), (-1, highlight_row-1),  BLACK),
        ("BACKGROUND",    (0, highlight_row), (-1, highlight_row), SURFACE2),
        ("LINEABOVE",     (0, highlight_row), (-1, highlight_row), 0.5, BORDER),
        ("BACKGROUND",    (0, highlight_row+1), (-1, -1), BLACK),
        ("GRID",          (0, 0), (-1, -1),               0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1),               "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1),               6),
        ("BOTTOMPADDING", (0, 0), (-1, -1),               6),
        ("LEFTPADDING",   (0, 0), (-1, -1),               8),
        ("RIGHTPADDING",  (0, 0), (-1, -1),               8),
    ]))
    flowables.append(t)
    return flowables


def _bloque_modelo_721(posiciones, styles):
    """
    Alerta Modelo 721. Devuelve lista de flowables.
    El coste FIFO total es un proxy conservador; el valor real de mercado puede diferir.
    """
    coste_total = sum(p.coste_total for p in posiciones) if posiciones else 0.0

    if coste_total >= 50_000:
        bg      = colors.HexColor("#180800")
        border  = colors.HexColor("#FF6B2B")
        t_color = colors.HexColor("#FF8C4B")
        b_color = colors.HexColor("#C8966A")
        titulo  = "⚠  MODELO 721 — POSIBLEMENTE OBLIGATORIO"
        texto   = (
            f"El coste de adquisición FIFO de los activos en cartera asciende a {coste_total:,.2f} EUR. "
            "Si el valor de mercado a 31 de diciembre supera 50.000 EUR en exchanges extranjeros "
            "(como Binance o Kraken), deberás presentar el Modelo 721 antes del 31 de marzo "
            "del ejercicio siguiente. Consulta con tu asesor fiscal."
        )
    else:
        bg      = colors.HexColor("#091400")
        border  = colors.HexColor("#00C896")
        t_color = colors.HexColor("#00C896")
        b_color = colors.HexColor("#5A9070")
        titulo  = "✓  MODELO 721 — EN PRINCIPIO NO OBLIGATORIO"
        texto   = (
            f"El coste de adquisición FIFO de los activos en cartera es de {coste_total:,.2f} EUR, "
            "por debajo del umbral de 50.000 EUR. Verifica igualmente el valor de mercado "
            "a 31 de diciembre para confirmar que no supera dicho umbral antes de descartar "
            "la presentación del Modelo 721."
        )

    t_style = ParagraphStyle("m721t", fontName="Helvetica-Bold", fontSize=8.5,
                              textColor=t_color, leading=13)
    b_style = ParagraphStyle("m721b", fontName="Helvetica",      fontSize=7.5,
                              textColor=b_color, leading=11.5)

    data = [[Paragraph(titulo, t_style), Paragraph(texto, b_style)]]
    t = Table(data, colWidths=[70*mm, 98*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg),
        ("BOX",           (0, 0), (-1, -1), 0.8, border),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    return [Spacer(1, 4*mm), t]


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

    cabecera = [
        Paragraph("ACTIVO",          styles["th"]),
        Paragraph("Nº OPS",          styles["th_right"]),
        Paragraph("GANANCIAS (EUR)", styles["th_right"]),
        Paragraph("PÉRDIDAS (EUR)",  styles["th_right"]),
        Paragraph("NETO (EUR)",      styles["th_right"]),
    ]
    rows = [cabecera]
    for activo, datos in sorted(por_activo.items()):
        neto = datos["ganancias"] + datos["perdidas"]
        neto_style = styles["td_green"] if neto >= 0 else styles["td_red"]
        rows.append([
            Paragraph(activo, styles["td"]),
            Paragraph(str(datos["ops"]), styles["td_muted_right"]),
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
    cabecera = [
        Paragraph("FECHA",             styles["th"]),
        Paragraph("TIPO",              styles["th"]),
        Paragraph("ACTIVO",            styles["th"]),
        Paragraph("CANTIDAD",          styles["th_right"]),
        Paragraph("PRECIO TRANSMISIÓN",styles["th_right"]),
        Paragraph("COSTE FIFO",        styles["th_right"]),
        Paragraph("G / P (EUR)",       styles["th_right"]),
        Paragraph("DÍAS",              styles["th_right"]),
    ]
    rows = [cabecera]
    for r in resultados:
        gp = r.ganancia_perdida
        gp_style = styles["td_green"] if gp >= 0 else styles["td_red"]
        gp_str   = f"+{gp:,.4f}" if gp >= 0 else f"{gp:,.4f}"
        rows.append([
            Paragraph(r.fecha.strftime("%d/%m/%Y"), styles["td_muted_right"]),
            Paragraph(r.tipo_operacion.upper(), styles["td"]),
            Paragraph(r.activo, styles["td"]),
            Paragraph(f"{r.cantidad_vendida:,.6f}", styles["td_mono"]),
            Paragraph(f"{r.precio_transmision:,.4f}", styles["td_mono"]),
            Paragraph(f"{r.precio_coste:,.4f}", styles["td_mono"]),
            Paragraph(gp_str, gp_style),
            Paragraph(str(int(r.periodo_dias)), styles["td_muted_right"]),
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
    cabecera = [
        Paragraph("ACTIVO",                   styles["th"]),
        Paragraph("CANTIDAD EN CARTERA",       styles["th_right"]),
        Paragraph("PRECIO MEDIO ADQUISICION",  styles["th_right"]),
        Paragraph("COSTE TOTAL",               styles["th_right"]),
    ]
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

    cabecera = [
        Paragraph("ACTIVO",         styles["th"]),
        Paragraph("TIPO",           styles["th"]),
        Paragraph("Nº ABONOS",      styles["th_right"]),
        Paragraph("CANTIDAD TOTAL", styles["th_right"]),
    ]
    rows = [cabecera]
    for (activo, subtipo), datos in sorted(agrupado.items()):
        rows.append([
            Paragraph(activo, styles["td"]),
            Paragraph(subtipo.replace("_", " ").capitalize(), styles["td_muted"]),
            Paragraph(str(datos["ops"]), styles["td_muted_right"]),
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

    # 2. COMPENSACIONES + MODELO 721 (siguen a la portada, misma página si caben)
    for fl in _bloque_compensaciones(
            resumen["ganancias_brutas"], resumen["perdidas_brutas"],
            resumen["resultado_neto"], rendimientos, styles):
        story.append(fl)
    for fl in _bloque_modelo_721(posiciones, styles):
        story.append(fl)

    # 3. RESUMEN POR ACTIVO + GRÁFICO
    if motor.resultados:
        story.append(PageBreak())
        story.append(Paragraph("Resumen de Ganancias y Pérdidas por Activo", styles["section"]))
        story.append(Paragraph("Resultado agregado por criptoactivo para el período analizado.", styles["body_muted"]))
        story.append(Spacer(1, 3*mm))
        grafico = _grafico_gp_activos(motor.resultados)
        if grafico:
            story.append(grafico)
            story.append(Spacer(1, 4*mm))
        story.append(_tabla_resumen_activos(motor.resultados, styles))

    # 4. DETALLE OPERACIONES
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

    # 5. POSICION ACTUAL
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

    # 6. RENDIMIENTOS (staking, rebates, etc.)
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

    # 7. ADVERTENCIAS
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

    # 8. NOTAS EXPLICATIVAS
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
    buf    = io.BytesIO()
    resumen = clasificador.resumen_fiscal()
    rendimientos = getattr(clasificador, "rendimientos", [])

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=33*mm, bottomMargin=18*mm,
        title=f"Informe Fiscal Cripto {ejercicio} - Bit2Me - Mariano Sevilla",
        author="marianosevilla.com"
    )
    story = []

    # 1. PORTADA
    _portada(story, styles, resumen, nombre_usuario, ejercicio, "Bit2Me")

    # 2. COMPENSACIONES
    for fl in _bloque_compensaciones(
            resumen["ganancias_brutas"], resumen["perdidas_brutas"],
            resumen["resultado_neto"], rendimientos, styles):
        story.append(fl)

    # 3. MODELO 721 — nota informativa (Bit2Me no exporta saldos de cartera)
    story.append(Spacer(1, 4*mm))
    nota_721_data = [[
        Paragraph("MODELO 721", ParagraphStyle(
            "b721lbl", fontName="Helvetica-Bold", fontSize=8.5,
            textColor=colors.HexColor("#888580"), leading=13)),
        Paragraph(
            "Bit2Me no incluye el valor de cartera a 31 de diciembre en su informe fiscal CSV. "
            "Para verificar si estás obligado a presentar el Modelo 721 (umbral: 50.000 EUR en "
            "exchanges extranjeros), consulta el informe de saldos de tu cuenta de Bit2Me "
            "y comprueba el valor de mercado a 31 de diciembre del ejercicio.",
            ParagraphStyle("b721txt", fontName="Helvetica", fontSize=7.5,
                           textColor=colors.HexColor("#707070"), leading=11.5))
    ]]
    t_721 = Table(nota_721_data, colWidths=[30*mm, 138*mm])
    t_721.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#141414")),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(t_721)

    # 4. RESUMEN POR ACTIVO + GRÁFICO
    if clasificador.resultados:
        story.append(PageBreak())
        story.append(Paragraph("Resumen de Ganancias y Pérdidas por Activo", styles["section"]))
        story.append(Paragraph(
            "Resultado agregado por criptoactivo. Datos calculados por Bit2Me en su informe fiscal oficial.",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))

        # Gráfico — _grafico_gp_activos acepta cualquier lista con .activo y .ganancia_perdida
        grafico = _grafico_gp_activos(clasificador.resultados)
        if grafico:
            story.append(grafico)
            story.append(Spacer(1, 4*mm))

        story.append(_tabla_resumen_activos(clasificador.resultados, styles))

    # 5. DETALLE OPERACIONES
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

        cabecera = [
            Paragraph("FECHA",              styles["th"]),
            Paragraph("TIPO",               styles["th"]),
            Paragraph("ACTIVO",             styles["th"]),
            Paragraph("CANTIDAD",           styles["th_right"]),
            Paragraph("PRECIO TRANSMISIÓN", styles["th_right"]),
            Paragraph("COSTE ADQUISICIÓN",  styles["th_right"]),
            Paragraph("G / P (EUR)",        styles["th_right"]),
        ]
        rows = [cabecera]
        for r in clasificador.resultados:
            gp   = r.ganancia_perdida
            gp_s = styles["td_green"] if gp >= 0 else styles["td_red"]
            rows.append([
                Paragraph(r.fecha_venta[:10], styles["td_muted_right"]),
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

    # 6. RENDIMIENTOS
    if rendimientos:
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("Rendimientos de Capital Mobiliario", styles["section"]))
        story.append(Paragraph(
            "Ingresos por staking y otros rendimientos. Tributan como rendimientos de capital mobiliario "
            "a la tarifa del ahorro (19-28%). Consúltalos con tu gestor fiscal.",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_rendimientos(rendimientos, styles))

    # 7. ADVERTENCIAS
    if clasificador.advertencias:
        story.append(Spacer(1, 8*mm))
        story.append(KeepTogether([
            Paragraph("Advertencias — Operaciones que Requieren Revisión", styles["section"]),
            Paragraph("Las siguientes situaciones requieren comprobación manual.", styles["body_muted"]),
            Spacer(1, 3*mm),
        ]))
        warn_data = [[Paragraph(f"!  {adv}", styles["warning"])] for adv in clasificador.advertencias]
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

    # 8. DISCLAIMER
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        "Los resultados de ganancias y pérdidas de este informe provienen de los datos calculados "
        "por Bit2Me en su informe fiscal oficial. Este documento complementa, no sustituye, "
        "el informe oficial de tu exchange. Preséntalo siempre junto al historial oficial. "
        "No constituye asesoramiento fiscal ni legal. Consulta siempre con un gestor o asesor "
        "fiscal autorizado antes de presentar tu declaración.",
        styles["disclaimer"]
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()
