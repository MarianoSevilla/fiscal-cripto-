"""
Generador de informe fiscal PDF
Mariano Sevilla — marianosevilla.com
v3.0 — diseño print-friendly, fondo blanco, apto para entregar a gestor fiscal
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


# ── PALETA PRINT-FRIENDLY ─────────────────────────────────────────────────────
BG          = colors.white
TEXT        = colors.HexColor("#111827")   # texto principal
TEXT_MUTED  = colors.HexColor("#4B5563")   # texto secundario
ACCENT      = colors.HexColor("#1E3A8A")   # azul oscuro (cabeceras, títulos)
BORDER      = colors.HexColor("#D1D5DB")   # bordes finos
TABLE_HEAD  = colors.HexColor("#F3F4F6")   # cabecera de tabla
TABLE_ALT   = colors.HexColor("#F9FAFB")   # fila alternada
INFO_BG     = colors.HexColor("#F9FAFB")   # fondo caja info
GREEN_P     = colors.HexColor("#166534")   # verde discreto (ganancias)
RED_P       = colors.HexColor("#991B1B")   # rojo discreto (pérdidas)
RULE_COLOR  = colors.HexColor("#E5E7EB")   # línea horizontal


def _build_styles():
    return {
        # Portada
        "title":              ParagraphStyle("title",         fontName="Helvetica-Bold",    fontSize=22, textColor=ACCENT,     leading=28, spaceAfter=4),
        "subtitle":           ParagraphStyle("subtitle",      fontName="Helvetica",         fontSize=9.5,textColor=TEXT_MUTED, leading=14, spaceAfter=3),
        # Secciones
        "section":            ParagraphStyle("section",       fontName="Helvetica-Bold",    fontSize=12, textColor=ACCENT,     leading=16, spaceBefore=14, spaceAfter=5),
        "subsection":         ParagraphStyle("subsection",    fontName="Helvetica-Bold",    fontSize=9.5,textColor=TEXT,       leading=13, spaceBefore=8,  spaceAfter=3),
        "body":               ParagraphStyle("body",          fontName="Helvetica",         fontSize=9.5,textColor=TEXT,       leading=14),
        "body_muted":         ParagraphStyle("body_muted",    fontName="Helvetica",         fontSize=8.5,textColor=TEXT_MUTED, leading=12),
        # KPI tarjetas
        "kpi_label":          ParagraphStyle("kpi_label",     fontName="Helvetica",         fontSize=7.5,textColor=TEXT_MUTED, leading=11, alignment=TA_CENTER),
        "kpi_value":          ParagraphStyle("kpi_value",     fontName="Helvetica-Bold",    fontSize=13, textColor=TEXT,       leading=17, alignment=TA_CENTER),
        "kpi_value_green":    ParagraphStyle("kpi_value_g",   fontName="Helvetica-Bold",    fontSize=13, textColor=GREEN_P,    leading=17, alignment=TA_CENTER),
        "kpi_value_red":      ParagraphStyle("kpi_value_r",   fontName="Helvetica-Bold",    fontSize=13, textColor=RED_P,      leading=17, alignment=TA_CENTER),
        # Tabla resumen
        "resumen_label":      ParagraphStyle("res_label",     fontName="Helvetica",         fontSize=9,  textColor=TEXT,       leading=13),
        "resumen_value":      ParagraphStyle("res_val",       fontName="Helvetica-Bold",    fontSize=9,  textColor=TEXT,       leading=13, alignment=TA_RIGHT),
        "resumen_value_green":ParagraphStyle("res_val_g",     fontName="Helvetica-Bold",    fontSize=9,  textColor=GREEN_P,    leading=13, alignment=TA_RIGHT),
        "resumen_value_red":  ParagraphStyle("res_val_r",     fontName="Helvetica-Bold",    fontSize=9,  textColor=RED_P,      leading=13, alignment=TA_RIGHT),
        # Tabla heads y celdas
        "th":                 ParagraphStyle("th",            fontName="Helvetica-Bold",    fontSize=7.5,textColor=TEXT,       leading=10),
        "th_right":           ParagraphStyle("th_r",          fontName="Helvetica-Bold",    fontSize=7.5,textColor=TEXT,       leading=10, alignment=TA_RIGHT),
        "td":                 ParagraphStyle("td",            fontName="Helvetica",         fontSize=8.5,textColor=TEXT,       leading=11),
        "td_mono":            ParagraphStyle("td_mono",       fontName="Courier",           fontSize=7.5,textColor=TEXT,       leading=11, alignment=TA_RIGHT),
        "td_green":           ParagraphStyle("td_g",          fontName="Helvetica-Bold",    fontSize=8.5,textColor=GREEN_P,    leading=11, alignment=TA_RIGHT),
        "td_red":             ParagraphStyle("td_r",          fontName="Helvetica-Bold",    fontSize=8.5,textColor=RED_P,      leading=11, alignment=TA_RIGHT),
        "td_muted":           ParagraphStyle("td_muted",      fontName="Helvetica",         fontSize=8,  textColor=TEXT_MUTED, leading=11),
        "td_muted_right":     ParagraphStyle("td_muted_r",    fontName="Helvetica",         fontSize=8,  textColor=TEXT_MUTED, leading=11, alignment=TA_RIGHT),
        # Notas
        "nota_label":         ParagraphStyle("nota_label",    fontName="Helvetica-Bold",    fontSize=8.5,textColor=ACCENT,     leading=12),
        "nota_body":          ParagraphStyle("nota_body",     fontName="Helvetica",         fontSize=8.5,textColor=TEXT,       leading=12),
        "nota_sub":           ParagraphStyle("nota_sub",      fontName="Helvetica-Oblique", fontSize=7.5,textColor=TEXT_MUTED, leading=11),
        # Advertencia y disclaimer
        "warning":            ParagraphStyle("warning",       fontName="Helvetica",         fontSize=8.5,textColor=RED_P,      leading=12),
        "disclaimer":         ParagraphStyle("disclaimer",    fontName="Helvetica-Oblique", fontSize=7,  textColor=TEXT_MUTED, leading=10),
        # Aviso legal portada
        "aviso_legal":        ParagraphStyle("aviso_legal",   fontName="Helvetica-Oblique", fontSize=7.5,textColor=TEXT_MUTED, leading=11),
    }


def _header_footer(canvas_obj, doc):
    """Cabecera y pie de página discretos, fondo blanco."""
    canvas_obj.saveState()
    w, h = A4

    # ── Cabecera ──────────────────────────────────────────────────────────
    # Línea inferior de cabecera
    canvas_obj.setStrokeColor(RULE_COLOR)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(18*mm, h - 14*mm, w - 18*mm, h - 14*mm)

    # Logo / nombre
    canvas_obj.setFont("Helvetica-Bold", 10)
    canvas_obj.setFillColor(ACCENT)
    canvas_obj.drawString(18*mm, h - 10*mm, "Mariano Sevilla")
    canvas_obj.setFont("Helvetica", 8.5)
    canvas_obj.setFillColor(TEXT_MUTED)
    canvas_obj.drawString(18*mm + 75, h - 10*mm, "· Informe Fiscal Cripto · Método FIFO · IRPF Base del Ahorro")

    # Fecha y página (derecha)
    fecha_str = datetime.now().strftime("%d/%m/%Y")
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(TEXT_MUTED)
    canvas_obj.drawRightString(w - 18*mm, h - 10*mm, f"Generado: {fecha_str}  |  Página {doc.page}")

    # ── Pie de página ─────────────────────────────────────────────────────
    canvas_obj.setStrokeColor(RULE_COLOR)
    canvas_obj.setLineWidth(0.5)
    canvas_obj.line(18*mm, 13*mm, w - 18*mm, 13*mm)

    canvas_obj.setFont("Helvetica-Oblique", 6.5)
    canvas_obj.setFillColor(TEXT_MUTED)
    canvas_obj.drawCentredString(
        w / 2, 8*mm,
        "Documento auxiliar de organización fiscal. No constituye asesoramiento fiscal ni legal. "
        "Debe ser revisado por un asesor fiscal antes de su presentación."
    )
    canvas_obj.drawCentredString(w / 2, 4.5*mm, f"marianosevilla.com  |  Página {doc.page}")

    canvas_obj.restoreState()


def _aviso_legal_caja(styles):
    """Caja de aviso legal para la portada, discreta y compacta."""
    texto = (
        "Este documento es un informe auxiliar generado automáticamente a partir de los datos aportados "
        "por el usuario. No constituye asesoramiento fiscal ni legal. Debe ser revisado por un asesor "
        "fiscal antes de su presentación ante la Agencia Tributaria."
    )
    data = [[Paragraph(texto, styles["aviso_legal"])]]
    t = Table(data, colWidths=[168*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), INFO_BG),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    return t


def _portada(story, styles, resumen, nombre_usuario, ejercicio, exchange, periodo=None):
    story.append(Spacer(1, 4*mm))

    # ── Construir textos de ejercicio ────────────────────────────────────
    ejercicio = (ejercicio or "").strip()
    if ejercicio and ejercicio.lower() != "all":
        partes = sorted([p.strip() for p in ejercicio.split(",") if p.strip()])
        if len(partes) == 1:
            titulo_ejercicio = partes[0]
            texto_ejercicio  = f"<b>Ejercicio fiscal:</b>  {partes[0]}"
        else:
            titulo_ejercicio = ", ".join(partes)
            texto_ejercicio  = f"<b>Ejercicios fiscales:</b>  {', '.join(partes)}"
    else:
        titulo_ejercicio = None
        texto_ejercicio  = "<b>Ejercicios:</b>  Todos los incluidos en el CSV"

    titulo = "Informe Fiscal Cripto"
    if titulo_ejercicio:
        titulo += f"  {titulo_ejercicio}"
    story.append(Paragraph(titulo, styles["title"]))
    story.append(Paragraph("Método FIFO · Art. 37.2 LIRPF · IRPF Base del Ahorro", styles["subtitle"]))
    story.append(Spacer(1, 4*mm))

    # Datos del informe
    if nombre_usuario:
        story.append(Paragraph(f"<b>Preparado para:</b>  {nombre_usuario.upper()}", styles["body"]))
    story.append(Paragraph(texto_ejercicio, styles["body"]))
    if not ejercicio and periodo and periodo.get("fecha_min"):
        story.append(Paragraph(f"<b>Período analizado:</b>  {periodo['fecha_min']} — {periodo['fecha_max']}", styles["body"]))
    if exchange:
        story.append(Paragraph(f"<b>Exchange:</b>  {exchange}", styles["body"]))
    story.append(Paragraph(f"<b>Fecha de generación:</b>  {datetime.utcnow().strftime('%d/%m/%Y')}", styles["body"]))

    story.append(Spacer(1, 4*mm))

    # Aviso legal compacto
    story.append(_aviso_legal_caja(styles))

    # Nota FIFO (solo cuando se han seleccionado ejercicios concretos)
    if ejercicio and ejercicio.lower() != "all":
        fifo_data = [[Paragraph(
            "<b>Nota sobre el cálculo FIFO:</b> El cálculo de costes se realiza utilizando el histórico "
            "completo del CSV para respetar correctamente la cola FIFO (art. 37.2 LIRPF). "
            "Este informe muestra únicamente las transmisiones y rendimientos correspondientes "
            "a los ejercicios fiscales seleccionados.",
            styles["aviso_legal"])]]
        t_fifo = Table(fifo_data, colWidths=[168*mm])
        t_fifo.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(Spacer(1, 3*mm))
        story.append(t_fifo)

    story.append(Spacer(1, 6*mm))

    # ── Resumen ejecutivo — 4 tarjetas ──────────────────────────────────
    neto = resumen["resultado_neto"]
    neto_style = styles["kpi_value_green"] if neto >= 0 else styles["kpi_value_red"]
    neto_fmt   = f"+{neto:,.2f} EUR" if neto >= 0 else f"{neto:,.2f} EUR"

    kpi_data = [
        [Paragraph("OPERACIONES",      styles["kpi_label"]),
         Paragraph("GANANCIAS BRUTAS", styles["kpi_label"]),
         Paragraph("PÉRDIDAS BRUTAS",  styles["kpi_label"]),
         Paragraph("RESULTADO NETO",   styles["kpi_label"])],
        [Paragraph(str(resumen["operaciones_con_resultado"]),  styles["kpi_value"]),
         Paragraph(f"+{resumen['ganancias_brutas']:,.2f} EUR", styles["kpi_value_green"]),
         Paragraph(f"{resumen['perdidas_brutas']:,.2f} EUR",   styles["kpi_value_red"]),
         Paragraph(neto_fmt, neto_style)],
    ]
    t_kpi = Table(kpi_data, colWidths=[42*mm]*4, rowHeights=[9*mm, 13*mm])
    t_kpi.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BG),
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.5, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ]))
    story.append(t_kpi)
    story.append(Spacer(1, 6*mm))

    # ── Determinación de bases imponibles ──────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE_COLOR))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph("Determinación de Bases Imponibles", styles["section"]))
    story.append(Paragraph(
        "Desglose de las ganancias y pérdidas según su tratamiento fiscal en el IRPF español.",
        styles["body_muted"]
    ))
    story.append(Spacer(1, 3*mm))

    ganancias = resumen["ganancias_brutas"]
    perdidas  = resumen["perdidas_brutas"]
    neto2     = resumen["resultado_neto"]

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
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, ACCENT),
        ("BACKGROUND",    (0, 1), (-1, 2),  BG),
        ("BACKGROUND",    (0, 3), (-1, 3),  TABLE_HEAD),
        ("LINEABOVE",     (0, 3), (-1, 3),  0.5, BORDER),
        ("LINEBELOW",     (0, 3), (-1, 3),  1.2, ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ]))
    story.append(t2)
    story.append(Spacer(1, 5*mm))

    # Nota FIFO compacta
    nota_data = [[
        Paragraph(
            "<b>Método FIFO obligatorio (art. 37.2 LIRPF).</b> Las comisiones de compra incrementan el precio de coste "
            "del lote. Las comisiones de venta reducen el valor de transmisión. Los swaps entre criptoactivos "
            "se tratan como venta y compra simultánea a valor de mercado, generando hecho imponible. "
            "Los depósitos y retiradas entre wallets propias no generan hecho imponible.",
            styles["nota_body"])
    ]]
    t3 = Table(nota_data, colWidths=[168*mm])
    t3.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), INFO_BG),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 9),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 9),
    ]))
    story.append(t3)


def _grafico_gp_activos(resultados, width_mm=168):
    """Gráfico de barras horizontal G/P neta por activo — fondo blanco para impresión."""
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

    MAX_ACTIVOS = 20
    todos = sorted(por_activo.items(), key=lambda x: abs(x[1]), reverse=True)
    if len(todos) > MAX_ACTIVOS:
        todos = todos[:MAX_ACTIVOS]

    items   = sorted(todos, key=lambda x: x[1])
    activos = [i[0] for i in items]
    valores = [i[1] for i in items]
    # Verde/rojo discretos aptos para impresión B&N
    colores = ["#991B1B" if v < 0 else "#166534" for v in valores]

    n        = len(activos)
    fig_w_in = 7.2
    fig_h_in = min(max(2.4, n * 0.44 + 0.7), 7.0)

    fig, ax = plt.subplots(figsize=(fig_w_in, fig_h_in))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    bars = ax.barh(activos, valores, color=colores, height=0.55,
                   edgecolor="#D1D5DB", linewidth=0.5, zorder=3)
    ax.axvline(0, color="#9CA3AF", linewidth=0.7, zorder=2)

    max_abs = max(abs(v) for v in valores) if valores else 1.0
    if max_abs == 0:
        max_abs = 1.0
    pad = max_abs * 0.025
    for bar, val in zip(bars, valores):
        x         = bar.get_width()
        bar_ratio = abs(x) / max_abs
        inside    = bar_ratio > 0.35
        lbl       = f"+{val:,.2f} €" if val >= 0 else f"{val:,.2f} €"
        if val >= 0:
            ha   = "right" if inside else "left"
            xpos = x - pad  if inside else x + pad
            col  = "white"   if inside else "#166534"
        else:
            ha   = "left"  if inside else "right"
            xpos = x + pad  if inside else x - pad
            col  = "white"   if inside else "#991B1B"
        ax.text(xpos, bar.get_y() + bar.get_height() / 2, lbl,
                va="center", ha=ha, fontsize=6.5, color=col, fontweight="bold")

    for spine in ax.spines.values():
        spine.set_color("#E5E7EB")
    ax.tick_params(colors="#4B5563", labelsize=7.5)
    ax.xaxis.grid(True, color="#F3F4F6", linewidth=0.5, zorder=0)
    ax.set_axisbelow(True)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.set_xlabel("EUR", fontsize=7, color="#4B5563", labelpad=4)
    ax.tick_params(axis='y', labelcolor="#111827")

    plt.tight_layout(pad=0.6)

    img_buf = io.BytesIO()
    plt.savefig(img_buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    img_buf.seek(0)

    from reportlab.platypus import Image as RLImage
    pdf_w = width_mm * mm
    pdf_h = pdf_w * (fig_h_in / fig_w_in)
    return RLImage(img_buf, width=pdf_w, height=pdf_h)


def _bloque_compensaciones(ganancias, perdidas, neto, rendimientos_list, styles):
    """Bloque de compensaciones fiscales (art. 49 LIRPF). Devuelve lista de flowables."""
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
            limite_25 = rcm_total * 0.25
            comp_rcm  = min(abs(neto), limite_25)
            pendiente = abs(neto) - comp_rcm
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

    highlight_row = 3
    t = Table(rows, colWidths=[128*mm, 40*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),                        TABLE_HEAD),
        ("LINEBELOW",     (0, 0), (-1, 0),                        1, ACCENT),
        ("BACKGROUND",    (0, 1), (-1, highlight_row - 1),        BG),
        ("BACKGROUND",    (0, highlight_row), (-1, highlight_row), TABLE_HEAD),
        ("LINEABOVE",     (0, highlight_row), (-1, highlight_row), 0.5, BORDER),
        ("LINEBELOW",     (0, highlight_row), (-1, highlight_row), 1.2, ACCENT),
        ("BACKGROUND",    (0, highlight_row + 1), (-1, -1),       BG),
        ("BOX",           (0, 0), (-1, -1),                       0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1),                       0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1),                       "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1),                       6),
        ("BOTTOMPADDING", (0, 0), (-1, -1),                       6),
        ("LEFTPADDING",   (0, 0), (-1, -1),                       8),
        ("RIGHTPADDING",  (0, 0), (-1, -1),                       8),
    ]))
    flowables.append(t)
    return flowables


def _bloque_modelo_721(posiciones, styles, ejercicio=""):
    """Bloque Modelo 721 — presentación prudente y print-friendly.

    Si se han seleccionado varios ejercicios, muestra un aviso genérico.
    Si es un año único, muestra el análisis con referencia explícita a ese año.
    """
    ejercicio = (ejercicio or "").strip()
    es_multi  = False
    año_label = ""

    if ejercicio and ejercicio.lower() != "all":
        partes = [p.strip() for p in ejercicio.split(",") if p.strip()]
        if len(partes) > 1:
            es_multi  = True
            año_label = ", ".join(partes)
        elif len(partes) == 1:
            año_label = partes[0]

    # ── Caso multi-año: mensaje genérico prudente ──────────────────────
    if es_multi:
        t_style = ParagraphStyle("m721t", fontName="Helvetica-Bold", fontSize=8.5,
                                  textColor=TEXT, leading=13)
        b_style = ParagraphStyle("m721b", fontName="Helvetica", fontSize=8.5,
                                  textColor=TEXT_MUTED, leading=12)
        titulo  = f"Modelo 721 — Revisión orientativa (ejercicios {año_label})"
        texto   = (
            "El informe abarca varios ejercicios fiscales. La obligación de presentar el Modelo 721 "
            "debe evaluarse por separado para cada ejercicio a 31 de diciembre de cada año, "
            "comprobando si el valor de mercado de los activos en exchanges extranjeros superó "
            "los 50.000 EUR en esa fecha. Consulta con tu asesor fiscal."
        )
        data = [[Paragraph(titulo, t_style), Paragraph(texto, b_style)]]
        t = Table(data, colWidths=[60*mm, 108*mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), INFO_BG),
            ("BOX",           (0, 0), (-1, -1), 0.8, BORDER),
            ("LINEAFTER",     (0, 0), (0, -1),  0.5, BORDER),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 9),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 9),
        ]))
        return [Spacer(1, 4*mm), t]

    # ── Caso año único o todos ─────────────────────────────────────────
    coste_total = sum(p.coste_total for p in posiciones) if posiciones else 0.0

    if año_label:
        sufijo_fecha = f"a 31 de diciembre de {año_label}"
        sufijo_nota  = (
            f" Tenga en cuenta que este análisis usa la posición al cierre del CSV, "
            f"no necesariamente el saldo exacto a 31/12/{año_label}."
        )
    else:
        sufijo_fecha = "a 31 de diciembre del ejercicio"
        sufijo_nota  = ""

    if coste_total >= 50_000:
        titulo = f"Modelo 721 — Revisión orientativa: posiblemente obligatorio"
        texto  = (
            f"El coste de adquisición FIFO de los activos en cartera asciende a {coste_total:,.2f} EUR. "
            f"Debe verificarse el valor de mercado {sufijo_fecha}: si supera 50.000 EUR en exchanges "
            "extranjeros (como Binance o Kraken), la presentación del Modelo 721 sería obligatoria "
            f"antes del 31 de marzo del ejercicio siguiente. Consulta con tu asesor fiscal.{sufijo_nota}"
        )
        borde_color = colors.HexColor("#B45309")
    else:
        titulo = f"Modelo 721 — Revisión orientativa: en principio no obligatorio"
        texto  = (
            f"El coste de adquisición FIFO de los activos en cartera es de {coste_total:,.2f} EUR, "
            "por debajo del umbral de 50.000 EUR. No obstante, debe verificarse el valor de mercado "
            f"{sufijo_fecha} para confirmar que no supera dicho umbral antes de descartar la "
            f"presentación del Modelo 721. Esta valoración es meramente orientativa.{sufijo_nota}"
        )
        borde_color = BORDER

    t_style = ParagraphStyle("m721t", fontName="Helvetica-Bold", fontSize=8.5,
                              textColor=TEXT, leading=13)
    b_style = ParagraphStyle("m721b", fontName="Helvetica", fontSize=8.5,
                              textColor=TEXT_MUTED, leading=12)

    data = [[Paragraph(titulo, t_style), Paragraph(texto, b_style)]]
    t = Table(data, colWidths=[60*mm, 108*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), INFO_BG),
        ("BOX",           (0, 0), (-1, -1), 0.8, borde_color),
        ("LINEAFTER",     (0, 0), (0, -1),  0.5, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 9),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 9),
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
    for i, (activo, datos) in enumerate(sorted(por_activo.items())):
        neto = datos["ganancias"] + datos["perdidas"]
        neto_style = styles["td_green"] if neto >= 0 else styles["td_red"]
        rows.append([
            Paragraph(activo, styles["td"]),
            Paragraph(str(datos["ops"]), styles["td_muted_right"]),
            Paragraph(f"+{datos['ganancias']:,.4f}" if datos["ganancias"] else "—", styles["td_green"]),
            Paragraph(f"{datos['perdidas']:,.4f}"   if datos["perdidas"]  else "—", styles["td_red"]),
            Paragraph(f"+{neto:,.4f}" if neto >= 0 else f"{neto:,.4f}", neto_style),
        ])

    col_w = [28*mm, 18*mm, 44*mm, 44*mm, 34*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    n = len(rows)
    row_bgs = []
    for i in range(1, n):
        row_bgs.append(("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else TABLE_ALT))
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
    ] + row_bgs))
    return t


def _tabla_operaciones(resultados, styles):
    cabecera = [
        Paragraph("FECHA",               styles["th"]),
        Paragraph("TIPO",                styles["th"]),
        Paragraph("ACTIVO",              styles["th"]),
        Paragraph("CANTIDAD",            styles["th_right"]),
        Paragraph("PRECIO TRANSMISIÓN",  styles["th_right"]),
        Paragraph("COSTE FIFO",          styles["th_right"]),
        Paragraph("G / P (EUR)",         styles["th_right"]),
        Paragraph("DÍAS",                styles["th_right"]),
    ]
    rows = [cabecera]
    for r in resultados:
        gp = r.ganancia_perdida
        gp_style = styles["td_green"] if gp >= 0 else styles["td_red"]
        gp_str   = f"+{gp:,.4f}" if gp >= 0 else f"{gp:,.4f}"
        rows.append([
            Paragraph(r.fecha.strftime("%d/%m/%Y"), styles["td_muted"]),
            Paragraph(r.tipo_operacion.upper(), styles["td"]),
            Paragraph(r.activo, styles["td"]),
            Paragraph(f"{r.cantidad_vendida:,.6f}",  styles["td_mono"]),
            Paragraph(f"{r.precio_transmision:,.4f}", styles["td_mono"]),
            Paragraph(f"{r.precio_coste:,.4f}",       styles["td_mono"]),
            Paragraph(gp_str, gp_style),
            Paragraph(str(int(r.periodo_dias)), styles["td_muted_right"]),
        ])

    col_w = [20*mm, 13*mm, 16*mm, 26*mm, 26*mm, 26*mm, 24*mm, 13*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    n = len(rows)
    row_bgs = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else TABLE_ALT) for i in range(1, n)]
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("ALIGN",         (3, 0), (-1, -1), "RIGHT"),
    ] + row_bgs))
    return t


def _tabla_posicion(posiciones, styles):
    cabecera = [
        Paragraph("ACTIVO",                    styles["th"]),
        Paragraph("CANTIDAD EN CARTERA",       styles["th_right"]),
        Paragraph("PRECIO MEDIO ADQUISICIÓN",  styles["th_right"]),
        Paragraph("COSTE TOTAL",               styles["th_right"]),
    ]
    rows = [cabecera]
    for pos in posiciones:
        rows.append([
            Paragraph(pos.activo, styles["td"]),
            Paragraph(f"{pos.cantidad_total:,.6f}",   styles["td_mono"]),
            Paragraph(f"{pos.precio_medio:,.4f} EUR",  styles["td_mono"]),
            Paragraph(f"{pos.coste_total:,.4f} EUR",   styles["td_mono"]),
        ])
    col_w = [28*mm, 50*mm, 54*mm, 36*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    n = len(rows)
    row_bgs = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else TABLE_ALT) for i in range(1, n)]
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
    ] + row_bgs))
    return t


def _tabla_rendimientos(rendimientos: list, styles) -> object:
    """Tabla de rendimientos (staking, rebates, etc.) para el PDF."""
    from collections import defaultdict

    agrupado = defaultdict(lambda: {"cantidad": 0.0, "ops": 0, "subtipo": ""})
    for r in rendimientos:
        key = (r.activo, r.subtipo)
        agrupado[key]["cantidad"] += r.cantidad
        agrupado[key]["ops"]      += 1
        agrupado[key]["subtipo"]   = r.subtipo

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
    n = len(rows)
    row_bgs = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else TABLE_ALT) for i in range(1, n)]
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (2, 0), (-1, -1), "RIGHT"),
    ] + row_bgs))
    return t


def generar_pdf(motor, nombre_usuario="", ejercicio="", exchange="Binance", rendimientos=None) -> bytes:
    styles = _build_styles()
    buf = io.BytesIO()
    resumen    = motor.resumen_fiscal()
    posiciones = motor.posicion_actual()
    rendimientos = rendimientos or []

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=22*mm, bottomMargin=20*mm,
        title=f"Informe Fiscal Cripto {ejercicio or 'Completo'} - Mariano Sevilla",
        author="marianosevilla.com"
    )
    story = []

    # 1. PORTADA
    _portada(story, styles, resumen, nombre_usuario, ejercicio, exchange)

    # 2. COMPENSACIONES + MODELO 721
    for fl in _bloque_compensaciones(
            resumen["ganancias_brutas"], resumen["perdidas_brutas"],
            resumen["resultado_neto"], rendimientos, styles):
        story.append(fl)
    for fl in _bloque_modelo_721(posiciones, styles, ejercicio):
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
        # Nota prudente cuando se filtra por ejercicio concreto
        _ej = (ejercicio or "").strip()
        if _ej and _ej.lower() != "all":
            _partes = [p.strip() for p in _ej.split(",") if p.strip()]
            _año_txt = _partes[-1] if _partes else _ej
            story.append(Paragraph(
                f"Nota: el inventario refleja la situación tras todas las operaciones contenidas "
                f"en el CSV, no necesariamente el saldo exacto a 31 de diciembre de {_año_txt}. "
                "Verifique y concilie con los saldos reales en su exchange o wallet.",
                styles["body_muted"]
            ))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_posicion(posiciones, styles))

    # 6. RENDIMIENTOS
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
        warn_rows = [[Paragraph(f"⚠  {adv}", styles["warning"])] for adv in motor.advertencias]
        t_warn = Table(warn_rows, colWidths=[168*mm])
        t_warn.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#FEF9F0")),
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#FCD34D")),
            ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(t_warn)

    # 8. NOTAS EXPLICATIVAS
    story.append(PageBreak())
    story.append(Paragraph("Notas Explicativas", styles["section"]))
    story.append(Paragraph(
        "Conceptos fiscales aplicados en la generación de este informe.",
        styles["body_muted"]
    ))
    story.append(Spacer(1, 4*mm))

    notas = [
        ("Método FIFO\nart. 37.2 LIRPF",
         "La normativa española establece que cuando existan valores homogéneos, se considerará que los "
         "transmitidos son los adquiridos en primer lugar (First In, First Out). Este método es obligatorio "
         "y no puede sustituirse por LIFO, HIFO ni precio medio."),
        ("Comisiones de compra\nincremento del coste",
         "Las comisiones pagadas en el momento de adquirir un criptoactivo forman parte del precio de "
         "adquisición y se suman al coste del lote correspondiente. Esto reduce la ganancia futura o "
         "aumenta la pérdida cuando se venda dicho lote."),
        ("Comisiones de venta\nreducción del valor de transmisión",
         "Las comisiones pagadas al vender un criptoactivo reducen el valor de transmisión declarado. "
         "Esto reduce la ganancia o aumenta la pérdida resultante de la operación."),
        ("Swaps entre criptoactivos\nhecho imponible",
         "El intercambio directo entre dos criptoactivos distintos se considera una transmisión a efectos "
         "del IRPF. Genera una ganancia o pérdida patrimonial calculada como la diferencia entre el valor "
         "de mercado del activo recibido y el coste FIFO del activo entregado."),
        ("Depósitos y retiradas\nno generan hecho imponible",
         "Los movimientos de criptoactivos entre wallets propias o entre exchanges del mismo titular no "
         "constituyen transmisión patrimonial. Es importante conservar los registros para acreditar "
         "que se trata del mismo titular."),
        ("Staking y rendimientos\nrendimiento de capital mobiliario",
         "Los ingresos por staking, intereses de lending o comisiones de referido se califican "
         "generalmente como rendimientos de capital mobiliario y tributan a la tarifa del ahorro (19-28%). "
         "Esta herramienta los clasifica pero no los incluye en el cálculo de la base del ahorro por transmisiones."),
        ("Filtrado por ejercicio\nbase FIFO = histórico completo",
         "Cuando se seleccionan ejercicios concretos, el cálculo FIFO se realiza sobre la totalidad "
         "del historial del CSV para respetar la normativa (art. 37.2 LIRPF). El informe muestra "
         "únicamente las transmisiones y rendimientos cuya fecha corresponde a los ejercicios "
         "seleccionados, pero el coste FIFO de cada venta se calcula correctamente usando las "
         "compras previas aunque sean de ejercicios anteriores."),
    ]

    # Tabla de notas — dos columnas: Concepto | Explicación
    notas_cabecera = [
        Paragraph("CONCEPTO", styles["th"]),
        Paragraph("EXPLICACIÓN", styles["th"]),
    ]
    notas_rows = [notas_cabecera]
    for titulo_nota, texto in notas:
        partes = titulo_nota.split("\n")
        celda_izq = [Paragraph(partes[0], styles["nota_label"])]
        if len(partes) > 1:
            celda_izq.append(Paragraph(partes[1], styles["nota_sub"]))
        notas_rows.append([celda_izq, Paragraph(texto, styles["nota_body"])])

    t_notas = Table(notas_rows, colWidths=[46*mm, 122*mm])
    n = len(notas_rows)
    row_bgs_n = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else TABLE_ALT) for i in range(1, n)]
    t_notas.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ] + row_bgs_n))
    story.append(t_notas)

    # DISCLAIMER
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE_COLOR))
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
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=22*mm, bottomMargin=20*mm,
        title=f"Informe Fiscal Cripto {ejercicio or 'Completo'} - Bit2Me - Mariano Sevilla",
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
                Paragraph(r.fecha_venta[:10], styles["td_muted"]),
                Paragraph(r.tipo_op.upper(),  styles["td"]),
                Paragraph(r.activo,           styles["td"]),
                Paragraph(f"{r.cantidad:,.6f}",            styles["td_mono"]),
                Paragraph(f"{r.precio_transmision:,.4f}",  styles["td_mono"]),
                Paragraph(f"{r.precio_coste:,.4f}",        styles["td_mono"]),
                Paragraph(f"+{gp:,.4f}" if gp >= 0 else f"{gp:,.4f}", gp_s),
            ])
        col_w = [22*mm, 14*mm, 18*mm, 28*mm, 32*mm, 32*mm, 22*mm]
        t = Table(rows, colWidths=col_w, repeatRows=1)
        n = len(rows)
        row_bgs = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else TABLE_ALT) for i in range(1, n)]
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
            ("LINEBELOW",     (0, 0), (-1, 0),  1, ACCENT),
            ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
            ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ("ALIGN",         (3, 0), (-1, -1), "RIGHT"),
        ] + row_bgs))
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
        warn_rows = [[Paragraph(f"⚠  {adv}", styles["warning"])] for adv in clasificador.advertencias]
        t_warn = Table(warn_rows, colWidths=[168*mm])
        t_warn.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#FEF9F0")),
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#FCD34D")),
            ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(t_warn)

    # Disclaimer
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE_COLOR))
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
