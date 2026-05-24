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


def _td_safe(text: str, max_chars: int = 300) -> str:
    """
    Trunca strings de datos de usuario antes de meterlos en celdas de tabla PDF.

    ReportLab lanza LayoutError cuando el contenido de una celda es tan alto
    que no cabe en una página (p.ej. un ticker de 500 chars sin espacios en
    una columna de 28mm). Truncar a max_chars evita ese caso extremo sin
    alterar datos calculados — solo afecta a la presentación visual.
    """
    s = str(text) if text is not None else ""
    if len(s) > max_chars:
        return s[:max_chars - 1] + "…"
    return s


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

# ── PALETA PREMIUM v2 (portada + resumen ejecutivo) ───────────────────────────
ACCENT_SOFT  = colors.HexColor("#EFF6FF")  # fondo tarjetas KPI suave
ACCENT_MID   = colors.HexColor("#BFDBFE")  # borde tarjetas KPI
GREEN_SOFT   = colors.HexColor("#F0FDF4")  # fondo tarjeta positiva
GREEN_MID    = colors.HexColor("#86EFAC")  # borde tarjeta positiva
RED_SOFT     = colors.HexColor("#FEF2F2")  # fondo tarjeta negativa
RED_MID      = colors.HexColor("#FCA5A5")  # borde tarjeta negativa
NEUTRAL_SOFT = colors.HexColor("#F8FAFC")  # fondo tarjetas neutras
COVER_RULE   = colors.HexColor("#1E3A8A")  # línea divisora portada (ACCENT, explícita)
GRID_LIGHT   = colors.HexColor("#EAECF0")  # grid v2 — más suave que BORDER (#D1D5DB)
ZEBRA_LIGHT  = colors.HexColor("#FAFBFC")  # zebra v2 — casi imperceptible, más premium


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

        # ── Estilos v2 — portada premium + resumen ejecutivo ──────────────────
        # Portada — branding y hero
        "cover_brand":        ParagraphStyle("cover_brand",   fontName="Helvetica-Bold",    fontSize=9,  textColor=ACCENT,      leading=13),
        "cover_brand_sub":    ParagraphStyle("cover_brand_s", fontName="Helvetica",         fontSize=8,  textColor=TEXT_MUTED,  leading=11),
        "cover_title":        ParagraphStyle("cover_title",   fontName="Helvetica-Bold",    fontSize=30, textColor=ACCENT,      leading=36, spaceAfter=2),
        "cover_title_year":   ParagraphStyle("cover_title_y", fontName="Helvetica-Bold",    fontSize=30, textColor=TEXT,        leading=36, spaceAfter=4),
        "cover_subtitle":     ParagraphStyle("cover_subtitle",fontName="Helvetica",         fontSize=11, textColor=TEXT_MUTED,  leading=16, spaceAfter=0),
        "cover_footer":       ParagraphStyle("cover_footer",  fontName="Helvetica",         fontSize=8,  textColor=TEXT_MUTED,  leading=11, alignment=TA_CENTER),
        # Portada — info grid (preparado para / ejercicio / exchange / fecha)
        "cover_info_label":   ParagraphStyle("cov_inf_l",     fontName="Helvetica",         fontSize=8,  textColor=TEXT_MUTED,  leading=12),
        "cover_info_value":   ParagraphStyle("cov_inf_v",     fontName="Helvetica-Bold",    fontSize=8,  textColor=TEXT,        leading=12),
        # Portada — tarjetas KPI premium
        "kpi_v2_label":       ParagraphStyle("kpi2_lab",      fontName="Helvetica-Bold",    fontSize=6.5,textColor=TEXT_MUTED,  leading=9,  alignment=TA_CENTER, spaceAfter=3),
        "kpi_v2_value":       ParagraphStyle("kpi2_val",      fontName="Helvetica-Bold",    fontSize=16, textColor=TEXT,        leading=20, alignment=TA_CENTER),
        "kpi_v2_value_green": ParagraphStyle("kpi2_val_g",    fontName="Helvetica-Bold",    fontSize=16, textColor=GREEN_P,     leading=20, alignment=TA_CENTER),
        "kpi_v2_value_red":   ParagraphStyle("kpi2_val_r",    fontName="Helvetica-Bold",    fontSize=16, textColor=RED_P,       leading=20, alignment=TA_CENTER),
        "kpi_v2_value_sm":    ParagraphStyle("kpi2_val_sm",   fontName="Helvetica-Bold",    fontSize=13, textColor=TEXT,        leading=17, alignment=TA_CENTER),
        # Resumen ejecutivo — metadatos y badges
        "exec_meta_label":    ParagraphStyle("exec_ml",       fontName="Helvetica",         fontSize=8.5,textColor=TEXT_MUTED,  leading=13),
        "exec_meta_value":    ParagraphStyle("exec_mv",       fontName="Helvetica-Bold",    fontSize=8.5,textColor=TEXT,        leading=13),
        "exec_badge":         ParagraphStyle("exec_badge",    fontName="Helvetica-Bold",    fontSize=7,  textColor=ACCENT,      leading=10, alignment=TA_CENTER),
        # FAQ cards — página de notas explicativas
        "faq_title":          ParagraphStyle("faq_title",     fontName="Helvetica-Bold",    fontSize=10, textColor=ACCENT,      leading=14),
        "faq_ref":            ParagraphStyle("faq_ref",       fontName="Helvetica-Oblique", fontSize=7.5,textColor=TEXT_MUTED,  leading=11, spaceBefore=1),
        "faq_body":           ParagraphStyle("faq_body",      fontName="Helvetica",         fontSize=9,  textColor=TEXT,        leading=14, spaceBefore=4),
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

    # Footer: texto legal discreto — gris muy suave, tamaño mínimo, bajo contraste
    _FOOTER_GRAY = colors.HexColor("#9CA3AF")
    canvas_obj.setFont("Helvetica-Oblique", 6.0)
    canvas_obj.setFillColor(_FOOTER_GRAY)
    canvas_obj.drawCentredString(
        w / 2, 8*mm,
        "Documento auxiliar de organización fiscal. No constituye asesoramiento fiscal ni legal. "
        "Debe ser revisado por un asesor fiscal antes de su presentación."
    )
    canvas_obj.drawCentredString(w / 2, 4.5*mm, f"marianosevilla.com  |  Página {doc.page}")

    canvas_obj.restoreState()


