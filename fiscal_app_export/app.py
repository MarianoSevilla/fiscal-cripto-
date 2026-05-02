"""
Backend Flask — Herramienta Fiscal Cripto
Mariano Sevilla — marianosevilla.com

Seguridad aplicada:
- Rate limiting: 1 análisis por 10 minutos por IP
- CORS restringido a dominios propios
- Security headers (CSP, HSTS, X-Frame-Options, etc.)
- Validación estricta de CSV (extensión + tamaño + contenido + exchange)
- Validación de ejercicio fiscal (2009 – año actual + 1)
- Sanitización de inputs de texto
- PDF borrado automáticamente tras descarga
- Protección path traversal en tokens
- Autenticación: Flask-Login + SQLAlchemy + bcrypt
"""

import os
import re
import sys
import tempfile
import traceback
import threading
from datetime import datetime
from flask import Flask, request, jsonify, send_file, send_from_directory, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from models import db, bcrypt, User

sys.path.insert(0, os.path.dirname(__file__))

from clasificador import ClasificadorBinance
from clasificador_bit2me import ClasificadorBit2Me
from clasificador_bitvavo import ClasificadorBitvavo
from motor_fifo import MotorFIFO
from generador_pdf import generar_pdf, generar_pdf_bit2me

app = Flask(__name__, static_folder="static")

# Proxy fix: necesario para que url_for() genere https:// en producción detrás de nginx
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)


# ── CONFIGURACIÓN ─────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# SECRET_KEY obligatoria. En desarrollo se usa un valor por defecto con aviso.
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    if os.environ.get("FLASK_ENV") == "production":
        raise RuntimeError("SECRET_KEY no está configurada. Define la variable de entorno antes de arrancar.")
    import warnings
    warnings.warn("SECRET_KEY no definida — usando clave de desarrollo. NO uses esto en producción.", stacklevel=1)
    _secret = "dev-only-insecure-key-change-me"

app.config["SECRET_KEY"] = _secret
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(_BASE_DIR, 'fiscal_users.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Cookies de sesión seguras
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"]   = os.environ.get("FLASK_ENV") == "production"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# ── EXTENSIONES ───────────────────────────────
db.init_app(app)
bcrypt.init_app(app)

login_manager = LoginManager(app)

@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    """JSON 401 para rutas API; redirect a /login/ para rutas de navegador."""
    if request.path.startswith("/api/"):
        return jsonify({"error": "Autenticación requerida"}), 401
    return redirect("/login/")


# ── GOOGLE OAUTH ──────────────────────────────
_GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID")
_GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
_google_oauth_enabled = bool(_GOOGLE_CLIENT_ID and _GOOGLE_CLIENT_SECRET)

oauth = OAuth(app)
if _google_oauth_enabled:
    google_oauth = oauth.register(
        name="google",
        client_id=_GOOGLE_CLIENT_ID,
        client_secret=_GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

with app.app_context():
    db.create_all()


# ── CORS ──────────────────────────────────────
ALLOWED_ORIGINS = [
    "https://marianosevilla.com",
    "https://www.marianosevilla.com",
    "https://fiscal.marianosevilla.com",
    "http://localhost:5050",
    "http://127.0.0.1:5050",
]
CORS(
    app,
    origins=ALLOWED_ORIGINS,
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    supports_credentials=True,   # necesario para que las cookies de sesión funcionen entre origen y API
)


# ── RATE LIMITING ─────────────────────────────
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per day", "20 per hour"],
    storage_uri="memory://",
)


# ── SECURITY HEADERS ──────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
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
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    return response


# ── VALIDACIÓN AUTH ───────────────────────────

def _validar_email(email: str) -> tuple[bool, str]:
    """Valida formato de email. Permite + y - en la parte local."""
    if not email or len(email) > 254:
        return False, "Email inválido."
    if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email):
        return False, "Email inválido."
    return True, ""


def _validar_password(password: str) -> tuple[bool, str]:
    if not password or len(password) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres."
    if len(password) > 128:
        return False, "La contraseña es demasiado larga."
    return True, ""


# ── VALIDACIÓN Y SANITIZACIÓN ─────────────────

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
AÑO_MIN = 2009
AÑO_MAX = datetime.now().year + 1

BINANCE_SIGNATURES = ["Tiempo", "Operación", "Moneda", "Cambio", "Cuenta"]
BIT2ME_SIGNATURES  = ["Bit", "2Me", "Informe Fiscal", "Estimado"]
BITVAVO_SIGNATURES = ["Timezone", "Date", "Time", "Type", "Currency", "Amount"]


def _sanitizar_texto(texto: str, max_len: int = 100) -> str:
    if not texto:
        return ""
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = re.sub(r"[^\w\s\-\.,@áéíóúÁÉÍÓÚñÑüÜ]", "", texto)
    return texto[:max_len].strip()


