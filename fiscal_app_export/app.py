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
import json
import secrets
import hashlib
import tempfile
import traceback
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, send_from_directory, redirect, url_for, render_template, session, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from flask_compress import Compress
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from authlib.integrations.flask_client import OAuth
import resend
from sqlalchemy import func, extract, text, or_
from models import db, bcrypt, User, FifoReport, Contacto, ProcessingError, CommunicationCampaign, CommunicationDelivery

# Advisory / Stripe imports
try:
    import stripe as _stripe_module
    _stripe_available = True
except ImportError:
    _stripe_available = False
    _stripe_module = None
from models import FiscalAdvisoryRequest, FiscalAdvisoryFile, FiscalAdvisoryStatusHistory, AdvisoryInternalNote, AdvisoryAuditLog
from models import Resource, ResourceRequest
from error_tracking import record_processing_error_safe, is_actionable_processing_error

sys.path.insert(0, os.path.dirname(__file__))

from clasificador import ClasificadorBinance
from clasificador_binance_tx import ClasificadorBinanceTx
from clasificador_bit2me import ClasificadorBit2Me
from clasificador_bit2me_excel import (
    ClasificadorBit2MeExcel, validar_columnas_bit2me_excel, Bit2MeExcelError,
)
from clasificador_bitvavo import ClasificadorBitvavo
from clasificador_kraken import ClasificadorKraken
from clasificador_coinbase import ClasificadorCoinbase
from clasificador_nexo import ClasificadorNexo
from clasificador_cryptocom import ClasificadorCryptoCom
from clasificador_uphold import ClasificadorUphold, UPHOLD_SIGNATURES
from clasificador_mexc import (
    ClasificadorMEXC, _detectar_tipo_mexc, _contar_filas_xlsx,
    MexcUnsupportedFormatError, MexcUserError,
)
from clasificador_bitget import (
    ClasificadorBitget, ClasificadorBitgetMulti, BitgetUserError,
    detect_bitget_file_type, BITGET_SIGNATURES,
)
from clasificador_kucoin import ClasificadorKuCoin, KucoinUserError
from motor_fifo import MotorFIFO
from generador_pdf import generar_pdf, generar_pdf_bit2me
from generador_pdf_mexc import generar_pdf_mexc
from generador_pdf_bitget import generar_pdf_bitget
from modelo721 import generar_datos_modelo_721
from precios_historicos import obtener_precios_historicos, enriquecer_721_con_precios
from generador_xml_721 import (
    validar_para_xml, generar_xml_721, ErrXMLBloqueado, ErrXMLInvalidoXSD, ValidacionXML,
)
from auth import (
    ADMIN_EMAILS,
    FISCAL_ADVISOR_EMAILS,
    _role_is_admin,
    _role_is_fiscal_advisor,
    require_roles,
    require_admin,
    require_fiscal_advisor,
    require_admin_page,
    require_fiscal_advisor_page,
)

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

# ADMIN_EMAILS y FISCAL_ADVISOR_EMAILS se importan desde auth.py.
# _is_admin / _is_fiscal_advisor son aliases de las funciones centralizadas
# para mantener compatibilidad con exempt_when=_is_admin en rate limiter
# y cualquier llamada inline que quede durante la migración.
_is_admin          = _role_is_admin
_is_fiscal_advisor = _role_is_fiscal_advisor

# Railway usa "postgres://" pero SQLAlchemy requiere "postgresql://"
_db_url = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(_BASE_DIR, 'fiscal_users.db')}")
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
_engine_opts: dict = {
    # pool_pre_ping: descarta conexiones muertas antes de usarlas (evita 502 post-restart).
    "pool_pre_ping": True,
    # pool_timeout: máx 10s esperando una conexión libre del pool.
    "pool_timeout":  10,
    # pool_recycle: recicla conexiones > 5 min para evitar "server closed the connection".
    "pool_recycle":  300,
}
if not _db_url.startswith("sqlite"):
    # connect_timeout solo aplica a PostgreSQL/MySQL; sqlite3 no lo acepta.
    _engine_opts["connect_args"] = {"connect_timeout": 5}
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = _engine_opts

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

# Sesión NO persistente: session.permanent no se activa en ningún login.
# La cookie de sesión es ephemeral (sin Max-Age) → el navegador la destruye al cerrar.
# La cookie de remember-me (checkbox "Recordarme") sí persiste, con este límite:
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)


# ── EXTENSIONES ───────────────────────────────
db.init_app(app)
bcrypt.init_app(app)
migrate = Migrate(app, db)

# ── BLUEPRINTS ────────────────────────────────
from communications import comms_bp          # noqa: E402
app.register_blueprint(comms_bp)

# ── RESEND (email) ────────────────────────────
resend.api_key = os.environ.get("RESEND_API_KEY", "")
_RESEND_FROM   = os.environ.get("RESEND_FROM_EMAIL", "noreply@marianosevilla.com")
_RESEND_FROM_DISPLAY = (
    _RESEND_FROM if "<" in _RESEND_FROM else f"Mariano Sevilla <{_RESEND_FROM}>"
)
_APP_BASE_URL  = os.environ.get("APP_BASE_URL", "https://www.marianosevilla.com")

from email_templates import (  # noqa: E402
    verification_email,
    advisory_confirmation_email,
    advisory_status_email,
    advisory_quote_email,
    advisory_message_email,
    advisory_payment_confirmed_email,
    advisory_payment_internal_email,
    password_reset_email,
    resource_request_confirmation_email,
    resource_request_internal_email,
)

# ── ADVISORY / STRIPE ────────────────────────
_STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
_STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# ── PAYPAL ────────────────────────────────────
_PAYPAL_CLIENT_ID      = os.environ.get("PAYPAL_CLIENT_ID", "")
_PAYPAL_CLIENT_SECRET  = os.environ.get("PAYPAL_CLIENT_SECRET", "")
_PAYPAL_WEBHOOK_ID     = os.environ.get("PAYPAL_WEBHOOK_ID", "")
_PAYPAL_ENV            = os.environ.get("PAYPAL_ENVIRONMENT", "sandbox")   # 'sandbox' | 'live'
_PAYPAL_BASE_URL       = (
    "https://api-m.sandbox.paypal.com" if _PAYPAL_ENV == "sandbox"
    else "https://api-m.paypal.com"
)
_PAYPAL_ENABLED        = bool(_PAYPAL_CLIENT_ID and _PAYPAL_CLIENT_SECRET)
_ADVISORY_NOTIFY_EMAILS = [
    e.strip() for e in os.environ.get("FISCAL_ADVISORY_NOTIFY_EMAILS", "").split(",") if e.strip()
]
_RESOURCE_NOTIFY_EMAIL = os.environ.get("RESOURCE_NOTIFY_EMAIL", "colab.marianosevilla@gmail.com")
# Precios en céntimos. Configura en Railway env vars.
_ADVISORY_PRICES = {
    "revision_basica":          int(os.environ.get("FISCAL_ADVISORY_BASIC_PRICE",   "7900")),
    "revision_avanzada":        int(os.environ.get("FISCAL_ADVISORY_ADVANCED_PRICE","14900")),
    "caso_complejo":            int(os.environ.get("FISCAL_ADVISORY_COMPLEX_PRICE", "4900")),
    # Tipo genérico para solicitudes de presupuesto: el usuario pide valoración
    # sin seleccionar servicio; Rafa asigna tipo y precio al revisar el caso.
    "presupuesto_personalizado": 0,
}
_ADVISORY_PRICE_LABELS = {
    "revision_basica":          "Revisión fiscal básica",
    "revision_avanzada":        "Revisión fiscal avanzada",
    "caso_complejo":            "Valoración inicial — caso complejo",
    "presupuesto_personalizado": "Solicitud de presupuesto personalizado",
}

# Feature flag: emails automáticos al usuario al cambiar estado de solicitud.
# Activar en Railway: ENABLE_ADVISORY_STATUS_EMAILS=true
# Por defecto false — validar diseño/copy antes de exponer a usuarios reales.
_ADVISORY_STATUS_EMAILS_ENABLED = (
    os.environ.get("ENABLE_ADVISORY_STATUS_EMAILS", "false").lower() == "true"
)

# Subida de archivos al servidor desactivada — la documentación fiscal se envía por email.
# Activar con ENABLE_ADVISORY_UPLOADS=true solo si se migra a almacenamiento persistente.
_ADVISORY_UPLOADS_ENABLED = (
    os.environ.get("ENABLE_ADVISORY_UPLOADS", "false").lower() == "true"
)

# Soporte del Excel "Historial de operaciones" de Bit2Me como fuente del MotorFIFO.
# Por defecto DESACTIVADO: el código puede desplegarse sin exponer la funcionalidad.
# Con el flag a false, Bit2Me sigue aceptando solo el CSV "Informe Fiscal" (sin cambios).
_BIT2ME_EXCEL_ENABLED = (
    os.environ.get("BIT2ME_EXCEL_ENABLED", "false").lower() == "true"
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

# ── BOOTSTRAP DB (columnas de emergencia) ─────────────────────────────────────
# Nota: las migraciones formales van en el Procfile via `flask db upgrade`.
# Este bloque añade columnas que pueden faltar en instancias antiguas.
# Está protegido contra cuelgues gracias a connect_timeout en SQLALCHEMY_ENGINE_OPTIONS.
try:
    with app.app_context():
        db.create_all()
        try:
            from sqlalchemy import text
            with db.engine.connect() as _conn:
                _conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP"
                ))
                _conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(150)"
                ))
                _conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user' NOT NULL"
                ))
                _conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS nif VARCHAR(20)"
                ))
                _conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token_hash VARCHAR(64)"
                ))
                _conn.execute(text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMP"
                ))
                # Error taxonomy columns (migration k4l5m6n7o8p9)
                _conn.execute(text(
                    "ALTER TABLE fifo_reports ADD COLUMN IF NOT EXISTS error_category VARCHAR(50)"
                ))
                _conn.execute(text(
                    "ALTER TABLE processing_errors ADD COLUMN IF NOT EXISTS error_category VARCHAR(50)"
                ))
                _conn.execute(text(
                    "ALTER TABLE processing_errors ADD COLUMN IF NOT EXISTS error_code VARCHAR(50)"
                ))
                # Evidencia técnica del CSV (migration Sprint 1)
                _conn.execute(text(
                    "ALTER TABLE processing_errors ADD COLUMN IF NOT EXISTS csv_context TEXT"
                ))
                _conn.commit()
        except Exception:
            pass  # columnas ya existen o DB no disponible — no es crítico en arranque
except Exception:
    pass  # si DB no está lista aún, flask db upgrade (Procfile) lo gestiona


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


# Mapa exchange → nombre real de la clase clasificadora (para csv_context / observabilidad)
_PARSER_CLASS_MAP = {
    "bitvavo":   "ClasificadorBitvavo",
    "kraken":    "ClasificadorKraken",
    "coinbase":  "ClasificadorCoinbase",
    "nexo":      "ClasificadorNexo",
    "cryptocom": "ClasificadorCryptoCom",
    "uphold":    "ClasificadorUphold",
    "mexc":      "ClasificadorMEXC",
    "bit2me":    "ClasificadorBit2Me",
    "bitget":    "ClasificadorBitget",
}


def _capturar_evidencia(filepath: str, *, exchange: str = None, is_xlsx: bool = False) -> dict:
    """Captura contexto técnico del archivo para diagnóstico posterior.

    Best-effort: nunca lanza excepciones. Devuelve dict vacío si falla todo.
    El llamador serializa a JSON y pasa como csv_context a record_processing_error_safe().
    """
    import csv as _csv
    ctx: dict = {}
    try:
        # SHA256 del archivo completo (máx. 10 MB garantizado por validación previa)
        with open(filepath, "rb") as f:
            ctx["sha256"] = hashlib.sha256(f.read()).hexdigest()

        if is_xlsx:
            ctx["file_type"] = "xlsx"
            return ctx

        ctx["file_type"] = "csv"

        # Detección de encoding: UTF-8 estricto primero, latin-1 como fallback
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                f.read(8192)
            ctx["encoding"] = "utf-8"
        except UnicodeDecodeError:
            ctx["encoding"] = "latin-1"
        except Exception:
            pass

        # Cabeceras y separador
        enc = ctx.get("encoding", "utf-8")
        try:
            with open(filepath, "r", encoding=enc, errors="replace") as f:
                first_line = f.readline().strip()
            if first_line:
                for sep in (",", ";", "\t", "|"):
                    cols = next(_csv.reader([first_line], delimiter=sep), [])
                    if len(cols) > 1:
                        ctx["separator"] = sep
                        ctx["headers"]   = cols[:50]   # máx. 50 columnas en evidencia
                        ctx["n_columns"] = len(cols)
                        break
        except Exception:
            pass

        # Variante de formato Binance (detectada aquí para evitar doble lectura)
        if exchange == "binance":
            try:
                ctx["exchange_format_variant"] = _detectar_formato_binance(filepath)
            except Exception:
                pass

    except Exception:
        pass

    return ctx


def _derivar_ruta_pdf(tmp_path: str) -> str:
    """Ruta del PDF temporal derivada del fichero subido, sea cual sea su
    extensión (.csv, .xls, .xlsx). El token de descarga es el basename de esta
    ruta y debe terminar en .pdf para pasar la validación de /api/descargar."""
    return os.path.splitext(tmp_path)[0] + ".pdf"


def _registrar_informe(
    exchange: str,
    fiscal_year: int,
    csv_rows: int,
    distinct_assets: int,
    processing_ms: int,
    status: str = "generated",
    error_type=None,
    error_category=None,   # "parser_error" | "unsupported_format" | "user_error"
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
            error_category    = error_category,
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
    "mexc": {
        "exchange_id":      "mexc",
        "exchange_name":    "MEXC",
        "exchange_logo":    "MX",
        "page_title":       "Informe FIFO MEXC para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el Excel de MEXC y calcula tus ganancias y pérdidas patrimoniales con FIFO obligatorio. Informe PDF listo para la declaración de la renta en España.",
        "page_canonical":   f"{_BASE_URL}/mexc",
        "page_og_title":    "Informe fiscal MEXC para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el Excel de MEXC y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO MEXC — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de MEXC para Hacienda",
        "hero_desc":        "Sube el archivo XLS/XLSX del historial de operaciones de MEXC y obtén el informe FIFO con tus ganancias y pérdidas patrimoniales. Listo para la declaración de la renta.",
        "how_to": [
            {"title": "Exporta el Excel de Trade Records desde MEXC",
             "desc":  "En tu cuenta de MEXC ve a Órdenes → Historial de operaciones → Exportar. Selecciona el período completo desde tu primera operación hasta hoy y descarga el fichero XLS o XLSX."},
            {"title": "Sube el archivo XLS/XLSX",
             "desc":  "Arrastra el archivo directamente, sin convertirlo a CSV. La herramienta lee el formato Excel de MEXC de forma nativa."},
            _HOW_TO_STEP3,
        ],
    },
    "bitget": {
        "exchange_id":      "bitget",
        "exchange_name":    "Bitget",
        "exchange_logo":    "BG",
        "page_title":       "Informe FIFO Bitget para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube el CSV de Bitget y calcula tus ganancias y pérdidas patrimoniales con FIFO obligatorio. Informe PDF listo para la declaración de la renta en España.",
        "page_canonical":   f"{_BASE_URL}/bitget",
        "page_og_title":    "Informe fiscal Bitget para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube el CSV de Bitget y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Bitget — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Bitget para Hacienda",
        "hero_desc":        "Bitget exporta varios historiales. Sube el «Historial de operaciones en spot» (obligatorio) y, si lo tienes, el «Historial de depósitos y retiros». Obtendrás el informe FIFO con tus ganancias y pérdidas patrimoniales, listo para la declaración de la renta.",
        "how_to": [
            {"title": "Exporta tu «Historial de operaciones en spot» desde Bitget",
             "desc":  "Es el fichero principal: contiene todas tus operaciones ejecutadas con su precio y comisión. En Bitget ve a Activos → Registros → Spot y descarga el «Historial de operaciones en spot» (Spot Trading History). Importante: elige el período completo desde tu primera compra hasta hoy; si sólo exportas los últimos meses, faltarán las compras antiguas y el cálculo del coste saldría incompleto."},
            {"title": "Añade tu «Historial de depósitos y retiros» (opcional, recomendado)",
             "desc":  "Exporta también el «Historial de depósitos y retiros» (Deposit & Withdrawal History). Sirve para reflejar y conciliar las monedas que enviaste o sacaste de Bitget. Puedes subir varios ficheros a la vez; el sistema detecta automáticamente cada uno."},
            _HOW_TO_STEP3,
        ],
        "aviso_extra": (
            "El fichero «Spot Financial Record» es opcional y sólo se utiliza para "
            "auditorías y conciliación de saldos. No subas el «Historial de órdenes» "
            "como fuente principal: puede incluir órdenes canceladas o información no "
            "adecuada para el cálculo FIFO. El fichero correcto es el historial de "
            "operaciones ejecutadas."
        ),
    },
    "kucoin": {
        "exchange_id":      "kucoin",
        "exchange_name":    "KuCoin",
        "exchange_logo":    "KC",
        "page_title":       "Informe FIFO KuCoin para Hacienda | Mariano Sevilla",
        "page_meta_desc":   "Sube los CSV de KuCoin y calcula tus ganancias y pérdidas patrimoniales con FIFO obligatorio. Informe PDF listo para la declaración de la renta en España.",
        "page_canonical":   f"{_BASE_URL}/kucoin",
        "page_og_title":    "Informe fiscal KuCoin para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube los historiales de KuCoin y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO KuCoin — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de KuCoin para Hacienda",
        "hero_desc":        "KuCoin exporta varios historiales. Sube todos los CSV que tengas (Cuenta de trading, Cuenta de financiación, Órdenes fiat, depósitos cripto) y obtén el informe FIFO con tus ganancias y pérdidas patrimoniales. Si alguno está vacío, no pasa nada.",
        "how_to": [
            {"title": "Exporta tus historiales desde KuCoin",
             "desc":  "En tu cuenta de KuCoin ve a Activos → Historial de la cuenta y exporta la Cuenta de trading y la Cuenta de financiación. Si operaste con fiat, exporta también Órdenes fiat. Selecciona siempre el período completo desde tu primera operación."},
            {"title": "Sube todos los CSV a la vez",
             "desc":  "Arrastra todos los ficheros CSV juntos. El sistema detecta automáticamente el tipo de cada uno y te muestra qué ha reconocido. Puedes subir sólo los que tengas; los archivos vacíos no rompen nada."},
            _HOW_TO_STEP3,
        ],
    },
}