# ── HELPERS v2 ───────────────────────────────────────────────────────────────

def _divisor_portada(width_mm: float = 168) -> HRFlowable:
    """Línea divisora en ACCENT — más gruesa y de color que la gris habitual."""
    return HRFlowable(width="100%", thickness=1.5, color=COVER_RULE, spaceAfter=0)


def _tarjeta_kpi_v2(label: str, value: str, value_style_key: str,
                    bg_color, border_color, styles, width_mm: float = 52) -> Table:
    """
    Tarjeta KPI premium — label pequeño en mayúsculas + valor grande centrado.
    Fondo de color suave, borde tenue, mucho padding.
    """
    data = [
        [Paragraph(label.upper(), styles["kpi_v2_label"])],
        [Paragraph(value, styles[value_style_key])],
    ]
    t = Table(data, colWidths=[width_mm * mm], rowHeights=[10 * mm, 14 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg_color),
        ("BOX",           (0, 0), (-1, -1), 0.8, border_color),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.3, border_color),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, 0),  7),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  4),
        ("TOPPADDING",    (0, 1), (-1, 1),  4),
        ("BOTTOMPADDING", (0, 1), (-1, 1),  8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    return t


def _portada_v2(story, styles, resumen, nombre_usuario, ejercicio, exchange, periodo=None):
    """
    Portada premium v2 — estilo fintech / dashboard cover.
    Diseño: branding → hero title → divisor → info grid → 6 KPI cards → disclaimer.
    NO incluye la tabla "Determinación de Bases Imponibles" (se mueve al resumen ejecutivo).
    Compatible con generar_pdf(); NO se usa en generar_pdf_bit2me().
    """
    # ── Construir textos de ejercicio ─────────────────────────────────────────
    ejercicio = (ejercicio or "").strip()
    if ejercicio and ejercicio.lower() != "all":
        partes = sorted([p.strip() for p in ejercicio.split(",") if p.strip()])
        titulo_ejercicio = ", ".join(partes)
        meta_ejercicio   = ", ".join(partes)
    else:
        titulo_ejercicio = None
        meta_ejercicio   = "Todos los ejercicios"

    story.append(Spacer(1, 2 * mm))

    # ── 1. Hero title ─────────────────────────────────────────────────────────
    story.append(Paragraph("INFORME FISCAL CRIPTO", styles["cover_title"]))
    if titulo_ejercicio:
        story.append(Paragraph(titulo_ejercicio, styles["cover_title_year"]))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Método FIFO · Compatible con AEAT", styles["cover_subtitle"]))
    story.append(Spacer(1, 8 * mm))

    # ── 2. Divisor en ACCENT ──────────────────────────────────────────────────
    story.append(_divisor_portada())
    story.append(Spacer(1, 8 * mm))

    # ── 4. Info card premium — Ejercicio · Titular · Fecha ───────────────────────
    fecha_gen   = datetime.utcnow().strftime("%d/%m/%Y")
    nombre_show = nombre_usuario.upper() if nombre_usuario else "—"

    _ic_lbl = ParagraphStyle("ic_lbl", fontName="Helvetica",     fontSize=6.5,
                              textColor=TEXT_MUTED, leading=10, alignment=TA_CENTER,
                              spaceAfter=3)
    _ic_val = ParagraphStyle("ic_val", fontName="Helvetica-Bold", fontSize=11,
                              textColor=TEXT,       leading=15, alignment=TA_CENTER)

    info_card_rows = [
        [Paragraph("EJERCICIO",    _ic_lbl),
         Paragraph("TITULAR",      _ic_lbl),
         Paragraph("GENERADO",     _ic_lbl)],
        [Paragraph(meta_ejercicio, _ic_val),
         Paragraph(nombre_show,    _ic_val),
         Paragraph(fecha_gen,      _ic_val)],
    ]
    t_info = Table(info_card_rows,
                   colWidths=[56 * mm, 56 * mm, 56 * mm],
                   rowHeights=[7 * mm, 11 * mm])
    t_info.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), NEUTRAL_SOFT),
        ("BOX",           (0, 0), (-1, -1), 0.6, BORDER),
        ("LINEAFTER",     (0, 0), (1, -1),  0.5, RULE_COLOR),   # separadores verticales suaves
        ("VALIGN",        (0, 0), (-1, 0),  "BOTTOM"),           # labels pegadas al fondo de su fila
        ("VALIGN",        (0, 1), (-1, 1),  "TOP"),              # valores pegados al techo de su fila
        ("TOPPADDING",    (0, 0), (-1, 0),  9),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  2),
        ("TOPPADDING",    (0, 1), (-1, 1),  2),
        ("BOTTOMPADDING", (0, 1), (-1, 1),  10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))
    story.append(t_info)
    story.append(Spacer(1, 14 * mm))

    # ── 5. KPI cards — 2 filas × 3 columnas ──────────────────────────────────
    neto      = resumen["resultado_neto"]
    ganancias = resumen["ganancias_brutas"]
    perdidas  = resumen["perdidas_brutas"]
    n_ops     = resumen["operaciones_con_resultado"]

    neto_fmt = f"+{neto:,.2f} EUR" if neto >= 0 else f"{neto:,.2f} EUR"
    neto_key = "kpi_v2_value_green" if neto >= 0 else "kpi_v2_value_red"
    neto_bg  = GREEN_SOFT if neto >= 0 else RED_SOFT
    neto_brd = GREEN_MID  if neto >= 0 else RED_MID

    # Detectar activos (posición actual del motor — no disponible aquí, se pasa desde fuera)
    # Usamos el campo _n_activos que se inyecta opcionalmente via kwarg
    # (Si no se pasa, mostramos "—")

    card_neto     = _tarjeta_kpi_v2("Resultado Neto",     neto_fmt,                     neto_key,           neto_bg,      neto_brd,  styles, 52)
    card_gan      = _tarjeta_kpi_v2("Ganancias Brutas",   f"+{ganancias:,.2f} EUR",      "kpi_v2_value_green", GREEN_SOFT, GREEN_MID, styles, 52)
    card_perd     = _tarjeta_kpi_v2("Pérdidas Brutas",    f"{perdidas:,.2f} EUR",        "kpi_v2_value_red",   RED_SOFT,   RED_MID,   styles, 52)

    card_ops      = _tarjeta_kpi_v2("Operaciones",        str(n_ops),                   "kpi_v2_value_sm",    ACCENT_SOFT, ACCENT_MID, styles, 52)
    card_exchange = _tarjeta_kpi_v2("Exchange",           exchange or "—",              "kpi_v2_value_sm",    NEUTRAL_SOFT, BORDER,    styles, 52)

    # Activos: se determina desde resumen si está disponible, si no "—"
    n_activos_str = resumen.get("_n_activos", "—")
    if isinstance(n_activos_str, int):
        n_activos_str = str(n_activos_str)
    card_activos  = _tarjeta_kpi_v2("Activos Detectados", str(n_activos_str),           "kpi_v2_value_sm",    NEUTRAL_SOFT, BORDER,    styles, 52)

    # Fila 1: resultado / ganancias / pérdidas
    row1 = [[card_neto, card_gan, card_perd]]
    t_row1 = Table(row1, colWidths=[54 * mm, 54 * mm, 54 * mm])
    t_row1.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("INNERGRID",     (0, 0), (-1, -1), 0, colors.white),
    ]))
    # Separación entre tarjetas: se logra con rightPadding del contenedor
    # Solución más limpia: usar colWidths con 2mm de gutter
    row1b = [[card_neto, Spacer(2*mm, 1), card_gan, Spacer(2*mm, 1), card_perd]]
    t_kpi1 = Table(row1b, colWidths=[52*mm, 2*mm, 52*mm, 2*mm, 52*mm])
    t_kpi1.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(t_kpi1)
    story.append(Spacer(1, 4 * mm))

    # Fila 2: operaciones / exchange / activos
    row2b = [[card_ops, Spacer(2*mm, 1), card_exchange, Spacer(2*mm, 1), card_activos]]
    t_kpi2 = Table(row2b, colWidths=[52*mm, 2*mm, 52*mm, 2*mm, 52*mm])
    t_kpi2.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(t_kpi2)
    story.append(Spacer(1, 8 * mm))

    # ── 6. Disclaimer discreto ───────────────────────────────────────────────
    story.append(Spacer(1, 5 * mm))
    _disc_style = ParagraphStyle(
        "portada_disc", fontName="Helvetica-Oblique", fontSize=7,
        textColor=colors.HexColor("#9CA3AF"),   # más apagado que TEXT_MUTED
        leading=10, alignment=TA_CENTER,
    )
    _disc_texto = (
        "Documento auxiliar generado automáticamente. No constituye asesoramiento fiscal ni legal. "
        "Debe ser revisado por un asesor fiscal antes de su presentación ante la Agencia Tributaria."
    )
    _disc_data = [[Paragraph(_disc_texto, _disc_style)]]
    _t_disc = Table(_disc_data, colWidths=[140 * mm])   # más estrecho que los 168mm habituales
    _t_disc.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    story.append(_t_disc)
    story.append(Spacer(1, 4 * mm))

    # ── 7. Footer portada ─────────────────────────────────────────────────────
    story.append(Paragraph("generado por marianosevilla.com", styles["cover_footer"]))


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