def _validar_ejercicio(ejercicio: str) -> tuple[bool, str]:
    """Valida que el ejercicio sea un año entre 2009 y año_actual+1."""
    if not ejercicio:
        return True, ""  # Campo opcional — si está vacío, OK
    if not re.match(r"^\d{4}$", ejercicio):
        return False, "El ejercicio fiscal debe ser un año de 4 dígitos (ej: 2024)."
    año = int(ejercicio)
    if año < AÑO_MIN:
        return False, f"El ejercicio fiscal no puede ser anterior a {AÑO_MIN}."
    if año > AÑO_MAX:
        return False, f"El ejercicio fiscal no puede ser posterior a {AÑO_MAX}."
    return True, ""


def _validar_csv(filepath: str, exchange: str) -> tuple[bool, str]:
    size = os.path.getsize(filepath)
    if size > MAX_FILE_SIZE_BYTES:
        return False, f"El fichero es demasiado grande. Máximo 10 MB."
    if size == 0:
        return False, "El fichero está vacío."

    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            primeras = "".join(f.readline() for _ in range(20))
    except Exception:
        return False, "No se pudo leer el fichero. Asegúrate de que es un CSV válido."

    # CSV injection
    for linea in primeras.splitlines()[:5]:
        limpia = linea.strip().strip('"')
        if limpia and limpia[0] in ("=", "+", "-", "@", "|", "%"):
            return False, "El fichero contiene contenido no permitido."

    # Validar exchange
    sigs = {
        "binance": BINANCE_SIGNATURES,
        "bit2me":  BIT2ME_SIGNATURES,
        "bitvavo": BITVAVO_SIGNATURES,
    }
    nombres = {
        "binance": "Binance",
        "bit2me":  "Bit2Me",
        "bitvavo": "Bitvavo",
    }
    if exchange in sigs:
        if not any(sig in primeras for sig in sigs[exchange]):
            return False, (
                f"El fichero no parece ser un CSV de {nombres[exchange]}. "
                f"Asegúrate de exportar el historial desde tu cuenta de {nombres[exchange]}."
            )

    # Binance: detectar el formato "Historial de Transacciones" (incorrecto para FIFO)
    if exchange == "binance":
        try:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                muestra = "".join(f.readline() for _ in range(100))
            if "Buy Crypto With Fiat" in muestra:
                return False, (
                    "El CSV de Binance no es el correcto para calcular el FIFO. "
                    "Has exportado el 'Historial de Transacciones', que no incluye el importe en euros de cada compra. "
                    "Necesitas el 'Historial de Operaciones Spot': "
                    "en Binance ve a Órdenes → Historial de operaciones → selecciona el rango de fechas → Exportar."
                )
        except Exception:
            pass

    return True, ""


# ── PIPELINES ─────────────────────────────────

def _pipeline_motor(clasificador) -> MotorFIFO:
    """Pipeline común: clasificador → motor FIFO."""
    motor = MotorFIFO()
    ops = []
    for op in clasificador.compraventas:
        ops.append(("cv", op.fecha, op))
    for op in clasificador.swaps:
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


def procesar_con_fifo(clasificador) -> tuple:
    """Pipeline genérico: clasificador ya instanciado → motor FIFO + rendimientos."""
    motor = _pipeline_motor(clasificador)
    rendimientos = clasificador.rendimientos if hasattr(clasificador, 'rendimientos') else []
    return motor, rendimientos


def procesar_binance(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorBinance(filepath).clasificar())


def procesar_bitvavo(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorBitvavo(filepath).clasificar())


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


def _detectar_periodo(motor=None, clasificador=None) -> dict:
    """Detecta las fechas mínima y máxima del CSV procesado."""
    fechas = []
    try:
        if motor and motor.resultados:
            fechas += [r.fecha for r in motor.resultados]
        if motor and hasattr(motor, '_lotes'):
            for lotes in motor._lotes.values():
                for lote in lotes:
                    if hasattr(lote, 'fecha'):
                        fechas.append(lote.fecha)
        if clasificador and hasattr(clasificador, 'resultados'):
            for r in clasificador.resultados:
                try:
                    from datetime import datetime
                    fechas.append(datetime.strptime(r.fecha_venta[:10], "%Y-%m-%d"))
                except Exception:
                    pass
    except Exception:
        pass

    if not fechas:
        return {}

    fecha_min = min(fechas)
    fecha_max = max(fechas)
    return {
        "fecha_min": fecha_min.strftime("%d/%m/%Y") if hasattr(fecha_min, 'strftime') else str(fecha_min)[:10],
        "fecha_max": fecha_max.strftime("%d/%m/%Y") if hasattr(fecha_max, 'strftime') else str(fecha_max)[:10],
    }