# ── CORS ──────────────────────────────────────
ALLOWED_ORIGINS = [
    "https://marianosevilla.com",
    "https://www.marianosevilla.com",
    "https://fiscal.marianosevilla.com",
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
def redirect_trailing_slash():
    """Redirect canónico 301: /ruta/ → /ruta.

    Excluye la raíz '/' y solo actúa sobre GET/HEAD para no romper POSTs.
    Preserva query string.
    """
    if (
        request.path != "/"
        and request.path.endswith("/")
        and request.method in ("GET", "HEAD")
    ):
        clean = request.path.rstrip("/")
        target = clean + ("?" + request.query_string.decode() if request.query_string else "")
        return redirect(target, code=301)


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
MAX_KUCOIN_FILES    = 8                  # KuCoin es multiarchivo: tope de ficheros por análisis
MAX_BITGET_FILES    = 8                  # Bitget es multiarchivo: tope de ficheros por análisis
AÑO_MIN = 2009
AÑO_MAX = datetime.now().year + 1

# ── MODELO 721: exchanges ──────────────────────────────────────────────────────
# Primer ejercicio obligatorio del Modelo 721 (Ley 10/2021, DA decimocuarta LIRPF).
_721_PRIMER_EJERCICIO = 2022
# Exchanges con MotorFIFO → pueden generar snapshot 31/12 via posicion_a_fecha().
_721_EXCHANGES_CON_MOTOR = frozenset({
    "binance", "bitvavo", "kraken", "coinbase", "nexo", "cryptocom", "uphold", "mexc", "bitget"
})
# Exchanges españoles: no sujetos al 721 (entidad custodio en España).
_721_EXCHANGES_ES = frozenset({"bit2me"})

BINANCE_SIGNATURES   = ["Tiempo", "Operación", "Moneda", "Cambio", "Cuenta",  # ES
                         "Operation", "Coin", "Change", "Account"]              # EN
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


_NIF_RE = re.compile(r"^[A-Z0-9][0-9]{7}[A-Z0-9]$")

def _normalizar_nif(nif: str) -> str:
    """Quita espacios y convierte a mayúsculas."""
    return nif.strip().upper()

def _validar_nif_usuario(nif: str) -> tuple[bool, str]:
    """
    Valida NIF/NIE/CIF español básico.
    Devuelve (True, "") si es válido o vacío; (False, mensaje) si inválido.
    El campo es opcional: vacío se acepta (significa "no guardado todavía").
    """
    nif = _normalizar_nif(nif)
    if not nif:
        return True, ""
    if len(nif) > 20:
        return False, "El NIF no puede tener más de 20 caracteres."
    if not _NIF_RE.match(nif):
        return False, "Formato no válido. Ejemplos válidos: 12345678Z, X1234567L, B12345678."
    return True, ""


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
        "bitget":    BITGET_SIGNATURES,
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
        "bitget":    "Bitget",
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
        if ("Buy Crypto With Fiat" in muestra or "Sell Crypto To Fiat" in muestra
                or "ID de usuario" in muestra or "User ID" in muestra):
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


def procesar_mexc(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorMEXC(filepath).clasificar())


def procesar_bitget(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorBitget(filepath).clasificar())


def procesar_kucoin(filepaths: list, filenames: list = None) -> tuple:
    """KuCoin es multiarchivo: recibe una lista de rutas CSV ya guardadas."""
    return procesar_con_fifo(ClasificadorKuCoin(filepaths, filenames).clasificar())


def procesar_bitget_multi(filepaths: list, filenames: list = None) -> tuple:
    """Bitget multiarchivo: recibe una lista de rutas CSV ya guardadas."""
    return procesar_con_fifo(ClasificadorBitgetMulti(filepaths, filenames).clasificar())


def _motor_desde_csv_721(exchange: str, tmp_path: str) -> MotorFIFO:
    """
    Construye el MotorFIFO completo desde un CSV para uso exclusivo de /api/721.

    Diferencia crítica respecto a /api/analizar: NO llama a
    _filtrar_motor_por_ejercicio(). El inventario completo desde el primer lote
    histórico es necesario para que posicion_a_fecha() reconstruya el snapshot
    correcto a 31/12 del ejercicio declarado. Filtrar aquí rompería el FIFO.
    """
    if exchange == "binance":
        if _detectar_formato_binance(tmp_path) == "tx":
            motor, _, _ = procesar_binance_tx(tmp_path)
        else:
            motor, _, _ = procesar_binance(tmp_path)
    elif exchange == "bitvavo":
        motor, _, _ = procesar_bitvavo(tmp_path)
    elif exchange == "kraken":
        motor, _, _ = procesar_kraken(tmp_path)
    elif exchange == "coinbase":
        motor, _, _ = procesar_coinbase(tmp_path)
    elif exchange == "nexo":
        motor, _, _ = procesar_nexo(tmp_path)
    elif exchange == "cryptocom":
        motor, _, _ = procesar_cryptocom(tmp_path)
    elif exchange == "uphold":
        motor, _, _ = procesar_uphold(tmp_path)
    elif exchange == "mexc":
        motor, _, _ = procesar_mexc(tmp_path)
    elif exchange == "bitget":
        motor, _, _ = procesar_bitget(tmp_path)
    else:
        raise ValueError(f"Exchange '{exchange}' no soportado para Modelo 721.")
    return motor


def _calcular_pendiente_721(datos: dict, validacion: "ValidacionXML") -> dict:
    """
    Construye el bloque 'pendiente' del endpoint /api/721.

    Combina:
      · precios_historicos: tickers sin precio EUR a 31/12 (CoinGecko/BCE)
      · tax_id_custodio: exchanges extranjeros sin identificador fiscal confirmado
      · Estado XML: xml_generable, es_borrador, bloqueantes y advertencias
        derivados de ValidacionXML (generador_xml_721.validar_para_xml)
    """
    activos_sin_precio:   list = []
    exchanges_sin_tax_id: list = []

    for exc in datos.get("exchanges", []):
        if exc.get("extranjero") is False:
            continue   # Entidades españolas fuera del ámbito del 721
        if exc.get("nif_custodio") is None:
            exchanges_sin_tax_id.append(
                exc.get("exchange_key") or exc.get("exchange", "")
            )
        for activo in exc.get("activos", []):
            if activo.get("valor_eur") is None:
                activos_sin_precio.append(activo["activo"])

    completo = (
        not activos_sin_precio
        and not exchanges_sin_tax_id
        and validacion.xml_generable
        and not validacion.es_borrador
    )

    return {
        # ── Datos pendientes para el XML ──────────────────────────────────
        "precios_historicos": sorted(set(activos_sin_precio)),
        "tax_id_custodio":    exchanges_sin_tax_id,
        # ── Estado del XML AEAT ───────────────────────────────────────────
        "xml_generable":      validacion.xml_generable,
        "xml_es_borrador":    validacion.es_borrador,
        "xml_bloqueantes":    validacion.bloqueantes,
        "xml_advertencias":   validacion.advertencias,
        "por_debajo_umbral":  validacion.por_debajo_umbral,
        # ── ¿Está todo resuelto? ──────────────────────────────────────────
        "completo":           completo,
    }


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


# Aviso de "estimación" que encabeza las advertencias del informe Excel de Bit2Me.
# Se inyecta en motor.advertencias → aparece en el PDF (generar_pdf ya las renderiza)
# y en la respuesta de la API, sin tocar el generador compartido.
_BIT2ME_EXCEL_BANNER = (
    "Informe ORIENTATIVO (estimación) calculado a partir del historial de operaciones "
    "de Bit2Me, no del Informe Fiscal oficial. Para tu cifra fiscal exacta usa el CSV "
    "«Informe Fiscal» de Bit2Me. Revisa las advertencias siguientes antes de declarar."
)


def procesar_bit2me_excel(filepath: str) -> tuple:
    """Historial de operaciones Excel de Bit2Me → MotorFIFO (igual que MEXC/Binance).

    Devuelve (motor, rendimientos, clasificador). Fusiona las advertencias del
    clasificador y el banner de estimación en motor.advertencias para que lleguen
    al PDF y a la UI."""
    clasificador = ClasificadorBit2MeExcel(filepath).clasificar()
    motor, rendimientos, clasificador = procesar_con_fifo(clasificador)
    motor.advertencias = (
        [_BIT2ME_EXCEL_BANNER] + clasificador.advertencias + list(motor.advertencias)
    )
    return motor, rendimientos, clasificador


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
    # ValueError descriptivos propagados intencionalmente (ej. futuros MEXC, formato no reconocido)
    if etype == "ValueError" and len(msg) > 20:
        return msg
    if isinstance(e, KeyError) or etype == "KeyError" or "column" in msg.lower():
        return "El fichero no tiene las columnas esperadas. Exporta el historial completo desde tu exchange."
    if "NoneType" in msg or etype == "AttributeError":
        return "El fichero no tiene el formato esperado. Asegúrate de exportarlo directamente desde tu exchange."
    if etype in ("UnicodeDecodeError", "UnicodeError") or "codec" in msg:
        return "El fichero no puede leerse. Descárgalo de nuevo desde tu exchange sin abrirlo con Excel."
    if etype == "MemoryError":
        return "El fichero es demasiado grande para procesarse. Intenta con un rango de fechas más reducido."
    if "JSON" in msg or "float" in msg.lower() or "range" in msg.lower() or "serializ" in msg.lower():
        return "Error al generar el informe. Comprueba que el fichero no ha sido modificado y vuelve a intentarlo."
    if etype == "ParserError" or "tokeniz" in msg.lower():
        return "El fichero está mal formado. Descárgalo de nuevo desde tu exchange sin abrirlo con Excel."
    if "zipfile" in msg.lower() or "openpyxl" in msg.lower() or "xlsx" in msg.lower():
        return "El fichero Excel no se puede leer. Descárgalo de nuevo desde MEXC sin abrirlo antes."
    return "No se ha podido procesar el fichero. Comprueba que es el archivo exportado desde tu exchange y vuelve a intentarlo."


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
@limiter.exempt
def landing():
    return send_from_directory("static", "landing.html")


@app.route("/fiscal")
@login_required
def fiscal():
    return render_template("tool.html", **_TOOL_GENERIC)


@app.route("/about", strict_slashes=False)
@limiter.exempt
def about():
    return send_from_directory("static", "about.html")


@app.route("/privacidad", strict_slashes=False)
@limiter.exempt
def privacidad():
    return send_from_directory("static", "privacidad.html")


@app.route("/terminos", strict_slashes=False)
@limiter.exempt
def terminos():
    return send_from_directory("static", "terminos.html")


@app.route("/aviso-legal", strict_slashes=False)
@limiter.exempt
def aviso_legal():
    return send_from_directory("static", "aviso-legal.html")


@app.route("/seguridad", strict_slashes=False)
@limiter.exempt
def seguridad():
    return send_from_directory("static", "seguridad.html")


@app.route("/cookies", strict_slashes=False)
@limiter.exempt
def cookies():
    return send_from_directory("static", "cookies.html")


@app.route("/preferencias", strict_slashes=False)
@limiter.exempt
def preferencias():
    return send_from_directory("static", "preferencias.html")


@app.route("/dashboard", strict_slashes=False)
@login_required
@limiter.exempt
def dashboard():
    """Dashboard principal: selector de exchange. Requiere autenticación."""
    return send_from_directory("static", "dashboard.html")


@app.route("/modelo721", strict_slashes=False)
@login_required
@limiter.exempt
def modelo721_page():
    """Herramienta Modelo 721 — criptomonedas en el extranjero. Requiere autenticación."""
    return send_from_directory("static", "modelo721.html")


@app.route("/account", strict_slashes=False)
@login_required
@limiter.exempt
def account():
    """Página de cuenta de usuario. Requiere autenticación."""
    return send_from_directory("static", "account.html")


# ── EMAIL VERIFICATION ────────────────────────

_VERIFY_TOKEN_SALT   = "email-verification-v1"
_DELETE_ACCOUNT_SALT = "delete-account-v1"
_VERIFY_TOKEN_TTL    = 86_400  # 24 horas
_RESET_TOKEN_TTL     = 3_600   # 1 hora
_DELETE_TOKEN_TTL    = 600     # 10 minutos


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

    token      = _generate_verification_token(user.email)
    verify_url = f"{_APP_BASE_URL}/verify-email?token={token}"
    html, text = verification_email(verify_url)

    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [user.email],
            "subject": "Verifica tu email — marianosevilla.com",
            "html":    html,
            "text":    text,
        })
        return True
    except Exception as exc:
        app.logger.error("Error enviando email de verificación: %s", exc)
        return False


def _generate_reset_token() -> tuple[str, str]:
    """Genera (token_raw, token_hash). El raw va al email; el hash se guarda en DB."""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


def _send_password_reset_email(user: User) -> bool:
    """Genera token, lo persiste en DB y envía el email. Devuelve True si el email se envió."""
    token_raw, token_hash = _generate_reset_token()
    user.password_reset_token_hash = token_hash
    user.password_reset_expires_at = datetime.utcnow() + timedelta(seconds=_RESET_TOKEN_TTL)
    db.session.commit()

    if not resend.api_key:
        app.logger.warning("RESEND_API_KEY no configurada — email de reset no enviado.")
        return False

    reset_url = f"{_APP_BASE_URL}/reset-password/{token_raw}"
    html, text = password_reset_email(reset_url)

    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [user.email],
            "subject": "Restablece tu contraseña — marianosevilla.com",
            "html":    html,
            "text":    text,
        })
        return True
    except Exception as exc:
        app.logger.error("Error enviando email de reset: %s", exc)
        return False


def _generate_delete_token(user_id: int) -> str:
    """Genera token firmado con itsdangerous que codifica el user_id. Sin persistencia en BD."""
    s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    return s.dumps(user_id, salt=_DELETE_ACCOUNT_SALT)


def _verify_delete_token(token: str, expected_user_id: int) -> tuple[bool, str]:
    """Valida el token de eliminación. Devuelve (ok, error_msg).

    Falla si: expirado, manipulado, o pertenece a otro usuario.
    """
    s = URLSafeTimedSerializer(app.config["SECRET_KEY"])
    try:
        user_id = s.loads(token, salt=_DELETE_ACCOUNT_SALT, max_age=_DELETE_TOKEN_TTL)
    except SignatureExpired:
        return False, "El código ha expirado. Solicita uno nuevo."
    except Exception:
        return False, "Código de confirmación inválido."
    if int(user_id) != expected_user_id:
        return False, "Código de confirmación inválido."
    return True, ""


def _send_delete_account_email(user: User) -> bool:
    """Genera token firmado con itsdangerous y lo envía por email. Sin escritura en BD."""
    if not resend.api_key:
        app.logger.warning("RESEND_API_KEY no configurada — email de eliminación no enviado.")
        return False

    token   = _generate_delete_token(user.id)
    subject = "Confirma la eliminación de tu cuenta — marianosevilla.com"
    html    = f"""
<p>Has solicitado eliminar tu cuenta en <strong>marianosevilla.com</strong>.</p>
<p>Introduce este código en la página para confirmar. Es válido durante <strong>10 minutos</strong>.</p>
<p style="font-family:monospace;word-break:break-all;background:#f4f4f4;color:#111;
          padding:14px;border-radius:6px;margin:24px 0;font-size:0.9rem">{token}</p>
<p>Si no has sido tú, ignora este email. Tu cuenta permanecerá intacta.</p>
"""
    text = (
        f"Has solicitado eliminar tu cuenta en marianosevilla.com.\n\n"
        f"Código de confirmación:\n{token}\n\n"
        f"Es válido durante 10 minutos. Si no has sido tú, ignora este email."
    )

    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [user.email],
            "subject": subject,
            "html":    html,
            "text":    text,
        })
        return True
    except Exception as exc:
        app.logger.error("Error enviando email de eliminación: %s", exc)
        return False


@app.route("/login/", strict_slashes=False)
@limiter.exempt
def login_page():
    """Página dedicada de inicio de sesión."""
    if current_user.is_authenticated:
        return redirect("/dashboard")
    return send_from_directory("static", "login.html")


@app.route("/signup/", strict_slashes=False)
@limiter.exempt
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
    except Exception as exc:
        app.logger.exception("Google OAuth callback failed: %s", exc)
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
            # Explícito: el default=True de la columna solo se aplica en el
            # INSERT, y el chequeo is_active de abajo corre antes del commit.
            is_active=True,
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
    return redirect("/dashboard")


@app.route("/binance")
@login_required
@limiter.exempt
def page_binance():
    return render_template("binance_v2.html")


@app.route("/binance-v2")
@login_required
@limiter.exempt
def page_binance_v2():
    return render_template("binance_v2.html")


@app.route("/bitvavo")
@login_required
@limiter.exempt
def page_bitvavo():
    return render_template("tool.html", **EXCHANGE_PAGES["bitvavo"])


@app.route("/bit2me")
@login_required
@limiter.exempt
def page_bit2me():
    return render_template("tool.html", bit2me_excel_enabled=_BIT2ME_EXCEL_ENABLED,
                           **EXCHANGE_PAGES["bit2me"])


@app.route("/kraken")
@login_required
@limiter.exempt
def page_kraken():
    return render_template("tool.html", **EXCHANGE_PAGES["kraken"])


@app.route("/coinbase")
@login_required
@limiter.exempt
def page_coinbase():
    return render_template("tool.html", **EXCHANGE_PAGES["coinbase"])


@app.route("/nexo")
@login_required
@limiter.exempt
def page_nexo():
    return render_template("tool.html", **EXCHANGE_PAGES["nexo"])


@app.route("/cryptocom")
@login_required
@limiter.exempt
def page_cryptocom():
    return render_template("tool.html", **EXCHANGE_PAGES["cryptocom"])


@app.route("/uphold")
@login_required
@limiter.exempt
def page_uphold():
    return render_template("tool.html", **EXCHANGE_PAGES["uphold"])


@app.route("/mexc")
@login_required
@limiter.exempt
def page_mexc():
    return render_template("tool.html", **EXCHANGE_PAGES["mexc"])


@app.route("/bitget")
@login_required
@limiter.exempt
def page_bitget():
    return render_template("tool.html", **EXCHANGE_PAGES["bitget"])


@app.route("/kucoin")
@login_required
@limiter.exempt
def page_kucoin():
    return render_template("tool.html", **EXCHANGE_PAGES["kucoin"])


@app.route("/api/mexc/anos", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def api_mexc_anos():
    """Detecta ejercicios fiscales en un XLSX de MEXC sin ejecutar el análisis FIFO completo."""
    archivo = request.files.get("file")
    if not archivo:
        return jsonify({"ok": False, "error": "No se recibió ningún fichero."})

    filename = archivo.filename or ""
    if not (filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls")):
        return jsonify({"ok": False, "error": "Se requiere fichero .xls o .xlsx"})

    suffix = ".xlsx" if filename.lower().endswith(".xlsx") else ".xls"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            archivo.save(tmp.name)
            tmp_path = tmp.name

        clasificador = ClasificadorMEXC(tmp_path).clasificar()

        años: set = set()
        for op in clasificador.compraventas:
            try:
                años.add(int(op.fecha[:4]))
            except (ValueError, TypeError):
                pass
        for op in clasificador.movimientos:
            try:
                años.add(int(op.fecha[:4]))
            except (ValueError, TypeError):
                pass

        return jsonify({"ok": True, "anos": sorted(años)})

    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    except Exception as exc:
        return jsonify({"ok": False, "error": _error_amigable(exc)})
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.route("/api/bit2me/anos", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def api_bit2me_anos():
    """Detecta ejercicios fiscales en el Excel "Historial de operaciones" de Bit2Me.

    Protegido por BIT2ME_EXCEL_ENABLED. El CSV de Bit2Me detecta años en el
    navegador; el Excel es binario y se analiza aquí (patrón /api/mexc/anos)."""
    if not _BIT2ME_EXCEL_ENABLED:
        return jsonify({"ok": False, "error": "Formato no disponible."}), 404

    archivo = request.files.get("file")
    if not archivo:
        return jsonify({"ok": False, "error": "No se recibió ningún fichero."})

    filename = (archivo.filename or "").lower()
    if not (filename.endswith(".xlsx") or filename.endswith(".xls")):
        return jsonify({"ok": False, "error": "Se requiere fichero .xls o .xlsx"})

    suffix = ".xlsx" if filename.endswith(".xlsx") else ".xls"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            archivo.save(tmp.name)
            tmp_path = tmp.name

        valido, error_msg = validar_columnas_bit2me_excel(tmp_path)
        if not valido:
            return jsonify({"ok": False, "error": error_msg})

        clasificador = ClasificadorBit2MeExcel(tmp_path).clasificar()

        años: set = set()
        for grupo in (clasificador.compraventas, clasificador.swaps,
                      clasificador.rendimientos, clasificador.movimientos):
            for op in grupo:
                try:
                    años.add(int(op.fecha[:4]))
                except (ValueError, TypeError):
                    pass

        return jsonify({"ok": True, "anos": sorted(años)})

    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)})
    except Exception as exc:
        return jsonify({"ok": False, "error": _error_amigable(exc)})
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _guardar_csvs_multi(archivos, max_files: int, label: str) -> tuple:
    """Guarda varios CSV subidos en ficheros temporales (flujo multiarchivo).
    Devuelve (tmp_paths, filenames). Valida extensión y número de ficheros.
    Lanza ValueError con mensaje amigable si algo no encaja."""
    if not archivos:
        raise ValueError("No se recibió ningún fichero.")
    if len(archivos) > max_files:
        raise ValueError(f"Demasiados ficheros. Máximo {max_files} CSV por análisis.")

    tmp_paths: list = []
    filenames: list = []
    for archivo in archivos:
        fn = archivo.filename or ""
        if not fn.lower().endswith(".csv"):
            # limpiar lo ya guardado antes de abortar
            for p in tmp_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            raise ValueError(f"Todos los ficheros de {label} deben tener extensión .csv")
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            archivo.save(tmp.name)
            tmp_paths.append(tmp.name)
            filenames.append(fn)
    return tmp_paths, filenames


def _guardar_csvs_kucoin(archivos) -> tuple:
    return _guardar_csvs_multi(archivos, MAX_KUCOIN_FILES, "KuCoin")


def _guardar_csvs_bitget(archivos) -> tuple:
    return _guardar_csvs_multi(archivos, MAX_BITGET_FILES, "Bitget")


