"""
Backend Flask — Herramienta Fiscal Cripto
Mariano Sevilla — marianosevilla.com

Seguridad aplicada:
- Rate limiting (Flask-Limiter)
- CORS restringido a dominios propios
- Security headers (CSP, HSTS, X-Frame-Options, etc.)
- Validación estricta de ficheros CSV (extensión + contenido)
- Sanitización de inputs de texto
- Sin SQL → no aplica SQL injection, pero sí sanitizamos paths
"""

import os
import re
import sys
import tempfile
import traceback
from flask import Flask, request, jsonify, send_file, send_from_directory, after_this_request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(__file__))

from clasificador import ClasificadorBinance
from clasificador_bit2me import ClasificadorBit2Me
from motor_fifo import MotorFIFO
from generador_pdf import generar_pdf

app = Flask(__name__, static_folder="static")


# ── CORS ──────────────────────────────────────
# Solo se aceptan peticiones desde los dominios propios
ALLOWED_ORIGINS = [
    "https://marianosevilla.com",
    "https://www.marianosevilla.com",
    "https://fiscal.marianosevilla.com",
    "http://localhost:5050",   # desarrollo local
    "http://127.0.0.1:5050",  # desarrollo local
]

CORS(app, origins=ALLOWED_ORIGINS, methods=["GET", "POST"], allow_headers=["Content-Type"])


# ── RATE LIMITING ─────────────────────────────
# Límites por IP para evitar abuso
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://",
)


# ── SECURITY HEADERS ──────────────────────────
@app.after_request
def set_security_headers(response):
    # Evita que el navegador renderice el sitio dentro de un iframe (clickjacking)
    response.headers["X-Frame-Options"] = "DENY"

    # El navegador no debe intentar adivinar el tipo MIME
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Activa protección XSS en navegadores antiguos
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # Política de referrer — no filtra la URL a terceros
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Content Security Policy — solo recursos propios + Google Fonts
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' https://script.google.com; "
        "frame-ancestors 'none'; "
        "form-action 'self';"
    )

    # HSTS — fuerza HTTPS durante 1 año (solo activo en producción con HTTPS)
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains"
    )

    # Permissions Policy — desactiva APIs de hardware innecesarias
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )

    return response


# ── VALIDACIÓN Y SANITIZACIÓN ─────────────────

MAX_FILE_SIZE_MB = 10
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Primeras líneas que deben aparecer en un CSV de Binance o Bit2Me
BINANCE_SIGNATURES = ["Tiempo", "Operación", "Moneda", "Cambio", "Cuenta"]
BIT2ME_SIGNATURES  = ["Bit", "2Me", "Francisco", "Informe Fiscal", "Estimado"]

def _sanitizar_texto(texto: str, max_len: int = 100) -> str:
    """Elimina caracteres peligrosos y limita longitud."""
    if not texto:
        return ""
    # Eliminar etiquetas HTML y caracteres de control
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = re.sub(r"[^\w\s\-\.,@áéíóúÁÉÍÓÚñÑüÜ]", "", texto)
    return texto[:max_len].strip()

def _validar_csv(filepath: str, exchange: str) -> tuple[bool, str]:
    """
    Valida que el fichero sea un CSV real y corresponda al exchange indicado.
    Comprueba extensión, tamaño y contenido de las primeras líneas.
    """
    # Tamaño máximo
    size = os.path.getsize(filepath)
    if size > MAX_FILE_SIZE_BYTES:
        return False, f"El fichero es demasiado grande ({size // (1024*1024)} MB). Máximo {MAX_FILE_SIZE_MB} MB."

    if size == 0:
        return False, "El fichero está vacío."

    # Leer primeras líneas para validar contenido
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            primeras = "".join(f.readline() for _ in range(20))
    except Exception:
        return False, "No se pudo leer el fichero. Asegúrate de que es un CSV válido."

    # Detectar posibles inyecciones de fórmulas en CSV (CSV injection)
    lineas = primeras.splitlines()
    for linea in lineas[:5]:
        linea_limpia = linea.strip().strip('"')
        if linea_limpia and linea_limpia[0] in ("=", "+", "-", "@", "|", "%"):
            return False, "El fichero contiene contenido no permitido."

    # Validar que corresponde al exchange seleccionado
    if exchange == "binance":
        if not any(sig in primeras for sig in BINANCE_SIGNATURES):
            return False, (
                "El fichero no parece ser un CSV de Binance. "
                "Asegúrate de exportar el historial de transacciones desde tu cuenta de Binance."
            )
    elif exchange == "bit2me":
        if not any(sig in primeras for sig in BIT2ME_SIGNATURES):
            return False, (
                "El fichero no parece ser un CSV de Bit2Me. "
                "Asegúrate de exportar el informe fiscal desde tu cuenta de Bit2Me."
            )

    return True, ""