def _error_amigable(e: Exception) -> str:
    """Convierte excepciones técnicas en mensajes amigables para el usuario."""
    msg = str(e)
    if "NoneType" in msg or "AttributeError" in msg:
        return "El fichero CSV no tiene el formato esperado. Asegúrate de exportarlo directamente desde tu exchange."
    if "UnicodeDecodeError" in msg or "codec" in msg:
        return "El fichero no se puede leer. Asegúrate de que es un CSV válido exportado desde tu exchange."
    if "KeyError" in msg or "column" in msg.lower():
        return "El fichero CSV no tiene las columnas esperadas. Exporta el historial completo desde tu exchange."
    if "MemoryError" in msg:
        return "El fichero es demasiado grande para procesarse. Intenta con un rango de fechas más reducido."
    return "No se ha podido procesar el fichero. Comprueba que es un CSV válido exportado desde tu exchange."


def _motor_a_json(motor) -> tuple:
    """Convierte el resultado del motor FIFO a formato JSON para la UI."""
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
    return resumen, posicion, operaciones


def _rendimientos_a_json(rendimientos: list) -> list:
    """Convierte lista de rendimientos a formato JSON para la UI."""
    from collections import defaultdict
    por_tipo = defaultdict(lambda: {"cantidad": 0.0, "operaciones": 0, "valor_eur": 0.0})
    for r in rendimientos:
        key = r.subtipo
        por_tipo[key]["cantidad"] += r.cantidad
        por_tipo[key]["operaciones"] += 1
        por_tipo[key]["valor_eur"] += getattr(r, 'valor_eur', 0.0)
        if "activo" not in por_tipo[key]:
            por_tipo[key]["activo"] = r.activo
    return [
        {
            "subtipo": k,
            "activo": v["activo"],
            "cantidad": round(v["cantidad"], 6),
            "operaciones": v["operaciones"],
            "valor_eur": round(v["valor_eur"], 4),
        }
        for k, v in por_tipo.items()
    ]


# ── RUTAS ─────────────────────────────────────

@app.route("/")
def landing():
    return send_from_directory("static", "landing.html")


@app.route("/fiscal")
def fiscal():
    return send_from_directory("static", "index.html")


@app.route("/login/", strict_slashes=False)
def login_page():
    """Página dedicada de inicio de sesión."""
    if current_user.is_authenticated:
        return redirect("/fiscal")
    return send_from_directory("static", "login.html")


@app.route("/signup/", strict_slashes=False)
def signup_page():
    """Página dedicada de registro."""
    if current_user.is_authenticated:
        return redirect("/fiscal")
    return send_from_directory("static", "signup.html")


@app.route("/auth/google")
def auth_google():
    """Inicia el flujo OAuth con Google."""
    if not _google_oauth_enabled:
        return redirect("/login/?error=google_not_configured")
    redirect_uri = url_for("auth_google_callback", _external=True)
    return google_oauth.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def auth_google_callback():
    """Callback OAuth de Google: busca/crea usuario y hace login."""
    if not _google_oauth_enabled:
        return redirect("/login/?error=google_not_configured")
    try:
        token     = google_oauth.authorize_access_token()
        user_info = token.get("userinfo") or {}
    except Exception:
        return redirect("/login/?error=oauth_failed")

    email = (user_info.get("email") or "").strip().lower()
    if not email:
        return redirect("/login/?error=no_email")

    google_id = user_info.get("sub", "")
    user      = User.query.filter_by(email=email).first()

    if not user:
        user = User(email=email, google_id=google_id)
        db.session.add(user)
    else:
        if not user.google_id:
            user.google_id = google_id

    if not user.is_active:
        return redirect("/login/?error=account_disabled")

    user.last_login = datetime.utcnow()
    db.session.commit()
    login_user(user, remember=True)
    return redirect("/fiscal")


@app.route("/binance")
@app.route("/bitvavo")
@app.route("/kraken")
@app.route("/bit2me")
@app.route("/coinbase")
def exchange_redirect():
    """Redirige las URLs de exchange al tool principal (301 permanente)."""
    return redirect("/fiscal", 301)


