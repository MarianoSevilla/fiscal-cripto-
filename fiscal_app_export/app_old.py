"""
Backend Flask — Herramienta Fiscal Cripto
Mariano Sevilla — marianosevilla.com
"""

import os
import sys
import tempfile
import traceback
from flask import Flask, request, jsonify, send_file, send_from_directory
import io

sys.path.insert(0, os.path.dirname(__file__))

from clasificador import ClasificadorBinance
from motor_fifo import MotorFIFO
from generador_pdf import generar_pdf

app = Flask(__name__, static_folder="static")


def procesar_csv(filepath: str) -> MotorFIFO:
    """Pipeline: CSV → clasificador → motor FIFO."""
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


@app.route("/")
def landing():
    return send_from_directory("static", "landing.html")


@app.route("/fiscal")
def fiscal():
    return send_from_directory("static", "index.html")


@app.route("/api/analizar", methods=["POST"])
def analizar():
    """
    Recibe CSV de Binance, devuelve JSON con el resumen fiscal.
    """
    if "csv" not in request.files:
        return jsonify({"error": "No se recibió ningún fichero CSV."}), 400

    archivo = request.files["csv"]
    nombre = request.form.get("nombre", "")
    ejercicio = request.form.get("ejercicio", "")

    if not archivo.filename.endswith(".csv"):
        return jsonify({"error": "El fichero debe ser un .csv exportado de Binance."}), 400

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        archivo.save(tmp.name)
        tmp_path = tmp.name

    try:
        motor = procesar_csv(tmp_path)
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

        # Guardar el motor en sesión simple (en memoria, por PID de proceso)
        # Para producción: usar Redis o DB. Aquí usamos archivo temporal firmado.
        pdf_bytes = generar_pdf(motor, nombre, ejercicio)
        pdf_tmp = tmp_path.replace(".csv", ".pdf")
        with open(pdf_tmp, "wb") as f:
            f.write(pdf_bytes)

        token = os.path.basename(pdf_tmp)

        return jsonify({
            "ok": True,
            "resumen": resumen,
            "operaciones": operaciones,
            "posicion": posicion,
            "advertencias": motor.advertencias,
            "token": token,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Error al procesar el CSV: {str(e)}"}), 500
    finally:
        # No borramos el PDF aún — se descarga en /api/descargar
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@app.route("/api/descargar/<token>")
def descargar(token):
    """Descarga el PDF generado."""
    # Seguridad mínima: solo nombres de archivo válidos (sin rutas)
    if "/" in token or "\\" in token or not token.endswith(".pdf"):
        return jsonify({"error": "Token inválido."}), 400

    pdf_path = os.path.join(tempfile.gettempdir(), token)
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Informe no encontrado o expirado."}), 404

    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="informe_fiscal_cripto.pdf"
    )


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(debug=True, port=5050)