def _resumen_ejecutivo(story, styles, resumen, motor, ejercicio, exchange, rendimientos):
    """
    Sección 'Resumen Ejecutivo' premium — aparece justo después de la portada v2,
    antes del gráfico y las tablas de datos.

    Contiene:
    - Grid de metadatos (2 columnas): financiero + contextual
    - Tabla 'Determinación de Bases Imponibles' (movida desde _portada)
    - Nota FIFO (movida desde _portada)
    - Bloque compensaciones + Modelo 721 (continúan igual, se llaman desde generar_pdf)

    NO modifica lógica fiscal. Solo presenta datos ya calculados.
    """
    ejercicio = (ejercicio or "").strip()

    # ── Calcular métricas de contexto ─────────────────────────────────────────
    n_activos      = len(set(r.activo for r in motor.resultados)) if motor.resultados else 0
    n_advertencias = len(motor.advertencias) if motor.advertencias else 0
    n_rendimientos = len(rendimientos) if rendimientos else 0

    if ejercicio and ejercicio.lower() != "all":
        partes = sorted([p.strip() for p in ejercicio.split(",") if p.strip()])
        año_txt = ", ".join(partes)
    else:
        año_txt = "Todos"

    ganancias = resumen["ganancias_brutas"]
    perdidas  = resumen["perdidas_brutas"]
    neto      = resumen["resultado_neto"]
    n_ops     = resumen["operaciones_con_resultado"]

    # ── Título de sección ─────────────────────────────────────────────────────
    story.append(Spacer(1, 5 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=RULE_COLOR))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Resumen Ejecutivo", styles["section"]))
    story.append(Paragraph(
        "Vista general del resultado fiscal y del alcance del análisis.",
        styles["body_muted"]
    ))
    story.append(Spacer(1, 4 * mm))

    # ── Grid de metadatos: 2 columnas ────────────────────────────────────────
    # Columna izquierda: magnitudes financieras
    # Columna derecha: contexto del análisis
    def _fila(label, value, label_style="exec_meta_label", value_style="exec_meta_value"):
        return [Paragraph(label, styles[label_style]),
                Paragraph(str(value), styles[value_style])]

    neto_str = f"+{neto:,.2f} EUR" if neto >= 0 else f"{neto:,.2f} EUR"
    rev_str  = f"{n_advertencias} operación{'es' if n_advertencias != 1 else ''}" if n_advertencias else "Ninguna"

    izq = [
        _fila("Resultado neto",     neto_str),
        _fila("Ganancias brutas",   f"+{ganancias:,.2f} EUR"),
        _fila("Pérdidas brutas",    f"{perdidas:,.2f} EUR"),
        _fila("Operaciones FIFO",   str(n_ops)),
    ]
    dch = [
        _fila("Exchange analizado",       exchange or "—"),
        _fila("Activos detectados",       str(n_activos) if n_activos else "—"),
        _fila("Con revisión manual",      rev_str),
        _fila("Año fiscal",               año_txt),
    ]

    # Construir tabla de 4 columnas (label izq | value izq | label dch | value dch)
    meta_rows = []
    for (li, vi), (ld, vd) in zip(izq, dch):
        meta_rows.append([li, vi, ld, vd])

    # Fila extra: método + rendimientos
    meta_rows.append([
        Paragraph("Método de cálculo",  styles["exec_meta_label"]),
        Paragraph("FIFO — art. 37.2 LIRPF", styles["exec_meta_value"]),
        Paragraph("Rendimientos RCM",   styles["exec_meta_label"]),
        Paragraph(str(n_rendimientos) if n_rendimientos else "—", styles["exec_meta_value"]),
    ])

    t_meta = Table(meta_rows, colWidths=[38 * mm, 46 * mm, 38 * mm, 46 * mm])
    n_meta = len(meta_rows)
    meta_bgs = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 0 else TABLE_ALT)
                for i in range(n_meta)]
    t_meta.setStyle(TableStyle([
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
        ("LINEAFTER",     (1, 0), (1, -1),  0.8, BORDER),   # separador entre columnas
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ] + meta_bgs))
    story.append(t_meta)
    story.append(Spacer(1, 5 * mm))

    # ── Tabla: Determinación de Bases Imponibles ──────────────────────────────
    # (movida aquí desde _portada / _portada_v2 para limpiar la cover)
    story.append(Paragraph("Determinación de Bases Imponibles", styles["section"]))
    story.append(Paragraph(
        "Desglose de las ganancias y pérdidas según su tratamiento fiscal en el IRPF español.",
        styles["body_muted"]
    ))
    story.append(Spacer(1, 3 * mm))

    resumen_data = [
        [Paragraph("BASE DEL AHORRO — Transmisiones de criptoactivos (art. 33 LIRPF)", styles["th"]),
         Paragraph("IMPORTE (EUR)", styles["th_right"])],
        [Paragraph("Suma de ganancias patrimoniales", styles["resumen_label"]),
         Paragraph(f"+{ganancias:,.2f}", styles["resumen_value_green"])],
        [Paragraph("Suma de pérdidas patrimoniales", styles["resumen_label"]),
         Paragraph(f"{perdidas:,.2f}", styles["resumen_value_red"])],
        [Paragraph("TOTAL GANANCIAS Y PÉRDIDAS PATRIMONIALES NETAS", styles["subsection"]),
         Paragraph(f"+{neto:,.2f}" if neto >= 0 else f"{neto:,.2f}",
                   styles["resumen_value_green"] if neto >= 0 else styles["resumen_value_red"])],
    ]
    t_bases = Table(resumen_data, colWidths=[128 * mm, 40 * mm])
    t_bases.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, ACCENT),
        ("BACKGROUND",    (0, 1), (-1, 2),  BG),
        ("BACKGROUND",    (0, 3), (-1, 3),  TABLE_HEAD),
        ("LINEABOVE",     (0, 3), (-1, 3),  0.5, BORDER),
        ("LINEBELOW",     (0, 3), (-1, 3),  1.2, ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),   # 6 → 8
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),   # 6 → 8
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),  # 8 → 10
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),  # 8 → 10
    ]))
    story.append(t_bases)
    story.append(Spacer(1, 5 * mm))

    # ── Nota FIFO compacta ────────────────────────────────────────────────────
    # (movida desde _portada / _portada_v2)
    if ejercicio and ejercicio.lower() != "all":
        fifo_data = [[Paragraph(
            "<b>Nota sobre el cálculo FIFO:</b> El cálculo de costes se realiza utilizando el histórico "
            "completo del CSV para respetar correctamente la cola FIFO (art. 37.2 LIRPF). "
            "Este informe muestra únicamente las transmisiones y rendimientos correspondientes "
            "a los ejercicios fiscales seleccionados.",
            styles["aviso_legal"])]]
        t_fifo = Table(fifo_data, colWidths=[168 * mm])
        t_fifo.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#EFF6FF")),
            ("BOX",           (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING",   (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ]))
        story.append(t_fifo)

    # ── Nota FIFO general ─────────────────────────────────────────────────────
    nota_data = [[Paragraph(
        "<b>Método FIFO obligatorio (art. 37.2 LIRPF).</b> Las comisiones de compra incrementan el precio de coste "
        "del lote. Las comisiones de venta reducen el valor de transmisión. Los swaps entre criptoactivos "
        "se tratan como venta y compra simultánea a valor de mercado, generando hecho imponible. "
        "Los depósitos y retiradas entre wallets propias no generan hecho imponible.",
        styles["nota_body"])]]
    t_nota = Table(nota_data, colWidths=[168 * mm])
    t_nota.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), INFO_BG),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),  # 7 → 10
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),  # 7 → 10
        ("LEFTPADDING",   (0, 0), (-1, -1), 11),  # 9 → 11
        ("RIGHTPADDING",  (0, 0), (-1, -1), 11),  # 9 → 11
    ]))
    story.append(Spacer(1, 4 * mm))
    story.append(t_nota)


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