@app.route("/api/kucoin/anos", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def api_kucoin_anos():
    """Detecta ejercicios fiscales y resume los ficheros KuCoin subidos (multiarchivo)
    sin ejecutar el análisis FIFO completo. Patrón /api/mexc/anos extendido a varios CSV."""
    archivos = request.files.getlist("csv") or request.files.getlist("files")
    tmp_paths: list = []
    try:
        tmp_paths, filenames = _guardar_csvs_kucoin(archivos)

        clasificador = ClasificadorKuCoin(tmp_paths, filenames).clasificar()

        años: set = set()
        for grupo in (clasificador.compraventas, clasificador.swaps,
                      clasificador.movimientos, clasificador.rendimientos):
            for op in grupo:
                try:
                    años.add(int(str(op.fecha)[:4]))
                except (ValueError, TypeError):
                    pass

        return jsonify({
            "ok": True,
            "anos": sorted(años),
            "resumen": clasificador.resumen_archivos,
            "advertencias": clasificador.advertencias,
        })

    except (KucoinUserError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)})
    except Exception as exc:
        return jsonify({"ok": False, "error": _error_amigable(exc)})
    finally:
        for p in tmp_paths:
            try:
                os.unlink(p)
            except OSError:
                pass


@app.route("/api/bitget/anos", methods=["POST"])
@login_required
@limiter.limit("30 per minute")
def api_bitget_anos():
    """Detecta ejercicios fiscales y resume los ficheros Bitget subidos (multiarchivo)
    sin ejecutar el análisis FIFO completo. Mismo patrón que /api/kucoin/anos."""
    archivos = request.files.getlist("csv") or request.files.getlist("files")
    tmp_paths: list = []
    try:
        tmp_paths, filenames = _guardar_csvs_bitget(archivos)

        clasificador = ClasificadorBitgetMulti(tmp_paths, filenames).clasificar()

        años: set = set()
        for grupo in (clasificador.compraventas, clasificador.swaps,
                      clasificador.movimientos, clasificador.rendimientos):
            for op in grupo:
                try:
                    años.add(int(str(op.fecha)[:4]))
                except (ValueError, TypeError):
                    pass

        return jsonify({
            "ok": True,
            "anos": sorted(años),
            "resumen": clasificador.resumen_archivos,
            "advertencias": clasificador.advertencias,
        })

    except (BitgetUserError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)})
    except Exception as exc:
        return jsonify({"ok": False, "error": _error_amigable(exc)})
    finally:
        for p in tmp_paths:
            try:
                os.unlink(p)
            except OSError:
                pass


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
        if exchange not in ("binance", "bit2me", "bitvavo", "kraken", "coinbase", "nexo", "cryptocom", "uphold", "mexc", "bitget"):
            return jsonify({"error": "Exchange no soportado."}), 400

        # Validar ejercicio fiscal
        valido_ej, error_ej = _validar_ejercicio(ejercicio)
        if not valido_ej:
            return jsonify({"error": error_ej}), 400

        # Validar extensión — MEXC usa XLS/XLSX; Bit2Me admite Excel solo con el flag;
        # el resto CSV.
        filename = archivo.filename or ""
        low      = filename.lower()
        # Bit2Me en Excel: solo si el feature flag está activo.
        _bit2me_excel = (
            exchange == "bit2me" and _BIT2ME_EXCEL_ENABLED
            and (low.endswith(".xlsx") or low.endswith(".xls"))
        )
        if exchange == "mexc":
            if not (low.endswith(".xlsx") or low.endswith(".xls")):
                return jsonify({"error": "MEXC requiere el archivo XLS o XLSX exportado desde la plataforma."}), 400
            _suffix = ".xlsx"
        elif _bit2me_excel:
            _suffix = ".xlsx" if low.endswith(".xlsx") else ".xls"
        else:
            if not low.endswith(".csv"):
                return jsonify({"error": "El fichero debe tener extensión .csv"}), 400
            _suffix = ".csv"

        with tempfile.NamedTemporaryFile(suffix=_suffix, delete=False) as tmp:
            archivo.save(tmp.name)
            tmp_path = tmp.name

        t_start   = time.time()
        csv_rows  = (_contar_filas_xlsx(tmp_path)
                     if exchange == "mexc" or _bit2me_excel
                     else _contar_csv_rows(tmp_path))

        # ── límite de filas ───────────────────────────────────────────────────
        if csv_rows > MAX_CSV_ROWS:
            return jsonify({
                "error": f"El CSV tiene demasiadas filas ({csv_rows:,}). "
                         f"El máximo permitido es {MAX_CSV_ROWS:,} filas."
            }), 400
        # ─────────────────────────────────────────────────────────────────────

        # ── Evidencia técnica del archivo (best-effort, para observabilidad) ─
        _is_xlsx      = (exchange == "mexc" or _bit2me_excel)
        _ev_ctx       = _capturar_evidencia(tmp_path, exchange=exchange, is_xlsx=_is_xlsx)
        _evidencia_json = json.dumps(_ev_ctx) if _ev_ctx else None
        # Clase parser real: para Binance depende del formato detectado en _ev_ctx
        _binance_fmt  = _ev_ctx.get("exchange_format_variant") if exchange == "binance" else None
        _parser_class = (
            "ClasificadorBinanceTx"    if _binance_fmt == "tx"
            else "ClasificadorBinance" if exchange == "binance"
            else "ClasificadorBit2MeExcel" if _bit2me_excel
            else _PARSER_CLASS_MAP.get(exchange, exchange)
        )
        # ─────────────────────────────────────────────────────────────────────

        try:
            # MEXC y Bit2Me-Excel no son CSV de texto: validación propia, no _validar_csv
            if exchange == "mexc":
                pass
            elif _bit2me_excel:
                valido, error_msg = validar_columnas_bit2me_excel(tmp_path)
                if not valido:
                    return jsonify({"error": error_msg}), 400
            else:
                valido, error_msg = _validar_csv(tmp_path, exchange)
                if not valido:
                    return jsonify({"error": error_msg}), 400

            rendimientos_json = []
            motor       = None   # MotorFIFO — asignado para todos los exchanges excepto bit2me
            clasificador = None  # clasificador original — para telemetría (swaps, movimientos, desconocidas)

            if exchange == "bit2me" and _bit2me_excel:
                # Historial de operaciones Excel → MotorFIFO (estimación). Vía nueva,
                # detrás del flag BIT2ME_EXCEL_ENABLED. El path CSV no se altera.
                motor, rendimientos, clasificador = procesar_bit2me_excel(tmp_path)
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                advertencias = motor.advertencias
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf(motor, nombre, ejercicio, "Bit2Me", rendimientos)

            elif exchange == "bit2me":
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

            elif exchange == "mexc":
                motor, rendimientos, clasificador = procesar_mexc(tmp_path)
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                # MEXC puede tener advertencias sobre pares USDT en el clasificador.
                # Las fusionamos igual que Uphold para que aparezcan en UI y PDF.
                advertencias = motor.advertencias + (clasificador.advertencias if clasificador else [])
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf_mexc(motor, nombre, ejercicio, rendimientos)

            elif exchange == "bitget":
                motor, rendimientos, clasificador = procesar_bitget(tmp_path)
                _filtrar_motor_por_ejercicio(motor, ejercicio)
                rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
                resumen, posicion, operaciones = _motor_a_json(motor)
                # Bitget puede tener advertencias sobre pares USDT en el clasificador.
                advertencias = motor.advertencias + (clasificador.advertencias if clasificador else [])
                rendimientos_json = _rendimientos_a_json(rendimientos)
                pdf_bytes = generar_pdf_bitget(motor, nombre, ejercicio, rendimientos)

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

            pdf_tmp = _derivar_ruta_pdf(tmp_path)
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
                "estimacion": bool(_bit2me_excel),   # Excel Bit2Me = informe orientativo
            })

        except Exception as e:
            # ── Clasificar el error semánticamente ────────────────────────────
            # Por defecto: bug inesperado del parser.
            _err_category = "parser_error"
            _err_code     = None

            if hasattr(e, "category") and hasattr(e, "code"):
                # Excepción tipificada: MexcUnsupportedFormatError / MexcUserError
                _err_category = e.category
                _err_code     = e.code
            elif isinstance(e, ValueError) and exchange == "coinbase":
                _msg_lower = str(e).lower()
                if "cabecera" in _msg_lower or "historial completo de transacciones" in _msg_lower:
                    _err_category, _err_code = "user_error", "invalid_coinbase_header"
            elif isinstance(e, ValueError) and exchange == "mexc":
                # Heurística de fallback para ValueError sin tipar (datos históricos)
                _msg_lower = str(e).lower()
                if any(kw in _msg_lower for kw in ("futuros", "futures", "copy trading")):
                    _err_category, _err_code = "unsupported_format", "futures"
                elif "no se reconoce" in _msg_lower:
                    _err_category, _err_code = "user_error", "wrong_file"

            # Solo imprimir traceback para bugs reales del parser
            if _err_category == "parser_error":
                traceback.print_exc()

            _registrar_informe(
                exchange        = exchange,
                fiscal_year     = _ejercicio_a_fiscal_year(ejercicio),
                csv_rows        = csv_rows,
                distinct_assets = 0,
                processing_ms   = int((time.time() - t_start) * 1000),
                status          = "failed",
                error_type      = type(e).__name__,
                error_category  = _err_category,
            )
            try:
                _csv_size = os.path.getsize(tmp_path) if tmp_path else None
            except Exception:
                _csv_size = None
            try:
                record_processing_error_safe(
                    user_id        = current_user.id if current_user.is_authenticated else None,
                    email          = current_user.email if current_user.is_authenticated else None,
                    exchange       = exchange,
                    stage          = "classify",
                    exc            = e,
                    csv_filename   = filename,
                    csv_size       = _csv_size,
                    parser         = _parser_class,
                    error_category = _err_category,
                    error_code     = _err_code,
                    csv_context    = _evidencia_json,
                )
            except Exception:
                app.logger.exception("[ERROR_TRACKING] unexpected error calling record_processing_error_safe")
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


@app.route("/api/kucoin/analizar", methods=["POST"])
@login_required
@limiter.limit("3 per 10 minutes", exempt_when=_is_admin)
@limiter.limit("6 per hour",       exempt_when=_is_admin)
@limiter.limit("15 per day",       exempt_when=_is_admin)
def analizar_kucoin():
    """Análisis fiscal KuCoin — flujo MULTIARCHIVO con endpoint dedicado.

    Aislado de /api/analizar (single-file) para no añadir superficie de regresión
    a los exchanges existentes. Reutiliza los helpers comunes (motor, filtros,
    PDF genérico, token, telemetría) y el bloqueo concurrente por usuario.
    """
    uid       = current_user.id
    tmp_paths: list = []

    with _analisis_lock:
        if uid in _analisis_en_curso:
            return jsonify({
                "error": "Ya tienes un análisis en proceso. "
                         "Espera a que termine antes de lanzar otro."
            }), 409
        _analisis_en_curso.add(uid)

    t_start  = time.time()
    csv_rows = 0
    try:
        archivos  = request.files.getlist("csv") or request.files.getlist("files")
        nombre    = _sanitizar_texto(request.form.get("nombre", ""))
        ejercicio = _sanitizar_texto(request.form.get("ejercicio", ""), max_len=40)

        valido_ej, error_ej = _validar_ejercicio(ejercicio)
        if not valido_ej:
            return jsonify({"error": error_ej}), 400

        try:
            tmp_paths, filenames = _guardar_csvs_kucoin(archivos)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400

        # Límite de filas: suma de todos los ficheros.
        csv_rows = sum(_contar_csv_rows(p) for p in tmp_paths)
        if csv_rows > MAX_CSV_ROWS:
            return jsonify({
                "error": f"Los ficheros suman demasiadas filas ({csv_rows:,}). "
                         f"El máximo permitido es {MAX_CSV_ROWS:,} filas."
            }), 400

        # ── Evidencia técnica de los archivos (best-effort, para observabilidad) ─
        _ev_list        = [_capturar_evidencia(p, exchange="kucoin") for p in tmp_paths]
        _evidencia_json = json.dumps(_ev_list) if _ev_list else None
        # ─────────────────────────────────────────────────────────────────────────

        try:
            motor, rendimientos, clasificador = procesar_kucoin(tmp_paths, filenames)
            _filtrar_motor_por_ejercicio(motor, ejercicio)
            rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
            resumen, posicion, operaciones = _motor_a_json(motor)
            # Las advertencias fiscales de KuCoin (ambigüedades, productos no cubiertos,
            # pares USD) viven en el clasificador; las fusionamos con las del motor.
            advertencias = motor.advertencias + (clasificador.advertencias if clasificador else [])
            rendimientos_json = _rendimientos_a_json(rendimientos)
            pdf_bytes = generar_pdf(motor, nombre, ejercicio, "KuCoin", rendimientos)

            processing_ms   = int((time.time() - t_start) * 1000)
            distinct_assets = len({op["activo"] for op in operaciones}) if operaciones else 0
            _adv_list  = advertencias if isinstance(advertencias, list) else []
            _tel_ops   = resumen.get("operaciones_con_resultado", len(operaciones))
            _tel_swaps = len(clasificador.swaps) if clasificador is not None else 0
            _tel_mov   = len(clasificador.movimientos) if clasificador is not None else 0
            _tel_desc  = len(clasificador.desconocidas) if clasificador is not None else 0

            pdf_tmp = _derivar_ruta_pdf(tmp_paths[0])
            with open(pdf_tmp, "wb") as f:
                f.write(pdf_bytes)

            report_id = _registrar_informe(
                exchange          = "kucoin",
                fiscal_year       = _ejercicio_a_fiscal_year(ejercicio),
                csv_rows          = csv_rows,
                distinct_assets   = distinct_assets,
                processing_ms     = processing_ms,
                fifo_operations   = _tel_ops,
                fifo_swaps        = _tel_swaps,
                fifo_rendimientos = len(rendimientos_json),
                fifo_movimientos  = _tel_mov,
                fifo_advertencias = len(_adv_list),
                fifo_desconocidas = _tel_desc,
                resultado_neto    = resumen.get("resultado_neto"),
                ganancias_brutas  = resumen.get("ganancias_brutas"),
                perdidas_brutas   = resumen.get("perdidas_brutas"),
                fiscal_years_str  = (ejercicio or "")[:50],
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
                "resumen_archivos": clasificador.resumen_archivos if clasificador else {},
                "token": token,
                "estimacion": False,
            })

        except Exception as e:
            _err_category = "parser_error"
            _err_code     = None
            if hasattr(e, "category") and hasattr(e, "code"):
                _err_category = e.category
                _err_code     = e.code
            if _err_category == "parser_error":
                traceback.print_exc()

            _registrar_informe(
                exchange        = "kucoin",
                fiscal_year     = _ejercicio_a_fiscal_year(ejercicio),
                csv_rows        = csv_rows,
                distinct_assets = 0,
                processing_ms   = int((time.time() - t_start) * 1000),
                status          = "failed",
                error_type      = type(e).__name__,
                error_category  = _err_category,
            )
            try:
                record_processing_error_safe(
                    user_id        = current_user.id if current_user.is_authenticated else None,
                    email          = current_user.email if current_user.is_authenticated else None,
                    exchange       = "kucoin",
                    stage          = "classify",
                    exc            = e,
                    csv_filename   = ", ".join(filenames) if tmp_paths else "",
                    csv_size       = None,
                    parser         = "ClasificadorKuCoin",
                    error_category = _err_category,
                    error_code     = _err_code,
                    csv_context    = _evidencia_json,
                )
            except Exception:
                app.logger.exception("[ERROR_TRACKING] unexpected error calling record_processing_error_safe")
            return jsonify({"error": _error_amigable(e)}), 500

    finally:
        with _analisis_lock:
            _analisis_en_curso.discard(uid)
        for p in tmp_paths:
            try:
                os.unlink(p)
            except Exception:
                pass


@app.route("/api/bitget/analizar", methods=["POST"])
@login_required
@limiter.limit("3 per 10 minutes", exempt_when=_is_admin)
@limiter.limit("6 per hour",       exempt_when=_is_admin)
@limiter.limit("15 per day",       exempt_when=_is_admin)
def analizar_bitget():
    """Análisis fiscal Bitget — flujo MULTIARCHIVO con endpoint dedicado.

    Mismo patrón que /api/kucoin/analizar: aislado de /api/analizar (single-file)
    para no añadir superficie de regresión. La ruta single-file de /api/analizar
    con exchange=bitget se mantiene por compatibilidad.
    """
    uid       = current_user.id
    tmp_paths: list = []

    with _analisis_lock:
        if uid in _analisis_en_curso:
            return jsonify({
                "error": "Ya tienes un análisis en proceso. "
                         "Espera a que termine antes de lanzar otro."
            }), 409
        _analisis_en_curso.add(uid)

    t_start  = time.time()
    csv_rows = 0
    filenames: list = []
    try:
        archivos  = request.files.getlist("csv") or request.files.getlist("files")
        nombre    = _sanitizar_texto(request.form.get("nombre", ""))
        ejercicio = _sanitizar_texto(request.form.get("ejercicio", ""), max_len=40)

        valido_ej, error_ej = _validar_ejercicio(ejercicio)
        if not valido_ej:
            return jsonify({"error": error_ej}), 400

        try:
            tmp_paths, filenames = _guardar_csvs_bitget(archivos)
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400

        csv_rows = sum(_contar_csv_rows(p) for p in tmp_paths)
        if csv_rows > MAX_CSV_ROWS:
            return jsonify({
                "error": f"Los ficheros suman demasiadas filas ({csv_rows:,}). "
                         f"El máximo permitido es {MAX_CSV_ROWS:,} filas."
            }), 400

        # ── Evidencia técnica de los archivos (best-effort, para observabilidad) ─
        _ev_list        = [_capturar_evidencia(p, exchange="bitget") for p in tmp_paths]
        _evidencia_json = json.dumps(_ev_list) if _ev_list else None
        # ─────────────────────────────────────────────────────────────────────────

        try:
            motor, rendimientos, clasificador = procesar_bitget_multi(tmp_paths, filenames)
            _filtrar_motor_por_ejercicio(motor, ejercicio)
            rendimientos = _filtrar_rendimientos_por_ejercicio(rendimientos, ejercicio)
            resumen, posicion, operaciones = _motor_a_json(motor)
            advertencias = motor.advertencias + (clasificador.advertencias if clasificador else [])
            rendimientos_json = _rendimientos_a_json(rendimientos)
            pdf_bytes = generar_pdf_bitget(motor, nombre, ejercicio, rendimientos)

            processing_ms   = int((time.time() - t_start) * 1000)
            distinct_assets = len({op["activo"] for op in operaciones}) if operaciones else 0
            _adv_list  = advertencias if isinstance(advertencias, list) else []
            _tel_ops   = resumen.get("operaciones_con_resultado", len(operaciones))
            _tel_swaps = len(clasificador.swaps) if clasificador is not None else 0
            _tel_mov   = len(clasificador.movimientos) if clasificador is not None else 0
            _tel_desc  = len(clasificador.desconocidas) if clasificador is not None else 0

            pdf_tmp = _derivar_ruta_pdf(tmp_paths[0])
            with open(pdf_tmp, "wb") as f:
                f.write(pdf_bytes)

            report_id = _registrar_informe(
                exchange          = "bitget",
                fiscal_year       = _ejercicio_a_fiscal_year(ejercicio),
                csv_rows          = csv_rows,
                distinct_assets   = distinct_assets,
                processing_ms     = processing_ms,
                fifo_operations   = _tel_ops,
                fifo_swaps        = _tel_swaps,
                fifo_rendimientos = len(rendimientos_json),
                fifo_movimientos  = _tel_mov,
                fifo_advertencias = len(_adv_list),
                fifo_desconocidas = _tel_desc,
                resultado_neto    = resumen.get("resultado_neto"),
                ganancias_brutas  = resumen.get("ganancias_brutas"),
                perdidas_brutas   = resumen.get("perdidas_brutas"),
                fiscal_years_str  = (ejercicio or "")[:50],
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
                "resumen_archivos": clasificador.resumen_archivos if clasificador else {},
                "token": token,
                "estimacion": False,
            })

        except Exception as e:
            _err_category = "parser_error"
            _err_code     = None
            if hasattr(e, "category") and hasattr(e, "code"):
                _err_category = e.category
                _err_code     = e.code
            if _err_category == "parser_error":
                traceback.print_exc()

            _registrar_informe(
                exchange        = "bitget",
                fiscal_year     = _ejercicio_a_fiscal_year(ejercicio),
                csv_rows        = csv_rows,
                distinct_assets = 0,
                processing_ms   = int((time.time() - t_start) * 1000),
                status          = "failed",
                error_type      = type(e).__name__,
                error_category  = _err_category,
            )
            try:
                record_processing_error_safe(
                    user_id        = current_user.id if current_user.is_authenticated else None,
                    email          = current_user.email if current_user.is_authenticated else None,
                    exchange       = "bitget",
                    stage          = "classify",
                    exc            = e,
                    csv_filename   = ", ".join(filenames) if tmp_paths else "",
                    csv_size       = None,
                    parser         = "ClasificadorBitgetMulti",
                    error_category = _err_category,
                    error_code     = _err_code,
                    csv_context    = _evidencia_json,
                )
            except Exception:
                app.logger.exception("[ERROR_TRACKING] unexpected error calling record_processing_error_safe")
            return jsonify({"error": _error_amigable(e)}), 500

    finally:
        with _analisis_lock:
            _analisis_en_curso.discard(uid)
        for p in tmp_paths:
            try:
                os.unlink(p)
            except Exception:
                pass


