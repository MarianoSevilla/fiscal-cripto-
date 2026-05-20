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
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, send_from_directory, redirect, url_for, render_template, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from flask_compress import Compress
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from authlib.integrations.flask_client import OAuth
import resend
from sqlalchemy import func, extract, text
from models import db, bcrypt, User, FifoReport, Contacto

# Advisory / Stripe imports
try:
    import stripe as _stripe_module
    _stripe_available = True
except ImportError:
    _stripe_available = False
    _stripe_module = None
from models import FiscalAdvisoryRequest, FiscalAdvisoryFile, FiscalAdvisoryStatusHistory

sys.path.insert(0, os.path.dirname(__file__))

from clasificador import ClasificadorBinance
from clasificador_binance_tx import ClasificadorBinanceTx
from clasificador_bit2me import ClasificadorBit2Me
from clasificador_bitvavo import ClasificadorBitvavo
from clasificador_kraken import ClasificadorKraken
from clasificador_coinbase import ClasificadorCoinbase
from clasificador_nexo import ClasificadorNexo
from clasificador_cryptocom import ClasificadorCryptoCom
from clasificador_uphold import ClasificadorUphold, UPHOLD_SIGNATURES
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

# Modo de ejecución: siempre desactivados en producción
app.config["DEBUG"]   = False
app.config["TESTING"] = False

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
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "connect_args":   {"connect_timeout": 5},   # TCP timeout 5s en lugar de infinito
    "pool_pre_ping":  True,                      # descarta conexiones muertas del pool
    "pool_timeout":   10,                        # espera máx 10s por una conexión del pool
    "pool_recycle":   300,                       # recicla conexiones cada 5 min
}

# Tamaño máximo de payload global — corta uploads gigantes antes de llegar a disco.
# Los CSV válidos son <10 MB; los ficheros de asesoramiento tienen su propio check a 10 MB.
# Flask devuelve 413 automáticamente si se supera este límite.
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB

# Cookies de sesión seguras
# SESSION_COOKIE_SECURE: True en producción (FLASK_ENV=production en Railway).
# En desarrollo local (http://127.0.0.1:5050) Flask lo ignora automáticamente
# para localhost — si usas otro host de dev, quita la condición temporalmente.
_prod = os.environ.get("FLASK_ENV") == "production"
app.config["SESSION_COOKIE_SECURE"]   = _prod
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# Flask-Login "remember me" cookie — misma política que la cookie de sesión
app.config["REMEMBER_COOKIE_SECURE"]   = _prod
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"

# Duración máxima de la cookie de sesión permanente (red de seguridad por encima del check de 7d).
# session.permanent = True se establece al hacer login.
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=8)


# ── EXTENSIONES ───────────────────────────────
db.init_app(app)
bcrypt.init_app(app)
migrate = Migrate(app, db)

# ── RESEND (email) ────────────────────────────
resend.api_key = os.environ.get("RESEND_API_KEY", "")
_RESEND_FROM   = os.environ.get("RESEND_FROM_EMAIL", "noreply@marianosevilla.com")
_APP_BASE_URL  = os.environ.get("APP_BASE_URL", "https://www.marianosevilla.com")

# ── ADVISORY / STRIPE ────────────────────────
_STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
_STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
_ADVISORY_NOTIFY_EMAILS = [
    e.strip() for e in os.environ.get("FISCAL_ADVISORY_NOTIFY_EMAILS", "").split(",") if e.strip()
]
# Precios en céntimos. Configura en Railway env vars.
_ADVISORY_PRICES = {
    "revision_basica":   int(os.environ.get("FISCAL_ADVISORY_BASIC_PRICE",   "7900")),
    "revision_avanzada": int(os.environ.get("FISCAL_ADVISORY_ADVANCED_PRICE","14900")),
    "caso_complejo":     int(os.environ.get("FISCAL_ADVISORY_COMPLEX_PRICE", "4900")),
}
_ADVISORY_PRICE_LABELS = {
    "revision_basica":   "Revisión fiscal básica",
    "revision_avanzada": "Revisión fiscal avanzada",
    "caso_complejo":     "Valoración inicial — caso complejo",
}

FISCAL_ADVISOR_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("FISCAL_ADVISOR_EMAILS", "").split(",")
    if e.strip()
}

def _is_fiscal_advisor() -> bool:
    return (
        current_user.is_authenticated and (
            getattr(current_user, 'role', 'user') in ('admin', 'fiscal_advisor')
            or current_user.email.strip().lower() in FISCAL_ADVISOR_EMAILS
            or _is_admin()
        )
    )

_ADVISORY_UPLOAD_DIR = os.path.join(_BASE_DIR, "uploads", "advisory")
os.makedirs(_ADVISORY_UPLOAD_DIR, exist_ok=True)

_ALLOWED_ADVISORY_EXTENSIONS = {".csv", ".xlsx", ".pdf", ".jpg", ".jpeg", ".png"}
_MAX_ADVISORY_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

login_manager = LoginManager(app)

@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))

@login_manager.unauthorized_handler
def unauthorized():
    """JSON 401 para rutas API; redirect a /login/ para rutas de navegador."""
    if request.path.startswith("/api/"):
        return jsonify({"error": "Autenticación requerida"}), 401
    return redirect(f"/login/?next={request.path}")


# ── POLÍTICA DE EXPIRACIÓN DE SESIÓN ──────────────────────────────────────────
_SESSION_MAX_SECS         = 7 * 86_400   # 7 días absolutos desde el login
_SESSION_INACTIVITY_ADMIN = 4 * 3_600    # 4 h para administradores
_SESSION_INACTIVITY_USER  = 12 * 3_600   # 12 h para usuarios normales


def _expire_session() -> None:
    """Cierra la sesión activa y limpia todos los datos almacenados en la cookie.

    session.clear() debe ir ANTES de logout_user() para que Flask-Login pueda
    escribir el flag _remember:clear en la sesión ya vacía. Si se invierte el orden,
    session.clear() borra ese flag y la remember cookie no se elimina del navegador.
    """
    session.clear()
    logout_user()


def _session_expired_response():
    """401 JSON para rutas /api/*; redirect a /login/ para el resto."""
    if request.path.startswith("/api/"):
        return jsonify({"error": "Sesión expirada.", "expired": True}), 401
    return redirect("/login/?expired=1")


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

print("[BOOT] Iniciando bootstrap de base de datos...", flush=True)
try:
    with app.app_context():
        print("[BOOT] app_context OK. Llamando db.create_all()...", flush=True)
        db.create_all()
        print("[BOOT] db.create_all() completado. Iniciando ALTER TABLE...", flush=True)
        try:
            from sqlalchemy import text
            with db.engine.connect() as _conn:
                print("[BOOT] Conexión a DB obtenida. Ejecutando migraciones de emergencia...", flush=True)
                _conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP"
                ))
                _conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(150)"
                ))
                _conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user' NOT NULL"
                ))
                _conn.commit()
                print("[BOOT] ALTER TABLE completado sin errores.", flush=True)
        except Exception as _boot_err:
            print(f"[BOOT] ALTER TABLE falló (no crítico): {_boot_err}", flush=True)
    print("[BOOT] Bootstrap DB completado. Gunicorn listo para servir requests.", flush=True)
