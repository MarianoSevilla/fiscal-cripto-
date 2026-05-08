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
import time
import tempfile
import traceback
import threading
from datetime import datetime
from flask import Flask, request, jsonify, send_file, send_from_directory, redirect, url_for, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from flask_compress import Compress
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from authlib.integrations.flask_client import OAuth
import resend
from sqlalchemy import func, extract
from models import db, bcrypt, User, FifoReport

sys.path.insert(0, os.path.dirname(__file__))

from clasificador import ClasificadorBinance
from clasificador_binance_tx import ClasificadorBinanceTx
from clasificador_bit2me import ClasificadorBit2Me
from clasificador_bitvavo import ClasificadorBitvavo
from clasificador_kraken import ClasificadorKraken
from clasificador_coinbase import ClasificadorCoinbase
from clasificador_nexo import ClasificadorNexo
from clasificador_cryptocom import ClasificadorCryptoCom
from motor_fifo import MotorFIFO
from generador_pdf import generar_pdf, generar_pdf_bit2me

app = Flask(__name__, static_folder="static")

# Proxy fix: necesario para que url_for() genere https:// en producción detrás de nginx
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

Compress(app)


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

# Emails de administrador: sin rate-limit en /api/analizar
# Configura en Railway: ADMIN_EMAILS=mario@ejemplo.com,otro@ejemplo.com
ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

def _is_admin() -> bool:
    """True si el usuario autenticado está en la lista de admins."""
    return (
        current_user.is_authenticated
        and current_user.email.strip().lower() in ADMIN_EMAILS
    )

# Railway usa "postgres://" pero SQLAlchemy requiere "postgresql://"
_db_url = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(_BASE_DIR, 'fiscal_users.db')}")
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Cookies de sesión seguras
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"]   = os.environ.get("FLASK_ENV") == "production"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


# ── EXTENSIONES ───────────────────────────────
db.init_app(app)
bcrypt.init_app(app)
migrate = Migrate(app, db)

# ── RESEND (email) ────────────────────────────
resend.api_key = os.environ.get("RESEND_API_KEY", "")
_RESEND_FROM   = os.environ.get("RESEND_FROM_EMAIL", "noreply@marianosevilla.com")
_APP_BASE_URL  = os.environ.get("APP_BASE_URL", "https://www.marianosevilla.com")

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
    # Migración de emergencia: añade columnas si no existen (PostgreSQL)
    try:
        from sqlalchemy import text
        with db.engine.connect() as _conn:
            _conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP"
            ))
            _conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(150)"
            ))
            _conn.commit()
    except Exception:
        pass


# ── PDF TOKEN STORE (Row-Level Security) ───────
# El token se guarda en la sesión Flask (cookie firmada), que viaja con el
# usuario independientemente del worker de Gunicorn que atienda la petición.
# Esto evita el problema de dicts en memoria que no se comparten entre workers.
_PDF_TTL = 300  # segundos

def _guardar_token_pdf(token: str, report_id=None) -> None:
    """Guarda el token en la sesión del usuario con su TTL."""
    from flask import session
    session["pdf_token"]       = token
    session["pdf_token_uid"]   = current_user.id
    session["pdf_token_exp"]   = time.time() + _PDF_TTL
    session["pdf_report_id"]   = report_id

def _consumir_token_pdf(token: str):
    """Valida propiedad, elimina el token de la sesión y devuelve el report_id (o None)."""
    from flask import session
    if session.get("pdf_token") != token:
        return None
    if session.get("pdf_token_uid") != current_user.id:
        return None
    if time.time() > session.get("pdf_token_exp", 0):
        return None
    report_id = session.get("pdf_report_id")
    session.pop("pdf_token",     None)
    session.pop("pdf_token_uid", None)
    session.pop("pdf_token_exp", None)
    session.pop("pdf_report_id", None)
    return report_id if report_id is not None else -1


