"""Informe documental Binance en PDF. Nunca emite cifras ni informes FIFO fiscales.

La fuente son los contadores y las incidencias ya validadas por el clasificador
Binance. No admite operaciones individuales, cotizaciones o costes reconstruidos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
)


_ESTADO = "INCOMPLETO_NO_APTO_PARA_DECLARAR"
_GRUPOS = (
    ("operaciones", "Operaciones y movimientos"),
    ("earn", "Earn y recompensas"),
    ("comisiones", "Ingresos y reembolsos de comisiones"),
)
_FUENTES = {
    "transaction_history": "Historial de transacciones",
    "spot_trades": "Operaciones Spot",
    "spot_orders": "Órdenes Spot (auditoría)",
    "convert_orders": "Convert",
    "fiat_trade": "Compras y ventas fiat",
    "crypto_deposit": "Depósitos cripto",
    "crypto_withdrawal": "Retiros cripto",
}


def _texto(value, limit: int = 1600) -> str:
    return escape(str(value or "")[:limit])


def _validar_borrador(borrador: dict) -> None:
    if (not isinstance(borrador, dict)
            or borrador.get("estado") != _ESTADO
            or borrador.get("no_es_informe_fiscal") is not True
            or borrador.get("costes_fifo_calculados") is not False
            or borrador.get("pdf_fiscal_disponible") is not False
            or borrador.get("ganancias_y_perdidas_eur") is not None
            or not isinstance(borrador.get("pendientes"), list)
            or not isinstance(borrador.get("fuentes"), list)
            or not isinstance(borrador.get("evidencias", []), list)
            or not isinstance(borrador.get("archivos_aportados", []), list)):
        raise ValueError("Borrador Binance no apto para informe diagnóstico")


def _watermark(canvas, doc):
    """Aviso inequívoco en TODAS las páginas, también al imprimir o separar."""
    canvas.saveState()
    w, h = A4
    canvas.setTitle("Diagnóstico documental Binance - INCOMPLETO - NO FISCAL")
    canvas.setAuthor("marianosevilla.com")
    canvas.setFillColor(colors.HexColor("#E4E8E9"))
    canvas.translate(w / 2, h / 2)
    canvas.rotate(36)
    canvas.setFont("Helvetica-Bold", 34)
    canvas.drawCentredString(0, 0, "DATOS INCOMPLETOS")
    canvas.setFont("Helvetica-Bold", 23)
    canvas.drawCentredString(0, -34, "NO VÁLIDO PARA DECLARAR")
    canvas.restoreState()
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#DFE4E9"))
    canvas.line(18 * mm, 19 * mm, w - 18 * mm, 19 * mm)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.HexColor("#9C3632"))
    canvas.drawString(18 * mm, 13.5 * mm, "DIAGNÓSTICO DOCUMENTAL - NO ES INFORME FIFO FISCAL")
    canvas.setFillColor(colors.HexColor("#576570"))
    canvas.drawRightString(w - 18 * mm, 13.5 * mm, f"Página {doc.page}")
    canvas.restoreState()


def generar_pdf_diagnostico_binance(borrador: dict) -> bytes:
    """Produce únicamente diagnóstico de cobertura, no resultados patrimoniales."""
    _validar_borrador(borrador)
    exchange = str(borrador.get("exchange_nombre") or "Binance")[:40]
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "BinanceDiagTitle", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=20, leading=26, spaceAfter=11, textColor=colors.HexColor("#172932"),
    )
    h2 = ParagraphStyle(
        "BinanceDiagSection", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=12, leading=16, spaceBefore=14, spaceAfter=7,
        textColor=colors.HexColor("#172932"), keepWithNext=True,
    )
    body = ParagraphStyle(
        "BinanceDiagBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.5, leading=15, spaceAfter=7,
        textColor=colors.HexColor("#334651"), splitLongWords=True,
    )
    small = ParagraphStyle(
        "BinanceDiagSmall", parent=body, fontSize=8.5, leading=13,
        textColor=colors.HexColor("#52636D"),
    )
    issue_title = ParagraphStyle(
        "BinanceDiagIssue", parent=body, fontName="Helvetica-Bold",
        fontSize=9.7, leading=14, spaceBefore=7, spaceAfter=2, keepWithNext=True,
    )
    warning = ParagraphStyle(
        "BinanceDiagWarning", parent=body, fontName="Helvetica-Bold",
        fontSize=10.2, leading=16, alignment=TA_CENTER, spaceAfter=0,
        textColor=colors.HexColor("#963A22"),
    )
    tiny = ParagraphStyle(
        "BinanceDiagSmallCenter", parent=small, alignment=TA_CENTER,
    )

    bio = BytesIO()
    pdf = SimpleDocTemplate(
        bio, pagesize=A4, leftMargin=19 * mm, rightMargin=19 * mm,
        topMargin=20 * mm, bottomMargin=27 * mm,
        title=f"Diagnóstico {exchange} - Incompleto, no fiscal",
        author="marianosevilla.com",
        pageCompression=1,
    )
    story = [
        Paragraph(f"MARIANOSEVILLA.COM / {_texto(exchange.upper(), 40)}", small),
        Spacer(1, 4 * mm),
        Paragraph("Informe de diagnóstico FIFO", h1),
        Paragraph(
            "Hemos leído los archivos aportados y reconocido sus formatos. "
            "No disponemos de información suficiente para emitir un informe "
            "fiscal FIFO definitivo.", body,
        ),
    ]
    notice = Table(
        [[Paragraph("DATOS INCOMPLETOS<br/>NO VÁLIDO PARA DECLARAR", warning)]],
        colWidths=[171 * mm],
    )
    notice.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FCF5EF")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#E6B9A6")),
        ("TOPPADDING", (0, 0), (-1, -1), 13),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
    ]))
    story += [
        Spacer(1, 3 * mm),
        notice,
        Spacer(1, 5 * mm),
        Paragraph(
            "<b>Documento de diagnóstico, no declaración tributaria.</b> "
            "No contiene costes FIFO, ganancias ni pérdidas en euros. "
            "No se muestran cálculos parciales porque la suficiencia e "
            "independencia de los lotes o valoraciones incompletos no están "
            "acreditadas. No utilices este documento para presentar la "
            "declaración ante la AEAT.",
            body,
        ),
        Paragraph(
            f"<b>Ejercicio solicitado:</b> {_texto(borrador.get('ejercicio_solicitado') or 'todos', 40)}"
            f"<br/><b>Años detectados en los archivos:</b> {_texto(', '.join(map(str, borrador.get('periodos_detectados') or [])) or 'no disponibles', 120)}"
            f"<br/><b>Alcance declarado:</b> {_texto(borrador.get('alcance_descripcion') or {'solo_binance': 'el usuario declara que solo utilizó Binance', 'otras_fuentes': 'el usuario declara actividad en otros exchanges o wallets', 'no_se': 'el usuario no pudo confirmar si hubo otros exchanges o wallets'}.get(borrador.get('alcance_declarado'), 'no confirmado'), 180)}"
            f"<br/><b>Fecha del diagnóstico:</b> {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')}",
            body,
        ),
        Paragraph(
            "La declaración de alcance del usuario no reemplaza los controles "
            "del motor ni demuestra que los archivos cubran toda la actividad.", small,
        ),
        Paragraph("Archivos y formatos aportados", h2),
    ]
    uploaded = [x for x in (borrador.get("archivos_aportados") or [])[:40] if isinstance(x, dict)]
    if uploaded:
        for item in uploaded:
            name = _texto(item.get("nombre") or "archivo sin nombre", 120)
            extension = _texto(item.get("formato") or "formato no disponible", 16)
            size = item.get("bytes")
            size_text = f"{size:,} bytes" if type(size) is int and size >= 0 else "tamaño no disponible"
            story.append(Paragraph(
                f"<b>{name}</b> · formato indicado por la extensión: {extension} · {size_text}", small
            ))
    else:
        story.append(Paragraph("No se conservó un inventario individual de archivos.", body))
    story += [
        Paragraph("Fuentes reconocidas", h2),
    ]
    fuentes = (borrador.get("fuentes") or [])[:40]
    if fuentes:
        for fuente in fuentes:
            if not isinstance(fuente, dict):
                continue
            tipo = str(fuente.get("tipo") or "")[:64]
            registros = fuente.get("registros")
            count = str(registros) if type(registros) is int and registros >= 0 else "no disponible"
            story.append(Paragraph(
                f"<b>{_texto(_FUENTES.get(tipo, tipo), 64)}:</b> {_texto(count, 32)} registros", body
            ))
    else:
        story.append(Paragraph("No se dispone de una relación de fuentes acreditadas.", body))

    counts = borrador.get("operaciones_detectadas") or {}
    if isinstance(counts, dict):
        available = [
            ("Compraventas candidatas", "compraventas_candidatas"),
            ("Permutas candidatas", "permutas_candidatas"),
            ("Movimientos candidatos", "movimientos_candidatos"),
            ("Rendimientos candidatos", "rendimientos_candidatos"),
            ("Operaciones sin reconocer", "operaciones_no_reconocidas"),
            ("Apuntes de comisiones revisados", "comisiones_referidos_analizadas"),
        ]
        summary = []
        for label, key in available:
            value = counts.get(key)
            if type(value) is int and value >= 0:
                summary.append(f"{label}: {value}")
        if summary:
            story += [
                Paragraph("Registros clasificados (no son operaciones fiscales)", h2),
                Paragraph(_texto(" · ".join(summary), 1000), small),
                Paragraph(
                    "Son eventos candidatos clasificados. No representan operaciones "
                    "únicas, adquisiciones/transmisiones conciliadas ni un FIFO completo.", small,
                ),
            ]

    evidence = [x for x in (borrador.get("evidencias") or [])[:30] if isinstance(x, dict)]
    if evidence:
        story.append(Paragraph("Hechos documentales identificados", h2))
        for item in evidence:
            story += [
                Paragraph(_texto(item.get("titulo") or "Evidencia documental", 200), issue_title),
                Paragraph(_texto(item.get("descripcion"), 1600), body),
                Paragraph(f"<b>Cómo completar:</b> {_texto(item.get('siguiente_paso'), 1600)}", small),
            ]

    pending = [x for x in (borrador.get("pendientes") or [])[:50] if isinstance(x, dict)]
    story.append(Paragraph("Información que falta para completar el FIFO", h2))
    story.append(Paragraph(
        "Las incidencias siguientes no significan que el CSV sea inválido. "
        "Indican qué operaciones requieren documentos, conciliaciones o "
        "valoraciones adicionales.", body,
    ))
    for group_code, group_label in _GRUPOS:
        group = [x for x in pending if x.get("grupo", "operaciones") == group_code]
        if not group:
            continue
        story.append(Paragraph(f"{_texto(group_label)} ({len(group)})", h2))
        for index, issue in enumerate(group, 1):
            title = _texto(issue.get("titulo") or "Información pendiente", 200)
            description = _texto(issue.get("descripcion"), 1600)
            next_step = _texto(issue.get("siguiente_paso"), 1600)
            story += [
                Paragraph(f"{index}. {title}", issue_title),
                Paragraph(description, body),
                Paragraph(
                    f"<b>Acción:</b> {_texto({'CORREGIR_ARCHIVO': 'corregir o volver a exportar el archivo', 'APORTAR_DOCUMENTACION': 'aportar documentación original', 'CONTACTAR_SOPORTE': 'contactar con soporte', 'REINTENTAR': 'volver a intentarlo', 'MANTENER_PROVISIONAL': 'mantener el resultado como provisional'}.get(issue.get('accion'), 'mantener el resultado como provisional'), 100)}"
                    f"<br/><b>Qué aportar:</b> {next_step}", small,
                ),
            ]
    story += [
        Spacer(1, 6 * mm),
        Paragraph("Próximos pasos", h2),
        Paragraph(
            f"Si dispones de más exportaciones originales de {exchange} o de otras fuentes, añádelas y repite el análisis. "
            "Conserva los archivos originales y este diagnóstico. "
            "Si declaraste actividad en otros exchanges o wallets, aporta también "
            "sus historiales antes de solicitar un informe definitivo. Si no puedes "
            "recuperar los documentos pendientes, consulta con un profesional.", body,
        ),
        Paragraph(
            "<b>Limitación:</b> contar registros no demuestra cobertura histórica "
            "completa, valoración EUR acreditada ni cálculo FIFO correcto. "
            "No se han supuesto costes de adquisición cero.", small,
        ),
    ]
    pdf.build(story, onFirstPage=_watermark, onLaterPages=_watermark)
    result = bio.getvalue()
    if not result.startswith(b"%PDF-"):
        raise ValueError("No se generó un PDF válido")
    return result