def _separador_bloque() -> list:
    """
    Separador visual elegante entre bloques de contenido fiscal en página 2.
    Devuelve [Spacer, HRFlowable, Spacer] — aire + línea fina gris + aire.
    No usa cajas ni colores: solo ritmo visual y jerarquía.
    """
    return [
        Spacer(1, 9 * mm),
        HRFlowable(width="100%", thickness=0.4, color=RULE_COLOR, spaceAfter=0),
        Spacer(1, 7 * mm),
    ]


def _bloque_compensaciones(ganancias, perdidas, neto, rendimientos_list, styles):
    """Bloque de compensaciones fiscales (art. 49 LIRPF). Devuelve lista de flowables."""
    flowables = []
    rcm_total = sum(getattr(r, "valor_eur", 0.0) for r in rendimientos_list) if rendimientos_list else 0.0

    for fl in _separador_bloque():
        flowables.append(fl)
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
        return _separador_bloque() + [t]

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
        titulo = f"Modelo 721 — Revisión orientativa — verificación manual requerida"
        texto  = (
            f"El coste de adquisición FIFO de los activos en cartera es de {coste_total:,.2f} EUR, "
            "por debajo del umbral de 50.000 EUR. No obstante, la obligación se determina por el "
            "<b>valor de mercado</b> (no el coste FIFO), que puede diferir significativamente. "
            f"Debe verificarse el valor de mercado {sufijo_fecha} antes de descartar la presentación "
            f"del Modelo 721. Esta valoración es meramente orientativa — verificación manual requerida.{sufijo_nota}"
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
    return _separador_bloque() + [t]


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
        # Mostrar "0.00" cuando hay operaciones con resultado cero (no "—", que implicaría ausencia)
        g_str = f"+{datos['ganancias']:,.2f}" if datos["ganancias"] != 0 else "0.00"
        p_str = f"{datos['perdidas']:,.2f}"   if datos["perdidas"]  != 0 else "0.00"
        n_str = f"+{neto:,.2f}" if neto >= 0 else f"{neto:,.2f}"
        rows.append([
            Paragraph(_td_safe(activo, 40), styles["td"]),
            Paragraph(str(datos["ops"]), styles["td_muted_right"]),
            Paragraph(g_str, styles["td_green"]),
            Paragraph(p_str, styles["td_red"]),
            Paragraph(n_str, neto_style),
        ])

    col_w = [28*mm, 18*mm, 44*mm, 44*mm, 34*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    n = len(rows)
    row_bgs = []
    for i in range(1, n):
        row_bgs.append(("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else ZEBRA_LIGHT))
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  ACCENT_SOFT),   # header azul suave
        ("LINEBELOW",     (0, 0), (-1, 0),  1,   ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.2, GRID_LIGHT),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING",    (0, 0), (-1, 0),  9),   # header: más alto
        ("BOTTOMPADDING", (0, 0), (-1, 0),  9),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
    ] + row_bgs))
    return t