# ── PIPELINES ─────────────────────────────────

def procesar_binance(filepath: str) -> MotorFIFO:
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
@limiter.limit("10 per minute")   # máx 10 análisis por minuto por IP
def analizar():
    if "csv" not in request.files:
        return jsonify({"error": "No se recibió ningún fichero."}), 400

    archivo  = request.files["csv"]
    nombre   = _sanitizar_texto(request.form.get("nombre", ""))
    ejercicio = _sanitizar_texto(request.form.get("ejercicio", ""), max_len=10)
    exchange = _sanitizar_texto(request.form.get("exchange", "binance"), max_len=20).lower()

    # Validar exchange permitido
    if exchange not in ("binance", "bit2me"):
        return jsonify({"error": "Exchange no soportado."}), 400

    # Validar extensión del fichero
    filename = archivo.filename or ""
    if not filename.lower().endswith(".csv"):
        return jsonify({"error": "El fichero debe tener extensión .csv"}), 400

    # Guardar temporalmente
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        archivo.save(tmp.name)
        tmp_path = tmp.name

    try:
        # Validar contenido del CSV
        valido, error_msg = _validar_csv(tmp_path, exchange)
        if not valido:
            return jsonify({"error": error_msg}), 400

        # Procesar según exchange
        if exchange == "bit2me":
            clasificador, resumen, operaciones = procesar_bit2me(tmp_path)
            advertencias = clasificador.advertencias
            posicion = []
            pdf_bytes = generar_pdf_bit2me(clasificador, nombre, ejercicio)
        else:
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
    from generador_pdf import (
        _build_styles, _header_footer, _portada,
        SimpleDocTemplate, A4, mm, PageBreak, Spacer,
        Paragraph, Table, TableStyle, HRFlowable,
        colors, SURFACE, SURFACE2, BLACK, BORDER, GREEN, MUTED
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
    _portada(story, styles, resumen, nombre_usuario, ejercicio, "Bit2Me")

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

    if clasificador.advertencias:
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph("Advertencias", styles["section"]))
        for adv in clasificador.advertencias:
            story.append(Paragraph(f"! {adv}", styles["warning"]))
            story.append(Spacer(1, 2*mm))

    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        "Los resultados de este informe provienen de los datos calculados por Bit2Me "
        "en su informe fiscal oficial. Consulta siempre con un gestor o asesor fiscal autorizado.",
        styles["disclaimer"]
    ))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buf.getvalue()


@app.route("/api/descargar/<token>")
@limiter.limit("20 per minute")
def descargar(token):
    # Validar token: solo nombre de fichero sin rutas ni caracteres especiales
    if not re.match(r"^[a-zA-Z0-9_\-]+\.pdf$", token):
        return jsonify({"error": "Token invalido."}), 400
    pdf_path = os.path.join(tempfile.gettempdir(), token)
    # Verificar que el path resultante está dentro del directorio temporal (path traversal)
    if not os.path.realpath(pdf_path).startswith(os.path.realpath(tempfile.gettempdir())):
        return jsonify({"error": "Token invalido."}), 400
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Informe no encontrado o expirado."}), 404
    return send_file(
        pdf_path, mimetype="application/pdf",
        as_attachment=True, download_name="informe_fiscal_cripto.pdf"
    )


@app.errorhandler(429)
def ratelimit_error(e):
    return jsonify({
        "error": "Demasiadas solicitudes. Por favor espera un momento antes de intentarlo de nuevo."
    }), 429


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(debug=False, port=5050)