@app.route("/api/analizar", methods=["POST"])
@login_required
@limiter.limit("1 per 10 minutes")
def analizar():
    if "csv" not in request.files:
        return jsonify({"error": "No se recibió ningún fichero."}), 400

    archivo   = request.files["csv"]
    nombre    = _sanitizar_texto(request.form.get("nombre", ""))
    ejercicio = _sanitizar_texto(request.form.get("ejercicio", ""), max_len=4)
    exchange  = _sanitizar_texto(request.form.get("exchange", "binance"), max_len=20).lower()

    # Validar exchange
    if exchange not in ("binance", "bit2me", "bitvavo"):
        return jsonify({"error": "Exchange no soportado."}), 400

    # Validar ejercicio fiscal
    valido_ej, error_ej = _validar_ejercicio(ejercicio)
    if not valido_ej:
        return jsonify({"error": error_ej}), 400

    # Validar extensión
    filename = archivo.filename or ""
    if not filename.lower().endswith(".csv"):
        return jsonify({"error": "El fichero debe tener extensión .csv"}), 400

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        archivo.save(tmp.name)
        tmp_path = tmp.name

    try:
        valido, error_msg = _validar_csv(tmp_path, exchange)
        if not valido:
            return jsonify({"error": error_msg}), 400

        rendimientos_json = []

        if exchange == "bit2me":
            clasificador, resumen, operaciones = procesar_bit2me(tmp_path)
            advertencias = clasificador.advertencias
            posicion = []
            rendimientos_json = _rendimientos_a_json(clasificador.rendimientos)
            pdf_bytes = generar_pdf_bit2me(clasificador, nombre, ejercicio)

        elif exchange == "bitvavo":
            motor, rendimientos = procesar_bitvavo(tmp_path)
            resumen, posicion, operaciones = _motor_a_json(motor)
            advertencias = motor.advertencias
            rendimientos_json = _rendimientos_a_json(rendimientos)
            pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Bitvavo", rendimientos)

        else:  # binance
            motor, rendimientos = procesar_binance(tmp_path)
            resumen, posicion, operaciones = _motor_a_json(motor)
            advertencias = motor.advertencias
            rendimientos_json = _rendimientos_a_json(rendimientos)
            pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Binance", rendimientos)

        pdf_tmp = tmp_path.replace(".csv", ".pdf")
        with open(pdf_tmp, "wb") as f:
            f.write(pdf_bytes)

        return jsonify({
            "ok": True,
            "resumen": resumen,
            "operaciones": operaciones,
            "posicion": posicion,
            "rendimientos": rendimientos_json,
            "advertencias": advertencias,
            "token": os.path.basename(pdf_tmp),
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": _error_amigable(e)}), 500
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@app.route("/api/descargar/<token>")
@login_required
@limiter.limit("5 per minute")
def descargar(token):
    """Sirve el PDF y lo borra inmediatamente después."""
    if not re.match(r"^[a-zA-Z0-9_\-]+\.pdf$", token):
        return jsonify({"error": "Token inválido."}), 400

    pdf_path = os.path.join(tempfile.gettempdir(), token)
    if not os.path.realpath(pdf_path).startswith(os.path.realpath(tempfile.gettempdir())):
        return jsonify({"error": "Token inválido."}), 400
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Informe no encontrado o ya descargado."}), 404

    # Borrar el PDF en un hilo separado tras servir la respuesta
    def borrar_pdf():
        import time
        time.sleep(2)  # pequeño margen para que el envío termine
        try:
            os.unlink(pdf_path)
        except Exception:
            pass

    threading.Thread(target=borrar_pdf, daemon=True).start()

    return send_file(
        pdf_path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="informe_fiscal_cripto.pdf"
    )


# ── RUTAS AUTH ────────────────────────────────

@app.route("/api/register", methods=["POST"])
@limiter.limit("5 per hour")
def register():
    data     = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    ok, err = _validar_email(email)
    if not ok:
        return jsonify({"error": err}), 400

    ok, err = _validar_password(password)
    if not ok:
        return jsonify({"error": err}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Ya existe una cuenta con ese email."}), 409

    user = User(email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    login_user(user, remember=False)
    return jsonify({"message": "Cuenta creada correctamente.", "email": user.email, "plan": user.plan}), 201


@app.route("/api/login", methods=["POST"])
@limiter.limit("10 per 15 minutes")
def login():
    data     = request.get_json(silent=True) or {}
    email    = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    remember = bool(data.get("remember", False))

    # Mensaje genérico: no revelar si el email existe o no
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Credenciales incorrectas."}), 401

    if not user.is_active:
        return jsonify({"error": "Cuenta desactivada. Contacta con soporte."}), 403

    user.last_login = datetime.utcnow()
    db.session.commit()

    login_user(user, remember=remember)
    return jsonify({"message": "Sesión iniciada.", "email": user.email, "plan": user.plan})


@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Sesión cerrada."})


@app.route("/api/me")
def me():
    """Devuelve los datos del usuario autenticado, o null si no hay sesión."""
    if not current_user.is_authenticated:
        return jsonify({"user": None})
    return jsonify({"user": {"email": current_user.email, "plan": current_user.plan}})


@app.errorhandler(429)
def ratelimit_error(e):
    return jsonify({
        "error": "Has alcanzado el límite de análisis. Por favor espera 10 minutos antes de intentarlo de nuevo."
    }), 429


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(debug=False, port=5050)