def _fmt_cantidad(q: float) -> str:
    """Formato adaptativo de cantidad según magnitud — evita desbordamiento de columna."""
    if q >= 1_000_000:
        return f"{q:,.0f}"
    elif q >= 10_000:
        return f"{q:,.1f}"
    elif q >= 100:
        return f"{q:,.2f}"
    elif q >= 1:
        return f"{q:,.4f}"
    else:
        return f"{q:,.6f}"


def _tabla_operaciones(resultados, styles):
    cabecera = [
        Paragraph("FECHA",                    styles["th"]),
        Paragraph("TIPO",                     styles["th"]),
        Paragraph("ACTIVO",                   styles["th"]),
        Paragraph("CANTIDAD",                 styles["th_right"]),
        Paragraph("VALOR TRANSMISIÓN (EUR)",  styles["th_right"]),
        Paragraph("COSTE ADQUISICIÓN (EUR)",  styles["th_right"]),
        Paragraph("GANANCIA/PÉRDIDA (EUR)",   styles["th_right"]),
        Paragraph("DÍAS",                     styles["th_right"]),
    ]
    rows = [cabecera]
    _filas_incompletas = []  # índices de filas con inventario_incompleto (base-1, incluyendo header)

    for i, r in enumerate(resultados):
        gp = r.ganancia_perdida
        gp_style = styles["td_green"] if gp >= 0 else styles["td_red"]
        gp_str   = f"+{gp:,.2f}" if gp >= 0 else f"{gp:,.2f}"
        _inc = getattr(r, "inventario_incompleto", False)

        if _inc:
            _filas_incompletas.append(i + 1)  # +1: la fila 0 es la cabecera
            coste_cell = Paragraph(f"⚠ {r.precio_coste:,.2f}", styles["td_red"])
        else:
            coste_cell = Paragraph(f"{r.precio_coste:,.2f}", styles["td_mono"])

        rows.append([
            Paragraph(r.fecha.strftime("%d/%m/%Y"), styles["td_muted"]),
            Paragraph(r.tipo_operacion.upper(), styles["td"]),
            Paragraph(_td_safe(r.activo, 40), styles["td"]),
            Paragraph(_fmt_cantidad(r.cantidad_vendida),  styles["td_mono"]),
            Paragraph(f"{r.precio_transmision:,.2f}", styles["td_mono"]),
            coste_cell,
            Paragraph(gp_str, gp_style),
            Paragraph(str(int(r.periodo_dias)), styles["td_muted_right"]),
        ])

    # Anchos corregidos: ACTIVO pasa de 14→22mm; se redistribuyen 8mm de columnas holgadas
    # Total: 20+14+22+20+25+25+27+15 = 168mm (= A4 − márgenes)
    col_w = [20*mm, 14*mm, 22*mm, 20*mm, 25*mm, 25*mm, 27*mm, 15*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    n = len(rows)
    row_bgs = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else ZEBRA_LIGHT) for i in range(1, n)]
    # Las filas con inventario insuficiente van en rojo suave (sobreescribe zebra)
    inc_bgs = [("BACKGROUND", (0, fi), (-1, fi), colors.HexColor("#FEF2F2"))
               for fi in _filas_incompletas]
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  ACCENT_SOFT),   # header azul suave
        ("LINEBELOW",     (0, 0), (-1, 0),  1,   ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.2, GRID_LIGHT),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),              # body: +2pt (era 4)
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, 0),  8),              # header: +4pt (era 4)
        ("BOTTOMPADDING", (0, 0), (-1, 0),  8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("ALIGN",         (3, 0), (-1, -1), "RIGHT"),
    ] + row_bgs + inc_bgs))
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
            Paragraph(_td_safe(pos.activo, 40), styles["td"]),
            Paragraph(f"{pos.cantidad_total:,.6f}",   styles["td_mono"]),
            Paragraph(f"{pos.precio_medio:,.4f} EUR",  styles["td_mono"]),
            Paragraph(f"{pos.coste_total:,.4f} EUR",   styles["td_mono"]),
        ])
    col_w = [28*mm, 50*mm, 54*mm, 36*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    n = len(rows)
    row_bgs = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else ZEBRA_LIGHT) for i in range(1, n)]
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  ACCENT_SOFT),
        ("LINEBELOW",     (0, 0), (-1, 0),  1,   ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.2, GRID_LIGHT),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING",    (0, 0), (-1, 0),  9),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  9),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
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
            Paragraph(_td_safe(activo, 40), styles["td"]),
            Paragraph(_td_safe(subtipo.replace("_", " ").capitalize(), 80), styles["td_muted"]),
            Paragraph(str(datos["ops"]), styles["td_muted_right"]),
            Paragraph(f"{datos['cantidad']:,.6f}", styles["td_mono"]),
        ])

    col_w = [28*mm, 60*mm, 28*mm, 52*mm]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    n = len(rows)
    row_bgs = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else ZEBRA_LIGHT) for i in range(1, n)]
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  ACCENT_SOFT),
        ("LINEBELOW",     (0, 0), (-1, 0),  1,   ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.4, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.2, GRID_LIGHT),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING",    (0, 0), (-1, 0),  9),
        ("BOTTOMPADDING", (0, 0), (-1, 0),  9),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("ALIGN",         (2, 0), (-1, -1), "RIGHT"),
    ] + row_bgs))
    return t