def _contar_csv_rows(filepath: str) -> int:
    """Cuenta filas de datos en el CSV (sin contar la cabecera)."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0


def _registrar_informe(
    exchange: str,
    fiscal_year: int,
    csv_rows: int,
    distinct_assets: int,
    processing_ms: int,
    status: str = "generated",
    error_type=None,
):
    """Crea un registro FifoReport y devuelve su id. No lanza excepciones."""
    if not current_user.is_authenticated:
        return None
    try:
        report = FifoReport(
            user_id         = current_user.id,
            exchange        = exchange,
            fiscal_year     = fiscal_year,
            csv_rows        = csv_rows,
            distinct_assets = distinct_assets,
            processing_ms   = processing_ms,
            status          = status,
            error_type      = error_type,
        )
        db.session.add(report)
        db.session.commit()
        return report.id
    except Exception:
        db.session.rollback()
        return None


# ── DATOS SEO POR EXCHANGE ─────────────────────
_BASE_URL = "https://marianosevilla.com"

_HOW_TO_STEP2 = {
    "title": "La herramienta aplica el método FIFO obligatorio",
    "desc":  "La herramienta clasifica automáticamente compras, ventas, swaps y comisiones. "
             "Aplica el método FIFO (art. 37.2 LIRPF) y calcula tus ganancias y pérdidas "
             "patrimoniales ejercicio a ejercicio.",
}
_HOW_TO_STEP3 = {
    "title": "Descarga el informe PDF listo para Hacienda",
    "desc":  "En segundos obtienes el PDF con el detalle de todas las operaciones del "
             "ejercicio, el resultado neto y los importes exactos para las casillas 1626 "
             "y 1627 de la declaración de la renta.",
}

_TOOL_GENERIC = {
    "exchange_id":      "",
    "exchange_name":    "tu exchange",
    "exchange_logo":    "&#x25CF;",
    "page_title":       "Calculadora FIFO Cripto para Hacienda | Mariano Sevilla",
    "page_meta_desc":   "Sube el CSV de tu exchange y calcula ganancias con FIFO obligatorio. Informe PDF listo para tu declaración de la renta.",
    "page_canonical":   f"{_BASE_URL}/fiscal",
    "page_og_title":    "Calculadora FIFO Criptomonedas para Hacienda — Mariano Sevilla",
    "page_og_desc":     "Sube el CSV de tu exchange y calcula ganancias y pérdidas patrimoniales con FIFO. Informe PDF listo para tu declaración de la renta.",
    "page_schema_name": "Calculadora FIFO Criptomonedas — Mariano Sevilla",
    "page_h1":          "",
    "hero_desc":        "",
    "how_to":           [],
}

EXCHANGE_PAGES = {
    "binance": {
        "exchange_id":      "binance",
        "exchange_name":    "Binance",
        "exchange_logo":    "B",
        "page_title":       "Informe FIFO Binance para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el CSV de Binance y calcula ganancias y pérdidas con FIFO obligatorio. Informe PDF para declarar Binance en la declaración de la renta.",
        "page_canonical":   f"{_BASE_URL}/binance",
        "page_og_title":    "Informe fiscal Binance para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el CSV de Binance y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Binance — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Binance para Hacienda",
        "hero_desc":        "La herramienta lee el CSV de Binance, aplica el método FIFO obligatorio según la normativa española y calcula tus plusvalías y pérdidas patrimoniales. Descarga el informe PDF con los importes exactos para las casillas 1626 y 1627 de la declaración de la renta.",
        "how_to": [
            {"title": "Exporta el CSV de Binance (Transaction History)",
             "desc":  "En tu cuenta de Binance ve a Wallet → Historial de transacciones → Exportar. Selecciona «All Transactions», elige el rango completo desde tu primera operación hasta hoy y descarga el fichero CSV."},
            _HOW_TO_STEP2, _HOW_TO_STEP3,
        ],
    },
    "bitvavo": {
        "exchange_id":      "bitvavo",
        "exchange_name":    "Bitvavo",
        "exchange_logo":    "BV",
        "page_title":       "Informe FIFO Bitvavo para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el CSV de Bitvavo y calcula tus ganancias y pérdidas patrimoniales con FIFO obligatorio. Informe PDF listo para la declaración de la renta.",
        "page_canonical":   f"{_BASE_URL}/bitvavo",
        "page_og_title":    "Informe fiscal Bitvavo para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el CSV de Bitvavo y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Bitvavo — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Bitvavo para Hacienda",
        "hero_desc":        "Sube el CSV del historial de transacciones de Bitvavo y obtén el informe FIFO con tus ganancias y pérdidas patrimoniales. Listo para la declaración de la renta.",
        "how_to": [
            {"title": "Exporta el CSV de transacciones desde Bitvavo",
             "desc":  "En tu cuenta de Bitvavo ve a Cuenta → Historial de transacciones → Exportar. Selecciona el período completo desde tu primera operación hasta hoy y descarga el fichero CSV."},
            _HOW_TO_STEP2, _HOW_TO_STEP3,
        ],
    },
    "bit2me": {
        "exchange_id":      "bit2me",
        "exchange_name":    "Bit2Me",
        "exchange_logo":    "B2",
        "page_title":       "Informe FIFO Bit2Me para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el CSV fiscal de Bit2Me y calcula tus ganancias y pérdidas patrimoniales con FIFO obligatorio. Informe PDF listo para la declaración de la renta.",
        "page_canonical":   f"{_BASE_URL}/bit2me",
        "page_og_title":    "Informe fiscal Bit2Me para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el CSV fiscal de Bit2Me y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Bit2Me — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Bit2Me para Hacienda",
        "hero_desc":        "Sube el CSV del informe fiscal de Bit2Me y obtén el cálculo FIFO con tus ganancias y pérdidas patrimoniales. Listo para la declaración de la renta.",
        "how_to": [
            {"title": "Descarga el informe fiscal CSV desde Bit2Me",
             "desc":  "En tu cuenta de Bit2Me ve a Mi cuenta → Informes fiscales. Selecciona el ejercicio fiscal, elige el período completo desde tu primera operación y descarga el informe en formato CSV."},
            _HOW_TO_STEP2, _HOW_TO_STEP3,
        ],
    },
    "kraken": {
        "exchange_id":      "kraken",
        "exchange_name":    "Kraken",
        "exchange_logo":    "K",
        "page_title":       "Informe FIFO Kraken para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el CSV de Ledgers de Kraken y calcula ganancias y pérdidas patrimoniales con FIFO obligatorio. Informe PDF listo para declarar Kraken en Hacienda.",
        "page_canonical":   f"{_BASE_URL}/kraken",
        "page_og_title":    "Informe fiscal Kraken para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el CSV de Ledgers de Kraken y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Kraken — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Kraken para Hacienda",
        "hero_desc":        "Sube el CSV de Ledgers de Kraken y obtén el informe FIFO con tus ganancias y pérdidas patrimoniales. Listo para la declaración de la renta.",
        "how_to": [
            {"title": "Exporta el CSV de Ledgers desde Kraken",
             "desc":  "En tu cuenta de Kraken ve a Historial → Exportar. Selecciona tipo «Ledgers» (no «Trades»), elige el período completo desde tu primera operación hasta hoy y descarga el fichero CSV."},
            _HOW_TO_STEP2, _HOW_TO_STEP3,
        ],
    },
    "coinbase": {
        "exchange_id":      "coinbase",
        "exchange_name":    "Coinbase",
        "exchange_logo":    "C",
        "page_title":       "Informe FIFO Coinbase para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el CSV de Coinbase y calcula tus ganancias y pérdidas patrimoniales con FIFO obligatorio. Informe PDF listo para la declaración de la renta.",
        "page_canonical":   f"{_BASE_URL}/coinbase",
        "page_og_title":    "Informe fiscal Coinbase para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el CSV de Coinbase y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Coinbase — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Coinbase para Hacienda",
        "hero_desc":        "Sube el CSV del historial de transacciones de Coinbase y obtén el informe FIFO con tus ganancias y pérdidas patrimoniales. Listo para la declaración de la renta.",
        "how_to": [
            {"title": "Exporta el CSV del historial de transacciones de Coinbase",
             "desc":  "En tu cuenta de Coinbase ve a Perfil → Extractos → Historial de transacciones. Haz clic en «Generar extracto», selecciona el rango completo desde tu primera operación hasta hoy y descarga el fichero CSV."},
            _HOW_TO_STEP2, _HOW_TO_STEP3,
        ],
    },
    "nexo": {
        "exchange_id":      "nexo",
        "exchange_name":    "Nexo",
        "exchange_logo":    "N",
        "page_title":       "Informe FIFO Nexo para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el CSV de Nexo y calcula tus ganancias, pérdidas e intereses con FIFO obligatorio. Informe PDF listo para la declaración de la renta en España.",
        "page_canonical":   f"{_BASE_URL}/nexo",
        "page_og_title":    "Informe fiscal Nexo para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el CSV de Nexo y calcula las plusvalías e intereses crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Nexo — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Nexo para Hacienda",
        "hero_desc":        "Sube el CSV del historial de transacciones de Nexo y obtén el informe FIFO con tus ganancias, pérdidas patrimoniales e intereses. Los intereses tributan como rendimientos del capital mobiliario (casilla 0033). Listo para la declaración de la renta.",
        "how_to": [
            {"title": "Exporta el CSV de transacciones desde Nexo",
             "desc":  "En tu cuenta de Nexo ve a Perfil → Declaración de activos → Historial de transacciones. Selecciona el rango de fechas completo desde tu primera operación hasta hoy y descarga el fichero CSV."},
            _HOW_TO_STEP2, _HOW_TO_STEP3,
        ],
    },
    "cryptocom": {
        "exchange_id":      "cryptocom",
        "exchange_name":    "Crypto.com",
        "exchange_logo":    "C.C",
        "page_title":       "Informe FIFO Crypto.com para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el CSV de Crypto.com y calcula tus ganancias, pérdidas e intereses con FIFO obligatorio. Informe PDF listo para la declaración de la renta en España.",
        "page_canonical":   f"{_BASE_URL}/cryptocom",
        "page_og_title":    "Informe fiscal Crypto.com para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el CSV de Crypto.com y calcula las plusvalías e intereses crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Crypto.com — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Crypto.com para Hacienda",
        "hero_desc":        "Sube el CSV del historial de transacciones de Crypto.com App y obtén el informe FIFO con tus ganancias y pérdidas patrimoniales. Los intereses de Crypto Earn tributan como rendimientos del capital mobiliario (casilla 0033). Listo para la declaración de la renta.",
        "how_to": [
            {"title": "Exporta el CSV de transacciones desde Crypto.com",
             "desc":  "En la app de Crypto.com ve a Cuenta → Declaración de activos → Historial de transacciones. Selecciona el rango de fechas completo desde tu primera operación hasta hoy y descarga el fichero CSV (crypto_transactions_record_*.csv)."},
            _HOW_TO_STEP2, _HOW_TO_STEP3,
        ],
    },
}


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
def _rate_limit_key() -> str:
    """Usuarios autenticados → rate limit por user_id (no por IP compartida)."""
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()

limiter = Limiter(
    _rate_limit_key,
    app=app,
    default_limits=["100 per day", "20 per hour"],
    # En producción con múltiples workers usar REDIS_URL para compartir contadores
    storage_uri=os.environ.get("REDIS_URL", "memory://"),
)


# ── WWW REDIRECT ──────────────────────────────
@app.before_request
def redirect_www():
    if request.host.startswith("www."):
        return redirect(request.url.replace("://www.", "://", 1), 301)


# ── SECURITY HEADERS ──────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers["X-Frame-Options"]                   = "DENY"
    response.headers["X-Content-Type-Options"]             = "nosniff"
    # X-XSS-Protection: 0 — desactiva el auditor XSS del navegador (deprecated y
    # con bugs conocidos). La protección real la provee la CSP de abajo.
    response.headers["X-XSS-Protection"]                  = "0"
    response.headers["Referrer-Policy"]                    = "strict-origin-when-cross-origin"
    response.headers["Cross-Origin-Opener-Policy"]         = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"]       = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "base-uri 'self';"
    )
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), "
        "usb=(), bluetooth=(), serial=()"
    )
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

BINANCE_SIGNATURES   = ["Tiempo", "Operación", "Moneda", "Cambio", "Cuenta"]
BIT2ME_SIGNATURES    = ["Bit", "2Me", "Informe Fiscal", "Estimado"]
BITVAVO_SIGNATURES   = ["Timezone", "Date", "Time", "Type", "Currency", "Amount"]
KRAKEN_SIGNATURES    = ["txid", "refid", "time", "type", "asset", "amount", "fee"]
COINBASE_SIGNATURES  = ["Timestamp", "Transaction Type", "Quantity Transacted"]
NEXO_SIGNATURES      = ["Transaction", "Type", "Input Currency", "Output Currency"]
CRYPTOCOM_SIGNATURES = ["Timestamp (UTC)", "Transaction Description", "Transaction Kind"]


def _sanitizar_texto(texto: str, max_len: int = 100) -> str:
    if not texto:
        return ""
    texto = re.sub(r"<[^>]+>", "", texto)
    texto = re.sub(r"[^\w\s\-\.,@áéíóúÁÉÍÓÚñÑüÜ]", "", texto)
    return texto[:max_len].strip()


def _title_case(texto: str) -> str:
    """Convierte 'mariano sevilla trujillo' → 'Mariano Sevilla Trujillo'."""
    return " ".join(w.capitalize() for w in texto.strip().split())


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
        "binance":   BINANCE_SIGNATURES,
        "bit2me":    BIT2ME_SIGNATURES,
        "bitvavo":   BITVAVO_SIGNATURES,
        "kraken":    KRAKEN_SIGNATURES,
        "coinbase":  COINBASE_SIGNATURES,
        "nexo":      NEXO_SIGNATURES,
        "cryptocom": CRYPTOCOM_SIGNATURES,
    }
    nombres = {
        "binance":   "Binance",
        "bit2me":    "Bit2Me",
        "bitvavo":   "Bitvavo",
        "kraken":    "Kraken",
        "coinbase":  "Coinbase",
        "nexo":      "Nexo",
        "cryptocom": "Crypto.com",
    }
    if exchange in sigs:
        if not any(sig in primeras for sig in sigs[exchange]):
            return False, (
                f"El fichero no parece ser un CSV de {nombres[exchange]}. "
                f"Asegúrate de exportar el historial desde tu cuenta de {nombres[exchange]}."
            )

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


def _detectar_formato_binance(filepath: str) -> str:
    """Devuelve 'tx' para Historial de Transacciones o 'spot' para Historial de Operaciones Spot."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            muestra = "".join(f.readline() for _ in range(20))
        if "Buy Crypto With Fiat" in muestra or "Sell Crypto To Fiat" in muestra or "ID de usuario" in muestra:
            return "tx"
    except Exception:
        pass
    return "spot"