except Exception as _fatal_err:
    print(f"[BOOT] *** ERROR FATAL en bootstrap DB: {_fatal_err} ***", flush=True)
    print("[BOOT] La app arrancará sin bootstrap. Algunas tablas pueden no existir.", flush=True)


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
    # ── FASE 2A: telemetría estratégica (todas opcionales) ──
    fifo_operations: int   = None,
    fifo_swaps: int        = None,
    fifo_rendimientos: int = None,
    fifo_movimientos: int  = None,
    fifo_advertencias: int = None,
    fifo_desconocidas: int = None,
    resultado_neto: float  = None,
    ganancias_brutas: float = None,
    perdidas_brutas: float  = None,
    fiscal_years_str: str  = None,
):
    """Crea un registro FifoReport y devuelve su id. No lanza excepciones."""
    if not current_user.is_authenticated:
        return None
    try:
        report = FifoReport(
            user_id           = current_user.id,
            exchange          = exchange,
            fiscal_year       = fiscal_year,
            csv_rows          = csv_rows,
            distinct_assets   = distinct_assets,
            processing_ms     = processing_ms,
            status            = status,
            error_type        = error_type,
            fifo_operations   = fifo_operations,
            fifo_swaps        = fifo_swaps,
            fifo_rendimientos = fifo_rendimientos,
            fifo_movimientos  = fifo_movimientos,
            fifo_advertencias = fifo_advertencias,
            fifo_desconocidas = fifo_desconocidas,
            resultado_neto    = resultado_neto,
            ganancias_brutas  = ganancias_brutas,
            perdidas_brutas   = perdidas_brutas,
            fiscal_years_str  = fiscal_years_str,
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
    "uphold": {
        "exchange_id":      "uphold",
        "exchange_name":    "Uphold",
        "exchange_logo":    "U",
        "page_title":       "Informe FIFO Uphold para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el CSV de Uphold y calcula tus ganancias y pérdidas con FIFO obligatorio. Informe PDF listo para la declaración de la renta en España.",
        "page_canonical":   f"{_BASE_URL}/uphold",
        "page_og_title":    "Informe fiscal Uphold para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el CSV de Uphold y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Uphold — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Uphold para Hacienda",
        "hero_desc":        "Sube el CSV del historial de transacciones de Uphold y obtén el informe FIFO con tus ganancias y pérdidas patrimoniales. Los Brave Rewards (BAT) tributan como rendimientos del capital mobiliario (casilla 0033). Listo para la declaración de la renta.",
        "how_to": [
            {"title": "Exporta el CSV de transacciones desde Uphold",
             "desc":  "En tu cuenta de Uphold ve a Actividad → selecciona el rango completo → Exportar CSV. Descarga el fichero con todas tus transacciones."},
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

# ── BLOQUEO CONCURRENTE DE ANÁLISIS ───────────────────────────────────────────
# Set de user_ids con un análisis actualmente en proceso (en este worker).
# Evita que el mismo usuario lance varios análisis simultáneos.
# Aplica a todos los usuarios, incluidos admins (exentos del rate limit, no de esto).
# Sin Redis: protección por proceso; para cobertura multi-worker → FASE 2B.
_analisis_en_curso: set = set()
_analisis_lock = threading.Lock()


# ── WWW → APEX REDIRECT (301 permanente) ─────
# Solo actúa sobre www.marianosevilla.com; ignora Railway internos,
# localhost y cualquier otro host.
_WWW_HOST  = "www.marianosevilla.com"
_APEX_HOST = "marianosevilla.com"

@app.before_request
def redirect_www_to_apex():
    """Redirect canónico 301: www.marianosevilla.com → marianosevilla.com.

    Conserva path, query string y protocolo HTTPS.
    No toca ningún otro host (Railway, localhost, staging…).
    """
    host = request.host.lower().split(":")[0]   # quita puerto si lo hubiera
    if host != _WWW_HOST:
        return                                   # cualquier otro host → sin tocar

    # Construimos la URL de destino de forma explícita y segura
    qs = request.query_string.decode("utf-8")
    target = f"https://{_APEX_HOST}{request.path}"
    if qs:
        target = f"{target}?{qs}"
    return redirect(target, 301)


@app.before_request
def enforce_session_expiry():
    """Expiración de sesión por inactividad y por máximo absoluto.

    Normal: 12 h de inactividad · 7 días máximo desde el login.
    Admin:   4 h de inactividad · 7 días máximo desde el login.
    """
    if not current_user.is_authenticated:
        return

    now      = time.time()
    login_at = session.get("login_at")
    last_act = session.get("last_activity")

    # Sesiones creadas antes del deploy (sin timestamps): inicializar y dejar pasar.
    if login_at is None:
        session["login_at"]      = now
        session["last_activity"] = now
        return

    # Expiración absoluta: 7 días desde el login inicial.
    if now - login_at > _SESSION_MAX_SECS:
        _expire_session()
        return _session_expired_response()

    # Expiración por inactividad.
    limit = _SESSION_INACTIVITY_ADMIN if _is_admin() else _SESSION_INACTIVITY_USER
    if last_act is not None and now - last_act >= limit:
        _expire_session()
        return _session_expired_response()

    # Sesión válida: actualizar marca de actividad.
    session["last_activity"] = now


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
        "script-src 'self' 'unsafe-inline' https://challenges.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' https://challenges.cloudflare.com; "
        "frame-src https://challenges.cloudflare.com; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "          # bloquea Flash / plugins embebidos
        "upgrade-insecure-requests;"   # fuerza HTTPS en recursos embebidos
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
MAX_CSV_ROWS        = 100_000            # filas máximas permitidas por CSV (≈ 10 MB de datos reales)
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
    """Valida ejercicio: vacío, 'all', un año o varios años separados por coma."""
    if not ejercicio or ejercicio.strip().lower() == "all":
        return True, ""
    for part in ejercicio.split(","):
        part = part.strip()
        if not re.match(r"^\d{4}$", part):
            return False, "Formato de ejercicio fiscal inválido. Usa años de 4 dígitos separados por coma."
        año = int(part)
        if año < AÑO_MIN:
            return False, f"El ejercicio fiscal no puede ser anterior a {AÑO_MIN}."
        if año > AÑO_MAX:
            return False, f"El ejercicio fiscal no puede ser posterior a {AÑO_MAX}."
    return True, ""


def _años_seleccionados(ejercicio_str: str) -> set:
    """Devuelve set de años enteros, o vacío si ejercicio es 'all'/vacío (= sin filtro)."""
    if not ejercicio_str or ejercicio_str.strip().lower() == "all":
        return set()
    return {int(p.strip()) for p in ejercicio_str.split(",") if p.strip().isdigit()}


def _filtrar_motor_por_ejercicio(motor, ejercicio_str: str) -> None:
    """Filtra motor.resultados por los años seleccionados.
    El inventario FIFO (posicion_actual) no se modifica: el cálculo usa todo el histórico.
    """
    años = _años_seleccionados(ejercicio_str)
    if not años:
        return
    motor.resultados = [r for r in motor.resultados if r.fecha.year in años]


def _filtrar_bit2me_por_ejercicio(clasificador, ejercicio_str: str) -> None:
    """Filtra clasificador.resultados de Bit2Me por los años seleccionados."""
    años = _años_seleccionados(ejercicio_str)
    if not años:
        return
    clasificador.resultados = [
        r for r in clasificador.resultados
        if len(r.fecha_venta) >= 4 and int(r.fecha_venta[:4]) in años
    ]


def _filtrar_rendimientos_por_ejercicio(rendimientos: list, ejercicio_str: str) -> list:
    """Filtra rendimientos (staking, rebates…) por los años seleccionados.
    La fecha de cada rendimiento es una cadena tipo '2024-01-15 …'; se extrae el año de los 4 primeros chars.
    """
    años = _años_seleccionados(ejercicio_str)
    if not años:
        return rendimientos
    resultado = []
    for r in rendimientos:
        try:
            if int(str(r.fecha)[:4]) in años:
                resultado.append(r)
        except (ValueError, TypeError, AttributeError):
            resultado.append(r)  # si la fecha no es parseable, incluir por precaución
    return resultado


def _ejercicio_a_fiscal_year(ejercicio_str: str) -> int:
    """Extrae el primer año de ejercicio para logging (0 si vacío o 'all')."""
    if not ejercicio_str or ejercicio_str.strip().lower() == "all":
        return 0
    for p in ejercicio_str.split(","):
        p = p.strip()
        if p.isdigit() and len(p) == 4:
            return int(p)
    return 0


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
        "uphold":    UPHOLD_SIGNATURES,
    }
    nombres = {
        "binance":   "Binance",
        "bit2me":    "Bit2Me",
        "bitvavo":   "Bitvavo",
        "kraken":    "Kraken",
        "coinbase":  "Coinbase",
        "nexo":      "Nexo",
        "cryptocom": "Crypto.com",
        "uphold":    "Uphold",
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
    """Pipeline genérico: clasificador ya instanciado → motor FIFO + rendimientos + clasificador.
    Devuelve 3-tupla (motor, rendimientos, clasificador) para permitir extracción de telemetría
    (swaps totales, movimientos, desconocidas) que solo viven en el clasificador.
    """
    motor = _pipeline_motor(clasificador)
    rendimientos = clasificador.rendimientos if hasattr(clasificador, 'rendimientos') else []
    return motor, rendimientos, clasificador


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


def procesar_uphold(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorUphold(filepath).clasificar())


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
    """Convierte lista de rendimientos a formato JSON para la UI.
    Agrupa por (subtipo, activo) para que cada activo tenga su propia fila.
    """
    from collections import defaultdict
    por_tipo = defaultdict(lambda: {"cantidad": 0.0, "operaciones": 0, "valor_eur": 0.0})
    for r in rendimientos:
        key = (r.subtipo, r.activo)          # ← agrupamos por tipo Y activo
        por_tipo[key]["cantidad"] += r.cantidad
        por_tipo[key]["operaciones"] += 1
        por_tipo[key]["valor_eur"] += getattr(r, 'valor_eur', 0.0)
    return [
        {
            "subtipo": k[0],
            "activo": k[1],
            "cantidad": round(v["cantidad"], 6),
            "operaciones": v["operaciones"],
            "valor_eur": round(v["valor_eur"], 4),
        }
        for k, v in por_tipo.items()
    ]


# ── RUTAS ─────────────────────────────────────

@app.route("/healthz")
@limiter.exempt
def healthz():
    """Healthcheck mínimo: sin DB, sin sesión, sin Redis. Diagnóstico de arranque."""
    return {"ok": True, "service": "fiscal-cripto"}, 200


@app.route("/")
def landing():
    return send_from_directory("static", "landing.html")


@app.route("/fiscal")
@login_required
def fiscal():
    return render_template("tool.html", **_TOOL_GENERIC)


@app.route("/about", strict_slashes=False)
def about():
    return send_from_directory("static", "about.html")


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
        return redirect("/dashboard")
    return send_from_directory("static", "login.html")


@app.route("/signup/", strict_slashes=False)
def signup_page():
    """Página dedicada de registro."""
    if current_user.is_authenticated:
        return redirect("/dashboard")
    return send_from_directory("static", "signup.html")


@app.route("/auth/google")
@limiter.limit("20 per minute")
def auth_google():
    """Inicia el flujo OAuth con Google."""
    if not _google_oauth_enabled:
        return redirect("/login/?error=google_not_configured")
    redirect_uri = url_for("auth_google_callback", _external=True)
    return google_oauth.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
@limiter.limit("20 per minute")
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
    login_user(user, remember=False)
    session.permanent       = True
    session["login_at"]      = time.time()
    session["last_activity"] = time.time()
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


@app.route("/uphold")
@login_required
def page_uphold():
    return render_template("tool.html", **EXCHANGE_PAGES["uphold"])


@app.route("/api/analizar", methods=["POST"])
@login_required
@limiter.limit("3 per 10 minutes", exempt_when=_is_admin)
@limiter.limit("6 per hour",       exempt_when=_is_admin)
@limiter.limit("15 per day",       exempt_when=_is_admin)
def analizar():
    uid      = current_user.id
    tmp_path = None

    # ── bloqueo concurrente por usuario ──────────────────────────────────────
    # Aplica a todos los usuarios, incluidos admins (exentos del rate limit,
    # pero no de la protección de recursos).
    with _analisis_lock:
        if uid in _analisis_en_curso:
            return jsonify({
                "error": "Ya tienes un análisis en proceso. "
                         "Espera a que termine antes de lanzar otro."
            }), 409
        _analisis_en_curso.add(uid)
    # ─────────────────────────────────────────────────────────────────────────

    try:
        if "csv" not in request.files:
            return jsonify({"error": "No se recibió ningún fichero."}), 400

        archivo   = request.files["csv"]
        nombre    = _sanitizar_texto(request.form.get("nombre", ""))
        ejercicio = _sanitizar_texto(request.form.get("ejercicio", ""), max_len=40)  # "all" o "2024,2025"
        exchange  = _sanitizar_texto(request.form.get("exchange", "binance"), max_len=20).lower()

        # Validar exchange
        if exchange not in ("binance", "bit2me", "bitvavo", "kraken", "coinbase", "nexo", "cryptocom", "uphold"):
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

        # ── límite de filas ───────────────────────────────────────────────────
        if csv_rows > MAX_CSV_ROWS:
            return jsonify({
                "error": f"El CSV tiene demasiadas filas ({csv_rows:,}). "
                         f"El máximo permitido es {MAX_CSV_ROWS:,} filas."
            }), 400
        # ─────────────────────────────────────────────────────────────────────

        try:
            valido, error_msg = _validar_csv(tmp_path, exchange)
            if not valido:
                return jsonify({"error": error_msg}), 400

            rendimientos_json = []
            motor       = None   # MotorFIFO — asignado para todos los exchanges excepto bit2me
            clasificador = None  # clasificador original — para telemetría (swaps, movimientos, desconocidas)

            if exchange == "bit2me":
                clasificador, _r, _ops = procesar_bit2me(tmp_path)
                _filtrar_bit2me_por_ejercicio(clasificador, ejercicio)
                clasificador.rendimientos = _filtrar_rendimientos_por_ejercicio(
                    clasificador.rendimientos, ejercicio)
                resumen = clasificador.resumen_fiscal()
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
                    for res in clasificador.resultados
                ]
                advertencias = clasificador.advertencias
                posicion = []
                rendimientos_json = _rendimientos_a_json(clasificador.rendimientos)
                pdf_bytes = generar_pdf_bit2me(clasificador, nombre, ejercicio)

            elif exchange == "bitvavo":
                motor, rendimientos, clasificador = procesar_bitvavo(tmp_path)
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                advertencias = motor.advertencias
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Bitvavo", rendimientos)

            elif exchange == "kraken":
                motor, rendimientos, clasificador = procesar_kraken(tmp_path)
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                advertencias = motor.advertencias
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Kraken", rendimientos)

            elif exchange == "coinbase":
                motor, rendimientos, clasificador = procesar_coinbase(tmp_path)
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                advertencias = motor.advertencias
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Coinbase", rendimientos)

            elif exchange == "nexo":
                motor, rendimientos, clasificador = procesar_nexo(tmp_path)
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                advertencias = motor.advertencias
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Nexo", rendimientos)

            elif exchange == "cryptocom":
                motor, rendimientos, clasificador = procesar_cryptocom(tmp_path)
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                advertencias = motor.advertencias
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Crypto.com", rendimientos)

            elif exchange == "uphold":
                motor, rendimientos, clasificador = procesar_uphold(tmp_path)
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                # Uphold no provee FMV en EUR: las advertencias fiscales viven en el clasificador
                # (el motor no las genera porque siempre hay inventario previo de compras EUR).
                # Fusionamos ambas listas para que aparezcan en la UI y en el PDF.
                advertencias = motor.advertencias + (clasificador.advertencias if clasificador else [])
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Uphold", rendimientos)

            else:  # binance — auto-detectar formato
                if _detectar_formato_binance(tmp_path) == "tx":
                    _clasificador_binance = ClasificadorBinanceTx(tmp_path).clasificar()
                    _clasificador_stats   = _clasificador_binance.resumen()
                    motor, rendimientos, clasificador = procesar_con_fifo(_clasificador_binance)
                else:
                    motor, rendimientos, clasificador = procesar_binance(tmp_path)
                    _clasificador_stats  = None
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                advertencias = motor.advertencias
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Binance", rendimientos,
                                        clasificador_stats=_clasificador_stats)

            processing_ms   = int((time.time() - t_start) * 1000)
            distinct_assets = len({op["activo"] for op in operaciones}) if operaciones else 0

            # ── FASE 2A: extraer telemetría estratégica ──────────────────────────
            # Fuente primaria: el clasificador (vive en memoria durante el procesamiento).
            # Para bit2me: clasificador es ClasificadorBit2Me (tiene movimientos, no swaps/desconocidas).
            # Para motor-based: clasificador es el clasificador del exchange correspondiente.
            _adv_list = advertencias if isinstance(advertencias, list) else []

            # fifo_operations: ventas+swaps que generaron resultado fiscal
            _tel_ops  = resumen.get("operaciones_con_resultado", len(operaciones))

            # fifo_swaps: todos los swaps detectados en el CSV (no solo los con resultado FIFO)
            # bit2me no tiene lista separada → fallback a conteo en operaciones
            _tel_swaps = (
                len(clasificador.swaps)
                if clasificador is not None and hasattr(clasificador, 'swaps')
                else sum(1 for op in operaciones if op.get("tipo") == "swap")
            )

            # fifo_rendimientos: staking, rewards, rebates, intereses
            _tel_rend = len(rendimientos_json)

            # fifo_movimientos: depósitos, retiros, movimientos internos sin impacto fiscal
            _tel_mov = len(clasificador.movimientos) if clasificador is not None and hasattr(clasificador, 'movimientos') else 0

            # fifo_advertencias: warnings del motor (inventario insuficiente, valoración manual)
            _tel_adv = len(_adv_list)

            # fifo_desconocidas: filas CSV no clasificadas por el clasificador
            # bit2me no trackea desconocidas → 0
            _tel_desc = len(clasificador.desconocidas) if clasificador is not None and hasattr(clasificador, 'desconocidas') else 0

            # métricas fiscales (numéricas, en EUR)
            _tel_neto = resumen.get("resultado_neto")
            _tel_gan  = resumen.get("ganancias_brutas")
            _tel_per  = resumen.get("perdidas_brutas")

            # ejercicio fiscal exacto tal como lo envió el usuario
            _tel_years = (ejercicio or "")[:50]
            # ────────────────────────────────────────────────────────────────────

            pdf_tmp = tmp_path.replace(".csv", ".pdf")
            with open(pdf_tmp, "wb") as f:
                f.write(pdf_bytes)

            report_id = _registrar_informe(
                exchange          = exchange,
                fiscal_year       = _ejercicio_a_fiscal_year(ejercicio),
                csv_rows          = csv_rows,
                distinct_assets   = distinct_assets,
                processing_ms     = processing_ms,
                fifo_operations   = _tel_ops,
                fifo_swaps        = _tel_swaps,
                fifo_rendimientos = _tel_rend,
                fifo_movimientos  = _tel_mov,
                fifo_advertencias = _tel_adv,
                fifo_desconocidas = _tel_desc,
                resultado_neto    = _tel_neto,
                ganancias_brutas  = _tel_gan,
                perdidas_brutas   = _tel_per,
                fiscal_years_str  = _tel_years,
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
                fiscal_year     = _ejercicio_a_fiscal_year(ejercicio),
                csv_rows        = csv_rows,
                distinct_assets = 0,
                processing_ms   = int((time.time() - t_start) * 1000),
                status          = "failed",
                error_type      = type(e).__name__,
            )
            return jsonify({"error": _error_amigable(e)}), 500

    finally:
        # Siempre liberar el bloqueo y limpiar el fichero temporal,
        # independientemente de cómo terminó la petición (éxito, error, early return).
        with _analisis_lock:
            _analisis_en_curso.discard(uid)
        if tmp_path:
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
    session.permanent       = True
    session["login_at"]      = time.time()
    session["last_activity"] = time.time()

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
@limiter.limit("10 per minute")
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
@limiter.limit("5 per hour")
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

@app.route("/home2")
def home2_page():
    return redirect("/", 301)


@app.route("/robots.txt")
def robots():
    return send_from_directory("static", "robots.txt", mimetype="text/plain")


@app.route("/llms.txt")
def llms():
    return send_from_directory("static", "llms.txt", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory("static", "sitemap.xml", mimetype="application/xml")


@app.route("/como-funciona", strict_slashes=False)
def como_funciona():
    return send_from_directory("static", "como-funciona.html")


@app.route("/modelo-721-criptomonedas", strict_slashes=False)
def modelo_721_criptomonedas():
    return send_from_directory("static", "modelo-721-criptomonedas.html")


@app.route("/faq", strict_slashes=False)
def faq():
    return send_from_directory("static", "faq.html")


@app.route("/contacto", strict_slashes=False)
def contacto():
    return send_from_directory("static", "contacto.html")


# ── CONTACT FORM API ──────────────────────────

_TIPOS_VALIDOS = {"soporte_tecnico", "informe_fifo", "asistencia_fiscal", "error_csv", "colaboraciones", "otro"}
_TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET_KEY", "")
_CONTACT_TO_EMAIL = os.environ.get("CONTACT_TO_EMAIL", "colab.marianosevilla@gmail.com")


def _verify_turnstile(token: str, remote_ip: str) -> bool:
    """Verifica el token de Cloudflare Turnstile. Devuelve True si es válido."""
    if not _TURNSTILE_SECRET:
        return True  # sin clave configurada, omitir verificación
    if not token:
        return False
    import urllib.request
    import urllib.parse
    import json as _json
    data = urllib.parse.urlencode({"secret": _TURNSTILE_SECRET, "response": token, "remoteip": remote_ip}).encode()
    try:
        with urllib.request.urlopen("https://challenges.cloudflare.com/turnstile/v0/siteverify", data, timeout=5) as r:
            result = _json.loads(r.read())
            return bool(result.get("success"))
    except Exception:
        return False


@app.route("/api/contacto", methods=["POST"])
@limiter.limit("5 per 15 minutes")
def api_contacto():
    data = request.get_json(silent=True) or {}

    # honeypot
    if data.get("website", ""):
        return jsonify({"ok": True})  # silently discard

    nombre        = (data.get("nombre") or "").strip()
    email_val     = (data.get("email") or "").strip()
    tipo_consulta = (data.get("tipo_consulta") or "").strip()
    mensaje       = (data.get("mensaje") or "").strip()
    ts_token      = data.get("ts_token", "")

    # validación backend
    if not nombre or len(nombre) > 80:
        return jsonify({"error": "Nombre inválido."}), 400
    if not email_val or len(email_val) > 254 or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_val):
        return jsonify({"error": "Email inválido."}), 400
    if tipo_consulta not in _TIPOS_VALIDOS:
        return jsonify({"error": "Tipo de consulta inválido."}), 400
    if len(mensaje) < 20 or len(mensaje) > 3000:
        return jsonify({"error": "El mensaje debe tener entre 20 y 3000 caracteres."}), 400

    remote_ip = request.remote_addr or ""

    # Turnstile
    if not _verify_turnstile(ts_token, remote_ip):
        return jsonify({"error": "Verificación de seguridad fallida. Recarga la página e inténtalo de nuevo."}), 400

    # guardar en DB
    try:
        contacto_row = Contacto(
            nombre=nombre,
            email=email_val,
            tipo_consulta=tipo_consulta,
            mensaje=mensaje,
            ip=remote_ip[:45],
            user_agent=(request.headers.get("User-Agent") or "")[:500],
        )
        db.session.add(contacto_row)
        db.session.commit()
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Error interno. Inténtalo de nuevo más tarde."}), 500

    # enviar email de notificación (no bloquea si falla)
    try:
        if resend.api_key:
            resend.Emails.send({
                "from": _RESEND_FROM,
                "to": [_CONTACT_TO_EMAIL],
                "subject": f"[Contacto] {tipo_consulta} — {nombre}",
                "text": (
                    f"Nuevo mensaje de contacto\n\n"
                    f"Nombre: {nombre}\n"
                    f"Email: {email_val}\n"
                    f"Tipo: {tipo_consulta}\n"
                    f"IP: {remote_ip}\n\n"
                    f"Mensaje:\n{mensaje}"
                ),
            })
    except Exception:
        pass  # el mensaje ya está en DB; el envío de email no es crítico

    return jsonify({"ok": True})


@app.route("/api/stats")
@login_required
def api_stats():
    if not _is_admin():
        return jsonify({"error": "Acceso denegado."}), 403

    try:
        return _api_stats_data()
    except Exception as e:
        traceback.print_exc()   # solo a logs — nunca al cliente
        return jsonify({"error": "Error interno al cargar estadísticas."}), 500


def _api_stats_data():
    from collections import defaultdict

    now = datetime.utcnow()
    treinta_dias_atras = now - timedelta(days=30)
    siete_dias_atras   = now - timedelta(days=7)
    veinticuatro_h     = now - timedelta(hours=24)
    hoy_inicio         = datetime(now.year, now.month, now.day)

    # Ventana de 6 meses: primer día del mes de hace 5 meses
    m = now.month - 5
    y = now.year
    if m <= 0:
        m += 12
        y -= 1
    seis_meses_atras = datetime(y, m, 1)

    # Helper: enmascarar email para privacidad
    def _mask_email(email):
        if not email:
            return "***"
        p = email.split("@")
        return (p[0][:2] + "***@" + p[1]) if len(p) == 2 else "***"

    def _daily_counts_from_ts(ts_list, days=7):
        """Lista de (datetime,) → array de 'days' conteos diarios, del más antiguo al más reciente."""
        bkt = defaultdict(int)
        for (ts,) in ts_list:
            if ts:
                bkt[ts.strftime("%Y-%m-%d")] += 1
        result = []
        for i in range(days - 1, -1, -1):
            day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            result.append(bkt.get(day, 0))
        return result

    # ── USUARIOS — SQL aggregations ──────────────────────────────────────────
    total_users   = db.session.query(func.count(User.id)).scalar() or 0
    verified      = db.session.query(func.count(User.id)).filter(User.email_verified_at.isnot(None)).scalar() or 0
    activos_30d   = db.session.query(func.count(User.id)).filter(User.last_login >= treinta_dias_atras).scalar() or 0
    plan_free     = db.session.query(func.count(User.id)).filter(User.plan == "free").scalar() or 0
    plan_pro      = db.session.query(func.count(User.id)).filter(User.plan == "pro").scalar() or 0
    con_informes  = db.session.query(func.count(func.distinct(FifoReport.user_id))).scalar() or 0
    usuarios_hoy  = db.session.query(func.count(User.id)).filter(User.created_at >= hoy_inicio).scalar() or 0

    # Registros por mes — cargamos solo created_at (evita traer objetos completos)
    u_ts = db.session.query(User.created_at).filter(User.created_at >= seis_meses_atras).all()
    u_bucket = defaultdict(int)
    for (ts,) in u_ts:
        if ts:
            u_bucket[ts.strftime("%Y-%m")] += 1
    usuarios_por_mes = [{"mes": k, "total": v} for k, v in sorted(u_bucket.items())]

    u_7d_raw = db.session.query(User.created_at).filter(User.created_at >= siete_dias_atras).all()

    # ── INFORMES FIFO — SQL aggregations ─────────────────────────────────────
    total_inf   = db.session.query(func.count(FifoReport.id)).scalar() or 0
    gen         = db.session.query(func.count(FifoReport.id)).filter(FifoReport.status == "generated").scalar() or 0
    fallidos    = total_inf - gen
    descargados = db.session.query(func.count(FifoReport.id)).filter(
        FifoReport.status == "generated", FifoReport.downloaded_at.isnot(None)
    ).scalar() or 0
    informes_hoy = db.session.query(func.count(FifoReport.id)).filter(
        FifoReport.status == "generated", FifoReport.created_at >= hoy_inicio
    ).scalar() or 0

    avg_ms   = db.session.query(func.avg(FifoReport.processing_ms)).filter(FifoReport.status == "generated").scalar()
    avg_rows = db.session.query(func.avg(FifoReport.csv_rows)).filter(FifoReport.status == "generated").scalar()

    # Power users
    power_1k = db.session.query(func.count(func.distinct(FifoReport.user_id))).filter(
        FifoReport.status == "generated", FifoReport.csv_rows >= 1000
    ).scalar() or 0
    power_10k = db.session.query(func.count(func.distinct(FifoReport.user_id))).filter(
        FifoReport.status == "generated", FifoReport.csv_rows >= 10000
    ).scalar() or 0

    por_exchange_raw = (
        db.session.query(FifoReport.exchange, func.count(FifoReport.id).label("c"))
        .filter(FifoReport.status == "generated")
        .group_by(FifoReport.exchange)
        .order_by(func.count(FifoReport.id).desc())
        .all()
    )
    por_ejercicio_raw = (
        db.session.query(FifoReport.fiscal_year, func.count(FifoReport.id).label("c"))
        .filter(FifoReport.status == "generated")
        .group_by(FifoReport.fiscal_year)
        .order_by(FifoReport.fiscal_year.desc())
        .all()
    )

    # Distribución por volumen de csv_rows
    rows_all = db.session.query(FifoReport.csv_rows).filter(
        FifoReport.status == "generated", FifoReport.csv_rows.isnot(None)
    ).all()
    vol_bkt = defaultdict(int)
    for (r,) in rows_all:
        if   r < 50:    vol_bkt["< 50"] += 1
        elif r < 250:   vol_bkt["50–250"] += 1
        elif r < 1000:  vol_bkt["250–1.000"] += 1
        elif r < 10000: vol_bkt["1.000–10.000"] += 1
        else:           vol_bkt["> 10.000"] += 1
    VOL_ORDER = ["< 50", "50–250", "250–1.000", "1.000–10.000", "> 10.000"]
    por_volumen = [{"rango": k, "total": vol_bkt.get(k, 0)} for k in VOL_ORDER]

    # TOP 5 usuarios por informes (emails enmascarados)
    top5_raw = (
        db.session.query(FifoReport.user_id, func.count(FifoReport.id).label("c"))
        .filter(FifoReport.status == "generated")
        .group_by(FifoReport.user_id)
        .order_by(func.count(FifoReport.id).desc())
        .limit(5)
        .all()
    )
    uids = [r.user_id for r in top5_raw]
    u_email_map = {u.id: u.email for u in User.query.filter(User.id.in_(uids)).all()} if uids else {}
    top5 = [{"user_id": r.user_id, "email_mask": _mask_email(u_email_map.get(r.user_id)), "total": r.c} for r in top5_raw]

    # Tipos de error más frecuentes
    por_error_raw = (
        db.session.query(FifoReport.error_type, func.count(FifoReport.id).label("c"))
        .filter(FifoReport.status == "failed")
        .group_by(FifoReport.error_type)
        .order_by(func.count(FifoReport.id).desc())
        .limit(10)
        .all()
    )
    por_error = [{"tipo": r.error_type or "sin clasificar", "total": r.c} for r in por_error_raw]

    # Informes generados por mes (últimos 6 meses)
    inf_ts = db.session.query(FifoReport.created_at).filter(
        FifoReport.status == "generated", FifoReport.created_at >= seis_meses_atras
    ).all()
    inf_mes_bkt = defaultdict(int)
    for (ts,) in inf_ts:
        if ts:
            inf_mes_bkt[ts.strftime("%Y-%m")] += 1
    informes_por_mes = [{"mes": k, "total": v} for k, v in sorted(inf_mes_bkt.items())]

    inf_7d_raw = db.session.query(FifoReport.created_at).filter(
        FifoReport.status == "generated", FifoReport.created_at >= siete_dias_atras
    ).all()

    # ── CONTACTOS ─────────────────────────────────────────────────────────────
    total_c    = db.session.query(func.count(Contacto.id)).scalar() or 0
    c_nuevos   = db.session.query(func.count(Contacto.id)).filter(Contacto.estado == "nuevo").scalar() or 0
    c_resp     = db.session.query(func.count(Contacto.id)).filter(Contacto.estado == "respondido").scalar() or 0
    por_tipo_c = (
        db.session.query(Contacto.tipo_consulta, func.count(Contacto.id).label("c"))
        .group_by(Contacto.tipo_consulta)
        .order_by(func.count(Contacto.id).desc())
        .all()
    )

    # ── ASESORAMIENTO FISCAL ──────────────────────────────────────────────────
    PAID_ST  = {"paid_received", "under_review", "waiting_user_info", "in_progress", "completed"}
    SL       = FiscalAdvisoryRequest.STATUS_LABELS
    SVL      = FiscalAdvisoryRequest.SERVICE_LABELS

    total_adv   = db.session.query(func.count(FiscalAdvisoryRequest.id)).scalar() or 0
    adv_pagadas = db.session.query(func.count(FiscalAdvisoryRequest.id)).filter(
        FiscalAdvisoryRequest.status.in_(list(PAID_ST))
    ).scalar() or 0
    adv_pend    = db.session.query(func.count(FiscalAdvisoryRequest.id)).filter(
        FiscalAdvisoryRequest.status == "pending_payment"
    ).scalar() or 0
    adv_sin_asig = db.session.query(func.count(FiscalAdvisoryRequest.id)).filter(
        FiscalAdvisoryRequest.assigned_to.is_(None),
        FiscalAdvisoryRequest.status.in_(list(PAID_ST))
    ).scalar() or 0

    ing_cents = db.session.query(func.sum(FiscalAdvisoryRequest.amount_paid)).filter(
        FiscalAdvisoryRequest.amount_paid.isnot(None)
    ).scalar() or 0

    por_estado_adv = (
        db.session.query(FiscalAdvisoryRequest.status, func.count(FiscalAdvisoryRequest.id).label("c"))
        .group_by(FiscalAdvisoryRequest.status)
        .order_by(func.count(FiscalAdvisoryRequest.id).desc())
        .all()
    )
    por_servicio_adv = (
        db.session.query(FiscalAdvisoryRequest.service_type, func.count(FiscalAdvisoryRequest.id).label("c"))
        .group_by(FiscalAdvisoryRequest.service_type)
        .order_by(func.count(FiscalAdvisoryRequest.id).desc())
        .all()
    )
    ing_sv_raw = (
        db.session.query(FiscalAdvisoryRequest.service_type,
                         func.sum(FiscalAdvisoryRequest.amount_paid).label("s"))
        .filter(FiscalAdvisoryRequest.amount_paid.isnot(None))
        .group_by(FiscalAdvisoryRequest.service_type)
        .order_by(func.sum(FiscalAdvisoryRequest.amount_paid).desc())
        .all()
    )

    # Ingresos por mes — solo las 2 columnas necesarias
    adv_mes_raw = db.session.query(
        FiscalAdvisoryRequest.created_at, FiscalAdvisoryRequest.amount_paid
    ).filter(
        FiscalAdvisoryRequest.amount_paid.isnot(None),
        FiscalAdvisoryRequest.created_at >= seis_meses_atras
    ).all()
    ing_mes_bkt = defaultdict(float)
    for ts, amount in adv_mes_raw:
        if ts:
            ing_mes_bkt[ts.strftime("%Y-%m")] += (amount or 0) / 100.0

    # ── ERRORES ───────────────────────────────────────────────────────────────
    errores_24h = db.session.query(func.count(FifoReport.id)).filter(
        FifoReport.status == "failed", FifoReport.created_at >= veinticuatro_h
    ).scalar() or 0

    err_ts = db.session.query(FifoReport.created_at).filter(
        FifoReport.status == "failed", FifoReport.created_at >= seis_meses_atras
    ).all()
    err_bkt = defaultdict(int)
    for (ts,) in err_ts:
        if ts:
            err_bkt[ts.strftime("%Y-%m")] += 1
    errores_por_mes = [{"mes": k, "total": v} for k, v in sorted(err_bkt.items())]

    err_7d_raw = db.session.query(FifoReport.created_at).filter(
        FifoReport.status == "failed", FifoReport.created_at >= siete_dias_atras
    ).all()

    err_detail_raw = (
        db.session.query(FifoReport.created_at, FifoReport.exchange, FifoReport.user_id)
        .filter(FifoReport.status == "failed")
        .order_by(FifoReport.created_at.desc())
        .limit(100)
        .all()
    )
    err_uids  = list({r.user_id for r in err_detail_raw})
    err_u_map = {u.id: u.email for u in User.query.filter(User.id.in_(err_uids)).all()} if err_uids else {}
    errores_detalle = [{
        "fecha":    r.created_at.strftime("%Y-%m-%d %H:%M"),
        "exchange": r.exchange,
        "usuario":  _mask_email(err_u_map.get(r.user_id)),
    } for r in err_detail_raw]

    # ── EXCHANGE MÁS PROBLEMÁTICO ─────────────────────────────────────────────
    exc_gen_map  = {r.exchange: r.c for r in por_exchange_raw}
    exc_fail_raw = (
        db.session.query(FifoReport.exchange, func.count(FifoReport.id).label("c"))
        .filter(FifoReport.status == "failed")
        .group_by(FifoReport.exchange)
        .all()
    )
    exc_mas_prob     = None
    exc_mas_prob_pct = 0.0
    for r in exc_fail_raw:
        total_exc = exc_gen_map.get(r.exchange, 0) + r.c
        if total_exc >= 3:
            rate = round(r.c / total_exc * 100, 1)
            if rate > exc_mas_prob_pct:
                exc_mas_prob_pct = rate
                exc_mas_prob = r.exchange

    # ── FASE 2B: COMPLEJIDAD Y SEGMENTOS ─────────────────────────────────────
    # Comprobación de migración: si las columnas nuevas aún no existen en la DB
    # (migración pendiente), se devuelven ceros en lugar de un error 500.
    # Esto protege /stats ante cualquier deploy con migración pendiente.
    _gen_filter = FifoReport.status == "generated"
    try:
        db.session.execute(text("SELECT fifo_swaps FROM fifo_reports LIMIT 0"))
        _tel_ok = True
    except Exception:
        db.session.rollback()
        _tel_ok = False

    if _tel_ok:
        avg_swaps_raw       = db.session.query(func.avg(FifoReport.fifo_swaps)).filter(
            _gen_filter, FifoReport.fifo_swaps.isnot(None)).scalar()
        avg_adv_raw         = db.session.query(func.avg(FifoReport.fifo_advertencias)).filter(
            _gen_filter, FifoReport.fifo_advertencias.isnot(None)).scalar()
        avg_rend_raw        = db.session.query(func.avg(FifoReport.fifo_rendimientos)).filter(
            _gen_filter, FifoReport.fifo_rendimientos.isnot(None)).scalar()

        informes_multi_year = db.session.query(func.count(FifoReport.id)).filter(
            _gen_filter,
            FifoReport.fiscal_years_str.isnot(None),
            (FifoReport.fiscal_years_str.contains(",") | (FifoReport.fiscal_years_str == "all"))
        ).scalar() or 0

        informes_con_adv    = db.session.query(func.count(FifoReport.id)).filter(
            _gen_filter, FifoReport.fifo_advertencias > 0
        ).scalar() or 0

        # "complejo" = tiene al menos 1 advertencia de inventario O ≥10 swaps
        informes_complejos  = db.session.query(func.count(FifoReport.id)).filter(
            _gen_filter,
            (FifoReport.fifo_advertencias > 0) | (FifoReport.fifo_swaps >= 10)
        ).scalar() or 0

        informes_gt_1k_ops  = db.session.query(func.count(FifoReport.id)).filter(
            _gen_filter, FifoReport.fifo_operations >= 1000
        ).scalar() or 0
        informes_gt_10k_ops = db.session.query(func.count(FifoReport.id)).filter(
            _gen_filter, FifoReport.fifo_operations >= 10000
        ).scalar() or 0

        exc_complexity_raw = (
            db.session.query(
                FifoReport.exchange,
                func.avg(FifoReport.fifo_advertencias).label("avg_adv"),
                func.avg(FifoReport.fifo_swaps).label("avg_swaps"),
                func.count(FifoReport.id).label("total"),
            )
            .filter(_gen_filter, FifoReport.fifo_advertencias.isnot(None))
            .group_by(FifoReport.exchange)
            .order_by(func.avg(FifoReport.fifo_advertencias).desc())
            .all()
        )
        exc_complexity = [
            {
                "exchange":  r.exchange,
                "avg_adv":   round(r.avg_adv or 0, 2),
                "avg_swaps": round(r.avg_swaps or 0, 2),
                "total":     r.total,
            }
            for r in exc_complexity_raw
        ]

        # ── SEGMENTOS DE USUARIOS PREMIUM ─────────────────────────────────────
        # HIGH VALUE: csv_rows ≥ 5000 OR fifo_swaps ≥ 50 OR fifo_advertencias ≥ 10
        usuarios_high_value = db.session.query(
            func.count(func.distinct(FifoReport.user_id))
        ).filter(
            _gen_filter,
            (FifoReport.csv_rows >= 5000) |
            (FifoReport.fifo_swaps >= 50) |
            (FifoReport.fifo_advertencias >= 10)
        ).scalar() or 0

        # MUY COMPLEJO: fifo_advertencias ≥ 100 OR fifo_swaps ≥ 250
        usuarios_muy_complejos = db.session.query(
            func.count(func.distinct(FifoReport.user_id))
        ).filter(
            _gen_filter,
            (FifoReport.fifo_advertencias >= 100) | (FifoReport.fifo_swaps >= 250)
        ).scalar() or 0

        # MULTI-EXCHANGE: usuarios con ≥ 2 exchanges distintos
        _multi_exc_sub = (
            db.session.query(FifoReport.user_id)
            .filter(_gen_filter)
            .group_by(FifoReport.user_id)
            .having(func.count(func.distinct(FifoReport.exchange)) >= 2)
            .subquery()
        )
        usuarios_multi_exchange = db.session.query(func.count()).select_from(_multi_exc_sub).scalar() or 0

        # MULTI-YEAR: fiscal_years_str contiene ',' o es 'all'
        usuarios_multi_year = db.session.query(
            func.count(func.distinct(FifoReport.user_id))
        ).filter(
            _gen_filter,
            FifoReport.fiscal_years_str.isnot(None),
            (FifoReport.fiscal_years_str.contains(",") | (FifoReport.fiscal_years_str == "all"))
        ).scalar() or 0

    else:
        # Migración pendiente — devolver ceros, sin error 500
        avg_swaps_raw = avg_adv_raw = avg_rend_raw = None
        informes_multi_year = informes_con_adv = informes_complejos = 0
        informes_gt_1k_ops  = informes_gt_10k_ops = 0
        exc_complexity = []
        usuarios_high_value = usuarios_muy_complejos = 0
        usuarios_multi_exchange = usuarios_multi_year = 0

    # ── RESPUESTA JSON ────────────────────────────────────────────────────────
    return jsonify({
        "meta": {
            "informes_hoy":  informes_hoy,
            "usuarios_hoy":  usuarios_hoy,
            "errores_24h":   errores_24h,
            "exchange_mas_problematico": {
                "exchange":   exc_mas_prob or "N/A",
                "tasa_error": exc_mas_prob_pct,
            },
        },
        "sparklines": {
            "informes_7d": _daily_counts_from_ts(inf_7d_raw),
            "usuarios_7d": _daily_counts_from_ts(u_7d_raw),
            "errores_7d":  _daily_counts_from_ts(err_7d_raw),
        },
        "usuarios": {
            "total":            total_users,
            "verificados":      verified,
            "sin_verificar":    total_users - verified,
            "con_informes":     con_informes,
            "sin_informes":     total_users - con_informes,
            "ratio_activacion": round(con_informes / total_users * 100, 1) if total_users else 0.0,
            "activos_30d":      activos_30d,
            "free":             plan_free,
            "pro":              plan_pro,
            "por_mes":          usuarios_por_mes,
        },
        "informes": {
            "total":             total_inf,
            "generados":         gen,
            "fallidos":          fallidos,
            "descargados":       descargados,
            "tasa_descarga":     round(descargados / gen * 100, 1) if gen else 0.0,
            "avg_processing_ms": int(avg_ms or 0),
            "avg_csv_rows":      int(avg_rows or 0),
            "power_1k":          power_1k,
            "power_10k":         power_10k,
            "avg_per_user":      round(gen / con_informes, 1) if con_informes else 0.0,
            "por_exchange":      [{"exchange": r.exchange, "total": r.c} for r in por_exchange_raw],
            "por_ejercicio":     [{"ejercicio": r.fiscal_year, "total": r.c} for r in por_ejercicio_raw],
            "por_volumen":       por_volumen,
            "por_mes":           informes_por_mes,
            "top_usuarios":      top5,
            "por_error_type":    por_error,
        },
        "contactos": {
            "total":       total_c,
            "nuevos":      c_nuevos,
            "respondidos": c_resp,
            "por_tipo":    [{"tipo": r.tipo_consulta, "total": r.c} for r in por_tipo_c],
        },
        "asesoramiento": {
            "total":                 total_adv,
            "pagadas":               adv_pagadas,
            "pendientes_pago":       adv_pend,
            "sin_asignar":           adv_sin_asig,
            "conversion_pct":        round(adv_pagadas / total_adv * 100, 1) if total_adv else 0.0,
            "ingresos_total_eur":    round(ing_cents / 100.0, 2),
            "por_estado":            [{"estado": r.status, "label": SL.get(r.status, r.status), "total": r.c} for r in por_estado_adv],
            "por_servicio":          [{"servicio": r.service_type, "label": SVL.get(r.service_type, r.service_type), "total": r.c} for r in por_servicio_adv],
            "ingresos_por_servicio": [{"label": SVL.get(r.service_type, r.service_type), "ingresos": round((r.s or 0) / 100.0, 2)} for r in ing_sv_raw],
            "ingresos_por_mes":      [{"mes": k, "ingresos": round(v, 2)} for k, v in sorted(ing_mes_bkt.items())],
        },
        "errores": {
            "por_mes":  errores_por_mes,
            "detalle":  errores_detalle,
        },
        "complejidad": {
            "avg_swaps":           round(avg_swaps_raw or 0, 2),
            "avg_advertencias":    round(avg_adv_raw   or 0, 2),
            "avg_rendimientos":    round(avg_rend_raw  or 0, 2),
            "informes_multi_year": informes_multi_year,
            "informes_con_adv":    informes_con_adv,
            "informes_complejos":  informes_complejos,
            "tasa_complejidad":    round(informes_complejos / gen * 100, 1) if gen else 0.0,
            "gt_1k_ops":           informes_gt_1k_ops,
            "gt_10k_ops":          informes_gt_10k_ops,
            "por_exchange":        exc_complexity,
        },
        "segmentos": {
            "high_value":      usuarios_high_value,
            "muy_complejos":   usuarios_muy_complejos,
            "multi_exchange":  usuarios_multi_exchange,
            "multi_year":      usuarios_multi_year,
        },
    })


@app.errorhandler(429)
def ratelimit_error(e):
    return jsonify({
        "error": "Has alcanzado el límite de análisis. Por favor espera 10 minutos antes de intentarlo de nuevo."
    }), 429


@app.errorhandler(413)
def payload_too_large(e):
    return jsonify({"error": "El fichero supera el tamaño máximo permitido (15 MB)."}), 413


# ── ADVISORY ROUTES ──────────────────────────

@app.route("/asesoramiento-fiscal-criptomonedas", strict_slashes=False)
def advisory_landing():
    return send_from_directory("static", "asesoramiento-fiscal.html")

@app.route("/pedir-asesoramiento-fiscal", strict_slashes=False)
@login_required
def advisory_request_page():
    return send_from_directory("static", "pedir-asesoramiento.html")

@app.route("/asesoramiento-fiscal-confirmado", strict_slashes=False)
def advisory_confirmed():
    return send_from_directory("static", "asesoramiento-confirmado.html")

@app.route("/asesoramiento-fiscal-cancelado", strict_slashes=False)
def advisory_cancelled():
    return send_from_directory("static", "asesoramiento-cancelado.html")

@app.route("/admin/asesoramiento", strict_slashes=False)
@login_required
def admin_advisory_page():
    if not _is_fiscal_advisor():
        return redirect("/dashboard")
    return send_from_directory("static", "admin-asesoramiento.html")


# ── ADVISORY API ─────────────────────────────

@app.route("/api/asesoramiento/precios")
def advisory_prices():
    """Devuelve los precios públicos del servicio."""
    return jsonify({
        k: {"label": _ADVISORY_PRICE_LABELS[k], "amount_cents": v, "amount_eur": v / 100}
        for k, v in _ADVISORY_PRICES.items()
    })


@app.route("/api/asesoramiento/solicitar", methods=["POST"])
@login_required
@limiter.limit("3 per hour")
def advisory_solicitar():
    """Crea una solicitud pending_payment y devuelve la URL de Stripe Checkout."""
    if not _stripe_available or not _STRIPE_SECRET_KEY:
        return jsonify({"error": "El sistema de pagos no está configurado. Contacta con nosotros directamente."}), 503

    data = request.get_json(silent=True) or {}

    # Validaciones
    service_type = (data.get("service_type") or "").strip()
    if service_type not in _ADVISORY_PRICES:
        return jsonify({"error": "Tipo de servicio inválido."}), 400

    full_name = _sanitizar_texto(data.get("full_name") or "", max_len=150)
    email_val = (data.get("email") or "").strip().lower()
    if not full_name:
        return jsonify({"error": "El nombre es obligatorio."}), 400
    ok, err = _validar_email(email_val)
    if not ok:
        return jsonify({"error": err}), 400

    tax_year = data.get("tax_year")
    try:
        tax_year = int(tax_year)
        assert 2015 <= tax_year <= datetime.utcnow().year
    except Exception:
        return jsonify({"error": "Año fiscal inválido."}), 400

    case_description = (data.get("case_description") or "").strip()
    if len(case_description) < 20:
        return jsonify({"error": "La descripción del caso debe tener al menos 20 caracteres."}), 400
    if len(case_description) > 5000:
        return jsonify({"error": "La descripción del caso es demasiado larga."}), 400

    tax_country = _sanitizar_texto(data.get("tax_residence_country") or "España", max_len=100)
    phone       = _sanitizar_texto(data.get("phone") or "", max_len=30) or None
    exchanges   = _sanitizar_texto(data.get("exchanges") or "", max_len=500) or None
    op_volume   = _sanitizar_texto(data.get("operation_volume") or "", max_len=50) or None

    op_types = data.get("operation_types") or []
    if not isinstance(op_types, list): op_types = []
    op_types = [str(x)[:50] for x in op_types[:20]]

    cur_situation = data.get("current_situation") or []
    if not isinstance(cur_situation, list): cur_situation = []
    cur_situation = [str(x)[:100] for x in cur_situation[:20]]

    # Crear solicitud en DB
    import json as _json
    advisory = FiscalAdvisoryRequest(
        user_id               = current_user.id,
        full_name             = full_name,
        email                 = email_val,
        phone                 = phone,
        tax_residence_country = tax_country,
        tax_year              = tax_year,
        service_type          = service_type,
        operation_types       = _json.dumps(op_types),
        exchanges             = exchanges,
        operation_volume      = op_volume,
        current_situation     = _json.dumps(cur_situation),
        case_description      = case_description,
        status                = "pending_payment",
    )
    db.session.add(advisory)
    db.session.flush()  # get ID without committing

    # Registrar historial
    history = FiscalAdvisoryStatusHistory(
        request_id = advisory.id,
        status     = "pending_payment",
        changed_by = None,
        note       = "Solicitud creada",
    )
    db.session.add(history)
    db.session.commit()

    # Crear sesión Stripe Checkout
    try:
        _stripe_module.api_key = _STRIPE_SECRET_KEY
        amount_cents = _ADVISORY_PRICES[service_type]
        label        = _ADVISORY_PRICE_LABELS[service_type]
        success_url  = f"{_APP_BASE_URL}/asesoramiento-fiscal-confirmado?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url   = f"{_APP_BASE_URL}/asesoramiento-fiscal-cancelado?advisory_id={advisory.id}"

        session_data = _stripe_module.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": label},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=email_val,
            metadata={
                "advisory_request_id": str(advisory.id),
                "user_id":             str(current_user.id),
                "service_type":        service_type,
            },
        )
        advisory.stripe_checkout_session_id = session_data.id
        db.session.commit()

        return jsonify({"checkout_url": session_data.url, "advisory_id": advisory.id})

    except Exception as exc:
        app.logger.error("Stripe error: %s", exc)
        db.session.rollback()
        return jsonify({"error": "Error al crear la sesión de pago. Inténtalo de nuevo."}), 500