def _bloque_estado_analisis(clasificador_stats: dict, motor, rendimientos: list, styles) -> list:
    """
    Bloque 'Estado del análisis' — muestra el desglose de filas del CSV
    clasificadas por tipo. Sólo se muestra cuando se pasa clasificador_stats
    (actualmente sólo para Binance TX).
    """
    if not clasificador_stats:
        return []

    total     = clasificador_stats.get("total_filas_csv", 0)
    n_cv      = clasificador_stats.get("compraventas", 0)
    n_sw      = clasificador_stats.get("swaps", 0)
    n_rend    = clasificador_stats.get("rendimientos", 0)
    n_mov     = clasificador_stats.get("movimientos", 0)
    n_desc    = clasificador_stats.get("desconocidas", 0)
    n_adv     = len(motor.advertencias) if motor.advertencias else 0

    th   = ParagraphStyle("ea_th",   fontName="Helvetica-Bold", fontSize=8,
                           textColor=TEXT, leading=11)
    td   = ParagraphStyle("ea_td",   fontName="Helvetica",      fontSize=8,
                           textColor=TEXT, leading=11)
    td_r = ParagraphStyle("ea_td_r", fontName="Helvetica",      fontSize=8,
                           textColor=TEXT, leading=11, alignment=2)
    td_warn = ParagraphStyle("ea_warn", fontName="Helvetica-Bold", fontSize=8,
                              textColor=colors.HexColor("#92400E"), leading=11, alignment=2)
    td_desc = ParagraphStyle("ea_desc", fontName="Helvetica-Bold", fontSize=8,
                              textColor=colors.HexColor("#991B1B"), leading=11, alignment=2)

    def _fmt(n):
        return f"{n:,}".replace(",", ".")

    filas = [
        [Paragraph("Categoría",              th), Paragraph("Filas CSV",   th), Paragraph("", th)],
        [Paragraph("Transmisiones (FIFO)",   td), Paragraph(_fmt(n_cv),    td_r), Paragraph("",  td)],
        [Paragraph("Swaps cripto↔cripto",    td), Paragraph(_fmt(n_sw),    td_r), Paragraph("",  td)],
        [Paragraph("Rendimientos de capital",td), Paragraph(_fmt(n_rend),  td_r), Paragraph("",  td)],
        [Paragraph("Movimientos internos",   td), Paragraph(_fmt(n_mov),   td_r), Paragraph("",  td)],
    ]

    # Fila de desconocidas — resalta en rojo si hay alguna
    desc_style = td_desc if n_desc > 0 else td_r
    filas.append([
        Paragraph("Filas no clasificadas",   td_desc if n_desc > 0 else td),
        Paragraph(_fmt(n_desc),              desc_style),
        Paragraph("⚠ Revisar" if n_desc > 0 else "", td_desc),
    ])
    filas.append([
        Paragraph("Advertencias de inventario", td_warn if n_adv > 0 else td),
        Paragraph(_fmt(n_adv),               td_warn if n_adv > 0 else td_r),
        Paragraph("⚠ Revisar" if n_adv > 0 else "", td_warn),
    ])
    filas.append([
        Paragraph(f"<b>Total filas CSV</b>", th),
        Paragraph(f"<b>{_fmt(total)}</b>",   ParagraphStyle("ea_tot", fontName="Helvetica-Bold",
                                                              fontSize=8, textColor=TEXT,
                                                              leading=11, alignment=2)),
        Paragraph("", th),
    ])

    n_rows = len(filas)
    row_bgs = [("BACKGROUND", (0, i), (-1, i), BG if i % 2 == 1 else TABLE_ALT) for i in range(1, n_rows)]
    t = Table(filas, colWidths=[78*mm, 28*mm, 22*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  TABLE_HEAD),
        ("LINEBELOW",     (0, 0), (-1, 0),  1, ACCENT),
        ("BOX",           (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID",     (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        # Highlight last row (totals)
        ("BACKGROUND",    (0, n_rows - 1), (-1, n_rows - 1), TABLE_HEAD),
    ] + row_bgs))

    elems = [
        Spacer(1, 5*mm),
        Paragraph("Estado del Análisis", styles["section"]),
        Paragraph(
            f"Desglose de las {_fmt(total)} filas del CSV de Binance según su clasificación fiscal. "
            "Las filas no clasificadas requieren revisión manual.",
            styles["body_muted"]
        ),
        Spacer(1, 3*mm),
        t,
    ]
    if n_adv > 0:
        nota_adv = ParagraphStyle(
            "ea_nota", fontName="Helvetica", fontSize=7.5,
            textColor=TEXT_MUTED, leading=11, spaceBefore=4
        )
        elems.append(Paragraph(
            f"<b>Nota sobre las {_fmt(n_adv)} advertencias de inventario:</b> "
            "Cuando el CSV no contiene el historial completo de compras de un activo entregado en un swap, "
            "el sistema no puede determinar su coste FIFO. En ese caso el activo recibido entra al inventario "
            "con coste base cero y la operación queda marcada para revisión manual. "
            "Esto <b>no es un error del sistema</b>: refleja una limitación de los datos aportados. "
            "Consulta la sección «Advertencias» al final del informe para el detalle.",
            nota_adv
        ))
    return elems