@app.route("/api/721", methods=["POST"])
@login_required
@limiter.limit("3 per 10 minutes", exempt_when=_is_admin)
@limiter.limit("6 per hour",       exempt_when=_is_admin)
@limiter.limit("15 per day",       exempt_when=_is_admin)
def api_modelo_721():
    """
    Genera los datos estructurados del Modelo 721 (declaración informativa
    de monedas virtuales en el extranjero) a partir de un CSV de exchange.

    Fase 3A: devuelve JSON con la posición exacta a 31/12 del ejercicio
    y un bloque 'pendiente' con lo que falta para el XML AEAT (Fase 3B).

    Diferencias clave respecto a /api/analizar:
      · Ejercicio: entero único ≥ 2022 (no acepta 'all' ni multi-año).
      · No llama a _filtrar_motor_por_ejercicio (lógica IRPF).
        La fecha de corte la gestiona motor.posicion_a_fecha(31/12/ejercicio).
      · No genera PDF ni calcula ganancias/pérdidas patrimoniales.
      · Exchanges españoles (bit2me) devuelven respuesta informativa sin error.

    Body: multipart/form-data
      csv:      CSV del exchange (mismo fichero que /api/analizar)
      exchange: binance, bitvavo, kraken, coinbase, nexo, cryptocom, uphold
      ejercicio: año fiscal único ≥ 2022  (ej. "2024")

    TODO Fase 3B: aceptar report_id de FifoReport cuando se implemente
    serialización del motor, para evitar re-procesar el CSV.
    """
    uid      = current_user.id
    tmp_path = None

    # Bloqueo concurrente: comparte el mismo set que /api/analizar.
    # Un usuario no puede tener dos análisis de CSV simultáneos.
    with _analisis_lock:
        if uid in _analisis_en_curso:
            return jsonify({
                "error": "Ya tienes un análisis en proceso. "
                         "Espera a que termine antes de lanzar otro."
            }), 409
        _analisis_en_curso.add(uid)

    try:
        # ── 1. Inputs ──────────────────────────────────────────────────────────
        if "csv" not in request.files:
            return jsonify({"error": "No se recibió ningún fichero CSV."}), 400

        archivo           = request.files["csv"]
        exchange          = _sanitizar_texto(
            request.form.get("exchange", ""), max_len=20
        ).lower()
        ejercicio_raw     = _sanitizar_texto(
            request.form.get("ejercicio", ""), max_len=6
        )
        # Opcionales para generar el XML AEAT (Fase 3B.3)
        # Prioridad: campo del formulario > NIF guardado en el perfil del usuario
        nif_declarante    = _sanitizar_texto(
            request.form.get("nif_declarante", ""), max_len=15
        ).strip().upper()
        nombre_declarante = _sanitizar_texto(
            request.form.get("nombre_declarante", ""), max_len=120
        ).strip()

        if not nif_declarante and current_user.nif:
            nif_declarante = current_user.nif
        if not nombre_declarante and current_user.full_name:
            nombre_declarante = current_user.full_name

        # ── 2. Validar exchange ────────────────────────────────────────────────
        if not exchange:
            return jsonify({"error": "Falta el parámetro 'exchange'."}), 400

        _721_todos = _721_EXCHANGES_CON_MOTOR | _721_EXCHANGES_ES
        if exchange not in _721_todos:
            return jsonify({
                "error": (
                    f"Exchange '{exchange}' no reconocido. "
                    f"Exchanges soportados: {', '.join(sorted(_721_todos))}."
                )
            }), 400

        # Bit2Me y otras entidades españolas: no sujetas al 721 — respuesta
        # informativa, no un error. El usuario debe saberlo explícitamente.
        if exchange in _721_EXCHANGES_ES:
            return jsonify({
                "ok":        True,
                "modelo":    "721",
                "ejercicio": None,
                "exchange":  exchange,
                "resultado": {
                    "modelo":                  "721",
                    "potencialmente_obligado": False,
                    "informe_orientativo":     True,
                    "exchanges":               [],
                    "advertencias": [
                        "Bit2Me (Bitnovo Solutions S.L.) es una entidad española (ES). "
                        "Los activos custodiados en Bit2Me no están sujetos al Modelo 721, "
                        "que solo aplica a monedas virtuales custodiadas fuera de España. "
                        "Si usas Bit2Me Pro u otra entidad EU distinta, consulta con tu "
                        "asesor fiscal antes de declarar."
                    ],
                },
                "pendiente": {
                    "precios_historicos": [],
                    "tax_id_custodio":    [],
                    "xml_generable":      False,
                    "xml_es_borrador":    False,
                    "xml_bloqueantes":    [
                        "Bit2Me es una entidad española — no aplica Modelo 721."
                    ],
                    "xml_advertencias":   [],
                    "por_debajo_umbral":  False,
                    "completo":           True,
                },
            }), 200

        # ── 3. Validar ejercicio: único, ≥ 2022, ≤ AÑO_MAX ───────────────────
        if not ejercicio_raw or not ejercicio_raw.strip().isdigit():
            return jsonify({
                "error": (
                    "El ejercicio debe ser un año en formato numérico (ej. 2024). "
                    "El Modelo 721 no acepta 'all' ni rangos multi-año: "
                    "cada ejercicio se declara por separado."
                )
            }), 400

        ejercicio = int(ejercicio_raw.strip())
        if ejercicio < _721_PRIMER_EJERCICIO:
            return jsonify({
                "error": (
                    f"El Modelo 721 aplica desde el ejercicio {_721_PRIMER_EJERCICIO} "
                    f"(Ley 10/2021). No se puede generar para {ejercicio}."
                )
            }), 400
        if ejercicio > AÑO_MAX:
            return jsonify({
                "error": f"El ejercicio no puede ser posterior a {AÑO_MAX}."
            }), 400

        # ── 4. Validar fichero — MEXC usa XLS/XLSX, resto CSV ────────────────────
        filename = archivo.filename or ""
        if exchange == "mexc":
            if not (filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls")):
                return jsonify({
                    "error": "MEXC requiere el archivo XLS o XLSX exportado desde la plataforma."
                }), 400
            _suffix_721 = ".xlsx"
        else:
            if not filename.lower().endswith(".csv"):
                return jsonify({"error": "El fichero debe tener extensión .csv."}), 400
            _suffix_721 = ".csv"

        with tempfile.NamedTemporaryFile(suffix=_suffix_721, delete=False) as tmp:
            archivo.save(tmp.name)
            tmp_path = tmp.name

        csv_rows = _contar_filas_xlsx(tmp_path) if exchange == "mexc" else _contar_csv_rows(tmp_path)
        if csv_rows > MAX_CSV_ROWS:
            return jsonify({
                "error": (
                    f"El archivo tiene demasiadas filas ({csv_rows:,}). "
                    f"El máximo permitido es {MAX_CSV_ROWS:,} filas."
                )
            }), 400

        try:
            # MEXC usa XLSX — su validación es interna al clasificador (no _validar_csv)
            if exchange != "mexc":
                valido, error_msg = _validar_csv(tmp_path, exchange)
                if not valido:
                    return jsonify({"error": error_msg}), 400

            # ── 5. Construir motor sin filtrar por ejercicio ───────────────────
            # posicion_a_fecha(31/12/ejercicio) dentro de generar_datos_modelo_721
            # aplica la fecha de corte correctamente. Filtrar aquí rompería el FIFO.
            motor = _motor_desde_csv_721(exchange, tmp_path)

            # ── 6. Generar datos 721 (snapshot a 31/12/ejercicio) ─────────────
            datos = generar_datos_modelo_721(motor, exchange, ejercicio)

            # ── 6B. Enriquecer con precios históricos (CoinGecko / BCE) ───────
            tickers = [
                a["activo"]
                for exc in datos.get("exchanges", [])
                for a in exc.get("activos", [])
            ]
            if tickers:
                precios = obtener_precios_historicos(tickers, ejercicio)
                datos   = enriquecer_721_con_precios(datos, precios)

            # ── 7. Validación XML + bloque pendiente ──────────────────────────
            validacion = validar_para_xml(datos, nif_declarante or None)
            pendiente  = _calcular_pendiente_721(datos, validacion)

            # ── 8. Generar XML si procede ──────────────────────────────────────
            # Condiciones: NIF y nombre proporcionados, y el XML es generable.
            xml_content = None
            if nif_declarante and nombre_declarante and validacion.xml_generable:
                try:
                    xml_content, _ = generar_xml_721(
                        datos,
                        nif_declarante,
                        nombre_declarante,
                    )
                except ErrXMLBloqueado as xml_exc:
                    # Sí puede ocurrir desde la validación XSD runtime: p.ej.
                    # exchange extranjero sin posiciones a 31/12 → 0 registros
                    # de detalle (validar_para_xml no detecta este caso).
                    # Se mantiene HTTP 200 (el análisis previo es válido) pero
                    # el estado del XML pasa a bloqueado con el motivo claro,
                    # que la UI ya sabe pintar via pendiente.xml_bloqueantes.
                    pendiente["xml_bloqueantes"] = list(
                        pendiente.get("xml_bloqueantes") or []
                    ) + xml_exc.bloqueantes
                    pendiente["xml_generable"] = False
                    pendiente["completo"]      = False
                except ErrXMLInvalidoXSD as xml_exc:
                    # El XML generado no pasa el XSD oficial: no se entrega.
                    app.logger.error(
                        "M721 XML no supera el XSD AEAT: %s",
                        "; ".join(e[:200] for e in xml_exc.errores[:3]),
                    )
                    pendiente["xml_advertencias"] = list(
                        pendiente.get("xml_advertencias") or []
                    ) + [
                        "El XML generado no supera la validación contra el esquema "
                        "oficial de la AEAT y no se ha incluido en la respuesta. "
                        "Contacta con soporte si el problema persiste."
                    ]
                except Exception as xml_exc:
                    import traceback as _tb
                    _tb.print_exc()
                    # No fallar el endpoint por error de XML; el JSON es suficiente

            respuesta: dict = {
                "ok":           True,
                "modelo":       "721",
                "ejercicio":    ejercicio,
                "exchange":     exchange,
                "generado_en":  datetime.utcnow().isoformat(),
                "resultado":    datos,
                "pendiente":    pendiente,
                "nif_faltante": not bool(nif_declarante),
            }
            if xml_content is not None:
                respuesta["xml"] = xml_content

            # ── Métricas de uso (sin PII) ───────────────────────────────────
            try:
                _n_activos = sum(
                    len(ex.get("activos", []))
                    for ex in datos.get("exchanges", [])
                )
                _total_eur = None
                try:
                    from decimal import Decimal as _D
                    _vals = [
                        _D(str(a.get("valor_eur") or 0))
                        for ex in datos.get("exchanges", [])
                        for a in ex.get("activos", [])
                        if a.get("valor_eur") is not None
                    ]
                    if _vals:
                        _total_eur = float(sum(_vals))
                except Exception:
                    pass

                _estado = (
                    "bloqueado" if not pendiente.get("xml_generable")
                    else ("borrador" if pendiente.get("xml_es_borrador") else "listo")
                )
                _metrica = {
                    "event":              "721_generado",
                    "exchange":           exchange,
                    "ejercicio":          ejercicio,
                    "estado":             _estado,
                    "n_activos":          _n_activos,
                    "xml_generable":      pendiente.get("xml_generable"),
                    "xml_es_borrador":    pendiente.get("xml_es_borrador"),
                    "por_debajo_umbral":  pendiente.get("por_debajo_umbral"),
                    "tickers_sin_precio": sorted(pendiente.get("precios_historicos") or []),
                    "n_custodios_sin_id": len(pendiente.get("tax_id_custodio") or []),
                    "n_bloqueantes":      len(pendiente.get("xml_bloqueantes") or []),
                    "n_advertencias":     len(pendiente.get("xml_advertencias") or []),
                    "xml_generado":       xml_content is not None,
                    "total_eur_aprox":    round(_total_eur, 2) if _total_eur is not None else None,
                }
                app.logger.info("M721 %s", json.dumps(_metrica, ensure_ascii=False))
            except Exception:
                pass  # El logging nunca debe romper la respuesta

            return jsonify(respuesta), 200

        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": _error_amigable(e)}), 500

    finally:
        with _analisis_lock:
            _analisis_en_curso.discard(uid)
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


@app.route("/api/721/xml", methods=["POST"])
@login_required
@limiter.limit("10 per 10 minutes", exempt_when=_is_admin)
@limiter.limit("20 per hour",       exempt_when=_is_admin)
def api_721_xml():
    """
    Genera el XML del Modelo 721 con datos complementados manualmente.

    Acepta el resultado del análisis previo (campo 'datos', que corresponde
    al campo 'resultado' de la respuesta de /api/721) más los valores
    introducidos por el usuario para completar los datos pendientes:
    precios a 31/12, NIF del declarante e identificadores fiscales del custodio.

    Body JSON:
      datos:             dict  — campo 'resultado' de la respuesta de /api/721
      nif_declarante:    str   — NIF/NIE/CIF (opcional si está en el perfil)
      nombre_declarante: str   — nombre completo (opcional si está en el perfil)
      valores:           dict  — {"TICKER": {"valor_eur": 5999.99, "origen": "CoinGecko"}}
      custodios:         dict  — {"exchange_key": {"codigo_pais": "BG",
                                                    "id_type": "04", "id": "BG123"}}

    El endpoint no re-procesa el CSV: opera exclusivamente sobre los datos
    ya analizados por /api/721, aplicando los overrides manuales del usuario.
    """
    import copy

    body = request.get_json(silent=True) or {}

    # ── 1. Validar presencia del bloque de datos ──────────────────────────────
    datos = body.get("datos")
    if not isinstance(datos, dict) or "exchanges" not in datos:
        return jsonify({
            "error": "Falta el campo 'datos' con el resultado del análisis."
        }), 400

    # Sanidad básica: máx. 50 exchanges y 200 activos total para evitar payloads
    # gigantes o intentos de manipulación.
    if len(datos.get("exchanges", [])) > 50:
        return jsonify({"error": "Demasiados exchanges en el payload."}), 400
    if sum(len(e.get("activos", [])) for e in datos.get("exchanges", [])) > 200:
        return jsonify({"error": "Demasiados activos en el payload."}), 400

    # ── 2. NIF y nombre del declarante ────────────────────────────────────────
    nif_declarante = _sanitizar_texto(
        body.get("nif_declarante") or "", max_len=15
    ).strip().upper()
    nombre_declarante = _sanitizar_texto(
        body.get("nombre_declarante") or "", max_len=120
    ).strip()

    # Fallback al perfil del usuario autenticado
    if not nif_declarante and current_user.nif:
        nif_declarante = current_user.nif
    if not nombre_declarante and current_user.full_name:
        nombre_declarante = current_user.full_name

    if not nif_declarante:
        return jsonify({
            "error": (
                "Falta el NIF del declarante. "
                "Introdúcelo en el formulario o guárdalo en tu cuenta."
            )
        }), 400
    if not nombre_declarante:
        return jsonify({"error": "Falta el nombre del declarante."}), 400

    valido_nif, error_nif = _validar_nif_usuario(nif_declarante)
    if not valido_nif:
        return jsonify({"error": error_nif}), 400

    # ── 3. Overrides de precio y custodio ─────────────────────────────────────
    valores_manuales   = body.get("valores") or {}
    custodios_manuales = body.get("custodios") or {}

    if not isinstance(valores_manuales, dict):
        return jsonify({"error": "El campo 'valores' debe ser un objeto."}), 400
    if not isinstance(custodios_manuales, dict):
        return jsonify({"error": "El campo 'custodios' debe ser un objeto."}), 400

    _IDTypes_validos = {"02", "03", "04", "05", "06"}

    # ── 4. Deep copy + aplicar overrides ─────────────────────────────────────
    datos_enriquecidos = copy.deepcopy(datos)

    for exc in datos_enriquecidos.get("exchanges", []):
        exc_key = exc.get("exchange_key") or exc.get("exchange", "").lower()

        # ── Custodio manual ────────────────────────────────────────────────
        if exc_key in custodios_manuales:
            cust    = custodios_manuales[exc_key]
            nombre_c = _sanitizar_texto(
                cust.get("nombre") or "", max_len=120
            ).strip()
            pais_c  = _sanitizar_texto(
                cust.get("codigo_pais") or "", max_len=2
            ).strip().upper()
            id_type = _sanitizar_texto(
                cust.get("id_type") or "", max_len=2
            ).strip()
            id_val  = _sanitizar_texto(
                cust.get("id") or "", max_len=20
            ).strip()

            if id_type and id_type not in _IDTypes_validos:
                return jsonify({
                    "error": (
                        f"IDType '{id_type}' no válido para '{exc_key}'. "
                        f"Valores válidos: {', '.join(sorted(_IDTypes_validos))}."
                    )
                }), 400

            if id_type and id_val:
                exc["id_otro"] = {
                    "codigo_pais": pais_c or None,
                    "id_type":     id_type,
                    "id":          id_val,
                }
                if pais_c:
                    exc["codigo_pais_iso"] = pais_c
                if nombre_c:
                    exc["nombre_legal"] = nombre_c
                # Marca el custodio como identificado para _calcular_pendiente_721
                exc["nif_custodio"] = id_val

        # ── Precios manuales ───────────────────────────────────────────────
        for activo in exc.get("activos", []):
            ticker = activo.get("activo", "").upper()
            if ticker not in valores_manuales:
                continue

            val_data  = valores_manuales[ticker]
            valor_raw = val_data.get("valor_eur")
            origen    = _sanitizar_texto(
                str(val_data.get("origen") or "O"), max_len=50
            ).strip()

            try:
                valor_eur = float(str(valor_raw).replace(",", "."))
            except (TypeError, ValueError):
                return jsonify({
                    "error": f"Valor EUR inválido para {ticker}: '{valor_raw}'."
                }), 400

            if valor_eur < 0:
                return jsonify({
                    "error": (
                        f"El valor EUR de {ticker} no puede ser negativo."
                    )
                }), 400

            from decimal import Decimal as _D, ROUND_HALF_UP as _RHU
            activo["valor_eur"]    = str(
                _D(str(valor_eur)).quantize(_D("0.01"), rounding=_RHU)
            )
            activo["origen_valor"] = origen or "O"

    # ── 5. Generar XML ────────────────────────────────────────────────────────
    try:
        xml_content, validacion = generar_xml_721(
            datos_enriquecidos,
            nif_declarante,
            nombre_declarante,
        )
    except ErrXMLBloqueado as e:
        # El frontend (showXMLError) solo muestra el campo 'error': usar el
        # primer bloqueante como mensaje para que el usuario vea el motivo
        # concreto en lugar de un texto genérico.
        _motivo = (
            e.bloqueantes[0] if e.bloqueantes
            else "No podemos generar el XML todavía porque faltan datos obligatorios."
        )
        return jsonify({
            "error":       _motivo,
            "bloqueantes": e.bloqueantes,
        }), 422
    except ErrXMLInvalidoXSD as xe:
        # El XML no pasa el esquema oficial AEAT: error nuestro, no del usuario.
        # No se entrega un fichero que la AEAT rechazaría.
        app.logger.error(
            "api_721_xml: XML no supera el XSD AEAT: %s",
            "; ".join(e[:200] for e in xe.errores[:5]),
        )
        return jsonify({
            "error": (
                "El XML generado no supera la validación contra el esquema oficial "
                "de la AEAT y no se ha entregado para evitar presentar un fichero "
                "inválido. Contacta con soporte si el problema persiste."
            ),
        }), 500
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as xe:
        app.logger.error("api_721_xml error: %s", xe)
        return jsonify({
            "error": "Error interno al generar el XML. Inténtalo de nuevo."
        }), 500

    return jsonify({
        "ok":          True,
        "xml":         xml_content,
        "es_borrador": validacion.es_borrador,
        "advertencias": validacion.advertencias,
        "ejercicio":   datos_enriquecidos.get("ejercicio"),
        "exchange":    _sanitizar_texto(body.get("exchange") or "", max_len=20).lower(),
    }), 200


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
        "nif":            current_user.nif or "",
        "plan":           current_user.plan,
        "email_verified": current_user.email_verified_at is not None,
        "is_google":      current_user.google_id is not None,
        "is_admin":           _is_admin(),
        "is_fiscal_advisor":  _is_fiscal_advisor(),
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


@app.route("/api/forgot-password", methods=["POST"])
@limiter.limit("5 per hour")
def forgot_password():
    """Solicita un email de recuperación de contraseña. No revela si el email existe."""
    data  = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    _GENERIC_MSG = "Si existe una cuenta con ese email, te enviaremos un enlace para restablecer la contraseña."

    ok, _ = _validar_email(email)
    if not ok:
        return jsonify({"message": _GENERIC_MSG}), 200

    user = User.query.filter_by(email=email).first()
    if user and user.is_active and user.password_hash:
        _send_password_reset_email(user)

    return jsonify({"message": _GENERIC_MSG}), 200


@app.route("/api/reset-password", methods=["POST"])
@limiter.limit("10 per hour")
def reset_password_api():
    """Valida token y actualiza contraseña."""
    data     = request.get_json(silent=True) or {}
    token    = (data.get("token") or "").strip()
    new_pw   = data.get("password") or ""
    confirm  = data.get("confirm_password") or ""

    if not token:
        return jsonify({"error": "Token inválido o expirado."}), 400

    ok, err = _validar_password(new_pw)
    if not ok:
        return jsonify({"error": err}), 400

    if new_pw != confirm:
        return jsonify({"error": "Las contraseñas no coinciden."}), 400

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    user = User.query.filter_by(password_reset_token_hash=token_hash).first()

    if not user or not user.password_reset_expires_at:
        return jsonify({"error": "El enlace de recuperación no es válido."}), 400

    if datetime.utcnow() > user.password_reset_expires_at:
        return jsonify({"error": "El enlace de recuperación ha expirado. Solicita uno nuevo."}), 400

    if not user.is_active:
        return jsonify({"error": "Cuenta desactivada. Contacta con soporte."}), 403

    user.set_password(new_pw)
    user.password_reset_token_hash  = None
    user.password_reset_expires_at  = None
    db.session.commit()

    return jsonify({"message": "Contraseña actualizada correctamente. Ya puedes iniciar sesión."}), 200


@app.route("/reset-password/<token>")
def reset_password_page(token):
    """Sirve la página de nueva contraseña. El token va embebido en la URL para que el JS lo lea."""
    return send_from_directory("static", "reset-password.html")


@app.route("/api/update-profile", methods=["POST"])
@login_required
def update_profile():
    """Actualiza nombre y, opcionalmente, NIF del usuario autenticado."""
    data      = request.get_json(silent=True) or {}
    full_name = _sanitizar_texto(data.get("full_name") or "", max_len=150)
    if not full_name:
        return jsonify({"error": "El nombre y apellidos no pueden estar vacíos."}), 400
    current_user.full_name = _title_case(full_name)

    # NIF: opcional — solo se toca si el campo está presente en el payload
    if "nif" in data:
        nif = _normalizar_nif(_sanitizar_texto(data["nif"] or "", max_len=20))
        if nif:
            valido, error = _validar_nif_usuario(nif)
            if not valido:
                return jsonify({"error": error}), 400
        current_user.nif = nif or None

    db.session.commit()
    return jsonify({
        "message":   "Perfil actualizado.",
        "full_name": current_user.full_name,
        "nif":       current_user.nif or "",
    })


@app.route("/api/update-nif", methods=["POST"])
@login_required
def update_nif():
    """Guarda o borra el NIF/NIE/CIF del usuario autenticado."""
    data    = request.get_json(silent=True) or {}
    nif_raw = _sanitizar_texto(data.get("nif") or "", max_len=20)
    nif     = _normalizar_nif(nif_raw)

    if nif:
        valido, error = _validar_nif_usuario(nif)
        if not valido:
            return jsonify({"error": error}), 400

    current_user.nif = nif or None
    db.session.commit()
    return jsonify({"message": "NIF actualizado.", "nif_saved": bool(nif)})


@app.route("/api/delete-account/request", methods=["POST"])
@login_required
@limiter.limit("3 per hour")
def delete_account_request():
    """Solo para usuarios OAuth: genera y envía el token de confirmación por email."""
    if current_user.password_hash is not None:
        return jsonify({"error": "Usa tu contraseña para confirmar la eliminación."}), 400
    sent = _send_delete_account_email(current_user)
    if not sent:
        return jsonify({"error": "No se pudo enviar el email. Inténtalo más tarde."}), 503
    return jsonify({"ok": True, "message": "Código enviado a tu email."})


def _anonymize_user(user: User) -> None:
    """Anonimiza PII del usuario. Se llama tras verificar identidad."""
    uid = user.id
    user.email             = f"deleted_{uid}@deleted"
    user.password_hash     = None
    user.google_id         = None
    user.full_name         = None
    user.nif               = None
    user.is_active         = False
    user.email_verified_at = None
    db.session.commit()


@app.route("/api/delete-account", methods=["POST"])
@login_required
@limiter.limit("5 per hour")
def delete_account():
    """Anonimiza la cuenta tras verificar identidad.

    Usuarios con contraseña: requiere campo 'password' en el body.
    Usuarios OAuth (sin password_hash): requiere campo 'token' en el body
    (código recibido por email vía /api/delete-account/request).
    """
    data = request.get_json(silent=True) or {}

    if current_user.password_hash is not None:
        # Usuarios con contraseña
        password = data.get("password") or ""
        if not password:
            return jsonify({"error": "Introduce tu contraseña para confirmar."}), 400
        if not current_user.check_password(password):
            return jsonify({"error": "Contraseña incorrecta."}), 403
    else:
        # Usuarios OAuth — verificar token itsdangerous enviado por email
        token = (data.get("token") or "").strip()
        if not token:
            return jsonify({"error": "Introduce el código de confirmación recibido por email."}), 400
        ok, err = _verify_delete_token(token, current_user.id)
        if not ok:
            return jsonify({"error": err}), 403

    _anonymize_user(current_user)
    logout_user()
    return jsonify({"message": "Cuenta eliminada correctamente."})


# ── ADMIN STATS ──────────────────────────────────────────────────────────────

@app.route("/stats")
@require_admin_page
def stats_page():
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


@app.route("/exchanges", strict_slashes=False)
@limiter.exempt
def exchanges_hub():
    return send_from_directory("static", "exchanges.html")


@app.route("/exchanges/binance", strict_slashes=False)
@limiter.exempt
def exchanges_binance():
    return send_from_directory("static/exchanges", "binance.html")


@app.route("/exchanges/bitvavo", strict_slashes=False)
@limiter.exempt
def exchanges_bitvavo():
    return send_from_directory("static/exchanges", "bitvavo.html")


@app.route("/exchanges/kraken", strict_slashes=False)
@limiter.exempt
def exchanges_kraken():
    return send_from_directory("static/exchanges", "kraken.html")


@app.route("/exchanges/coinbase", strict_slashes=False)
@limiter.exempt
def exchanges_coinbase():
    return send_from_directory("static/exchanges", "coinbase.html")


@app.route("/exchanges/nexo", strict_slashes=False)
@limiter.exempt
def exchanges_nexo():
    return send_from_directory("static/exchanges", "nexo.html")


@app.route("/exchanges/cryptocom", strict_slashes=False)
@limiter.exempt
def exchanges_cryptocom():
    return send_from_directory("static/exchanges", "cryptocom.html")


@app.route("/exchanges/bit2me", strict_slashes=False)
@limiter.exempt
def exchanges_bit2me():
    return send_from_directory("static/exchanges", "bit2me.html")


@app.route("/bienes-homogeneos-criptomonedas", strict_slashes=False)
@limiter.exempt
def bienes_homogeneos_criptomonedas():
    return send_from_directory("static", "bienes-homogeneos-criptomonedas.html")


@app.route("/perdidas-patrimoniales-criptomonedas", strict_slashes=False)
@limiter.exempt
def perdidas_patrimoniales_criptomonedas():
    return send_from_directory("static", "perdidas-patrimoniales-criptomonedas.html")


@app.route("/compensar-perdidas-criptomonedas", strict_slashes=False)
@limiter.exempt
def compensar_perdidas_criptomonedas():
    return send_from_directory("static", "compensar-perdidas-criptomonedas.html")


@app.route("/metodo-fifo-criptomonedas", strict_slashes=False)
@limiter.exempt
def metodo_fifo_criptomonedas():
    return send_from_directory("static", "metodo-fifo-criptomonedas.html")


@app.route("/regla-dos-meses-criptomonedas", strict_slashes=False)
@limiter.exempt
def regla_dos_meses_criptomonedas():
    return send_from_directory("static", "regla-dos-meses-criptomonedas.html")


@app.route("/permuta-criptomonedas-irpf", strict_slashes=False)
@limiter.exempt
def permuta_criptomonedas_irpf():
    return send_from_directory("static", "permuta-criptomonedas-irpf.html")


@app.route("/staking-criptomonedas-irpf", strict_slashes=False)
@limiter.exempt
def staking_criptomonedas_irpf():
    return send_from_directory("static", "staking-criptomonedas-irpf.html")


@app.route("/llms.txt")
@limiter.exempt
def llms_txt():
    return send_from_directory("static", "llms.txt", mimetype="text/plain")


@app.route("/como-funciona", strict_slashes=False)
def como_funciona():
    return send_from_directory("static", "como-funciona.html")


@app.route("/modelo-721-criptomonedas", strict_slashes=False)
def modelo_721_criptomonedas():
    return send_from_directory("static", "modelo-721-criptomonedas.html")


@app.route("/herramientas", strict_slashes=False)
@limiter.exempt
def herramientas():
    return send_from_directory("static", "herramientas.html")


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
                "from": _RESEND_FROM_DISPLAY,
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
@require_admin
def api_stats():
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

    # ── EXCLUSIÓN DE ADMINS DE MÉTRICAS OPERATIVAS ───────────────────────────
    _admin_uids = []
    if ADMIN_EMAILS:
        _admin_uids = [
            uid for (uid,) in
            db.session.query(User.id)
            .filter(func.lower(User.email).in_(ADMIN_EMAILS))
            .all()
        ]
    _no_adm_rep  = [FifoReport.user_id.notin_(_admin_uids)] if _admin_uids else []
    _no_adm_usr  = [User.id.notin_(_admin_uids)]            if _admin_uids else []
    # Excluir solicitudes de admins, pero incluir las anónimas (user_id IS NULL).
    # SQL: NULL NOT IN (...) → NULL (falsy), por lo que sin el OR las solicitudes
    # anónimas desaparecerían de las estadísticas del panel.
    _no_adm_adv  = [
        or_(
            FiscalAdvisoryRequest.user_id.is_(None),
            FiscalAdvisoryRequest.user_id.notin_(_admin_uids),
        )
    ] if _admin_uids else []
    _no_adm_proc = [ProcessingError.email.notin_(list(ADMIN_EMAILS))] if ADMIN_EMAILS else []

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
    total_users   = db.session.query(func.count(User.id)).filter(*_no_adm_usr).scalar() or 0
    verified      = db.session.query(func.count(User.id)).filter(*_no_adm_usr, User.email_verified_at.isnot(None)).scalar() or 0
    activos_30d   = db.session.query(func.count(User.id)).filter(*_no_adm_usr, User.last_login >= treinta_dias_atras).scalar() or 0
    plan_free     = db.session.query(func.count(User.id)).filter(*_no_adm_usr, User.plan == "free").scalar() or 0
    plan_pro      = db.session.query(func.count(User.id)).filter(*_no_adm_usr, User.plan == "pro").scalar() or 0
    con_informes  = db.session.query(func.count(func.distinct(FifoReport.user_id))).filter(*_no_adm_rep).scalar() or 0
    usuarios_hoy  = db.session.query(func.count(User.id)).filter(*_no_adm_usr, User.created_at >= hoy_inicio).scalar() or 0

    # Registros por mes — cargamos solo created_at (evita traer objetos completos)
    u_ts = db.session.query(User.created_at).filter(*_no_adm_usr, User.created_at >= seis_meses_atras).all()
    u_bucket = defaultdict(int)
    for (ts,) in u_ts:
        if ts:
            u_bucket[ts.strftime("%Y-%m")] += 1
    usuarios_por_mes = [{"mes": k, "total": v} for k, v in sorted(u_bucket.items())]

    u_7d_raw = db.session.query(User.created_at).filter(*_no_adm_usr, User.created_at >= siete_dias_atras).all()

    # ── INFORMES FIFO — SQL aggregations ─────────────────────────────────────
    total_inf   = db.session.query(func.count(FifoReport.id)).filter(*_no_adm_rep).scalar() or 0
    gen         = db.session.query(func.count(FifoReport.id)).filter(*_no_adm_rep, FifoReport.status == "generated").scalar() or 0
    fallidos    = total_inf - gen
    descargados = db.session.query(func.count(FifoReport.id)).filter(
        *_no_adm_rep, FifoReport.status == "generated", FifoReport.downloaded_at.isnot(None)
    ).scalar() or 0
    informes_hoy = db.session.query(func.count(FifoReport.id)).filter(
        *_no_adm_rep, FifoReport.status == "generated", FifoReport.created_at >= hoy_inicio
    ).scalar() or 0

    avg_ms   = db.session.query(func.avg(FifoReport.processing_ms)).filter(*_no_adm_rep, FifoReport.status == "generated").scalar()
    avg_rows = db.session.query(func.avg(FifoReport.csv_rows)).filter(*_no_adm_rep, FifoReport.status == "generated").scalar()

    # Power users
    power_1k = db.session.query(func.count(func.distinct(FifoReport.user_id))).filter(
        *_no_adm_rep, FifoReport.status == "generated", FifoReport.csv_rows >= 1000
    ).scalar() or 0
    power_10k = db.session.query(func.count(func.distinct(FifoReport.user_id))).filter(
        *_no_adm_rep, FifoReport.status == "generated", FifoReport.csv_rows >= 10000
    ).scalar() or 0

    por_exchange_raw = (
        db.session.query(FifoReport.exchange, func.count(FifoReport.id).label("c"))
        .filter(*_no_adm_rep, FifoReport.status == "generated")
        .group_by(FifoReport.exchange)
        .order_by(func.count(FifoReport.id).desc())
        .all()
    )
    por_ejercicio_raw = (
        db.session.query(FifoReport.fiscal_year, func.count(FifoReport.id).label("c"))
        .filter(*_no_adm_rep, FifoReport.status == "generated")
        .group_by(FifoReport.fiscal_year)
        .order_by(FifoReport.fiscal_year.desc())
        .all()
    )

    # Distribución por volumen de csv_rows
    rows_all = db.session.query(FifoReport.csv_rows).filter(
        *_no_adm_rep, FifoReport.status == "generated", FifoReport.csv_rows.isnot(None)
    ).all()
    vol_bkt = defaultdict(int)
    for (r,) in rows_all:
        if   r <= 100:   vol_bkt["0–100"] += 1
        elif r <= 1000:  vol_bkt["101–1.000"] += 1
        elif r <= 3000:  vol_bkt["1.001–3.000"] += 1
        elif r <= 10000: vol_bkt["3.001–10.000"] += 1
        elif r <= 25000: vol_bkt["10.001–25.000"] += 1
        elif r <= 50000: vol_bkt["25.001–50.000"] += 1
        else:            vol_bkt["> 50.000"] += 1
    VOL_ORDER = ["0–100", "101–1.000", "1.001–3.000", "3.001–10.000",
                 "10.001–25.000", "25.001–50.000", "> 50.000"]
    por_volumen = [{"rango": k, "total": vol_bkt.get(k, 0)} for k in VOL_ORDER]

    # Distribución de volumen csv_rows por exchange
    # Carga (exchange, csv_rows) en una sola query y bucketiza en Python.
    exc_vol_raw = db.session.query(FifoReport.exchange, FifoReport.csv_rows).filter(
        *_no_adm_rep, FifoReport.status == "generated", FifoReport.csv_rows.isnot(None)
    ).all()
    _exc_vol: dict = {}   # exchange → {bucket: count, _sum: int, _max: int, _n: int}
    for exc, rows in exc_vol_raw:
        if exc not in _exc_vol:
            _exc_vol[exc] = {k: 0 for k in VOL_ORDER}
            _exc_vol[exc]["_sum"] = 0
            _exc_vol[exc]["_max"] = 0
            _exc_vol[exc]["_n"]   = 0
        if   rows <= 100:   _exc_vol[exc]["0–100"] += 1
        elif rows <= 1000:  _exc_vol[exc]["101–1.000"] += 1
        elif rows <= 3000:  _exc_vol[exc]["1.001–3.000"] += 1
        elif rows <= 10000: _exc_vol[exc]["3.001–10.000"] += 1
        elif rows <= 25000: _exc_vol[exc]["10.001–25.000"] += 1
        elif rows <= 50000: _exc_vol[exc]["25.001–50.000"] += 1
        else:               _exc_vol[exc]["> 50.000"] += 1
        _exc_vol[exc]["_sum"] += rows
        _exc_vol[exc]["_max"]  = max(_exc_vol[exc]["_max"], rows)
        _exc_vol[exc]["_n"]   += 1
    # Filtrar exchanges con ≥ 5 informes y ordenar por avg_rows desc
    _MIN_EXC = 5
    por_exchange_volumen = sorted(
        [
            {
                "exchange": exc,
                "buckets":  [d[k] for k in VOL_ORDER],
                "avg_rows": round(d["_sum"] / d["_n"]) if d["_n"] else 0,
                "max_rows": d["_max"],
                "total":    d["_n"],
            }
            for exc, d in _exc_vol.items()
            if d["_n"] >= _MIN_EXC
        ],
        key=lambda x: x["avg_rows"],
        reverse=True,
    )

    # TOP 5 usuarios por informes (emails enmascarados)
    top5_raw = (
        db.session.query(FifoReport.user_id, func.count(FifoReport.id).label("c"))
        .filter(*_no_adm_rep, FifoReport.status == "generated")
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
        .filter(*_no_adm_rep, FifoReport.status == "failed")
        .group_by(FifoReport.error_type)
        .order_by(func.count(FifoReport.id).desc())
        .limit(10)
        .all()
    )
    por_error = [{"tipo": r.error_type or "sin clasificar", "total": r.c} for r in por_error_raw]

    # Informes generados por mes (últimos 6 meses)
    inf_ts = db.session.query(FifoReport.created_at).filter(
        *_no_adm_rep, FifoReport.status == "generated", FifoReport.created_at >= seis_meses_atras
    ).all()
    inf_mes_bkt = defaultdict(int)
    for (ts,) in inf_ts:
        if ts:
            inf_mes_bkt[ts.strftime("%Y-%m")] += 1
    informes_por_mes = [{"mes": k, "total": v} for k, v in sorted(inf_mes_bkt.items())]

    inf_7d_raw = db.session.query(FifoReport.created_at).filter(
        *_no_adm_rep, FifoReport.status == "generated", FifoReport.created_at >= siete_dias_atras
    ).all()

    # ── CONTACTOS — excluye archivados ───────────────────────────────────────
    _no_arch   = [Contacto.archived_at.is_(None)]
    total_c    = db.session.query(func.count(Contacto.id)).filter(*_no_arch).scalar() or 0
    c_nuevos   = db.session.query(func.count(Contacto.id)).filter(*_no_arch, Contacto.estado == "nuevo").scalar() or 0
    c_resp     = db.session.query(func.count(Contacto.id)).filter(*_no_arch, Contacto.estado == "respondido").scalar() or 0
    por_tipo_c = (
        db.session.query(Contacto.tipo_consulta, func.count(Contacto.id).label("c"))
        .filter(*_no_arch)
        .group_by(Contacto.tipo_consulta)
        .order_by(func.count(Contacto.id).desc())
        .all()
    )

    # ── ASESORAMIENTO FISCAL ──────────────────────────────────────────────────
    PAID_ST  = {"paid_received", "under_review", "waiting_user_info", "in_progress", "completed"}
    SL       = FiscalAdvisoryRequest.STATUS_LABELS
    SVL      = FiscalAdvisoryRequest.SERVICE_LABELS

    total_adv   = db.session.query(func.count(FiscalAdvisoryRequest.id)).filter(*_no_adm_adv).scalar() or 0
    adv_pagadas = db.session.query(func.count(FiscalAdvisoryRequest.id)).filter(
        *_no_adm_adv, FiscalAdvisoryRequest.status.in_(list(PAID_ST))
    ).scalar() or 0
    adv_pend    = db.session.query(func.count(FiscalAdvisoryRequest.id)).filter(
        *_no_adm_adv, FiscalAdvisoryRequest.status.in_(["submitted", "quote_sent"])
    ).scalar() or 0
    adv_sin_asig = db.session.query(func.count(FiscalAdvisoryRequest.id)).filter(
        *_no_adm_adv,
        FiscalAdvisoryRequest.assigned_to.is_(None),
        FiscalAdvisoryRequest.status.in_(list(PAID_ST))
    ).scalar() or 0

    ing_cents = db.session.query(func.sum(FiscalAdvisoryRequest.amount_paid)).filter(
        *_no_adm_adv, FiscalAdvisoryRequest.amount_paid.isnot(None)
    ).scalar() or 0

    por_estado_adv = (
        db.session.query(FiscalAdvisoryRequest.status, func.count(FiscalAdvisoryRequest.id).label("c"))
        .filter(*_no_adm_adv)
        .group_by(FiscalAdvisoryRequest.status)
        .order_by(func.count(FiscalAdvisoryRequest.id).desc())
        .all()
    )
    por_servicio_adv = (
        db.session.query(FiscalAdvisoryRequest.service_type, func.count(FiscalAdvisoryRequest.id).label("c"))
        .filter(*_no_adm_adv)
        .group_by(FiscalAdvisoryRequest.service_type)
        .order_by(func.count(FiscalAdvisoryRequest.id).desc())
        .all()
    )
    ing_sv_raw = (
        db.session.query(FiscalAdvisoryRequest.service_type,
                         func.sum(FiscalAdvisoryRequest.amount_paid).label("s"))
        .filter(*_no_adm_adv, FiscalAdvisoryRequest.amount_paid.isnot(None))
        .group_by(FiscalAdvisoryRequest.service_type)
        .order_by(func.sum(FiscalAdvisoryRequest.amount_paid).desc())
        .all()
    )

    # Ingresos por mes — solo las 2 columnas necesarias
    adv_mes_raw = db.session.query(
        FiscalAdvisoryRequest.created_at, FiscalAdvisoryRequest.amount_paid
    ).filter(
        *_no_adm_adv,
        FiscalAdvisoryRequest.amount_paid.isnot(None),
        FiscalAdvisoryRequest.created_at >= seis_meses_atras
    ).all()
    ing_mes_bkt = defaultdict(float)
    for ts, amount in adv_mes_raw:
        if ts:
            ing_mes_bkt[ts.strftime("%Y-%m")] += (amount or 0) / 100.0

    # ── ERRORES ───────────────────────────────────────────────────────────────
    errores_24h = db.session.query(func.count(FifoReport.id)).filter(
        *_no_adm_rep, FifoReport.status == "failed", FifoReport.created_at >= veinticuatro_h
    ).scalar() or 0

    err_ts = db.session.query(FifoReport.created_at).filter(
        *_no_adm_rep, FifoReport.status == "failed", FifoReport.created_at >= seis_meses_atras
    ).all()
    err_bkt = defaultdict(int)
    for (ts,) in err_ts:
        if ts:
            err_bkt[ts.strftime("%Y-%m")] += 1
    errores_por_mes = [{"mes": k, "total": v} for k, v in sorted(err_bkt.items())]

    err_7d_raw = db.session.query(FifoReport.created_at).filter(
        *_no_adm_rep, FifoReport.status == "failed", FifoReport.created_at >= siete_dias_atras
    ).all()

    err_detail_raw = (
        db.session.query(FifoReport.created_at, FifoReport.exchange, FifoReport.user_id)
        .filter(*_no_adm_rep, FifoReport.status == "failed")
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

    # ── PROCESSING ERRORS (nueva tabla enriquecida) ───────────────────────────
    # Guard: si la migración aún no se ha aplicado, devolver lista vacía
    _proc_err_ok = False
    try:
        db.session.execute(text("SELECT id FROM processing_errors LIMIT 0"))
        _proc_err_ok = True
    except Exception:
        db.session.rollback()

    proc_err_detail = []
    if _proc_err_ok:
        # Check whether error_category columns exist in processing_errors
        _proc_cat_ok = False
        try:
            db.session.execute(text("SELECT error_category FROM processing_errors LIMIT 0"))
            _proc_cat_ok = True
        except Exception:
            db.session.rollback()

        _proc_query_cols = [
            ProcessingError.id,
            ProcessingError.created_at,
            ProcessingError.exchange,
            ProcessingError.email,
            ProcessingError.user_id,
            ProcessingError.error_type,
            ProcessingError.stage,
            ProcessingError.message_short,
            ProcessingError.fingerprint,
            ProcessingError.auto_email_sent,
            ProcessingError.resolved,
        ]
        if _proc_cat_ok:
            _proc_query_cols += [
                ProcessingError.error_category,
                ProcessingError.error_code,
            ]

        proc_err_raw = (
            db.session.query(*_proc_query_cols)
            .filter(*_no_adm_proc)
            .order_by(ProcessingError.created_at.desc())
            .limit(100)
            .all()
        )
        proc_err_detail = [{
            "id":             r.id,
            "fecha":          r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            "exchange":       r.exchange or "—",
            "usuario":        _mask_email(r.email) if r.email else "—",
            "has_contact":    bool(r.email),
            "error_type":     r.error_type or "—",
            "stage":          r.stage or "—",
            "resumen":        (r.message_short or "")[:120],
            "fingerprint":    (r.fingerprint or "")[:8],
            "email_enviado":  bool(r.auto_email_sent),
            "resuelto":       bool(r.resolved),
            "error_category": getattr(r, "error_category", None) or "legacy",
            "error_code":     getattr(r, "error_code", None),
            "accionable":     is_actionable_processing_error(
                                  r.error_type,
                                  r.stage,
                                  r.message_short,
                                  error_category=getattr(r, "error_category", None),
                              ),
        } for r in proc_err_raw]

    # ── EXCHANGE MÁS PROBLEMÁTICO ─────────────────────────────────────────────
    # Guard: error_category column may not exist on first deploy before migration
    exc_gen_map = {r.exchange: r.c for r in por_exchange_raw}
    _err_cat_col_ok = False
    try:
        db.session.execute(text("SELECT error_category FROM fifo_reports LIMIT 0"))
        _err_cat_col_ok = True
    except Exception:
        db.session.rollback()

    # Window for "exchange más problemático": last 30 days only.
    # Using the full history inflates rates with launch-period bugs already fixed,
    # making healthy exchanges appear problematic (e.g. cryptocom at 45.8% historically,
    # 0% in the last 30 days). Rolling window reflects current parser health.
    _PROB_WINDOW = treinta_dias_atras
    _MIN_UPLOADS_THRESHOLD = 5

    if _err_cat_col_ok:
        # Only count REAL parser bugs — exclude unsupported formats and user mistakes.
        # NULL legacy rows (pre-taxonomy) are treated as parser_error by default.
        exc_fail_raw = (
            db.session.query(FifoReport.exchange, func.count(FifoReport.id).label("c"))
            .filter(
                *_no_adm_rep,
                FifoReport.status == "failed",
                FifoReport.created_at >= _PROB_WINDOW,
                (FifoReport.error_category == "parser_error")
                | FifoReport.error_category.is_(None),
            )
            .group_by(FifoReport.exchange)
            .all()
        )
        # Per-exchange breakdown: how many are unsupported vs user vs parser?
        _fail_cat_raw = (
            db.session.query(
                FifoReport.exchange,
                FifoReport.error_category,
                func.count(FifoReport.id).label("c"),
            )
            .filter(*_no_adm_rep, FifoReport.status == "failed")
            .group_by(FifoReport.exchange, FifoReport.error_category)
            .all()
        )
        exc_error_breakdown: dict = {}
        for r in _fail_cat_raw:
            exc_key = r.exchange or "unknown"
            cat     = r.error_category
            bucket  = cat if cat in ("unsupported_format", "user_error", "parser_error") else "legacy"
            if exc_key not in exc_error_breakdown:
                exc_error_breakdown[exc_key] = {
                    "unsupported_format": 0,
                    "user_error":         0,
                    "parser_error":       0,
                    "legacy":             0,
                }
            exc_error_breakdown[exc_key][bucket] += r.c
    else:
        # Migration not yet applied — fall back to unfiltered count (old behavior)
        exc_fail_raw = (
            db.session.query(FifoReport.exchange, func.count(FifoReport.id).label("c"))
            .filter(
                *_no_adm_rep,
                FifoReport.status == "failed",
                FifoReport.created_at >= _PROB_WINDOW,
            )
            .group_by(FifoReport.exchange)
            .all()
        )
        exc_error_breakdown = {}

    # Denominator: uploads (ok + failed) in the same 30-day window per exchange,
    # so numerator and denominator are consistent.
    _exc_total_30d_raw = (
        db.session.query(FifoReport.exchange, func.count(FifoReport.id).label("c"))
        .filter(*_no_adm_rep, FifoReport.created_at >= _PROB_WINDOW)
        .group_by(FifoReport.exchange)
        .all()
    )
    _exc_total_30d_map = {r.exchange: r.c for r in _exc_total_30d_raw}

    exc_mas_prob        = None
    exc_mas_prob_pct    = 0.0
    exc_mas_prob_total  = 0
    for r in exc_fail_raw:
        total_exc = _exc_total_30d_map.get(r.exchange, r.c)
        if total_exc >= _MIN_UPLOADS_THRESHOLD:
            rate = round(r.c / total_exc * 100, 1)
            if rate > exc_mas_prob_pct:
                exc_mas_prob_pct   = rate
                exc_mas_prob       = r.exchange
                exc_mas_prob_total = total_exc

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
            *_no_adm_rep, _gen_filter, FifoReport.fifo_swaps.isnot(None)).scalar()
        avg_adv_raw         = db.session.query(func.avg(FifoReport.fifo_advertencias)).filter(
            *_no_adm_rep, _gen_filter, FifoReport.fifo_advertencias.isnot(None)).scalar()
        avg_rend_raw        = db.session.query(func.avg(FifoReport.fifo_rendimientos)).filter(
            *_no_adm_rep, _gen_filter, FifoReport.fifo_rendimientos.isnot(None)).scalar()

        informes_multi_year = db.session.query(func.count(FifoReport.id)).filter(
            *_no_adm_rep,
            _gen_filter,
            FifoReport.fiscal_years_str.isnot(None),
            (FifoReport.fiscal_years_str.contains(",") | (FifoReport.fiscal_years_str == "all"))
        ).scalar() or 0

        informes_con_adv    = db.session.query(func.count(FifoReport.id)).filter(
            *_no_adm_rep, _gen_filter, FifoReport.fifo_advertencias > 0
        ).scalar() or 0

        # "complejo" = tiene al menos 1 advertencia de inventario O ≥10 swaps
        informes_complejos  = db.session.query(func.count(FifoReport.id)).filter(
            *_no_adm_rep,
            _gen_filter,
            (FifoReport.fifo_advertencias > 0) | (FifoReport.fifo_swaps >= 10)
        ).scalar() or 0

        informes_gt_1k_ops  = db.session.query(func.count(FifoReport.id)).filter(
            *_no_adm_rep, _gen_filter, FifoReport.fifo_operations >= 1000
        ).scalar() or 0
        informes_gt_10k_ops = db.session.query(func.count(FifoReport.id)).filter(
            *_no_adm_rep, _gen_filter, FifoReport.fifo_operations >= 10000
        ).scalar() or 0

        exc_complexity_raw = (
            db.session.query(
                FifoReport.exchange,
                func.avg(FifoReport.fifo_advertencias).label("avg_adv"),
                func.avg(FifoReport.fifo_swaps).label("avg_swaps"),
                func.count(FifoReport.id).label("total"),
            )
            .filter(*_no_adm_rep, _gen_filter, FifoReport.fifo_advertencias.isnot(None))
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
            *_no_adm_rep,
            _gen_filter,
            (FifoReport.csv_rows >= 5000) |
            (FifoReport.fifo_swaps >= 50) |
            (FifoReport.fifo_advertencias >= 10)
        ).scalar() or 0

        # MUY COMPLEJO: fifo_advertencias ≥ 100 OR fifo_swaps ≥ 250
        usuarios_muy_complejos = db.session.query(
            func.count(func.distinct(FifoReport.user_id))
        ).filter(
            *_no_adm_rep,
            _gen_filter,
            (FifoReport.fifo_advertencias >= 100) | (FifoReport.fifo_swaps >= 250)
        ).scalar() or 0

        # MULTI-EXCHANGE: usuarios con ≥ 2 exchanges distintos
        _multi_exc_sub = (
            db.session.query(FifoReport.user_id)
            .filter(*_no_adm_rep, _gen_filter)
            .group_by(FifoReport.user_id)
            .having(func.count(func.distinct(FifoReport.exchange)) >= 2)
            .subquery()
        )
        usuarios_multi_exchange = db.session.query(func.count()).select_from(_multi_exc_sub).scalar() or 0

        # MULTI-YEAR: fiscal_years_str contiene ',' o es 'all'
        usuarios_multi_year = db.session.query(
            func.count(func.distinct(FifoReport.user_id))
        ).filter(
            *_no_adm_rep,
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
                "exchange":      exc_mas_prob or "N/A",
                "tasa_error":    exc_mas_prob_pct,
                "total_uploads": exc_mas_prob_total,
                "min_threshold": _MIN_UPLOADS_THRESHOLD,
                "ventana_dias":  30,
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
            "por_volumen":           por_volumen,
            "por_exchange_volumen":  por_exchange_volumen,
            "por_mes":               informes_por_mes,
            "top_usuarios":      top5,
            "por_error_type":           por_error,
            "exchange_error_breakdown": exc_error_breakdown,
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
            "por_mes":            errores_por_mes,
            "detalle":            errores_detalle,
            "processing_errors":  proc_err_detail,
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
    # Rutas API: devolver JSON (consumido por JS del frontend)
    if request.path.startswith("/api/"):
        return jsonify({
            "error": "Has alcanzado el límite de análisis. Por favor espera 10 minutos antes de intentarlo de nuevo."
        }), 429
    # Rutas de navegador: devolver HTML — nunca mostrar JSON a un visitante
    retry_after = getattr(e, "retry_after", None)
    wait = f"Espera {int(retry_after)} segundos e " if retry_after else "Por favor "
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="refresh" content="60;url={request.path}">
  <title>Demasiadas peticiones — Mariano Sevilla</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'DM Sans',sans-serif;background:#0b1220;color:#eef0f6;
         min-height:100vh;display:flex;flex-direction:column;
         align-items:center;justify-content:center;gap:1rem;
         text-align:center;padding:2rem}}
    h1{{font-size:1.5rem;font-weight:700}}
    p{{color:#7a8099;font-size:.95rem;line-height:1.6}}
    a{{color:#00C896;text-decoration:none}}
    a:hover{{text-decoration:underline}}
  </style>
</head>
<body>
  <h1>Demasiadas peticiones</h1>
  <p>{wait}inténtalo de nuevo en unos momentos.<br>
     Esta página se recargará automáticamente.</p>
  <a href="/">← Volver al inicio</a>
</body>
</html>"""
    return html, 429


@app.errorhandler(413)
def payload_too_large(e):
    return jsonify({"error": "El fichero supera el tamaño máximo permitido (15 MB)."}), 413


# ── ADVISORY ROUTES ──────────────────────────

@app.route("/asesoramiento-fiscal-criptomonedas", strict_slashes=False)
@limiter.exempt
def advisory_landing():
    return send_from_directory("static", "asesoramiento-fiscal.html")

@app.route("/pedir-asesoramiento", strict_slashes=False)
@app.route("/pedir-asesoramiento-fiscal", strict_slashes=False)
@login_required
@limiter.exempt
def advisory_request_page():
    return send_from_directory("static", "pedir-asesoramiento.html")

@app.route("/asesoramiento-fiscal-confirmado", strict_slashes=False)
@limiter.exempt
def advisory_confirmed():
    return send_from_directory("static", "asesoramiento-confirmado.html")

@app.route("/asesoramiento-fiscal-cancelado", strict_slashes=False)
@limiter.exempt
def advisory_cancelled():
    return send_from_directory("static", "asesoramiento-cancelado.html")

@app.route("/mis-solicitudes-fiscales", strict_slashes=False)
@require_roles("admin", on_fail_abort=404)
@limiter.exempt
def advisory_my_requests_page():
    # Restringida a admins — devuelve 404 para no revelar que existe la página.
    return send_from_directory("static", "mis-solicitudes-fiscales.html")

@app.route("/admin/asesoramiento", strict_slashes=False)
@require_fiscal_advisor_page
@limiter.exempt
def admin_advisory_page():
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
    """Crea la solicitud. Rafa revisará el caso y enviará un presupuesto por email."""
    data = request.get_json(silent=True) or {}

    # Validaciones
    service_type = (data.get("service_type") or "").strip()
    if service_type not in _ADVISORY_PRICES:
        return jsonify({"error": "Tipo de servicio inválido."}), 400

    full_name = _sanitizar_texto(data.get("full_name") or "", max_len=150)
    if not full_name:
        return jsonify({"error": "El nombre es obligatorio."}), 400
    # H4: usuario siempre autenticado aquí (@login_required). Ignorar email del
    # body para evitar que un usuario vincule solicitudes con email de un tercero.
    if not current_user.email:
        return jsonify({"error": "Tu cuenta no tiene email asociado."}), 400
    email_val = current_user.email.strip().lower()

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

    tax_country  = _sanitizar_texto(data.get("tax_residence_country") or "España", max_len=100)
    phone        = _sanitizar_texto(data.get("phone") or "", max_len=30) or None
    exchanges    = _sanitizar_texto(data.get("exchanges") or "", max_len=500) or None
    op_volume    = _sanitizar_texto(data.get("operation_volume") or "", max_len=50) or None

    billing_nif          = _sanitizar_texto(data.get("billing_nif") or "", max_len=20) or None
    billing_address      = _sanitizar_texto(data.get("billing_address") or "", max_len=255) or None
    billing_city         = _sanitizar_texto(data.get("billing_city") or "", max_len=100) or None
    billing_postal_code  = _sanitizar_texto(data.get("billing_postal_code") or "", max_len=20) or None
    billing_company_name = _sanitizar_texto(data.get("billing_company_name") or "", max_len=255) or None

    op_types = data.get("operation_types") or []
    if not isinstance(op_types, list): op_types = []
    op_types = [str(x)[:50] for x in op_types[:20]]

    cur_situation = data.get("current_situation") or []
    if not isinstance(cur_situation, list): cur_situation = []
    cur_situation = [str(x)[:100] for x in cur_situation[:20]]

    import json as _json
    advisory = FiscalAdvisoryRequest(
        user_id               = current_user.id if current_user.is_authenticated else None,
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
        status                = "submitted",
        billing_nif           = billing_nif,
        billing_address       = billing_address,
        billing_city          = billing_city,
        billing_postal_code   = billing_postal_code,
        billing_company_name  = billing_company_name,
    )
    db.session.add(advisory)
    db.session.flush()

    db.session.add(FiscalAdvisoryStatusHistory(
        request_id = advisory.id,
        status     = "submitted",
        changed_by = None,
        note       = "Solicitud recibida",
    ))
    db.session.commit()

    _send_advisory_confirmation_email(advisory)
    _send_advisory_internal_notification(advisory)

    return jsonify({"ok": True, "advisory_id": advisory.id})


# ── PAYPAL HELPERS ───────────────────────────────────────────────────────────

def _paypal_get_access_token() -> str:
    """Obtiene un Bearer token OAuth2 de PayPal (válido ~9h, sin caché intencional)."""
    import requests as _req
    resp = _req.post(
        f"{_PAYPAL_BASE_URL}/v1/oauth2/token",
        auth=(_PAYPAL_CLIENT_ID, _PAYPAL_CLIENT_SECRET),
        data={"grant_type": "client_credentials"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _paypal_create_order(advisory: "FiscalAdvisoryRequest") -> dict:
    """Crea una orden PayPal usando quoted_amount y devuelve {order_id, approval_url}.
    Se llama on-demand cuando el cliente visita /pagar/<token> y pulsa Pagar.
    """
    import requests as _req
    if not advisory.quoted_amount:
        raise ValueError("La solicitud no tiene un importe presupuestado")
    token  = _paypal_get_access_token()
    euros  = f"{advisory.quoted_amount / 100:.2f}"
    base   = _APP_BASE_URL.rstrip("/")
    token_ = advisory.payment_link_token
    payload = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "custom_id":   str(advisory.id),
            "description": advisory.service_label()[:127],
            "amount": {
                "currency_code": "EUR",
                "value": euros,
            },
        }],
        "application_context": {
            "brand_name":   "Mariano Sevilla",
            "locale":       "es-ES",
            "landing_page": "NO_PREFERENCE",
            "user_action":  "PAY_NOW",
            "return_url":   f"{base}/api/pago/paypal/capture?request_id={advisory.id}",
            "cancel_url":   f"{base}/pagar/{token_}?cancelado=1",
        },
    }
    resp = _req.post(
        f"{_PAYPAL_BASE_URL}/v2/checkout/orders",
        json=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=15,
    )
    resp.raise_for_status()
    data         = resp.json()
    order_id     = data["id"]
    approval_url = next(
        (lnk["href"] for lnk in data.get("links", []) if lnk.get("rel") == "approve"),
        None,
    )
    if not approval_url:
        raise ValueError("PayPal no devolvió approval_url")
    return {"order_id": order_id, "approval_url": approval_url}


def _paypal_capture_order(order_id: str) -> dict:
    """Ejecuta el capture de una orden PayPal aprobada. Devuelve el JSON de PayPal."""
    import requests as _req
    token = _paypal_get_access_token()
    resp  = _req.post(
        f"{_PAYPAL_BASE_URL}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _on_payment_completed(
    advisory: "FiscalAdvisoryRequest",
    amount_cents: int,
    currency: str,
    provider: str,
    capture_note: str,
) -> None:
    """Centraliza la confirmación de pago de cualquier proveedor.
    Actualiza el expediente, crea historial y envía notificaciones.
    El caller debe verificar advisory.status == 'quote_sent' antes de llamar.
    """
    now = datetime.utcnow()
    advisory.status           = "paid_received"
    advisory.amount_paid      = amount_cents
    advisory.currency         = currency.lower()
    advisory.payment_provider = provider
    advisory.paid_at          = now

    db.session.add(FiscalAdvisoryStatusHistory(
        request_id = advisory.id,
        status     = "paid_received",
        changed_by = None,
        note       = capture_note,
    ))
    db.session.commit()

    _send_advisory_payment_confirmed_email(advisory)
    _send_advisory_payment_internal_notification(advisory)


# ── ADMIN: ENVIAR PRESUPUESTO ─────────────────────────────────────────────────

@app.route("/api/admin/asesoramiento/solicitudes/<int:req_id>/enviar-presupuesto", methods=["POST"])
@require_fiscal_advisor
def advisory_enviar_presupuesto(req_id):
    """Rafa introduce el precio y el sistema envía el link de pago al cliente."""

    advisory = FiscalAdvisoryRequest.query.get_or_404(req_id)

    if advisory.status not in ("submitted", "quote_sent"):
        return jsonify({"error": f"No se puede enviar presupuesto en estado '{advisory.status}'."}), 409

    data = request.get_json(silent=True) or {}

    # Importe
    try:
        amount_euros = float(str(data.get("amount_euros", "")).replace(",", "."))
        assert amount_euros >= 1
    except Exception:
        return jsonify({"error": "Importe inválido. Debe ser un número >= 1."}), 400
    amount_cents = int(round(amount_euros * 100))

    quote_message = (data.get("message") or "").strip()[:2000] or None

    import secrets as _secrets
    from datetime import timedelta

    now                          = datetime.utcnow()
    advisory.quoted_amount       = amount_cents
    advisory.quoted_by_user_id   = current_user.id
    advisory.quote_message       = quote_message
    advisory.quote_sent_at       = now
    advisory.quote_expires_at    = now + timedelta(days=30)
    advisory.payment_link_token  = _secrets.token_urlsafe(32)
    advisory.status              = "quote_sent"
    # Invalidar cualquier orden de PayPal anterior: el capture endpoint rechaza
    # órdenes cuyo ID no coincida con el almacenado, así que limpiar aquí
    # hace que los links antiguos ya no puedan completar un pago.
    advisory.paypal_order_id     = None
    advisory.paypal_capture_id   = None

    history_note = f"Presupuesto enviado: €{amount_euros:.2f} a {advisory.email}"
    if quote_message:
        history_note += ". Mensaje incluido."
    db.session.add(FiscalAdvisoryStatusHistory(
        request_id = advisory.id,
        status     = "quote_sent",
        changed_by = current_user.id,
        note       = history_note,
    ))
    db.session.add(AdvisoryAuditLog(
        request_id = advisory.id,
        admin_id   = current_user.id,
        action     = AdvisoryAuditLog.ACTION_QUOTE_SENT,
        detail     = f"Importe: {amount_euros:.2f} € a {advisory.email}",
    ))
    db.session.commit()

    payment_url = f"{_APP_BASE_URL.rstrip('/')}/pagar/{advisory.payment_link_token}"
    email_ok    = _send_advisory_quote_email(advisory, payment_url)

    return jsonify({
        "ok":           True,
        "payment_url":  payment_url,
        "email_sent":   email_ok,
        "email_to":     advisory.email,
        # Si email_sent es False el expediente ya está guardado; el admin puede reenviar.
        "email_warning": None if email_ok else (
            f"El presupuesto se guardó correctamente pero el email a {advisory.email} "
            "no pudo enviarse. Revisa los logs de Railway."
        ),
    })


# ── ENVIAR MENSAJE SIN PRESUPUESTO ───────────────────────────────────────────

@app.route("/api/admin/asesoramiento/solicitudes/<int:req_id>/mensaje", methods=["POST"])
@require_fiscal_advisor
def advisory_enviar_mensaje(req_id):
    """Envía un mensaje al cliente sin generar presupuesto ni link de pago.

    Opcionalmente cambia el estado a 'pendiente_info'.
    Registra el mensaje como nota interna y en el historial de estados.
    """
    advisory = FiscalAdvisoryRequest.query.get_or_404(req_id)

    # No permitir mensajes en estados terminales
    _ESTADOS_BLOQUEADOS = ("paid_received", "completed", "cancelled", "refunded")
    if advisory.status in _ESTADOS_BLOQUEADOS:
        return jsonify({"error": f"No se puede enviar mensaje en estado '{advisory.status}'."}), 409

    data    = request.get_json(silent=True) or {}
    mensaje = (data.get("mensaje") or "").strip()[:4000]
    if not mensaje:
        return jsonify({"error": "El mensaje no puede estar vacío."}), 400

    set_pendiente = bool(data.get("set_pendiente_info", False))
    nuevo_estado  = advisory.status

    if set_pendiente and advisory.status not in ("paid_received", "in_progress", "completed", "cancelled", "refunded"):
        nuevo_estado      = "pendiente_info"
        advisory.status   = nuevo_estado

    # Nota interna
    author_name = current_user.full_name if hasattr(current_user, "full_name") and current_user.full_name else current_user.email
    db.session.add(AdvisoryInternalNote(
        request_id  = advisory.id,
        author_id   = current_user.id,
        author_name = f"{author_name} [mensaje enviado al cliente]",
        text        = mensaje,
    ))

    # Historial
    db.session.add(FiscalAdvisoryStatusHistory(
        request_id = advisory.id,
        status     = nuevo_estado,
        changed_by = current_user.id,
        note       = f"Mensaje enviado al cliente. Estado: {nuevo_estado}",
    ))
    db.session.add(AdvisoryAuditLog(
        request_id = advisory.id,
        admin_id   = current_user.id,
        action     = AdvisoryAuditLog.ACTION_MESSAGE_SENT,
        detail     = f"Estado resultante: {nuevo_estado} · Mensaje: {mensaje[:200]}",
    ))
    db.session.commit()

    email_ok = _send_advisory_message_email(advisory, mensaje)

    return jsonify({
        "ok":           True,
        "email_sent":   email_ok,
        "email_to":     advisory.email,
        "new_status":   nuevo_estado,
        "email_warning": None if email_ok else (
            f"El mensaje se registró pero el email a {advisory.email} "
            "no pudo enviarse. Revisa los logs de Railway."
        ),
    })


# ── PÁGINA DE PAGO PÚBLICA ────────────────────────────────────────────────────

@app.route("/pagar/<token>")
def pago_page(token):
    """Página pública de pago para el cliente. No requiere login."""
    return send_from_directory("static", "pagar.html")


# ── API: INFO DEL PRESUPUESTO (para la página /pagar/<token>) ────────────────

@app.route("/api/pago/info/<token>", methods=["GET"])
@limiter.limit("30 per minute")
def pago_info(token):
    """Devuelve los datos públicos del presupuesto para mostrar en la página de pago."""
    advisory = FiscalAdvisoryRequest.query.filter_by(payment_link_token=token).first()
    if not advisory:
        return jsonify({"error": "Enlace no válido o expirado."}), 404

    now = datetime.utcnow()

    if advisory.status == "paid_received":
        return jsonify({"state": "already_paid"})

    if advisory.status not in ("quote_sent",):
        return jsonify({"error": "Este presupuesto ya no está disponible."}), 410

    if advisory.quote_expires_at and now > advisory.quote_expires_at:
        return jsonify({"state": "expired",
                        "expired_at": advisory.quote_expires_at.isoformat()})

    return jsonify({
        "state":           "pending",
        "service_label":   advisory.service_label(),
        "tax_year":        advisory.tax_year,
        "full_name":       advisory.full_name,
        "quoted_amount":   advisory.quoted_amount,
        "quote_message":   advisory.quote_message,
        "quote_expires_at": advisory.quote_expires_at.isoformat() if advisory.quote_expires_at else None,
    })


# ── API: INICIAR PAGO (acepta presupuesto + crea orden PayPal) ───────────────

@app.route("/api/pago/iniciar/<token>", methods=["POST"])
@limiter.limit("10 per hour")
def pago_iniciar(token):
    """El cliente acepta el presupuesto y solicita el link de PayPal.
    Registra la aceptación antes de crear la orden PayPal.
    """
    if not _PAYPAL_ENABLED:
        return jsonify({"error": "El sistema de pago no está disponible. Inténtalo más tarde."}), 503

    # FOR UPDATE: bloquea la fila durante toda la transacción para evitar
    # que dos requests concurrentes creen dos órdenes de PayPal.
    advisory = (FiscalAdvisoryRequest.query
                .filter_by(payment_link_token=token)
                .with_for_update()
                .first())
    if not advisory:
        return jsonify({"error": "Enlace no válido o expirado."}), 404

    if advisory.status == "paid_received":
        return jsonify({"error": "Este presupuesto ya ha sido pagado."}), 409

    if advisory.status != "quote_sent":
        return jsonify({"error": "Este presupuesto ya no está disponible."}), 410

    now = datetime.utcnow()
    if advisory.quote_expires_at and now > advisory.quote_expires_at:
        return jsonify({"error": "El presupuesto ha caducado. Contacta con nosotros para renovarlo."}), 410

    # Registrar aceptación del presupuesto
    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or ""
    )
    advisory.quote_accepted_at           = now
    advisory.quote_acceptance_ip         = client_ip[:45]
    advisory.quote_acceptance_user_agent = (request.user_agent.string or "")[:512]

    try:
        paypal_data          = _paypal_create_order(advisory)
        advisory.paypal_order_id = paypal_data["order_id"]
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        app.logger.error("PayPal create_order error (token=%s): %s", token, exc)
        return jsonify({"error": "No se pudo conectar con PayPal. Inténtalo de nuevo."}), 502

    return jsonify({"ok": True, "redirect_url": paypal_data["approval_url"]})


# ── PAYPAL CAPTURE (return URL — pública, no requiere login) ──────────────────

@app.route("/api/pago/paypal/capture", methods=["GET"])
@limiter.limit("30 per minute")
def pago_paypal_capture():
    """PayPal redirige aquí tras el pago. Ejecuta el capture y actualiza el expediente."""
    request_id   = request.args.get("request_id", "")
    paypal_token = request.args.get("token", "")   # PayPal añade ?token=ORDER_ID

    try:
        request_id = int(request_id)
    except (ValueError, TypeError):
        return redirect("/asesoramiento-fiscal-cancelado")

    # FOR UPDATE: garantiza que si el webhook corre en paralelo,
    # solo uno de los dos procesará el pago (el segundo verá status != 'quote_sent').
    advisory = (FiscalAdvisoryRequest.query
                .filter_by(id=request_id)
                .with_for_update()
                .first())
    if not advisory:
        return redirect("/asesoramiento-fiscal-cancelado")

    # Idempotente
    if advisory.status == "paid_received":
        return redirect("/asesoramiento-fiscal-confirmado")

    if advisory.status != "quote_sent":
        return redirect("/asesoramiento-fiscal-cancelado")

    # paypal_order_id debe existir y coincidir con el token que PayPal envía.
    # Si es NULL el cliente nunca completó pago_iniciar — rechazar siempre.
    if not advisory.paypal_order_id or advisory.paypal_order_id != paypal_token:
        app.logger.warning("PayPal token mismatch/null request_id=%s stored=%s received=%s",
                           request_id, advisory.paypal_order_id, paypal_token)
        return redirect("/asesoramiento-fiscal-cancelado")

    try:
        capture_data = _paypal_capture_order(paypal_token)
    except Exception as exc:
        app.logger.error("PayPal capture error request_id=%s: %s", request_id, exc)
        token_link = advisory.payment_link_token or ""
        return redirect(f"/pagar/{token_link}?error=capture")

    capture_status = capture_data.get("status", "")
    if capture_status != "COMPLETED":
        app.logger.warning("PayPal capture status inesperado: %s", capture_status)
        token_link = advisory.payment_link_token or ""
        return redirect(f"/pagar/{token_link}?error=status")

    purchase_units = capture_data.get("purchase_units", [{}])
    captures       = purchase_units[0].get("payments", {}).get("captures", [{}])
    capture_obj    = captures[0] if captures else {}
    capture_id     = capture_obj.get("id", "")
    amount_value   = capture_obj.get("amount", {}).get("value", "0")
    currency_code  = capture_obj.get("amount", {}).get("currency_code", "EUR")

    try:
        amount_cents = int(float(amount_value) * 100)
    except ValueError:
        amount_cents = advisory.quoted_amount or 0

    advisory.paypal_order_id   = paypal_token
    advisory.paypal_capture_id = capture_id

    try:
        _on_payment_completed(
            advisory,
            amount_cents = amount_cents,
            currency     = currency_code,
            provider     = "paypal",
            capture_note = f"Pago confirmado por PayPal. Capture ID: {capture_id}",
        )
    except Exception as exc:
        db.session.rollback()
        app.logger.error("PayPal _on_payment_completed error: %s", exc)
        token_link = advisory.payment_link_token or ""
        return redirect(f"/pagar/{token_link}?error=db")

    return redirect("/asesoramiento-fiscal-confirmado")


# ── PAYPAL WEBHOOK ────────────────────────────────────────────────────────────

@app.route("/api/webhooks/paypal", methods=["POST"])
@limiter.limit("120 per minute")
def paypal_webhook():
    """Red de seguridad: PayPal notifica el pago aunque el usuario cierre la pestaña."""
    if not _PAYPAL_ENABLED:
        return "", 200

    payload = request.get_data()
    event   = {}
    try:
        import json as _json
        event = _json.loads(payload)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    # Verificación de firma — obligatoria. Si PAYPAL_WEBHOOK_ID no está configurado
    # no podemos verificar la autenticidad del evento: no procesar y registrar el error.
    if not _PAYPAL_WEBHOOK_ID:
        app.logger.critical(
            "PayPal webhook recibido pero PAYPAL_WEBHOOK_ID no está configurado. "
            "Evento ignorado. Configura la variable de entorno para activar el webhook."
        )
        return "", 200  # 200 para evitar reintentos de PayPal; el admin debe corregir la config.

    import requests as _req
    try:
        token = _paypal_get_access_token()
        verify_resp = _req.post(
            f"{_PAYPAL_BASE_URL}/v1/notifications/verify-webhook-signature",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "auth_algo":         request.headers.get("PAYPAL-AUTH-ALGO", ""),
                "cert_url":          request.headers.get("PAYPAL-CERT-URL", ""),
                "transmission_id":   request.headers.get("PAYPAL-TRANSMISSION-ID", ""),
                "transmission_sig":  request.headers.get("PAYPAL-TRANSMISSION-SIG", ""),
                "transmission_time": request.headers.get("PAYPAL-TRANSMISSION-TIME", ""),
                "webhook_id":        _PAYPAL_WEBHOOK_ID,
                "webhook_event":     event,
            },
            timeout=10,
        )
        if not verify_resp.ok or verify_resp.json().get("verification_status") != "SUCCESS":
            app.logger.warning("PayPal webhook firma inválida — evento rechazado")
            return jsonify({"error": "Signature mismatch"}), 400
    except Exception as exc:
        app.logger.error("PayPal webhook verify error: %s — evento rechazado", exc)
        return jsonify({"error": "Verification failed"}), 500

    event_type = event.get("event_type", "")

    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        resource    = event.get("resource", {})
        capture_id  = resource.get("id", "")
        custom_id   = resource.get("custom_id") or (
            resource.get("purchase_units", [{}])[0].get("custom_id", "")
            if resource.get("purchase_units") else ""
        )
        # custom_id puede venir también en supplementary_data
        if not custom_id:
            supp = resource.get("supplementary_data", {})
            custom_id = supp.get("related_ids", {}).get("order_id", "")

        # Buscar por paypal_capture_id (ya procesado vía return URL) o por custom_id.
        # FOR UPDATE: previene doble procesado si capture y webhook llegan a la vez.
        advisory = None
        if capture_id:
            advisory = (FiscalAdvisoryRequest.query
                        .filter_by(paypal_capture_id=capture_id)
                        .with_for_update()
                        .first())
        if not advisory and custom_id:
            try:
                advisory = (FiscalAdvisoryRequest.query
                            .filter_by(id=int(custom_id))
                            .with_for_update()
                            .first())
            except (ValueError, TypeError):
                pass

        if advisory and advisory.status == "quote_sent":
            amount_value  = resource.get("amount", {}).get("value", "0")
            currency_code = resource.get("amount", {}).get("currency_code", "EUR")
            try:
                amount_cents = int(float(amount_value) * 100)
            except ValueError:
                amount_cents = advisory.amount_paid or 0

            advisory.paypal_capture_id = capture_id
            try:
                _on_payment_completed(
                    advisory,
                    amount_cents = amount_cents,
                    currency     = currency_code,
                    provider     = "paypal",
                    capture_note = f"Pago confirmado por webhook PayPal. Capture ID: {capture_id}",
                )
            except Exception as exc:
                db.session.rollback()
                app.logger.error("PayPal webhook _on_payment_completed error: %s", exc)
                return "", 500

    elif event_type == "PAYMENT.CAPTURE.REFUNDED":
        resource   = event.get("resource", {})
        capture_id = resource.get("id", "")
        if capture_id:
            advisory = FiscalAdvisoryRequest.query.filter_by(paypal_capture_id=capture_id).first()
            if advisory and advisory.status not in ("refunded", "cancelled"):
                advisory.status = "refunded"
                history = FiscalAdvisoryStatusHistory(
                    request_id = advisory.id,
                    status     = "refunded",
                    changed_by = None,
                    note       = f"Reembolso confirmado por PayPal. Capture ID: {capture_id}",
                )
                db.session.add(history)
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()

    return "", 200


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
        if advisory and advisory.status == "quote_sent":
            advisory.stripe_payment_intent_id = pi_id
            try:
                _on_payment_completed(
                    advisory,
                    amount_cents = amount_total or 0,
                    currency     = session_obj.get("currency", "eur"),
                    provider     = "stripe",
                    capture_note = f"Pago confirmado por Stripe. PI: {pi_id}",
                )
            except Exception:
                db.session.rollback()
                return "", 500

    return "", 200


def _send_advisory_confirmation_email(advisory: "FiscalAdvisoryRequest"):
    """Email de confirmación al usuario — se envía al crear la solicitud.
    Independiente del flag ENABLE_ADVISORY_STATUS_EMAILS (no es cambio de estado).
    """
    if not resend.api_key:
        return
    html, text = advisory_confirmation_email(advisory)
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [advisory.email],
            "subject": "Hemos recibido tu solicitud de asesoramiento fiscal",
            "html":    html,
            "text":    text,
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
            "from":    _RESEND_FROM_DISPLAY,
            "to":      _ADVISORY_NOTIFY_EMAILS,
            "subject": f"[Asesoramiento] Nueva solicitud #{advisory.id} — {advisory.service_label()}",
            "text":    text,
        })
    except Exception as exc:
        app.logger.error("Error enviando notificación interna advisory: %s", exc)


def _send_advisory_message_email(advisory: "FiscalAdvisoryRequest", mensaje: str) -> bool:
    """Email al cliente con un mensaje del asesor, sin presupuesto ni link de pago.
    Devuelve True si el envío fue aceptado por Resend, False en caso contrario.
    """
    if not resend.api_key:
        app.logger.error(
            "RESEND_API_KEY no configurada — email de mensaje NO enviado "
            "(advisory_id=%s, to=%s)", advisory.id, advisory.email
        )
        return False

    html, text = advisory_message_email(advisory, mensaje)

    app.logger.info(
        "Enviando email de mensaje | advisory_id=%s | to=%s | from=%s",
        advisory.id, advisory.email, _RESEND_FROM_DISPLAY,
    )
    try:
        resp = resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [advisory.email],
            "subject": "Mensaje sobre tu solicitud de asesoramiento fiscal",
            "html":    html,
            "text":    text,
        })
        app.logger.info(
            "Email de mensaje enviado OK | advisory_id=%s | resend_id=%s",
            advisory.id, getattr(resp, "id", resp),
        )
        return True
    except Exception as exc:
        app.logger.error(
            "ERROR enviando email de mensaje | advisory_id=%s | to=%s | error=%s",
            advisory.id, advisory.email, exc,
        )
        return False


def _send_advisory_quote_email(advisory: "FiscalAdvisoryRequest", payment_url: str):
    """Email al cliente con el presupuesto y el link de pago.
    Devuelve True si el envío fue aceptado por Resend, False en caso contrario.
    """
    if not resend.api_key:
        app.logger.error(
            "RESEND_API_KEY no configurada — email de presupuesto NO enviado "
            "(advisory_id=%s, to=%s)", advisory.id, advisory.email
        )
        return False

    html, text = advisory_quote_email(advisory, payment_url)
    amount_str = f"{advisory.quoted_amount / 100:.2f}" if advisory.quoted_amount else "?"
    subject    = f"Tu presupuesto de asesoramiento fiscal — {amount_str} €"

    app.logger.info(
        "Enviando email de presupuesto | advisory_id=%s | to=%s | from=%s | subject=%r",
        advisory.id, advisory.email, _RESEND_FROM_DISPLAY, subject,
    )
    try:
        resp = resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [advisory.email],
            "subject": subject,
            "html":    html,
            "text":    text,
        })
        app.logger.info(
            "Email de presupuesto enviado OK | advisory_id=%s | resend_id=%s",
            advisory.id, getattr(resp, "id", resp),
        )
        return True
    except Exception as exc:
        app.logger.error(
            "ERROR enviando email de presupuesto | advisory_id=%s | to=%s | error=%s",
            advisory.id, advisory.email, exc,
        )
        return False


def _send_advisory_payment_confirmed_email(advisory: "FiscalAdvisoryRequest"):
    """Email al cliente confirmando su pago."""
    if not resend.api_key:
        return
    html, text = advisory_payment_confirmed_email(advisory)
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [advisory.email],
            "subject": "Pago confirmado — comenzamos a trabajar en tu caso",
            "html":    html,
            "text":    text,
        })
    except Exception as exc:
        app.logger.error("Error enviando email pago confirmado advisory: %s", exc)


def _send_advisory_payment_internal_notification(advisory: "FiscalAdvisoryRequest"):
    """Email interno a Rafa cuando un cliente paga."""
    if not resend.api_key or not _ADVISORY_NOTIFY_EMAILS:
        return
    html, text = advisory_payment_internal_email(advisory)
    amount_str = f"{advisory.amount_paid / 100:.2f} €" if advisory.amount_paid else "?"
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      _ADVISORY_NOTIFY_EMAILS,
            "subject": f"💰 Pago confirmado — {advisory.full_name} · {amount_str}",
            "html":    html,
            "text":    text,
        })
    except Exception as exc:
        app.logger.error("Error enviando notificación interna pago advisory: %s", exc)


def _send_advisory_status_update_email(advisory: "FiscalAdvisoryRequest", note: str = "") -> None:
    """Email al usuario cuando el admin cambia el estado de su solicitud.

    Requiere ENABLE_ADVISORY_STATUS_EMAILS=true para enviar.
    Si está deshabilitado, solo registra un log informativo.

    Estados que generan email: under_review, waiting_user_info, in_progress,
    completed, cancelled.
    Omitidos: submitted, quote_sent, paid_received, refunded.
    """
    html, text = advisory_status_email(advisory, note=note, app_base_url=_APP_BASE_URL)
    if html is None:
        return

    _STATUS_SUBJECTS = {
        "under_review":      "Tu caso está siendo revisado",
        "waiting_user_info": "Necesitamos información adicional",
        "in_progress":       "Tu caso está en curso",
        "completed":         "Tu caso ha sido completado",
        "cancelled":         "Solicitud cerrada",
    }
    subject = _STATUS_SUBJECTS.get(advisory.status)
    if not subject:
        return

    if not _ADVISORY_STATUS_EMAILS_ENABLED:
        app.logger.info(
            "[advisory email] DESHABILITADO (ENABLE_ADVISORY_STATUS_EMAILS=false). "
            "Se habría enviado '%s' a %s (solicitud #%s).",
            subject, advisory.email, advisory.id,
        )
        return

    if not resend.api_key:
        return

    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [advisory.email],
            "subject": subject,
            "html":    html,
            "text":    text,
        })
        app.logger.info(
            "[advisory email] Enviado '%s' a %s (solicitud #%s).",
            subject, advisory.email, advisory.id,
        )
    except Exception as exc:
        app.logger.error(
            "[advisory email] Error enviando estado=%s solicitud #%s: %s",
            advisory.status, advisory.id, exc,
        )


@app.route("/api/asesoramiento/files/<int:request_id>", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def advisory_upload_file(request_id):
    """Sube un fichero asociado a una solicitud (solo el propietario)."""
    if not _ADVISORY_UPLOADS_ENABLED:
        return jsonify({"error": "La subida de archivos está desactivada. La documentación se gestiona por email."}), 410
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
@require_fiscal_advisor
def admin_advisory_list():

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
@require_fiscal_advisor
def admin_advisory_detail(request_id):
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
    # Notas internas estructuradas — más recientes primero
    d["notes"] = [
        n.to_dict()
        for n in sorted(advisory.notes, key=lambda x: x.created_at, reverse=True)
    ]
    return jsonify(d)


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>/estado", methods=["POST"])
@require_fiscal_advisor
def admin_advisory_change_status(request_id):
    advisory    = FiscalAdvisoryRequest.query.get_or_404(request_id)
    data        = request.get_json(silent=True) or {}
    new_status  = (data.get("status") or "").strip()
    note        = (data.get("note") or "").strip()[:1000]
    valid_statuses = list(FiscalAdvisoryRequest.STATUS_LABELS.keys())
    if new_status not in valid_statuses:
        return jsonify({"error": "Estado inválido."}), 400
    old_status      = advisory.status
    advisory.status = new_status
    history = FiscalAdvisoryStatusHistory(
        request_id = advisory.id,
        status     = new_status,
        changed_by = current_user.id,
        note       = note or None,
    )
    db.session.add(history)

    # Determinar la acción de auditoría
    if new_status == "completed":
        audit_action = AdvisoryAuditLog.ACTION_COMPLETED
    elif new_status == "cancelled":
        audit_action = AdvisoryAuditLog.ACTION_CANCELLED
    else:
        audit_action = AdvisoryAuditLog.ACTION_STATUS_CHANGED
    db.session.add(AdvisoryAuditLog(
        request_id = advisory.id,
        admin_id   = current_user.id,
        action     = audit_action,
        detail     = f"{old_status} → {new_status}" + (f" · {note}" if note else ""),
    ))

    db.session.commit()
    _send_advisory_status_update_email(advisory, note)
    return jsonify({"ok": True, "status": new_status, "status_label": advisory.status_label()})


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>/is-test", methods=["POST"])
@require_roles("admin")
def admin_advisory_set_is_test(request_id):
    """Marca o desmarca una solicitud como 'prueba'. Solo admins."""
    advisory      = FiscalAdvisoryRequest.query.get_or_404(request_id)
    data          = request.get_json(silent=True) or {}
    advisory.is_test = bool(data.get("is_test", False))
    db.session.commit()
    return jsonify({"ok": True, "is_test": advisory.is_test})


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>/nota", methods=["POST"])
@require_fiscal_advisor
def admin_advisory_add_note(request_id):
    advisory = FiscalAdvisoryRequest.query.get_or_404(request_id)
    data     = request.get_json(silent=True) or {}
    text     = (data.get("nota") or "").strip()[:2000]
    if not text:
        return jsonify({"error": "La nota no puede estar vacía."}), 400

    author_name = (current_user.full_name or current_user.email or "Admin").strip()
    note = AdvisoryInternalNote(
        request_id  = advisory.id,
        author_id   = current_user.id,
        author_name = author_name,
        text        = text,
    )
    db.session.add(note)
    # Tocar updated_at explícitamente (onupdate solo actúa en columnas del modelo)
    advisory.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "note": note.to_dict()})


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>", methods=["DELETE"])
@require_roles("admin")
def admin_advisory_delete(request_id):
    """Elimina una solicitud. Solo accesible para administradores.
    Los asesores fiscales reciben 403.
    El cascade de SQLAlchemy elimina automáticamente notas, historial y archivos.
    """
    advisory = FiscalAdvisoryRequest.query.get_or_404(request_id)

    # Registrar en auditoría antes de borrar (el id ya no existirá después)
    detail_parts = [f"Solicitud de {advisory.full_name} <{advisory.email}>"]
    if advisory.amount_paid and advisory.amount_paid > 0:
        detail_parts.append(f"Con pago de {advisory.amount_paid / 100:.2f} €")
    if advisory.status:
        detail_parts.append(f"Estado: {advisory.status_label()}")

    db.session.add(AdvisoryAuditLog(
        request_id = advisory.id,
        admin_id   = current_user.id,
        action     = AdvisoryAuditLog.ACTION_DELETED,
        detail     = " · ".join(detail_parts),
    ))

    db.session.delete(advisory)
    db.session.commit()
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# BIBLIOTECA DE RECURSOS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Páginas públicas ──────────────────────────────────────────────────────────

@app.route("/recursos", strict_slashes=False)
@limiter.exempt
def recursos_library():
    resources = Resource.query.filter_by(is_active=True).order_by(Resource.created_at.desc()).all()
    return render_template("recursos.html", resources=resources)


@app.route("/recursos/<slug>", strict_slashes=False)
@limiter.exempt
def recurso_detail(slug):
    resource = Resource.query.filter_by(slug=slug, is_active=True).first_or_404()
    return render_template("recurso.html", resource=resource)


# ── API pública — formulario de solicitud ─────────────────────────────────────

@app.route("/api/recursos/solicitar", methods=["POST"])
@limiter.limit("5 per hour")
def resource_solicitar():
    data = request.get_json(silent=True) or {}

    resource_id       = data.get("resource_id")
    name              = (data.get("name") or "").strip()[:150]
    email_val         = (data.get("email") or "").strip()[:254].lower()
    exchange          = (data.get("exchange") or "").strip()[:50] or None
    bitvavo_status    = (data.get("bitvavo_status") or "").strip()[:50] or None
    uid               = (data.get("uid") or "").strip()[:100] or None
    uid_unknown       = bool(data.get("uid_unknown"))
    telegram_user     = (data.get("telegram_user") or "").strip()[:100] or None
    legal_accepted    = bool(data.get("legal_accepted"))
    marketing_consent = bool(data.get("marketing_consent"))

    # Validación
    if not name:
        return jsonify({"error": "El nombre es obligatorio."}), 400
    if not email_val or "@" not in email_val:
        return jsonify({"error": "El email no es válido."}), 400
    if not legal_accepted:
        return jsonify({"error": "Debes aceptar la política de privacidad."}), 400
    if not marketing_consent:
        return jsonify({"error": "Debes aceptar recibir comunicaciones del canal."}), 400

    resource = Resource.query.filter_by(id=resource_id, is_active=True).first() if resource_id else None
    if not resource:
        return jsonify({"error": "Recurso no encontrado."}), 404

    # UID obligatorio salvo que el usuario marque que no lo conoce
    if not uid and not uid_unknown:
        return jsonify({"error": "Introduce tu UID o marca que no sabes dónde encontrarlo."}), 400

    valid_exchanges = {"bitvavo", "binance", None}
    if exchange not in valid_exchanges:
        return jsonify({"error": "Exchange no válido."}), 400

    valid_bitvavo = {"registered_via_link", "had_account", "no_account", "not_sure", None}
    if bitvavo_status not in valid_bitvavo:
        bitvavo_status = None

    rr = ResourceRequest(
        resource_id       = resource.id,
        name              = name,
        email             = email_val,
        exchange          = exchange,
        bitvavo_status    = bitvavo_status,
        uid               = uid,
        uid_unknown       = uid_unknown,
        telegram_user     = telegram_user,
        source            = None,
        legal_accepted    = True,
        marketing_consent = True,
        status            = "recibido",
        ip                = request.headers.get("X-Forwarded-For", request.remote_addr or "")[:45],
    )
    db.session.add(rr)
    db.session.commit()

    _send_resource_confirmation_email(rr, resource)
    _send_resource_internal_notification(rr, resource)

    return jsonify({"ok": True, "id": rr.id}), 201


# ── Email helpers — recursos ──────────────────────────────────────────────────

def _send_resource_confirmation_email(rr: "ResourceRequest", resource: "Resource"):
    if not resend.api_key:
        app.logger.warning("RESEND_API_KEY no configurada — confirmación de recurso no enviada.")
        return
    html, text = resource_request_confirmation_email(rr, resource)
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [rr.email],
            "subject": f"Solicitud recibida — {resource.title}",
            "html":    html,
            "text":    text,
        })
    except Exception as exc:
        app.logger.error("Error enviando confirmación de recurso #%s: %s", rr.id, exc)


def _send_resource_internal_notification(rr: "ResourceRequest", resource: "Resource"):
    if not resend.api_key or not _RESOURCE_NOTIFY_EMAIL:
        return
    html, text = resource_request_internal_email(rr, resource, _APP_BASE_URL)
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [_RESOURCE_NOTIFY_EMAIL],
            "subject": f"[Recursos] Nueva solicitud #{rr.id} — {resource.title}",
            "html":    html,
            "text":    text,
        })
    except Exception as exc:
        app.logger.error("Error enviando notificación interna de recurso #%s: %s", rr.id, exc)


# ── Admin — panel de solicitudes de recursos ──────────────────────────────────

@app.route("/admin/contactos", strict_slashes=False)
@require_admin_page
@limiter.exempt
def admin_contactos_page():
    return send_from_directory("static", "admin-contactos.html")


@app.route("/admin/recursos", strict_slashes=False)
@require_fiscal_advisor_page
@limiter.exempt
def admin_recursos_page():
    return send_from_directory("static", "admin-recursos.html")


@app.route("/api/admin/recursos/solicitudes")
@require_fiscal_advisor
def admin_recursos_list():
    status_filter = request.args.get("status", "")
    q = ResourceRequest.query
    if status_filter:
        q = q.filter_by(status=status_filter)
    items = q.order_by(ResourceRequest.created_at.desc()).limit(500).all()
    resource_titles = {r.id: r.title for r in Resource.query.all()}
    result = []
    for rr in items:
        d = rr.to_dict()
        d["resource_title"] = resource_titles.get(rr.resource_id, "—")
        result.append(d)
    return jsonify(result)


@app.route("/api/admin/recursos/solicitudes/<int:req_id>")
@require_fiscal_advisor
def admin_recursos_detail(req_id):
    rr = ResourceRequest.query.get_or_404(req_id)
    d  = rr.to_dict(full=True)
    d["resource_title"] = rr.resource.title if rr.resource else "—"
    return jsonify(d)


@app.route("/api/admin/recursos/solicitudes/<int:req_id>/estado", methods=["POST"])
@require_fiscal_advisor
def admin_recursos_change_status(req_id):
    rr         = ResourceRequest.query.get_or_404(req_id)
    data       = request.get_json(silent=True) or {}
    new_status = (data.get("status") or "").strip()
    if new_status not in ResourceRequest.STATUS_LABELS:
        return jsonify({"error": "Estado inválido."}), 400
    rr.status     = new_status
    rr.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "status": new_status, "status_label": rr.status_label()})


@app.route("/api/admin/recursos/solicitudes/<int:req_id>/nota", methods=["POST"])
@require_fiscal_advisor
def admin_recursos_add_note(req_id):
    rr   = ResourceRequest.query.get_or_404(req_id)
    data = request.get_json(silent=True) or {}
    text = (data.get("nota") or "").strip()[:2000]
    if not text:
        return jsonify({"error": "La nota no puede estar vacía."}), 400
    author = (current_user.full_name or current_user.email or "Admin").strip()
    ts     = datetime.utcnow().strftime("%d/%m/%Y %H:%M")
    prefix = f"[{ts} — {author}]\n"
    rr.internal_notes = (rr.internal_notes or "") + ("\n\n" if rr.internal_notes else "") + prefix + text
    rr.updated_at     = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "internal_notes": rr.internal_notes})


@app.route("/api/admin/recursos/solicitudes/<int:req_id>", methods=["DELETE"])
@require_fiscal_advisor
def admin_recursos_delete(req_id):
    rr = ResourceRequest.query.get_or_404(req_id)
    db.session.delete(rr)
    db.session.commit()
    return jsonify({"ok": True})


# ── ADMIN CONTACTOS ───────────────────────────────────────────────────────────

@app.route("/api/admin/contactos")
@require_admin
def admin_contactos_lista():
    """Lista todos los contactos. Admins únicamente.
    Query params opcionales:
      - archivados=1  → incluye archivados (por defecto solo activos)
      - estado=nuevo|respondido|...
    """

    incluir_archivados = request.args.get("archivados") == "1"
    filtros = []
    if not incluir_archivados:
        filtros.append(Contacto.archived_at.is_(None))
    estado_q = request.args.get("estado")
    if estado_q:
        filtros.append(Contacto.estado == estado_q)

    contactos = (
        Contacto.query
        .filter(*filtros)
        .order_by(Contacto.created_at.desc())
        .all()
    )

    def _mask(email):
        p = email.split("@")
        return (p[0][:2] + "***@" + p[1]) if len(p) == 2 else "***"

    return jsonify([{
        "id":            c.id,
        "created_at":    c.created_at.strftime("%Y-%m-%d %H:%M"),
        "nombre":        c.nombre,
        "email":         c.email,          # real — endpoint admin-only
        "email_mask":    _mask(c.email),   # para sidebar (privacidad visual)
        "tipo_consulta": c.tipo_consulta,
        "estado":        c.estado,
        "archived_at":   c.archived_at.strftime("%Y-%m-%d %H:%M") if c.archived_at else None,
        "mensaje_corto": (c.mensaje or "")[:120],
    } for c in contactos])


_ACCIONES_CONTACTO = {"responder", "archivar", "desarchivar"}

@app.route("/api/admin/contactos/<int:contacto_id>", methods=["PATCH"])
@require_admin
def admin_contactos_patch(contacto_id):
    """Actualiza estado o archivado de un contacto. Admins únicamente.
    Body JSON: { "accion": "responder" | "archivar" | "desarchivar" }
    """

    data   = request.get_json(silent=True) or {}
    accion = (data.get("accion") or "").strip().lower()
    if accion not in _ACCIONES_CONTACTO:
        return jsonify({"error": f"Acción no reconocida. Valores válidos: {sorted(_ACCIONES_CONTACTO)}"}), 400

    c = Contacto.query.get_or_404(contacto_id)

    if accion == "responder":
        c.estado = "respondido"
    elif accion == "archivar":
        c.archived_at = datetime.utcnow()
    elif accion == "desarchivar":
        c.archived_at = None

    db.session.commit()
    return jsonify({
        "ok":          True,
        "id":          c.id,
        "estado":      c.estado,
        "archived_at": c.archived_at.strftime("%Y-%m-%d %H:%M") if c.archived_at else None,
    })


if __name__ == "__main__":
    os.makedirs("static", exist_ok=True)
    app.run(debug=False, port=5050)