@app.route("/api/webhooks/stripe", methods=["POST"])
@limiter.limit("60 per minute")
def stripe_webhook():
    """Webhook de Stripe — solo este endpoint puede marcar un pago como confirmado."""
    if not _stripe_available or not _STRIPE_SECRET_KEY:
        return "", 200

    payload    = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        _stripe_module.api_key = _STRIPE_SECRET_KEY
        if _STRIPE_WEBHOOK_SECRET:
            event = _stripe_module.Webhook.construct_event(payload, sig_header, _STRIPE_WEBHOOK_SECRET)
        else:
            import json as _json
            event = _json.loads(payload)
    except Exception as exc:
        app.logger.warning("Stripe webhook error: %s", exc)   # solo a logs
        return jsonify({"error": "Invalid request."}), 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        cs_id        = session_obj.get("id")
        pi_id        = session_obj.get("payment_intent")
        amount_total = session_obj.get("amount_total")

        advisory = FiscalAdvisoryRequest.query.filter_by(stripe_checkout_session_id=cs_id).first()
        if advisory and advisory.status == "pending_payment":
            advisory.status                   = "paid_received"
            advisory.stripe_payment_intent_id = pi_id
            advisory.amount_paid              = amount_total
            advisory.currency                 = session_obj.get("currency", "eur")

            history = FiscalAdvisoryStatusHistory(
                request_id = advisory.id,
                status     = "paid_received",
                changed_by = None,
                note       = f"Pago confirmado por Stripe. PI: {pi_id}",
            )
            db.session.add(history)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                return "", 500

            # Notificaciones
            _send_advisory_confirmation_email(advisory)
            _send_advisory_internal_notification(advisory)

    return "", 200