def procesar_binance(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorBinance(filepath).clasificar())


def procesar_binance_tx(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorBinanceTx(filepath).clasificar())


def procesar_bitvavo(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorBitvavo(filepath).clasificar())


def procesar_kraken(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorKraken(filepath).clasificar())


def procesar_coinbase(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorCoinbase(filepath).clasificar())


def procesar_nexo(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorNexo(filepath).clasificar())


def procesar_cryptocom(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorCryptoCom(filepath).clasificar())


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
    etype = type(e).__name__
    msg = str(e)
    if isinstance(e, KeyError) or etype == "KeyError" or "column" in msg.lower():
        return "El fichero CSV no tiene las columnas esperadas. Exporta el historial completo desde tu exchange."
    if "NoneType" in msg or etype == "AttributeError":
        return "El fichero CSV no tiene el formato esperado. Asegúrate de exportarlo directamente desde tu exchange."
    if etype in ("UnicodeDecodeError", "UnicodeError") or "codec" in msg:
        return "El fichero no puede leerse. Descárgalo de nuevo desde tu exchange sin abrirlo con Excel."
    if etype == "MemoryError":
        return "El fichero es demasiado grande para procesarse. Intenta con un rango de fechas más reducido."
    if "JSON" in msg or "float" in msg.lower() or "range" in msg.lower() or "serializ" in msg.lower():
        return "Error al generar el informe. Comprueba que el CSV no ha sido modificado y vuelve a intentarlo."
    if etype == "ParserError" or "tokeniz" in msg.lower():
        return "El fichero CSV está mal formado. Descárgalo de nuevo desde tu exchange sin abrirlo con Excel."
    return "No se ha podido procesar el fichero. Comprueba que es el CSV exportado desde tu exchange y vuelve a intentarlo."


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
@login_required
def fiscal():
    return render_template("tool.html", **_TOOL_GENERIC)