def _aviso_fmv_estimado(n_swaps: int, styles) -> list:
    """
    Caja de aviso para exchanges (como Uphold) que no aportan FMV en EUR.
    Aparece antes de la tabla de operaciones cuando hay swaps con G/P = 0
    porque el precio de transmisión es el coste FIFO (mejor aproximación disponible).
    """
    texto = (
        f"<b>AVISO — Valoración orientativa: {n_swaps} swap{'s' if n_swaps != 1 else ''} requieren revisión manual.</b>  "
        "Uphold no incluye el valor de mercado en EUR en su CSV. Para los swaps cripto↔cripto, el sistema "
        "ha usado el <b>coste FIFO de adquisición como precio de transmisión</b> (mejor aproximación disponible "
        "sin datos de mercado), lo que produce ganancia/pérdida = 0 €. "
        "El valor real de transmisión es el precio de mercado del activo entregado en la fecha del swap. "
        "<b>Debes consultar precios históricos y corregir estos valores con tu asesor fiscal antes "
        "de presentar la declaración.</b>"
    )
    warn_style = ParagraphStyle(
        "fmv_warn", fontName="Helvetica", fontSize=8.5,
        textColor=colors.HexColor("#92400E"), leading=13,
    )
    data = [[Paragraph(texto, warn_style)]]
    t = Table(data, colWidths=[168*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#FFFBEB")),
        ("BOX",           (0, 0), (-1, -1), 0.8, colors.HexColor("#F59E0B")),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
    ]))
    return [t, Spacer(1, 3*mm)]


def _aviso_inventario_incompleto(n_ops: int, activos: list, styles) -> list:
    """
    Aviso rojo prominente cuando hay resultados con inventario_incompleto=True.

    Estas operaciones tienen coste de adquisición parcial o nulo porque el CSV
    no contiene el historial completo de compras previas (p.ej. activos adquiridos
    en un ejercicio anterior no incluido en el fichero exportado). Las ganancias
    mostradas son ARTIFICIALES y no deben declararse sin corrección manual.
    """
    activos_str = ", ".join(sorted(set(activos)))
    texto = (
        f"<b>⚠  INVENTARIO INSUFICIENTE — {n_ops} {'operación' if n_ops == 1 else 'operaciones'} "
        f"con coste de adquisición no verificable.</b>  "
        f"Activos afectados: {activos_str}.  "
        "El CSV aportado no contiene el historial completo de compras previas para estos activos "
        "(posiblemente adquiridos en un período anterior al rango del fichero exportado). "
        "El coste de adquisición de las unidades que no tienen lote de compra previo se ha registrado "
        "como <b>0,00 EUR</b>, produciendo ganancias artificialmente infladas. "
        "Las filas marcadas con <b>⚠</b> en la columna «Coste Adquisición» son las afectadas. "
        "<b>Estos valores NO reflejan el resultado fiscal real y no deben declararse sin antes "
        "aportar el historial completo de adquisición y corregir el coste con tu asesor fiscal.</b>"
    )
    warn_style = ParagraphStyle(
        "inv_inc_warn", fontName="Helvetica", fontSize=8.5,
        textColor=colors.HexColor("#7F1D1D"), leading=13,
    )
    data = [[Paragraph(texto, warn_style)]]
    t = Table(data, colWidths=[168 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor("#FEF2F2")),
        ("BOX",           (0, 0), (-1, -1), 1.5, colors.HexColor("#DC2626")),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
    ]))
    return [t, Spacer(1, 4 * mm)]


def _notas_faq(notas: list, styles) -> list:
    """
    Renderiza las notas explicativas como FAQ cards premium — un bloque por concepto.
    Sustituye la tabla densa de dos columnas de la página 7.

    Cada card:  título (bold ACCENT) + referencia (muted italic) + cuerpo (body)
    Entre cards: separador fino (HR 0.3pt) con aire generoso arriba y abajo.

    El contenido (lista `notas`) no se toca — solo cambia la presentación visual.
    """
    _SEP_CARD = [
        Spacer(1, 6 * mm),
        HRFlowable(width="100%", thickness=0.3, color=RULE_COLOR, spaceAfter=0),
        Spacer(1, 6 * mm),
    ]

    flowables = []
    for i, (titulo_nota, texto) in enumerate(notas):
        partes = titulo_nota.split("\n")
        titulo_principal = partes[0]
        subtitulo        = partes[1] if len(partes) > 1 else ""

        card = [
            Paragraph(titulo_principal, styles["faq_title"]),
        ]
        if subtitulo:
            card.append(Paragraph(subtitulo, styles["faq_ref"]))
        card.append(Paragraph(texto, styles["faq_body"]))

        flowables.append(KeepTogether(card))

        # Separador entre cards, excepto tras la última
        if i < len(notas) - 1:
            flowables.extend(_SEP_CARD)

    return flowables


