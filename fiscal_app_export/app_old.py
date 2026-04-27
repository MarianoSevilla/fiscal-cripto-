"""
Backend Flask — Herramienta Fiscal Cripto
Mariano Sevilla — marianosevilla.com
"""

import os
import sys
import tempfile
import traceback
from flask import Flask, request, jsonify, send_file, send_from_directory

sys.path.insert(0, os.path.dirname(__file__))

from clasificador import ClasificadorBinance
from clasificador_bit2me import ClasificadorBit2Me
from motor_fifo import MotorFIFO
from generador_pdf import generar_pdf

app = Flask(__name__, static_folder="static")


# ── PIPELINES ─────────────────────────────────

def procesar_binance(filepath: str) -> MotorFIFO:
    """CSV Binance → clasificador → motor FIFO."""
    c = ClasificadorBinance(filepath).clasificar()
    motor = MotorFIFO()

    ops = []
    for op in c.compraventas:
        ops.append(("cv", op.fecha, op))
    for op in c.swaps:
        ops.append(("swap", op.fecha, op))
    ops.sort(key=lambda x: x[1])

    for tipo, fecha, op in ops:
        if tipo == "cv":
            if op.tipo == "COMPRA":
                motor.registrar_compra(
                    fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                    importe=op.importe, contraparte=op.contraparte,
                    fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad
                )
            else:
                motor.registrar_venta(
                    fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                    importe=op.importe, contraparte=op.contraparte,
                    fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad
                )
        elif tipo == "swap":
            motor.registrar_swap(
                fecha=op.fecha,
                activo_entregado=op.activo_entregado,
                cantidad_entregada=op.cantidad_entregada,
                activo_recibido=op.activo_recibido,
                cantidad_recibida=op.cantidad_recibida,
                nota=op.nota
            )
    return motor


def procesar_bit2me(filepath: str) -> tuple:
    """
    CSV Bit2Me → clasificador.
    Devuelve (resumen, operaciones, advertencias) directamente
    porque Bit2Me ya tiene el FIFO calculado.
    """
    c = ClasificadorBit2Me(filepath).clasificar()
    r = c.resumen_fiscal()

    operaciones = [
        {
            "fecha": res.fecha_venta[:10],
            "tipo": res.tipo_op,
            "activo": res.activo,
            "cantidad": round(res.cantidad, 6),
            "transmision": round(res.precio_transmision, 4),
            "coste_fifo": round(res.precio_coste, 4),
            "ganancia_perdida": round(res.ganancia_perdida, 4),
            "periodo_dias": 0,
        }
        for res in c.resultados
    ]

    return c, r, operaciones


# ── RUTAS ─────────────────────────────────────

@app.route("/")
def landing():
    return send_from_directory("static", "landing.html")


@app.route("/fiscal")
def fiscal():
    return send_from_directory("static", "index.html")


@app.route("/api/analizar", methods=["POST"])
def analizar():
    if "csv" not in request.files:
        return jsonify({"error": "No se recibió ningún fichero CSV."}), 400

    archivo  = request.files["csv"]
    nombre   = request.form.get("nombre", "")
    ejercicio = request.form.get("ejercicio", "")
    exchange = request.form.get("exchange", "binance").lower()

    if not archivo.filename.endswith(".csv"):
        return jsonify({"error": "El fichero debe ser un .csv exportado de tu exchange."}), 400

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        archivo.save(tmp.name)
        tmp_path = tmp.name

    try:
        if exchange == "bit2me":
            clasificador, resumen, operaciones = procesar_bit2me(tmp_path)
            advertencias = clasificador.advertencias
            posicion = []  # Bit2Me no exporta posición actual
            pdf_bytes = generar_pdf_bit2me(clasificador, nombre, ejercicio)

        else:  # binance por defecto
            motor = procesar_binance(tmp_path)
            resumen = motor.resumen_fiscal()
            posicion = [
                {
                    "activo": p.activo,
                    "cantidad": round(p.cantidad_total, 6),
                    "precio_medio": round(p.precio_medio, 4),
                    "coste_total": round(p.coste_total, 4),
                }
                for p in motor.posicion_actual()
            ]
            operaciones = [
                {
                    "fecha": r.fecha.strftime("%Y-%m-%d"),
                    "tipo": r.tipo_operacion,
                    "activo": r.activo,
                    "cantidad": round(r.cantidad_vendida, 6),
                    "transmision": round(r.precio_transmision, 4),
                    "coste_fifo": round(r.precio_coste, 4),
                    "ganancia_perdida": round(r.ganancia_perdida, 4),
                    "periodo_dias": int(r.periodo_dias),
                }
                for r in motor.resultados
            ]
            advertencias = motor.advertencias
            pdf_bytes = generar_pdf(motor, nombre, ejercicio, exchange.capitalize())

        pdf_tmp = tmp_path.replace(".csv", ".pdf")
        with open(pdf_tmp, "wb") as f:
            f.write(pdf_bytes)

        return jsonify({
            "ok": True,
            "resumen": resumen,
            "operaciones": operaciones,
            "posicion": posicion,
            "advertencias": advertencias,
            "token": os.path.basename(pdf_tmp),
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Error al procesar el CSV: {str(e)}"}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def generar_pdf_bit2me(clasificador, nombre_usuario, ejercicio):
    """Genera PDF para Bit2Me usando los resultados del clasificador."""
    from generador_pdf import (
        _build_styles, _header_footer, _portada,
        SimpleDocTemplate, A4, mm, PageBreak, Spacer,
        Paragraph, Table, TableStyle, HRFlowable, KeepTogether,
        colors, SURFACE, SURFACE2, BLACK, BORDER, GREEN, RED_C, MUTED, WHITE
    )
    import io

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

    # Portada con resumen
    _portada(story, styles, resumen, nombre_usuario, ejercicio, "Bit2Me")

    # Tabla de operaciones
    if clasificador.resultados:
        story.append(PageBreak())
        story.append(Paragraph("Extracto de Operaciones con Resultado Fiscal", styles["section"]))
        story.append(Paragraph(
            f"{len(clasificador.resultados)} operaciones · "
            f"Ganancias: +{resumen['ganancias_brutas']:,.2f} EUR · "
            f"Perdidas: {resumen['perdidas_brutas']:,.2f} EUR · "
            f"Resultado neto: {resumen['resultado_neto']:+,.2f} EUR",
            styles["body_muted"]
        ))
        story.append(Spacer(1, 3*mm))

        cabecera = [Paragraph(h, styles["th"]) for h in
                    ["FECHA", "TIPO", "ACTIVO", "CANTIDAD", "PRECIO TRANSMISION", "COSTE ADQUISICION", "G / P (EUR)"]]
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
        "Los resultados de este informe provienen de los datos ya calculados por Bit2Me "
        "en su informe fiscal oficial. Mariano Sevilla no recalcula el FIFO para Bit2Me "
        "sino que procesa y presenta los datos del informe exportado por el exchange. "
        "Consulta siempre con un gestor o asesor fiscal autorizado.",
        styles["disclaimer"]
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()


@app.route("/api/descargar/<token>")
def descargar(token):
    if "/" in token or "\\" in token or not token.endswith(".pdf"):
        return jsonify({"error": "Token invalido."}), 400
    pdf_path = os.path.join(tempfile.gettempdir(), token)
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Informe no encontrado o expirado."}), 404
    return send_file(
        pdf_path, mimetype="application/pdf",
        as_attachment=True, download_name="informe_fiscal_cripto.pdf"
    )


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(debug=True, port=5050)