@app.route("/privacidad", strict_slashes=False)
def privacidad():
    return send_from_directory("static", "privacidad.html")


@app.route("/terminos", strict_slashes=False)
def terminos():
    return send_from_directory("static", "terminos.html")


@app.route("/aviso-legal", strict_slashes=False)
def aviso_legal():
    return send_from_directory("static", "aviso-legal.html")


@app.route("/seguridad", strict_slashes=False)
def seguridad():
    return send_from_directory("static", "seguridad.html")


@app.route("/cookies", strict_slashes=False)
def cookies():
    return send_from_directory("static", "cookies.html")


@app.route("/preferencias", strict_slashes=False)
def preferencias():
    return send_from_directory("static", "preferencias.html")


@app.route("/dashboard", strict_slashes=False)
def dashboard():
    """Dashboard principal: selector de exchange. Requiere autenticación (gestionada en JS)."""
    return send_from_directory("static", "dashboard.html")


@app.route("/account", strict_slashes=False)
def account():
    return send_from_directory("static", "account.html")


# ── EMAIL VERIFICATION ────────────────────────

_VERIFY_TOKEN_SALT = "email-verification-v1"
_VERIFY_TOKEN_TTL  = 86_400  # 24 horas


def _generate_verification_token(email: str) -> str:
    s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    return s.dumps(email.lower(), salt=_VERIFY_TOKEN_SALT)