def _send_advisory_confirmation_email(advisory: "FiscalAdvisoryRequest"):
    """Email de confirmación al usuario."""
    if not resend.api_key:
        return
    amount_str = f"{advisory.amount_paid / 100:.2f} EUR" if advisory.amount_paid else ""
    html = f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#080c12;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#080c12;padding:40px 0;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#10141e;border-radius:12px;border:1px solid rgba(255,255,255,0.08);">
        <tr><td style="background:#0d1018;padding:28px 40px;border-bottom:1px solid rgba(0,200,150,0.25);">
          <span style="font-size:18px;font-weight:700;color:#eef0f6;">Mariano</span><span style="font-size:18px;font-weight:700;color:#00C896;">Sevilla</span>
          <span style="font-size:12px;color:#7a8099;margin-left:10px;">Asesoramiento Fiscal Cripto</span>
        </td></tr>
        <tr><td style="padding:36px 40px;">
          <h1 style="margin:0 0 12px;font-size:22px;color:#eef0f6;font-weight:700;">Solicitud recibida correctamente</h1>
          <p style="margin:0 0 16px;font-size:15px;color:#9aa0b8;line-height:1.6;">
            Hola <strong style="color:#eef0f6;">{advisory.full_name}</strong>,<br><br>
            Hemos recibido tu solicitud de <strong style="color:#eef0f6;">{advisory.service_label()}</strong> para el ejercicio <strong style="color:#eef0f6;">{advisory.tax_year}</strong>.
            {f'<br>Importe abonado: <strong style="color:#00C896;">{amount_str}</strong>' if amount_str else ''}
          </p>
          <p style="margin:0 0 16px;font-size:15px;color:#9aa0b8;line-height:1.6;">
            Rafael revisará tu caso y se pondrá en contacto contigo en un plazo de <strong style="color:#eef0f6;">2–3 días hábiles</strong>.
            Es posible que necesitemos información adicional para analizar correctamente tu situación.
          </p>
          <p style="margin:0;font-size:13px;color:#7a8099;">
            Número de solicitud: <strong style="color:#eef0f6;">#{advisory.id}</strong>
          </p>
        </td></tr>
        <tr><td style="background:#0d1018;padding:18px 40px;border-top:1px solid rgba(255,255,255,0.06);">
          <p style="margin:0;font-size:11px;color:#555c70;">marianosevilla.com · Asesoramiento Fiscal Cripto</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM,
            "to":      [advisory.email],
            "subject": "Hemos recibido tu solicitud de asesoramiento fiscal",
            "html":    html,
        })
    except Exception as exc:
        app.logger.error("Error enviando email confirmación advisory: %s", exc)