def generar_pdf(motor, nombre_usuario="", ejercicio="", exchange="Binance", rendimientos=None,
                clasificador_stats=None) -> bytes:
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

    # Inyectar n_activos en el resumen para las tarjetas KPI de portada v2
    resumen["_n_activos"] = len(set(r.activo for r in motor.resultados)) if motor.resultados else 0

    # 1. PORTADA v2 (premium — sin tabla de bases imponibles, esas van al resumen ejecutivo)
    _portada_v2(story, styles, resumen, nombre_usuario, ejercicio, exchange)

    # 2. RESUMEN EJECUTIVO (bases imponibles + metadatos + nota FIFO)
    _resumen_ejecutivo(story, styles, resumen, motor, ejercicio, exchange, rendimientos)

    # 3. COMPENSACIONES + MODELO 721
    for fl in _bloque_compensaciones(
            resumen["ganancias_brutas"], resumen["perdidas_brutas"],
            resumen["resultado_neto"], rendimientos, styles):
        story.append(fl)
    for fl in _bloque_modelo_721(posiciones, styles, ejercicio):
        story.append(fl)

    # 3b. ESTADO DEL ANÁLISIS (solo cuando se pasa clasificador_stats, p.ej. Binance TX)
    for fl in _bloque_estado_analisis(clasificador_stats, motor, rendimientos, styles):
        story.append(fl)

    # 4. RESUMEN POR ACTIVO + GRÁFICO
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

    # 5. DETALLE OPERACIONES
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
        # Aviso inventario insuficiente — coste no verificable (p.ej. activos comprados
        # fuera del rango del CSV; las ganancias mostradas pueden ser artificiales).
        _res_inc = [r for r in motor.resultados if getattr(r, "inventario_incompleto", False)]
        if _res_inc:
            _activos_inc = [r.activo for r in _res_inc]
            for _fl in _aviso_inventario_incompleto(len(_res_inc), _activos_inc, styles):
                story.append(_fl)
        # Aviso específico cuando el exchange no aporta FMV en EUR (p.ej. Uphold):
        # los swaps muestran G/P = 0 porque se usa coste FIFO como proxy.
        if exchange == "Uphold":
            _n_swaps_sin_fmv = sum(
                1 for r in motor.resultados
                if r.tipo_operacion == "swap" and abs(r.ganancia_perdida) < 0.001
            )
            if _n_swaps_sin_fmv > 0:
                for _fl in _aviso_fmv_estimado(_n_swaps_sin_fmv, styles):
                    story.append(_fl)
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
        for fl in _separador_bloque():
            story.append(fl)
        story.append(Paragraph("Rendimientos de Capital Mobiliario", styles["section"]))
        story.append(Paragraph(
            "Ingresos por staking, rebates y otros rendimientos recibidos durante el período. "
            "Tributan como rendimientos de capital mobiliario a la tarifa del ahorro (19-28%). "
            "No se incluyen en la base del ahorro por transmisiones — consúltalos con tu gestor.",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))
        story.append(_tabla_rendimientos(rendimientos, styles))
        # Nota de valoración si hay rendimientos en cripto (sin precio EUR conocido)
        _activos_cripto_rend = {
            r.activo for r in rendimientos if r.activo not in ("EUR", "USDT", "USDC", "BUSD", "FDUSD", "DAI", "USD")
        }
        if _activos_cripto_rend:
            story.append(Spacer(1, 3*mm))
            story.append(Paragraph(
                "<b>Nota sobre valoración de rendimientos en criptomoneda:</b> "
                "Los rendimientos expresados en criptomonedas (comisiones, recompensas de pools, "
                "airdrops, etc.) se muestran por <i>cantidad de tokens recibidos</i>, no por su "
                "equivalente en EUR. Para calcular la base imponible correcta es necesario "
                "aplicar el valor de mercado en EUR en la fecha de cada abono "
                "(art. 43 LIRPF). Consulta a tu gestor para la valoración definitiva.",
                styles["aviso_legal"]
            ))

    # 7. ADVERTENCIAS
    if motor.advertencias:
        for fl in _separador_bloque():
            story.append(fl)
        story.append(KeepTogether([
            Paragraph("Advertencias — Operaciones que Requieren Revisión Manual", styles["section"]),
            Paragraph(
                "Las siguientes situaciones requieren comprobación manual. "
                "<b>No son errores del sistema</b>: indican operaciones cuya valoración no puede "
                "determinarse automáticamente porque el CSV no contiene el historial completo "
                "(p.ej. activos adquiridos fuera del período del CSV, swaps con cripto sin compra previa registrada). "
                "El coste base de estos lotes ha quedado en cero y debe corregirse con los datos reales.",
                styles["body_muted"]
            ),
            Spacer(1, 3*mm),
        ]))
        warn_rows = [[Paragraph(f"⚠  {_td_safe(adv, 300)}", styles["warning"])] for adv in motor.advertencias]
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
         "de mercado del activo recibido y el coste FIFO del activo entregado. "
         "El activo recibido entra en el inventario con un coste base igual al valor EUR del activo entregado: "
         "si el entregado es una stablecoin o EUR, se toma su importe directamente (1:1); "
         "si es un criptoactivo, se usa el coste FIFO acumulado de los lotes consumidos. "
         "<b>Cuando el CSV no contiene el historial completo de compras de un activo entregado en un swap, "
         "el sistema no puede determinar su coste FIFO y el activo recibido entra al inventario con coste "
         "base cero. La operación queda marcada en la sección de advertencias para revisión manual.</b>"),
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

    # FAQ cards — cada concepto es un bloque independiente (ver _notas_faq)
    for fl in _notas_faq(notas, styles):
        story.append(fl)

    # DISCLAIMER FINAL — nota legal secundaria, discreta
    story.append(Spacer(1, 12 * mm))
    story.append(HRFlowable(width="100%", thickness=0.3, color=RULE_COLOR))
    story.append(Spacer(1, 5 * mm))
    _disc_final_style = ParagraphStyle(
        "disc_final", fontName="Helvetica-Oblique", fontSize=7,
        textColor=colors.HexColor("#9CA3AF"),  # mismo gris suave que el footer
        leading=11, alignment=TA_CENTER,
    )
    _disc_data = [[Paragraph(
        "Este documento ha sido generado automáticamente por la herramienta de Mariano Sevilla "
        "(marianosevilla.com) a partir del historial de operaciones exportado por el usuario. "
        "No constituye asesoramiento fiscal ni legal. Los resultados deben ser revisados y validados "
        "por un gestor o asesor fiscal autorizado antes de su presentación a la Agencia Tributaria. "
        "Mariano Sevilla no asume responsabilidad alguna por errores derivados de datos incorrectos "
        "o incompletos en el fichero CSV de origen.",
        _disc_final_style
    )]]
    _t_disc = Table(_disc_data, colWidths=[130 * mm])  # más estrecho que los 168mm habituales
    _t_disc.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    story.append(_t_disc)

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
        warn_rows = [[Paragraph(f"⚠  {_td_safe(adv, 300)}", styles["warning"])] for adv in clasificador.advertencias]
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