def _confirm_verification_token(token: str):
    """Devuelve (email, None) o (None, 'expired'|'invalid')."""
    s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    try:
        email = s.loads(token, salt=_VERIFY_TOKEN_SALT, max_age=_VERIFY_TOKEN_TTL)
        return email, None
    except SignatureExpired:
        return None, "expired"
    except BadSignature:
        return None, "invalid"


def _send_verification_email(user: User) -> bool:
    """Envía el email de verificación. Devuelve True si se envió correctamente."""
    if not resend.api_key:
        app.logger.warning("RESEND_API_KEY no configurada — email de verificación no enviado.")
        return False

    token = _generate_verification_token(user.email)
    verify_url = f"{_APP_BASE_URL}/verify-email?token={token}"

    html = f"""
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#080c12;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#080c12;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#10141e;border-radius:12px;border:1px solid rgba(255,255,255,0.08);overflow:hidden;">
        <tr>
          <td style="background:#0d1018;padding:28px 40px;border-bottom:1px solid rgba(0,200,150,0.25);">
            <span style="font-size:18px;font-weight:700;color:#eef0f6;">Mariano</span><span style="font-size:18px;font-weight:700;color:#00C896;">Sevilla</span>
            <span style="font-size:12px;color:#7a8099;margin-left:10px;">Herramienta Fiscal Cripto</span>
          </td>
        </tr>
        <tr>
          <td style="padding:36px 40px;">
            <h1 style="margin:0 0 12px;font-size:22px;color:#eef0f6;font-weight:700;">Verifica tu dirección de email</h1>
            <p style="margin:0 0 24px;font-size:15px;color:#9aa0b8;line-height:1.6;">
              Haz clic en el botón para confirmar tu cuenta y empezar a generar informes FIFO.
            </p>
            <table cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
              <tr>
                <td style="background:#00C896;border-radius:8px;padding:14px 32px;">
                  <a href="{verify_url}" style="color:#080c12;font-size:15px;font-weight:700;text-decoration:none;display:block;">
                    Verificar email
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 8px;font-size:13px;color:#7a8099;line-height:1.5;">
              Si el botón no funciona, copia y pega este enlace en tu navegador:
            </p>
            <p style="margin:0 0 28px;font-size:12px;color:#00C896;word-break:break-all;">{verify_url}</p>
            <p style="margin:0 0 12px;font-size:12px;color:#555c70;">
              Este enlace caduca en 24 horas. Si no creaste esta cuenta, ignora este mensaje.
            </p>
            <p style="margin:0;font-size:12px;color:#7a8099;background:rgba(255,255,255,0.04);border-radius:6px;padding:10px 14px;">
              📬 ¿No ves este email? Revisa tu carpeta de <strong style="color:#eef0f6;">spam o correo no deseado</strong> y márcalo como «No es spam» para recibirlos en el futuro.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#0d1018;padding:18px 40px;border-top:1px solid rgba(255,255,255,0.06);">
            <p style="margin:0;font-size:11px;color:#555c70;">
              marianosevilla.com · Herramienta Fiscal Cripto para el IRPF español
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    text = (
        f"Verifica tu dirección de email\n\n"
        f"Haz clic en el siguiente enlace para confirmar tu cuenta:\n{verify_url}\n\n"
        f"Este enlace caduca en 24 horas.\n"
        f"Si no ves este email en tu bandeja de entrada, revisa la carpeta de spam.\n\n"
        f"Si no creaste esta cuenta, ignora este mensaje.\n\n"
        f"marianosevilla.com — Herramienta Fiscal Cripto"
    )

    try:
        resend.Emails.send({
            "from":    _RESEND_FROM,
            "to":      [user.email],
            "subject": "Verifica tu email — Herramienta Fiscal Cripto",
            "html":    html,
            "text":    text,
        })
        return True
    except Exception as exc:
        app.logger.error("Error enviando email de verificación: %s", exc)
        return False


@app.route("/login/", strict_slashes=False)
def login_page():
    """Página dedicada de inicio de sesión."""
    if current_user.is_authenticated:
        return redirect("/")
    return send_from_directory("static", "login.html")


@app.route("/signup/", strict_slashes=False)
def signup_page():
    """Página dedicada de registro."""
    if current_user.is_authenticated:
        return redirect("/")
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

    # Obtener nombre desde perfil de Google
    given_name  = (user_info.get("given_name") or "").strip()
    family_name = (user_info.get("family_name") or "").strip()
    google_name = (given_name + " " + family_name).strip() or (user_info.get("name") or "").strip()
    google_full_name = _title_case(google_name) if google_name else None

    if not user:
        user = User(
            email=email,
            google_id=google_id,
            email_verified_at=datetime.utcnow(),
            full_name=google_full_name,
        )
        db.session.add(user)
    else:
        if not user.google_id:
            user.google_id = google_id
        # Google garantiza que el email es válido
        if not user.email_verified_at:
            user.email_verified_at = datetime.utcnow()
        # Actualizar nombre solo si el usuario no tenía uno guardado
        if not user.full_name and google_full_name:
            user.full_name = google_full_name

    if not user.is_active:
        return redirect("/login/?error=account_disabled")

    user.last_login = datetime.utcnow()
    db.session.commit()
    login_user(user, remember=True)
    return redirect("/dashboard")


@app.route("/binance")
@login_required
def page_binance():
    return render_template("tool.html", **EXCHANGE_PAGES["binance"])


@app.route("/bitvavo")
@login_required
def page_bitvavo():
    return render_template("tool.html", **EXCHANGE_PAGES["bitvavo"])


@app.route("/bit2me")
@login_required
def page_bit2me():
    return render_template("tool.html", **EXCHANGE_PAGES["bit2me"])


@app.route("/kraken")
@login_required
def page_kraken():
    return render_template("tool.html", **EXCHANGE_PAGES["kraken"])


@app.route("/coinbase")
@login_required
def page_coinbase():
    return render_template("tool.html", **EXCHANGE_PAGES["coinbase"])


@app.route("/nexo")
@login_required
def page_nexo():
    return render_template("tool.html", **EXCHANGE_PAGES["nexo"])


@app.route("/cryptocom")
@login_required
def page_cryptocom():
    return render_template("tool.html", **EXCHANGE_PAGES["cryptocom"])


@app.route("/api/analizar", methods=["POST"])
@login_required
@limiter.limit("1 per 10 minutes", exempt_when=_is_admin)
def analizar():
    if "csv" not in request.files:
        return jsonify({"error": "No se recibió ningún fichero."}), 400

    archivo   = request.files["csv"]
    nombre    = _sanitizar_texto(request.form.get("nombre", ""))
    ejercicio = _sanitizar_texto(request.form.get("ejercicio", ""), max_len=4)
    exchange  = _sanitizar_texto(request.form.get("exchange", "binance"), max_len=20).lower()

    # Validar exchange
    if exchange not in ("binance", "bit2me", "bitvavo", "kraken", "coinbase", "nexo", "cryptocom"):
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

    t_start   = time.time()
    csv_rows  = _contar_csv_rows(tmp_path)

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

        elif exchange == "kraken":
            motor, rendimientos = procesar_kraken(tmp_path)
            resumen, posicion, operaciones = _motor_a_json(motor)
            advertencias = motor.advertencias
            rendimientos_json = _rendimientos_a_json(rendimientos)
            pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Kraken", rendimientos)

        elif exchange == "coinbase":
            motor, rendimientos = procesar_coinbase(tmp_path)
            resumen, posicion, operaciones = _motor_a_json(motor)
            advertencias = motor.advertencias
            rendimientos_json = _rendimientos_a_json(rendimientos)
            pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Coinbase", rendimientos)

        elif exchange == "nexo":
            motor, rendimientos = procesar_nexo(tmp_path)
            resumen, posicion, operaciones = _motor_a_json(motor)
            advertencias = motor.advertencias
            rendimientos_json = _rendimientos_a_json(rendimientos)
            pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Nexo", rendimientos)

        elif exchange == "cryptocom":
            motor, rendimientos = procesar_cryptocom(tmp_path)
            resumen, posicion, operaciones = _motor_a_json(motor)
            advertencias = motor.advertencias
            rendimientos_json = _rendimientos_a_json(rendimientos)
            pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Crypto.com", rendimientos)

        else:  # binance — auto-detectar formato
            if _detectar_formato_binance(tmp_path) == "tx":
                motor, rendimientos = procesar_binance_tx(tmp_path)
            else:
                motor, rendimientos = procesar_binance(tmp_path)
            resumen, posicion, operaciones = _motor_a_json(motor)
            advertencias = motor.advertencias
            rendimientos_json = _rendimientos_a_json(rendimientos)
            pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Binance", rendimientos)

        processing_ms   = int((time.time() - t_start) * 1000)
        distinct_assets = len({op["activo"] for op in operaciones}) if operaciones else 0

        pdf_tmp = tmp_path.replace(".csv", ".pdf")
        with open(pdf_tmp, "wb") as f:
            f.write(pdf_bytes)

        report_id = _registrar_informe(
            exchange        = exchange,
            fiscal_year     = int(ejercicio) if ejercicio else 0,
            csv_rows        = csv_rows,
            distinct_assets = distinct_assets,
            processing_ms   = processing_ms,
        )
        token = os.path.basename(pdf_tmp)
        _guardar_token_pdf(token, report_id)

        return jsonify({
            "ok": True,
            "resumen": resumen,
            "operaciones": operaciones,
            "posicion": posicion,
            "rendimientos": rendimientos_json,
            "advertencias": advertencias,
            "token": token,
        })

    except Exception as e:
        traceback.print_exc()
        _registrar_informe(
            exchange        = exchange,
            fiscal_year     = int(ejercicio) if ejercicio.isdigit() else 0,
            csv_rows        = csv_rows,
            distinct_assets = 0,
            processing_ms   = int((time.time() - t_start) * 1000),
            status          = "failed",
            error_type      = type(e).__name__,
        )
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

    # RLS: solo el usuario que generó el PDF puede descargarlo
    report_id = _consumir_token_pdf(token)
    if report_id is None:
        return jsonify({"error": "Token inválido o expirado."}), 403

    if not os.path.exists(pdf_path):
        return jsonify({"error": "Informe no encontrado o ya descargado."}), 404

    # Registrar descarga
    if report_id and report_id > 0:
        try:
            report = db.session.get(FifoReport, report_id)
            if report:
                report.downloaded_at = datetime.utcnow()
                db.session.commit()
        except Exception:
            db.session.rollback()

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
        download_name=f"informe_fiscal_cripto_{re.sub(r'[^a-z0-9]', '', (request.args.get('exchange', '') or 'cripto').lower())}.pdf"
    )


# ── RUTAS AUTH ────────────────────────────────

@app.route("/api/register", methods=["POST"])
@limiter.limit("5 per hour")
def register():
    data      = request.get_json(silent=True) or {}
    email     = (data.get("email") or "").strip().lower()
    password  = data.get("password") or ""
    full_name = _sanitizar_texto(data.get("full_name") or "", max_len=150)

    if not full_name:
        return jsonify({"error": "El nombre y apellidos son obligatorios."}), 400

    ok, err = _validar_email(email)
    if not ok:
        return jsonify({"error": err}), 400

    ok, err = _validar_password(password)
    if not ok:
        return jsonify({"error": err}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Ya existe una cuenta con ese email."}), 409

    user = User(email=email, full_name=_title_case(full_name))
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    _send_verification_email(user)
    return jsonify({
        "pending_verification": True,
        "email": user.email,
        "message": "Cuenta creada. Revisa tu bandeja de entrada para verificar tu email.",
    }), 201


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

    if not user.email_verified_at:
        _send_verification_email(user)
        return jsonify({
            "message": "Sesión iniciada.",
            "email": user.email,
            "plan": user.plan,
            "pending_verification": True,
        })

    return jsonify({"message": "Sesión iniciada.", "email": user.email, "plan": user.plan})


@app.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"message": "Sesión cerrada."})


@app.route("/verify-email")
def verify_email():
    """Procesa el token del enlace enviado por email."""
    token = request.args.get("token", "")
    if not token:
        return redirect("/verify-email-result?status=invalid")

    email, error = _confirm_verification_token(token)
    if error == "expired":
        return redirect("/verify-email-result?status=expired")
    if error == "invalid" or not email:
        return redirect("/verify-email-result?status=invalid")

    user = User.query.filter_by(email=email).first()
    if not user:
        return redirect("/verify-email-result?status=invalid")

    if user.email_verified_at:
        return redirect("/verify-email-result?status=already")

    user.email_verified_at = datetime.utcnow()
    db.session.commit()
    return redirect("/verify-email-result?status=success")


@app.route("/verify-email-result")
def verify_email_result():
    return send_from_directory("static", "verify-email.html")


@app.route("/api/resend-verification", methods=["POST"])
@limiter.limit("3 per hour")
def resend_verification():
    """Reenvía el email de verificación. No requiere sesión activa."""
    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "Email requerido."}), 400

    user = User.query.filter_by(email=email).first()
    # Respuesta genérica: no revelar si el email existe
    if not user or user.email_verified_at:
        return jsonify({"message": "Si el email existe y no está verificado, recibirás un nuevo enlace."}), 200

    _send_verification_email(user)
    return jsonify({"message": "Email de verificación reenviado."}), 200


@app.route("/api/me")
def me():
    """Devuelve los datos del usuario autenticado, o null si no hay sesión."""
    if not current_user.is_authenticated:
        return jsonify({"user": None})
    return jsonify({"user": {
        "email":          current_user.email,
        "full_name":      current_user.full_name or "",
        "plan":           current_user.plan,
        "email_verified": current_user.email_verified_at is not None,
        "is_google":      current_user.google_id is not None,
        "is_admin":       _is_admin(),
        "created_at":     current_user.created_at.isoformat() if current_user.created_at else None,
    }})


@app.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    """Cambia la contraseña del usuario autenticado (solo cuentas email, no OAuth)."""
    if current_user.google_id:
        return jsonify({"error": "Las cuentas de Google no tienen contraseña."}), 400
    data        = request.get_json(silent=True) or {}
    current_pw  = data.get("current_password", "")
    new_pw      = data.get("new_password", "")
    if not current_user.check_password(current_pw):
        return jsonify({"error": "La contraseña actual no es correcta."}), 400
    if len(new_pw) < 8:
        return jsonify({"error": "La nueva contraseña debe tener al menos 8 caracteres."}), 400
    current_user.set_password(new_pw)
    db.session.commit()
    return jsonify({"message": "Contraseña actualizada correctamente."})


@app.route("/api/update-profile", methods=["POST"])
@login_required
def update_profile():
    """Actualiza el nombre y apellidos del usuario autenticado."""
    data      = request.get_json(silent=True) or {}
    full_name = _sanitizar_texto(data.get("full_name") or "", max_len=150)
    if not full_name:
        return jsonify({"error": "El nombre y apellidos no pueden estar vacíos."}), 400
    current_user.full_name = _title_case(full_name)
    db.session.commit()
    return jsonify({"message": "Perfil actualizado.", "full_name": current_user.full_name})


@app.route("/api/delete-account", methods=["POST"])
@login_required
def delete_account():
    """Anonimiza la cuenta: borra PII pero mantiene la fila para estadísticas."""
    uid = current_user.id
    current_user.email             = f"deleted_{uid}@deleted"
    current_user.password_hash     = None
    current_user.google_id         = None
    current_user.is_active         = False
    current_user.email_verified_at = None
    db.session.commit()
    logout_user()
    return jsonify({"message": "Cuenta eliminada correctamente."})


# ── ADMIN STATS ──────────────────────────────────────────────────────────────

@app.route("/stats")
@login_required
def stats_page():
    if not _is_admin():
        return redirect("/dashboard")
    return send_from_directory("static", "stats.html")


@app.route("/api/stats")
@login_required
def api_stats():
    if not _is_admin():
        return jsonify({"error": "Acceso denegado."}), 403

    try:
        return _api_stats_data()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _api_stats_data():
    from collections import defaultdict

    now = datetime.utcnow()

    # Primer día del mes de hace 5 meses (= ventana de 6 meses: 5 completos + mes actual)
    m = now.month - 5
    y = now.year
    if m <= 0:
        m += 12
        y -= 1
    seis_meses_atras = datetime(y, m, 1)

    # ── Usuarios ─────────────────────────────────────────────────────────────
    todos_usuarios   = User.query.all()
    total_users      = len(todos_usuarios)
    verified_users   = sum(1 for u in todos_usuarios if u.email_verified_at)
    unverified_users = total_users - verified_users

    # Nuevos por mes (últimos 6 meses) — agrupado en Python
    usuarios_bucket = defaultdict(int)
    for u in todos_usuarios:
        if u.created_at and u.created_at >= seis_meses_atras:
            usuarios_bucket[u.created_at.strftime("%Y-%m")] += 1
    usuarios_por_mes_json = [
        {"mes": k, "total": v}
        for k, v in sorted(usuarios_bucket.items())
    ]

    # ── Informes FIFO ────────────────────────────────────────────────────────
    todos_reports     = FifoReport.query.all()
    generados         = [r for r in todos_reports if r.status == "generated"]
    total_generados   = len(generados)
    total_descargados = sum(1 for r in generados if r.downloaded_at)

    exchange_bucket = defaultdict(int)
    for r in generados:
        exchange_bucket[r.exchange] += 1
    por_exchange_json = [
        {"exchange": k, "total": v}
        for k, v in sorted(exchange_bucket.items(), key=lambda x: -x[1])
    ]

    ejercicio_bucket = defaultdict(int)
    for r in generados:
        ejercicio_bucket[r.fiscal_year] += 1
    por_ejercicio_json = [
        {"ejercicio": k, "total": v}
        for k, v in sorted(ejercicio_bucket.items(), key=lambda x: -x[0])
    ]

    # ── Errores por mes — últimos 6 meses ────────────────────────────────────
    user_map = {u.id: u for u in todos_usuarios}
    errores_bucket = defaultdict(int)
    errores_detalle = []
    for r in todos_reports:
        if r.status == "failed" and r.created_at and r.created_at >= seis_meses_atras:
            errores_bucket[r.created_at.strftime("%Y-%m")] += 1
    for r in todos_reports:
        if r.status == "failed" and r.created_at:
            u = user_map.get(r.user_id)
            errores_detalle.append({
                "fecha":    r.created_at.strftime("%Y-%m-%d %H:%M"),
                "exchange": r.exchange,
                "usuario":  u.email if u else f"#{r.user_id}",
            })
    errores_detalle.sort(key=lambda x: x["fecha"], reverse=True)

    errores_por_mes_json = [
        {"mes": k, "total": v}
        for k, v in sorted(errores_bucket.items())
    ]

    return jsonify({
        "usuarios": {
            "total":       total_users,
            "verificados": verified_users,
            "sin_verificar": unverified_users,
            "por_mes":     usuarios_por_mes_json,
        },
        "informes": {
            "total_generados":  total_generados,
            "total_descargados": total_descargados,
            "por_exchange":     por_exchange_json,
            "por_ejercicio":    por_ejercicio_json,
        },
        "errores": {
            "por_mes":  errores_por_mes_json,
            "detalle":  errores_detalle,
        },
    })


@app.errorhandler(429)
def ratelimit_error(e):
    return jsonify({
        "error": "Has alcanzado el límite de análisis. Por favor espera 10 minutos antes de intentarlo de nuevo."
    }), 429


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(debug=False, port=5050)