def _send_advisory_internal_notification(advisory: "FiscalAdvisoryRequest"):
    """Email interno a Mariano y Rafa."""
    if not resend.api_key or not _ADVISORY_NOTIFY_EMAILS:
        return
    amount_str = f"{advisory.amount_paid / 100:.2f} EUR" if advisory.amount_paid else "—"
    panel_url  = f"{_APP_BASE_URL}/admin/asesoramiento"
    text = (
        f"Nueva solicitud de asesoramiento fiscal\n\n"
        f"ID: #{advisory.id}\n"
        f"Nombre: {advisory.full_name}\n"
        f"Email: {advisory.email}\n"
        f"Servicio: {advisory.service_label()}\n"
        f"Año fiscal: {advisory.tax_year}\n"
        f"Importe: {amount_str}\n\n"
        f"Descripción:\n{advisory.case_description[:500]}\n\n"
        f"Panel: {panel_url}"
    )
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM,
            "to":      _ADVISORY_NOTIFY_EMAILS,
            "subject": f"[Asesoramiento] Nueva solicitud #{advisory.id} — {advisory.service_label()}",
            "text":    text,
        })
    except Exception as exc:
        app.logger.error("Error enviando notificación interna advisory: %s", exc)


@app.route("/api/asesoramiento/files/<int:request_id>", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def advisory_upload_file(request_id):
    """Sube un fichero asociado a una solicitud (solo el propietario)."""
    advisory = FiscalAdvisoryRequest.query.get_or_404(request_id)
    if advisory.user_id != current_user.id:
        return jsonify({"error": "Acceso denegado."}), 403

    if "file" not in request.files:
        return jsonify({"error": "No se recibió ningún fichero."}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Fichero inválido."}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _ALLOWED_ADVISORY_EXTENSIONS:
        return jsonify({"error": f"Extensión no permitida. Usa: {', '.join(_ALLOWED_ADVISORY_EXTENSIONS)}"}), 400

    # Leer y verificar tamaño
    content = f.read(_MAX_ADVISORY_FILE_SIZE + 1)
    if len(content) > _MAX_ADVISORY_FILE_SIZE:
        return jsonify({"error": "El fichero supera el límite de 10 MB."}), 413

    from werkzeug.utils import secure_filename
    safe_name  = secure_filename(f.filename)
    upload_dir = os.path.join(_ADVISORY_UPLOAD_DIR, str(advisory.id))
    os.makedirs(upload_dir, exist_ok=True)
    file_path  = os.path.join(upload_dir, safe_name)

    with open(file_path, "wb") as out:
        out.write(content)

    file_record = FiscalAdvisoryFile(
        request_id = advisory.id,
        user_id    = current_user.id,
        file_name  = safe_name,
        file_path  = os.path.join(str(advisory.id), safe_name),
        file_type  = f.content_type or "",
        file_size  = len(content),
    )
    db.session.add(file_record)
    db.session.commit()

    return jsonify({"ok": True, "file_id": file_record.id, "file_name": safe_name})


@app.route("/api/asesoramiento/files/download/<int:file_id>")
@login_required
def advisory_download_file(file_id):
    """Descarga protegida: solo propietario o advisor/admin."""
    file_record = FiscalAdvisoryFile.query.get_or_404(file_id)
    advisory    = FiscalAdvisoryRequest.query.get_or_404(file_record.request_id)

    if advisory.user_id != current_user.id and not _is_fiscal_advisor():
        return jsonify({"error": "Acceso denegado."}), 403

    full_path = os.path.join(_ADVISORY_UPLOAD_DIR, file_record.file_path)
    if not os.path.realpath(full_path).startswith(os.path.realpath(_ADVISORY_UPLOAD_DIR)):
        return jsonify({"error": "Ruta inválida."}), 400
    if not os.path.exists(full_path):
        return jsonify({"error": "Fichero no encontrado."}), 404

    return send_file(full_path, as_attachment=True, download_name=file_record.file_name)


@app.route("/api/asesoramiento/mis-solicitudes")
@login_required
def advisory_my_requests():
    """Solicitudes del usuario autenticado."""
    requests_list = FiscalAdvisoryRequest.query.filter_by(user_id=current_user.id)\
        .order_by(FiscalAdvisoryRequest.created_at.desc()).all()
    return jsonify([r.to_dict() for r in requests_list])


# ── ADMIN ADVISORY API ────────────────────────

@app.route("/api/admin/asesoramiento/solicitudes")
@login_required
def admin_advisory_list():
    if not _is_fiscal_advisor():
        return jsonify({"error": "Acceso denegado."}), 403

    status_filter  = request.args.get("status", "")
    service_filter = request.args.get("service_type", "")
    q = FiscalAdvisoryRequest.query
    if status_filter:
        q = q.filter_by(status=status_filter)
    if service_filter:
        q = q.filter_by(service_type=service_filter)
    items = q.order_by(FiscalAdvisoryRequest.created_at.desc()).limit(200).all()
    return jsonify([r.to_dict() for r in items])


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>")
@login_required
def admin_advisory_detail(request_id):
    if not _is_fiscal_advisor():
        return jsonify({"error": "Acceso denegado."}), 403
    advisory = FiscalAdvisoryRequest.query.get_or_404(request_id)
    d = advisory.to_dict(full=True)
    d["files"] = [
        {"id": f.id, "file_name": f.file_name, "file_size": f.file_size,
         "file_type": f.file_type, "uploaded_at": f.uploaded_at.isoformat()}
        for f in advisory.files
    ]
    d["status_history"] = [
        {"status": h.status, "note": h.note,
         "created_at": h.created_at.isoformat(), "changed_by": h.changed_by}
        for h in sorted(advisory.status_history, key=lambda x: x.created_at)
    ]
    return jsonify(d)


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>/estado", methods=["POST"])
@login_required
def admin_advisory_change_status(request_id):
    if not _is_fiscal_advisor():
        return jsonify({"error": "Acceso denegado."}), 403
    advisory    = FiscalAdvisoryRequest.query.get_or_404(request_id)
    data        = request.get_json(silent=True) or {}
    new_status  = (data.get("status") or "").strip()
    note        = (data.get("note") or "").strip()[:1000]
    valid_statuses = list(FiscalAdvisoryRequest.STATUS_LABELS.keys())
    if new_status not in valid_statuses:
        return jsonify({"error": "Estado inválido."}), 400
    advisory.status = new_status
    history = FiscalAdvisoryStatusHistory(
        request_id = advisory.id,
        status     = new_status,
        changed_by = current_user.id,
        note       = note or None,
    )
    db.session.add(history)
    db.session.commit()
    return jsonify({"ok": True, "status": new_status, "status_label": advisory.status_label()})


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>/nota", methods=["POST"])
@login_required
def admin_advisory_add_note(request_id):
    if not _is_fiscal_advisor():
        return jsonify({"error": "Acceso denegado."}), 403
    advisory = FiscalAdvisoryRequest.query.get_or_404(request_id)
    data     = request.get_json(silent=True) or {}
    nota     = (data.get("nota") or "").strip()[:2000]
    if not nota:
        return jsonify({"error": "La nota no puede estar vacía."}), 400
    advisory.internal_notes = ((advisory.internal_notes or "") + f"\n\n[{datetime.utcnow().strftime('%d/%m/%Y %H:%M')} - {current_user.email}]\n{nota}").strip()
    db.session.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(debug=False, port=5050)
