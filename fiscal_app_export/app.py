Warning: truncated output (original token count: 83380)
Total output lines: 7455

"""
Backend Flask — Herramienta Fiscal Cripto
Mariano Sevilla — marianosevilla.com

Seguridad aplicada:
- Rate limiting: 1 análisis por 10 minutos por IP
- CORS restringido a dominios propios
- Security headers (CSP, HSTS, X-Frame-Options, etc.)
- Validación estricta de CSV (extensión + tamaño + contenido + exchange)
- Validación de ejercicio fiscal IRPF (2009 – año actual en España)
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
import math
import tempfile
from io import BytesIO
import fifo_pdf_lifecycle as _pdf_lifecycle
import traceback
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, send_file, send_from_directory, redirect, url_for, render_template, session, abort, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS
from flask_compress import Compress
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from authlib.integrations.flask_client import OAuth
from authlib.oidc.core import UserInfo
from advisory_prefreeze import advisory_financial_prefreeze, refuse_advisory_financial_operation
from advisory_s01_c2_management import (
    C2_TARGET_STATES, c2_can_change_state, c2_change_internal_state,
    C2ProtectedState,
)
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
from models import FiscalAdvisoryRequest, FiscalAdvisoryFile, FiscalAdvisoryStatusHistory, AdvisoryInternalNote, AdvisoryAuditLog, S01StripeCheckoutAttempt
from advisory_s01_pricing import calculate_s01_quote, QuotePricingError, COMMISSION_RATE_BPS
from models import Resource, ResourceRequest
from error_tracking import record_processing_error_safe, is_actionable_processing_error

sys.path.insert(0, os.path.dirname(__file__))

from clasificador import ClasificadorBinance
from clasificador_binance_tx import ClasificadorBinanceTx
from clasificador_binance_multi import ClasificadorBinanceMulti, BinanceMultiUserError
from binance_uploads import save_binance_uploads, BinanceUploadError
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
from security_config import build_security_config
from auth_flow import AUTH_POST_PATHS, safe_auth_next, session_user_id
from auth_timing import LoginTiming
from urllib.parse import urlencode
from sqlalchemy.exc import IntegrityError
import hmac
from staging_isolation import (
    validate_staging_isolation,
    staging_request_denial,
    install_staging_email_barrier,
)
from lab_isolation import (
    validate_lab_isolation,
    lab_request_denial,
    install_lab_email_barrier,
)

app = Flask(__name__, static_folder="static")

# Proxy fix: necesario para que url_for() genere https:// en producción detrás de nginx
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

Compress(app)


# ── CONFIGURACIÓN ─────────────────────────────
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Valida secretos, modo y cookies ANTES de inicializar DB o ejecutar su bootstrap.
# Por defecto exige clave real y HTTPS; sólo development/testing locales explícitos
# permiten una excepción. No altera la clave suministrada ni las firmas existentes.
app.config.update(build_security_config(os.environ))

# El catálogo de mercado se genera offline desde Binance Vision con ZIP +
# CHECKSUM; nunca se construye a partir de CSV privados ni se descarga aquí.
# Ambas variables son operativas: si se instala solo una, fallar al arrancar.
_binance_catalog_path = (os.environ.get("BINANCE_MARKET_CATALOG_PATH") or "").strip()
_binance_catalog_hash = (os.environ.get("BINANCE_MARKET_CATALOG_SHA256") or "").strip()
if bool(_binance_catalog_path) != bool(_binance_catalog_hash):
    raise RuntimeError("Configuración incompleta de catálogo Binance verificado")
if _binance_catalog_path:
    from binance_verified_price_catalog import load_pinned_verified_catalog
    app.config["BINANCE_VERIFIED_MARKET_PRICES"] = load_pinned_verified_catalog(
        _binance_catalog_path, expected_sha256=_binance_catalog_hash
    )

# STG-LOCK-001: preserve preflight firewall from the dedicated staging branch.
# Validate the Railway identity, isolated PostgreSQL hostname, and absence
# of provider credentials BEFORE db.init_app() or any migration/financial route.
# Deliberately no lab-mode override in deployed staging: synthetic E2E runs
# only with FLASK_ENV=testing and an ephemeral, fixture-only CI database.
# STG-B04/B06: resolve identities BEFORE database initialization.
# Real lab service and private HTTP origin are pinned, but every runtime marker
# must match; no boolean LAB_MODE bypass and no network/DB I/O in this gate.
# The original staging firewall is not weakened by this mutually exclusive path.
_LAB_ISOLATED = validate_lab_isolation(os.environ)
_STAGING_ISOLATED = False if _LAB_ISOLATED else validate_staging_isolation(os.environ)
if _LAB_ISOLATED:
    install_lab_email_barrier(resend)

    @app.before_request
    def _lab_preflight_lockdown():
        denial = lab_request_denial(
            host=request.host,
            path=request.path,
            method=request.method,
            origin=request.headers.get("Origin"),
        )
        if denial is not None:
            status, message = denial
            headers = {"Cache-Control": "no-store"}
            if status == 503:
                headers["Retry-After"] = "300"
            return jsonify({"error": message}), status, headers

if _STAGING_ISOLATED:
    install_staging_email_barrier(resend)

    @app.before_request
    def _staging_preflight_lockdown():
        denial = staging_request_denial(
            host=request.host,
            path=request.path,
            method=request.method,
            origin=request.headers.get("Origin"),
        )
        if denial is not None:
            status, message = denial
            headers = {"Cache-Control": "no-store"}
            if status == 503:
                headers["Retry-After"] = "300"
            return jsonify({"error": message}), status, headers

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
# SQLAlchemy >=2.1 defaults to psycopg (v3) for plain postgresql://,
# while this application intentionally installs psycopg2-binary.
# Make the existing driver explicit. URLs that already declare a
# driver (e.g. postgresql+psycopg2://) are not modified.
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
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

# Las cookies de sesión no son persistentes; algunos navegadores las restauran.
# La caducidad efectiva se aplica en el servidor (véase enforce_session_expiry).
# No se ofrece "Recordarme": no permitir que una cookie heredada reactive el acceso.
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(minutes=30)


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
# Public diagnostic upload stays OFF unless explicitly enabled.
app.config["CSV_DIAGNOSTIC_SUPPORT_ENABLED"] = (
    os.environ.get("CSV_DIAGNOSTIC_SUPPORT_ENABLED", "false").lower() == "true"
)
# Optional single-account smoke test, independent of the public flag.
# Empty by default: no authenticated user can send while public flag is OFF.
app.config["CSV_DIAGNOSTIC_TEST_EMAIL"] = (
    os.environ.get("CSV_DIAGNOSTIC_TEST_EMAIL", "").strip().lower()
)

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

# ── PAYPAL RETIRADO ──────────────────────────
# Constante sin interruptor de entorno. Se conserva por compatibilidad de
# tests antiguos; ningún secreto de PayPal se carga y ningún helper hace IO.
_PAYPAL_ENABLED = False
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
    uid = session_user_id(user_id)
    if uid is None:
        return None
    user = db.session.get(User, uid)
    if not user or not user.is_active or not hmac.compare_digest(user.get_id(), user_id):
        return None
    return user

# Límite por inactividad, aplicado en servidor; no confiar en cerrar pestañas.
_USER_IDLE_TTL_S = 30 * 60
_STAFF_IDLE_TTL_S = 15 * 60
_STAFF_ABSOLUTE_TTL_S = 8 * 60 * 60
_AUTH_CREATED_KEY = "auth_started_at"
_AUTH_ACTIVITY_KEY = "auth_last_activity_at"


def _stamp_login_session() -> None:
    """Inicializa una sesión sin remember-cookie, tanto para password como Google."""
    now = int(time.time())
    session.permanent = False
    session[_AUTH_CREATED_KEY] = now
    session[_AUTH_ACTIVITY_KEY] = now
    # Borra también una posible cookie remember emitida por la versión anterior.
    session["_remember"] = "clear"


def _expire_login_session() -> None:
    """Revoca la sesión actual (y remember heredado) antes de autorizar la ruta."""
    logout_user()
    session.clear()
    session["_remember"] = "clear"
    g.session_expired = True


@app.before_request
def enforce_session_expiry():
    """Caducidad comprobada en cada petición, sin almacenar timestamps en BD.

    Una sesión antigua sin sellos de caducidad exige un nuevo acceso. Nunca
    se reconstituye la identidad desde una cookie remember persistente.
    No contar /api/me ni assets como actividad humana.
    """
    if "_user_id" not in session:
        if request.cookies.get(app.config.get("REMEMBER_COOKIE_NAME", "remember_token")):
            logout_user()
            session["_remember"] = "clear"
        return

    now = int(time.time())
    started = session.get(_AUTH_CREATED_KEY)
    last = session.get(_AUTH_ACTIVITY_KEY)
    if (type(started) is not int or type(last) is not int
            or started > now or last > now or last < started):
        _expire_login_session()
        return

    if not current_user.is_authenticated:
        _expire_login_session()
        return

    staff = _role_is_fiscal_advisor()
    idle_limit = _STAFF_IDLE_TTL_S if staff else _USER_IDLE_TTL_S
    if now - last >= idle_limit or (staff and now - started >= _STAFF_ABSOLUTE_TTL_S):
        _expire_login_session()
        return

    # Solo peticiones funcionales prolongan la sesión, no los assets ni el
    # sondeo /api/me. Las escrituras no son excluidas del límite de caducidad.
    if request.path != "/api/me" and not request.path.startswith("/static/"):
        session[_AUTH_ACTIVITY_KEY] = now
    # Elimina remember heredado incluso si la sesión firmada sigue vigente.
    if request.cookies.get(app.config.get("REMEMBER_COOKIE_NAME", "remember_token")):
        session["_remember"] = "clear"


@login_manager.unauthorized_handler
def unauthorized():
    """401 de API o redirección a login, con explicación si ha expirado."""
    expired = getattr(g, "session_expired", False)
    if request.path.startswith("/api/"):
        if expired:
            return jsonify({
                "error": "Tu sesión ha caducado. Vuelve a iniciar sesión.",
                "code": "session_expired",
            }), 401
        return jsonify({"error": "Autenticación requerida"}), 401
    target = f"/login/?next={request.path}"
    if expired:
        target += "&expired=1"
    return redirect(target)


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

# ── DB SCHEMA: NO DDL DURING APP IMPORT ──────────────────────────────────────
# Importing app.py also happens in Gunicorn workers and in Alembic.
# Never create/alter tables here: schema changes require a separately
# authorized, explicit bootstrap/migration command. The Procfile's
# startup_schema_gate.py rejects stale/incomplete databases READ ONLY before
# Gunicorn starts. Legacy emergency ALTERs are owned by Alembic migrations.

# ── PDF TOKEN STORE (Row-Level Security) ───────
# El token se guarda en la sesión Flask (cookie firmada), que viaja con el
# usuario independientemente del worker de Gunicorn que atienda la petición.
# Esto evita el problema de dicts en memoria que no se comparten entre workers.
_PDF_TTL = _pdf_lifecycle.PDF_TTL_SECONDS  # segundos
_pdf_lifecycle.start_pdf_reaper()  # recupera temporales caducados tras reiniciar un worker

def _guardar_token_pdf(token: str, report_id=None) -> None:
    """Guarda el token en la sesión del usuario con su TTL."""
    from flask import session
    session["pdf_token"]       = token
    session["pdf_token_uid"]   = current_user.id
    session["pdf_token_exp"]   = time.time() + _PDF_TTL
    session["pdf_report_id"]   = report_id
    # Alinear el mtime con el inicio real del TTL, después de registrar el informe.
    # Así la limpieza no adelanta una caducidad si la BD tarda en responder.
    try:
        os.utime(os.path.join(tempfile.gettempdir(), token), None)
    except OSError:
        app.logger.warning("fifo_pdf_touch_failed")

def _validar_token_pdf(token: str):
    """Comprueba propiedad y TTL sin consumir el token ante fallos de E/S."""
    from flask import session
    if session.get("pdf_token") != token:
        return None
    if session.get("pdf_token_uid") != current_user.id:
        return None
    if time.time() > session.get("pdf_token_exp", 0):
        return None
    report_id = session.get("pdf_report_id")
    return report_id if report_id is not None else -1


def _consumir_token_pdf(token: str):
    """Invalida el token solo después de preparar una descarga válida."""
    from flask import session
    report_id = _validar_token_pdf(token)
    if report_id is None:
        return None
    for key in ("pdf_token", "pdf_token_uid", "pdf_token_exp", "pdf_report_id"):
        session.pop(key, None)
    return report_id


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
    """Recoge solo metadatos técnicos; nunca contenido, cabeceras ni hash del fichero."""
    import csv as _csv
    ctx = {"file_type": "xlsx" if is_xlsx else "csv"}
    if is_xlsx:
        return ctx
    try:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                f.read(8192)
            ctx["encoding"] = "utf-8"
        except UnicodeDecodeError:
            ctx["encoding"] = "latin-1"

        with open(filepath, "r", encoding=ctx.get("encoding", "utf-8"), errors="replace") as f:
            first_line = f.readline().strip()
        for sep in (",", ";", "\t", "|"):
            columns = next(_csv.reader([first_line], delimiter=sep), [])
            if len(columns) > 1:
                ctx["separator"] = sep
                ctx["n_columns"] = len(columns)
                break
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


def _guardar_pdf_temporal(tmp_path: str, pdf_bytes: bytes) -> str:
    """Almacena el PDF con permisos privados y limpieza temporal independiente."""
    pdf_tmp = _derivar_ruta_pdf(tmp_path)
    _pdf_lifecycle.write_private_pdf(pdf_tmp, pdf_bytes)
    return pdf_tmp


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
        "page_meta_desc":   "Sube los historiales de Binance y calcula ganancias y pérdidas con FIFO obligatorio. Informe PDF para declarar Binance en la declaración de la renta.",
        "page_canonical":   f"{_BASE_URL}/binance",
        "page_og_title":    "Informe fiscal Binance para Hacienda — FIFO automático | Mariano Sevilla",
        "page_og_desc":     "Sube los historiales de Binance y calcula las plusvalías crypto con FIFO. Informe PDF para tu gestor.",
        "page_schema_name": "Informe FIFO Binance — Mariano Sevilla",
        "page_h1":          "Genera tu informe fiscal de Binance para Hacienda",
        "hero_desc":        "Sube los historiales de Binance que correspondan a tu actividad. La herramienta combina Spot, Convert, operaciones fiat y transferencias, evita duplicidades y aplica FIFO sin inventar valoraciones EUR.",
        "how_to": [
            {"title": "Descarga tus historiales de Binance",
             "desc":  "Exporta el historial completo desde tu primera operación. Según tu actividad, descarga Operaciones Spot, Órdenes Convert, depósitos, retiros y compras/ventas fiat. Puedes subir directamente los CSV o ZIP de Binance. Transaction History se usa como fuente complementaria cuando corresponde."},
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

@app.before_request
def sensitive_admin_origin_boundary():
    """Deny explicit cross-site writes to administrative resource/contact APIs.

    Covers resource/contact mutations and communication campaign operations,
    including bodyless send-test requests. Read-only routes and payment
    webhooks are unaffected. A missing Origin requires same-origin metadata.
    This intentionally fails closed for headerless administrative writes.
    """
    if request.method not in {'POST', 'PATCH', 'PUT', 'DELETE'}:
        return
    protected = (
        request.path.startswith('/api/admin/recursos/solicitudes/')
        or request.path.startswith('/api/admin/contactos/')
        or request.path.startswith('/api/admin/comunicaciones/')
    )
    if not protected:
        return
    origin = request.headers.get('Origin')
    site = request.headers.get('Sec-Fetch-Site')
    if ((origin is not None and origin.rstrip('/') != request.host_url.rstrip('/'))
            or site in {'cross-site', 'same-site'}
            or (origin is None and site != 'same-origin')):
        return jsonify({'error': 'Origen de solicitud no válido.'}), 403


@app.before_request
def auth_request_boundary():
    """Reject cross-origin auth writes and malformed JSON before auth handlers."""
    if request.method != 'POST' or request.path not in AUTH_POST_PATHS:
        return
    origin = request.headers.get('Origin')
    if ((origin is not None and origin.rstrip('/') != request.host_url.rstrip('/'))
            or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
        return jsonify({'error': 'Solicitud de acceso no válida.'}), 403
    if request.path == '/api/logout':
        return
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Revisa los datos del formulario.'}), 400
    for key in ('email', 'password', 'full_name', 'token', 'confirm_password',
                'current_password', 'new_password', 'next'):
        if key in data and (not isinstance(data[key], str) or len(data[key]) > 2048):
            return jsonify({'error': 'Revisa los datos del formulario.'}), 400
        if key in data:
            try:
                data[key].encode('utf-8')
            except UnicodeEncodeError:
                return jsonify({'error': 'Revisa los datos del formulario.'}), 400
    if 'remember' in data and not isinstance(data['remember'], bool):
        return jsonify({'error': 'Revisa los datos del formulario.'}), 400


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
    if (request.path in AUTH_POST_PATHS or request.path.rstrip('/') in
            {'/api/me', '/login', '/signup', '/verify-email', '/verify-email-result', '/recuperar-contrasena'}
            or request.path.startswith('/reset-password/')):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers["X-Frame-Options"]                   = "DENY"
    response.headers["X-Content-Type-Options"]             = "nosniff"
    # X-XSS-Protection: 0 — desactiva el auditor XSS del navegador (deprecated y
    # con bugs conocidos). La protección real la provee la CSP de abajo.
    response.headers["X-XSS-Protection"]                  = "0"
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
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
    if not isinstance(password, str) or len(password) < 15:
        return False, "Usa una contraseña de al menos 15 caracteres."
    if len(password.encode('utf-8')) > 72:
        return False, "La contraseña es demasiado larga. Prueba una frase más corta."
    return True, ""


# ── VALIDACIÓN Y SANITIZACIÓN ─────────────────

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_CSV_ROWS        = 100_000            # límite conservador compartido por los demás exchanges
MAX_BINANCE_CSV_ROWS = 350_000            # límite independiente: históricos Binance multi-año
MAX_KUCOIN_FILES    = 8                  # KuCoin es multiarchivo: tope de ficheros por análisis
MAX_BITGET_FILES    = 8                  # Bitget es multiarchivo: tope de ficheros por análisis
AÑO_MIN = 2009


def _ultimo_ejercicio_irpf(ahora=None) -> int:
    """Máximo año admitido en informes FIFO, incluido el año en curso en España.

    Se calcula por petición para no mantener un límite obsoleto al cambiar
    de año sin reiniciar Gunicorn. No cambia la regla del Modelo 721, que
    exige siempre el último ejercicio cerrado.
    """
    momento = ahora if ahora is not None else datetime.now(ZoneInfo("Europe/Madrid"))
    return momento.astimezone(ZoneInfo("Europe/Madrid")).year

# ── MODELO 721: exchanges ──────────────────────────────────────────────────────
# Orden HFP/886/2023 (DF 2.ª): primer ejercicio declarable, 2023.
_721_PRIMER_EJERCICIO = 2023


def _721_ultimo_ejercicio(ahora=None) -> int:
    """Último ejercicio cerrado a 31/12 en España, también al cambiar de año."""
    momento = ahora if ahora is not None else datetime.now(ZoneInfo("Europe/Madrid"))
    return momento.astimezone(ZoneInfo("Europe/Madrid")).year - 1
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


class BinanceUserError(ValueError):
    """CSV de Binance con tipo incompatible con FIFO o archivo alterado. Error imputable al usuario."""
    def __init__(self, code: str, mensaje_usuario: str):
        super().__init__(mensaje_usuario)
        self.code     = code
        self.category = "user_error"


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
    ultimo_ejercicio = _ultimo_ejercicio_irpf()
    for part in ejercicio.split(","):
        part = part.strip()
        if not re.match(r"^\d{4}$", part):
            return False, "Formato de ejercicio fiscal inválido. Usa años de 4 dígitos separados por coma."
        año = int(part)
        if año < AÑO_MIN:
            return False, f"El ejercicio fiscal no puede ser anterior a {AÑO_MIN}."
        if año > ultimo_ejercicio:
            return False, f"El ejercicio fiscal no puede ser posterior a {ultimo_ejercicio}."
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

def _pipeline_motor(clasificador, *, binance_market_prices=None) -> MotorFIFO:
    """Pipeline común; Binance solo acepta swaps con mercado EUR verificado.

    El proveedor histórico se carga fuera de la petición. Nunca se buscan
    cotizaciones en la red desde este pipeline ni se asume paridad.
    """
    priced_swaps = ()
    verified_bnb_fees = ()
    if (binance_market_prices is not None
            and isinstance(clasificador, ClasificadorBinanceMulti)
            and clasificador.comisiones_pendientes):
        from binance_spot_bnb_fee_execution import prepare_spot_eur_bnb_fees
        verified_bnb_fees = prepare_spot_eur_bnb_fees(
            clasificador, binance_market_prices
        )
    if binance_market_prices is not None and isinstance(clasificador, ClasificadorBinanceMulti):
        if clasificador.swaps:
            from binance_valuation_audit import valorar_permutas_nativas
            from binance_eur_valuation import BinanceHistoricalEURPrices, BinancePriceEvidenceError
            if not isinstance(binance_market_prices, BinanceHistoricalEURPrices):
                raise BinancePriceEvidenceError("Proveedor histórico Binance sin validar")
            # Fiat trade contra USD/GBP/etc. no constituye automáticamente
            # una permuta cripto-cripto bajo el art. 37.1.h. Rechazarla ANTES
            # de consultar precios y no aplicar esa regla fiscal indebidamente.
            for event in clasificador.intercambios_nativos:
                if (event.given_asset != "EUR" and event.received_asset != "EUR"
                        and event.source not in {"Spot BUY", "Spot SELL", "Convert"}):
                    raise BinancePriceEvidenceError(
                        "Permuta fiat/externa sin tratamiento acreditado"
                    )
            priced_swaps = valorar_permutas_nativas(clasificador, binance_market_prices)
            if len(priced_swaps) != len(clasificador.swaps):
                raise BinancePriceEvidenceError("No están valoradas todas las permutas Binance")
            # Dos adquisiciones al mismo segundo pueden crear lotes con
            # distinto coste unitario: esto también ocurre con Convert, o
            # mezclando una compra EUR y una permuta que recibe el mismo
            # activo. No escoger el orden del CSV cuando después se consumen
            # esos lotes; el importe FIFO de una venta dependería de ello.
            acquired_unit_costs = {}
            for event in clasificador.intercambios_nativos:
                if event.given_asset == "EUR" and event.received_asset != "EUR":
                    net_qty = event.received_amount - (
                        event.fee_amount if event.fee_asset == event.received_asset
                        else Decimal("0")
                    )
                    if net_qty <= 0:
                        raise BinancePriceEvidenceError(
                            "Adquisición EUR sin cantidad neta verificable"
                        )
                    eur_cost = event.given_amount + (
                        event.fee_amount if event.fee_asset == "EUR"
                        else Decimal("0")
                    )
                    acquired_unit_costs.setdefault(
                        (event.local_time, event.received_asset), set()
                    ).add(eur_cost / net_qty)
            for priced in priced_swaps:
                event = priced.source
                acquired_unit_costs.setdefault(
                    (event.local_time, event.received_asset), set()
                ).add(priced.valuation.fiscal_value_eur / event.received_amount)
            latest_disposal = {}
            for event in clasificador.intercambios_nativos:
                if event.given_asset != "EUR" and event.given_asset != event.received_asset:
                    latest_disposal[event.given_asset] = max(
                        event.local_time, latest_disposal.get(event.given_asset, "")
                    )
            if any(
                len(unit_costs) > 1 and latest_disposal.get(asset, "") > at
                for (at, asset), unit_costs in acquired_unit_costs.items()
            ):
                marker = "binance_fifo_lotes_mismo_segundo_precio_distinto"
                if marker not in clasificador.fuentes_materiales_no_soportadas:
                    clasificador.fuentes_materiales_no_soportadas.append(marker)
                raise BinancePriceEvidenceError(
                    "Orden de lotes recibidos por Spot/Convert no acreditado"
                )
            # El CSV de órdenes carece de milisegundos. Si existen varias
            # disposiciones del mismo activo dentro del mismo segundo, no
            # se conoce qué hecho consumió cada lote en primer lugar.
            counts = {}
            for priced in priced_swaps:
                event = priced.source
                if event.source not in {"Spot BUY", "Spot SELL", "Convert"}:
                    raise BinancePriceEvidenceError(
                        "Permuta fiat/externa sin tratamiento acreditado"
                    )
                key = (event.local_time, event.given_asset)
                counts[key] = counts.get(key, 0) + 1
            if any(n > 1 for n in counts.values()):
                marker = "binance_orden_intrasegundo_incierto"
                if marker not in clasificador.fuentes_materiales_no_soportadas:
                    clasificador.fuentes_materiales_no_soportadas.append(marker)
                raise BinancePriceEvidenceError(
                    "Orden de disposiciones Binance dentro del mismo segundo no acreditado"
                )
            # La misma marca de segundo no prueba si se compró el activo
            # antes o después de venderlo/convertirlo. Evaluar TODAS las
            # fuentes nativas, no solo la cotización EUR o la lista de swaps.
            directions = {}
            for event in clasificador.intercambios_nativos:
                at = event.local_time
                if event.given_asset != "EUR":
                    directions.setdefault((at, event.given_asset), set()).add("out")
                if event.received_asset != "EUR":
                    directions.setdefault((at, event.received_asset), set()).add("in")
            if any(len(kinds) > 1 for kinds in directions.values()):
                marker = "binance_orden_intrasegundo_incierto"
                if marker not in clasificador.fuentes_materiales_no_soportadas:
                    clasificador.fuentes_materiales_no_soportadas.append(marker)
                raise BinancePriceEvidenceError(
                    "Adquisición y disposición del mismo activo sin orden intrasegundo"
                )
    motor = MotorFIFO()
    ops = []
    verified_fee_by_index = {
        fee.native_ordinal: fee for fee in verified_bnb_fees
    }
    # Several fills of one documented native order may share a second.
    # Their EUR expenses belong to individual fills, but their BNB FIFO
    # consumption is one total disposal; no arbitrary intra-second cost
    # allocation among those fees.
    bnb_fees_by_second = {}
    for fee in verified_bnb_fees:
        bnb_fees_by_second.setdefault(fee.timestamp, []).append(fee)
    grouped_bnb_seconds = {
        at for at, fees in bnb_fees_by_second.items() if len(fees) > 1
    }
    for index, op in enumerate(clasificador.compraventas):
        if verified_bnb_fees:
            ops.append(("cv_with_bnb_fee", op.fecha, (index, op)))
        else:
            ops.append(("cv", op.fecha, op))
    for at in sorted(grouped_bnb_seconds):
        ops.append(("bnb_fee_group", at, tuple(bnb_fees_by_second[at])))
    if priced_swaps:
        for priced in priced_swaps:
            ops.append(("verified_swap", priced.source.local_time, priced))
    else:
        for op in clasificador.swaps:
            ops.append(("swap", op.fecha, op))
    # Coinbase and Bitvavo record the received reward only in rendimientos.
    # A fiscal income entry also creates one acquisition lot at its verified
    # EUR value. Crypto.com ALREADY adds this lot in its parser: never add
    # it again or the inventory would double.
    if isinstance(clasificador, (ClasificadorCoinbase, ClasificadorBitvavo)):
        for income in clasificador.rendimientos:
            qty = income.cantidad
            eur = income.valor_eur
            if not (math.isfinite(qty) and math.isfinite(eur)
                    and qty > 0 and eur > 0):
                raise ValueError(
                    "Datos fiscales no seguros: rendimiento sin cantidad "
                    "y valoración EUR positivas; no puede crearse lote FIFO."
                )
            ops.append(("reward", income.fecha, income))
    ops.sort(key=lambda x: x[1])
    prechecked_bnb_seconds = set()
    for tipo, fecha, op in ops:
        if tipo == "cv_with_bnb_fee":
            from binance_spot_bnb_fee_execution import (
                apply_spot_eur_trade_with_bnb_fee,
                verify_spot_bnb_fee_inventory,
            )
            index, original = op
            if (fecha in grouped_bnb_seconds
                    and fecha not in prechecked_bnb_seconds):
                # Check total BNB holdings before recording the FIRST Spot
                # fill of a same-second order; fail atomically if insufficient.
                verify_spot_bnb_fee_inventory(
                    motor, bnb_fees_by_second[fecha]
                )
                prechecked_bnb_seconds.add(fecha)
            apply_spot_eur_trade_with_bnb_fee(
                motor, original, verified_fee_by_index.get(index),
                defer_bnb_disposal=fecha in grouped_bnb_seconds,
            )
        elif tipo == "bnb_fee_group":
            from binance_spot_bnb_fee_execution import settle_spot_bnb_fees_same_second
            settle_spot_bnb_fees_same_second(motor, op)
        elif tipo == "cv":
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
        elif tipo == "verified_swap":
            from binance_fiscal_swap import aplicar_permuta_binance_valorada
            source = op.source
            aplicar_permuta_binance_valorada(
                motor,
                fecha_local=source.local_time,
                export_filename=source.filename,
                given_asset=source.given_asset,
                given_amount=source.given_amount,
                received_asset=source.received_asset,
                received_amount=source.received_amount,
                fee_amount=source.fee_amount,
                valuation=op.valuation,
            )
        elif tipo == "reward":
            motor.registrar_compra(
                fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                importe=op.valor_eur, contraparte="EUR",
                fee_activo="EUR", fee_cantidad=0.0,
            )
    if (isinstance(clasificador, ClasificadorBinanceMulti)
            and getattr(clasificador, "earn_principal_only_audit", None) is not None):
        from binance_earn_transfer_only import validate_principal_only_motor
        validate_principal_only_motor(clasificador.earn_principal_only_audit, motor)
    if verified_bnb_fees:
        # Fix the acceptance evidence only after ALL fee disposals completed.
        # Pending rows remain intact for audit; the validator compares their
        # number with the proven one-to-one settlements.
        clasificador._binance_verified_bnb_fees = tuple(verified_bnb_fees)
    if priced_swaps:
        # Fijar esta prueba interna solo después de aplicar TODOS los swaps.
        # Los validadores posteriores vuelven a comprobar identidad y cantidad.
        clasificador._binance_verified_swaps = tuple(priced_swaps)
    return motor


def procesar_con_fifo(clasificador, *, binance_market_prices=None) -> tuple:
    """Pipeline genérico: clasificador ya instanciado → motor FIFO + rendimientos + clasificador.
    Devuelve 3-tupla (motor, rendimientos, clasificador) para permitir extracción de telemetría
    (swaps totales, movimientos, desconocidas) que solo viven en el clasificador.
    """
    motor = _pipeline_motor(
        clasificador, binance_market_prices=binance_market_prices
    )
    rendimientos = clasificador.rendimientos if hasattr(clasificador, 'rendimientos') else []
    return motor, rendimientos, clasificador


def _detectar_formato_binance(filepath: str) -> str:
    """
    Detecta el subtipo de CSV de Binance.

    'tx'              — Historial de Transacciones (válido para FIFO)
    'fiat_deposit'    — Historial de depósitos fiat (incompatible con FIFO)
    'spot_orders'     — Historial de órdenes de spot (incompatible con FIFO)
    'crypto_deposits' — Historial de depósitos/retiros de cripto (incompatible con FIFO)
    'altered_csv'     — Metadata de web o separador no estándar (archivo alterado)
    'spot'            — Fallback (Historial de Operaciones Spot)
    """
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            primera = f.readline()
            muestra = primera + "".join(f.readline() for _ in range(19))
        if "www.binance.com" in primera:
            return "altered_csv"
        if primera.count(";") > primera.count(","):
            return "altered_csv"
        if ("Buy Crypto With Fiat" in muestra or "Sell Crypto To Fiat" in muestra
                or "ID de usuario" in muestra or "User ID" in muestra):
            return "tx"
        if "Importe de depósito" in muestra or "Recibir cantidad" in muestra:
            return "fiat_deposit"
        if "Número de pedido" in muestra or "Total de trading" in muestra:
            return "spot_orders"
        # Cabecera observada en producción (incidente 6b73e4de, evento 42):
        # Time,Coin,Network,Amount,Address,TXID,Status
        if "TXID" in primera and ("Network" in primera or "Address" in primera):
            return "crypto_deposits"
    except Exception:
        pass
    return "spot"


def procesar_binance(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorBinance(filepath).clasificar())


def procesar_binance_tx(filepath: str) -> tuple:
    return procesar_con_fifo(ClasificadorBinanceTx(filepath).clasificar())


def procesar_binance_multi(filepaths: list, filenames: list = None, *, market_prices=None) -> tuple:
    """Binance multifuente, con valoración opcional desde mercado verificado.

    Sin catálogo previo, los swaps siguen bloqueados y nunca se descarga
    mercado público dentro de esta solicitud.
    """
    return procesar_con_fifo(
        ClasificadorBinanceMulti(filepaths, filenames).clasificar(),
        binance_market_prices=market_prices,
    )


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
        _fmt_721 = _detectar_formato_binance(tmp_path)
        if _fmt_721 == "altered_csv":
            raise BinanceUserError(
                "altered_csv",
                "El archivo parece haber sido modificado o guardado con un programa externo "
                "(Excel, LibreOffice). Descarga el historial de transacciones directamente "
                "desde Binance sin abrirlo antes: Wallet → Historial de transacciones → Exportar.",
            )
        if _fmt_721 == "fiat_deposit":
            raise BinanceUserError(
                "fiat_deposit_history",
                "Este archivo es el historial de depósitos fiat de Binance, no el historial de "
                "transacciones. Para el cálculo FIFO necesitas el historial completo: en Binance "
                "ve a Wallet → Historial de transacciones → Exportar.",
            )
        if _fmt_721 == "spot_orders":
            raise BinanceUserError(
                "spot_orders_history",
                "Este archivo es el historial de órdenes de spot de Binance, no el historial de "
                "transacciones. Para el cálculo FIFO necesitas el historial completo: en Binance "
                "ve a Wallet → Historial de transacciones → Exportar.",
            )
        if _fmt_721 == "crypto_deposits":
            raise BinanceUserError(
                "crypto_deposits_history",
                "Este archivo es el historial de depósitos y retiros de cripto de Binance, no el "
                "«Historial de transacciones» que necesita la herramienta. Para el cálculo FIFO "
                "necesitas el historial completo: en Binance ve a Wallet → Historial de "
                "transacciones → Exportar y descarga todas las transacciones desde tu primera "
                "operación.",
            )
        if _fmt_721 == "tx":
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


def _validar_aceptacion_fuentes_fifo(clasificador) -> None:
    """P0: distinguir advertencias informativas de datos fiscales incompletos.

    Sólo MEXC, Bitget (ambas rutas) y KuCoin. Ninguna advertencia genérica
    causa bloqueo: se inspeccionan operaciones, divisas y omisiones tipadas.
    No se realizan conversiones aproximadas ni llamadas a proveedores.
    """
    if not isinstance(clasificador, (
        ClasificadorMEXC, ClasificadorBitget, ClasificadorBitgetMulti,
        ClasificadorKuCoin,
    )):
        return

    if getattr(clasificador, "desconocidas", ()):
        raise ValueError(
            "Datos fiscales no seguros: hay operaciones no interpretadas "
            "que podrían afectar al cálculo FIFO. Revisa el historial."
        )
    if getattr(clasificador, "_no_reconocidos", ()):
        raise ValueError(
            "Datos fiscales no seguros: uno o varios archivos no se han "
            "podido interpretar. No se puede emitir un informe parcial."
        )
    if getattr(clasificador, "_fuentes_materiales_omitidas", ()):
        raise ValueError(
            "Datos fiscales no seguros: se omitieron archivos con "
            "operaciones potencialmente relevantes para el IRPF."
        )

    # El importe del MotorFIFO se interpreta como euros. Sin cotización
    # histórica acreditada no puede pasar un total USDT/USD u otra divisa.
    for op in getattr(clasificador, "compraventas", ()):
        if str(getattr(op, "contraparte", "")).upper() != "EUR":
            raise ValueError(
                "Datos fiscales no seguros: existen compraventas sin "
                "valoración histórica acreditada en EUR."
            )

    # Bitget recoge Interest/Earn como cantidad de cripto sin valor_eur.
    # El rendimiento puede además alterar el coste de adquisición futuro.
    for op in getattr(clasificador, "rendimientos", ()):
        if (getattr(op, "cantidad", 0) > 0
                and not (isinstance(getattr(op, "valor_eur", None), (int, float))
                         and math.isfinite(op.valor_eur) and op.valor_eur > 0)):
            raise ValueError(
                "Datos fiscales no seguros: existen rendimientos sin "
                "valoración EUR acreditada ni coste FIFO verificable."
            )

    # Estos movimientos no son simples traspasos: el clasificador registra
    # una adquisición/conversión pendiente, sin integrar su base fiscal.
    for op in getattr(clasificador, "movimientos", ()):
        subtipo = str(getattr(op, "subtipo", "")).lower()
        observacion = str(getattr(op, "observacion", "")).lower()
        if ("convert dust (revisar)" in subtipo
                or "valoración eur no disponible" in observacion):
            raise ValueError(
                "Datos fiscales no seguros: existe una adquisición o "
                "permuta sin reconstrucción fiscal y valoración EUR."
            )


def _validar_aceptacion_fifo(motor, clasificador=None) -> None:
    """R01–R04: no emitir IRPF cuando falta base fiscal acreditada.

    Se llama únicamente desde el recorrido IRPF antes de JSON/PDF/token;
    no modifica el motor, el clasificador ni los recorridos Modelo 721.
    """
    _validar_aceptacion_fuentes_fifo(clasificador)

    # Legacy Transaction History: tampoco emitir un informe parcial si Binance
    # introduce un tipo de evento nuevo que el parser todavía no interpreta.
    if isinstance(clasificador, ClasificadorBinanceTx) and getattr(clasificador, "desconocidas", ()):
        raise ValueError(
            "Datos fiscales no seguros: Binance contiene operaciones no interpretadas. "
            "Sube las fuentes nativas Spot/Convert/Fiat o revisa el historial."
        )

    # Binance multifuente: la reconstrucción económica puede ser completa aunque
    # falte la valoración fiscal EUR. Nunca emitir un PDF parcial ni asumir
    # paridad de stablecoins / coste cero / comisión irrelevante.
    if isinstance(clasificador, ClasificadorBinanceMulti):
        # Without an explicit, valid UTC offset per source file, two local
        # seconds cannot safely be compared across ZIP/CSV exports. This is
        # a fiscal-acceptance gate, not a parser restriction: users can still
        # obtain the file diagnosis without inventing a timezone.
        from binance_eur_valuation import (
            BinancePriceEvidenceError, binance_export_time_to_utc,
        )
        # Spot orders reconcile fills but never create fiscal operations;
        # bank deposits/withdrawals likewise do not create crypto lots.
        # Requiring a timezone on those auxiliary files would reject an
        # otherwise fully evidenced FIFO without improving lot chronology.
        fiscal_sources = {
            "spot_trades", "convert_orders", "fiat_trade",
            "transaction_history",
        }
        economic_files = {
            filename
            for source, rows in clasificador._source_rows.items()
            if source in fiscal_sources
            for _row, filename in rows
        }
        try:
            for filename in economic_files:
                binance_export_time_to_utc("2025-01-01 12:00:00", filename)
        except BinancePriceEvidenceError as exc:
            marker = "binance_zona_horaria_sin_acreditar"
            if marker not in clasificador.fuentes_materiales_no_soportadas:
                clasificador.fuentes_materiales_no_soportadas.append(marker)
            raise ValueError(
                "Datos fiscales no seguros: los archivos Binance contienen "
                "operaciones sin un desplazamiento UTC explícito y válido. "
                "No se puede acreditar el orden cronológico del FIFO."
            ) from exc
        priced_swaps = getattr(clasificador, "_binance_verified_swaps", ())
        if priced_swaps:
            from binance_valuation_audit import BinanceSwapAuditRecord
            if (len(priced_swaps) != len(clasificador.swaps)
                    or len(priced_swaps) != len(clasificador.valoraciones_pendientes)
                    or not all(isinstance(record, BinanceSwapAuditRecord)
                               for record in priced_swaps)
                    or len([r for r in motor.resultados if r.tipo_operacion == "swap"])
                    != len(priced_swaps)):
                raise ValueError(
                    "Datos fiscales no seguros: permutas Binance no conciliadas "
                    "con el cálculo FIFO valorado."
                )
        if (getattr(clasificador, "earn_events", ())
                and getattr(clasificador, "earn_principal_only_audit", None) is None):
            rewards_section = getattr(
                clasificador, "_sections", {}
            ).get("earn_flexible_rewards")
            if (rewards_section is not None and rewards_section.detectado
                    and rewards_section.vacio):
                raise ValueError(
                    "Datos fiscales no seguros: el CSV "
                    "de recompensas de Binance Simple Earn está vacío, pero "
                    "no acredita el período de fechas que cubre. No se puede "
                    "descartar que existan rendimientos Earn omitidos."
                )
            raise ValueError(
                "Datos fiscales no seguros: Binance Simple Earn contiene "
                "suscripciones, redenciones o recompensas pendientes de "
                "conciliar con el inventario FIFO y de valorar en EUR."
            )
        if getattr(clasificador, "desconocidas", ()):
            raise ValueError(
                "Datos fiscales no seguros: Binance contiene operaciones no "
                "interpretadas que podrían afectar al FIFO."
            )
        if getattr(clasificador, "fuentes_materiales_no_soportadas", ()):
            raise ValueError(
                "Datos fiscales no seguros: Binance contiene una fuente con "
                "operaciones que todavía no se pueden reconstruir con seguridad."
            )
        # Los depósitos cripto aportan cantidad, pero sus lotes externos
        # (fecha/coste de adquisición) no se incorporan al motor FIFO.
        # Aunque existan compras locales suficientes, una venta posterior
        # podría consumir los lotes equivocados por orden histórico.
        # Tampoco sería fiable la posición final si se omite el depósito.
        if any(
            getattr(m, "subtipo", "") == "Depósito cripto"
            for m in getattr(clasificador, "movimientos", ())
        ):
            raise ValueError(
                "Datos fiscales no seguros: Binance contiene depósitos cripto "
                "cuyos lotes de adquisición, fechas y costes no están "
                "reconstruidos en el FIFO. Requiere conciliar su origen."
            )
        # Un retiro de cripto no demuestra que el destino sea una cartera
        # propia. Puede ser traspaso neutral, pago o transmisión; omitirlo
        # del FIFO y presentar la posición como acreditada sería inseguro.
        if any(
            getattr(m, "subtipo", "") == "Retiro cripto"
            for m in getattr(clasificador, "movimientos", ())
        ):
            raise ValueError(
                "Datos fiscales no seguros: Binance contiene retiradas de "
                "criptomonedas sin acreditar su destino y tratamiento en el "
                "inventario global. Requiere conciliar cartera receptora o "
                "transmisión, según corresponda."
            )
        if (getattr(clasificador, "valoraciones_pendientes", ())
                and not priced_swaps):
            raise ValueError(
                "Datos fiscales no seguros: Binance contiene permutas o rendimientos "
                "sin valoración histórica acreditada en EUR."
            )
        fees_pending = tuple(getattr(clasificador, "comisiones_pendientes", ()))
        fees_settled = tuple(getattr(clasificador, "_binance_verified_bnb_fees", ()))
        if fees_pending and len(fees_pending) != len(fees_settled):
            raise ValueError(
                "Datos fiscales no seguros: Binance contiene comisiones en cripto "
                "sin valoración EUR y tratamiento fiscal verificable."
            )

    # El clasificador Binance TX a…33380 tokens truncated…red
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
    """Desactiva y desidentifica la cuenta tras verificar su identidad.

    No equivale a borrar los expedientes ni a anonimizar registros vinculados
    por user_id u otros identificadores; su conservación se decide aparte.
    """
    uid = user.id
    user.email                    = f"deleted_{uid}@deleted"
    user.password_hash            = None
    user.google_id                = None
    user.full_name                = None
    user.nif                      = None
    user.is_active                = False
    user.email_verified_at        = None
    # Los tokens y el último acceso ya no son necesarios para una cuenta
    # desactivada. No tocar registros fiscales, pagos ni expedientes asociados.
    user.comms_unsubscribe_token   = None
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None
    user.last_login                = None
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
    return jsonify({"message": "Cuenta desactivada y datos principales de identificación retirados. Otros registros del servicio pueden conservarse."})


# ── ADMIN STATS ──────────────────────────────────────────────────────────────

@app.route("/stats")
@require_admin_page
def stats_page():
    return send_from_directory("static", "stats.html")


# ── /stats-v2 — Product Intelligence (Hito 1, fase 2) ────────────────────────
# Página-encuentro (docs/stats-v2/10-interface-design.md). Admin-only,
# noindex, fuera del sitemap. Fase 2: renderiza el contrato de datos con el
# fixture del escenario 02 — sin backend de razonamiento.

@app.route("/stats-v2")
@require_admin_page
def stats_v2_page():
    return render_template("stats_v2.html")


@app.route("/api/stats-v2/encuentro")
@require_admin
def api_stats_v2_encuentro():
    from stats_v2_fixture import ENCUENTRO_FIXTURE
    return jsonify(ENCUENTRO_FIXTURE)


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


def _rate_limit_retry_after_seconds(limits, now=None):
    """Return the wait for every breached window, not just the shortest one."""
    now = int(time.time()) if now is None else int(now)
    reset_times = [
        int(limit.reset_at) for limit in limits
        if getattr(limit, "breached", False)
    ]
    if not reset_times:
        return None
    return max(0, max(reset_times) - now)


def _current_rate_limit_retry_after_seconds():
    try:
        return _rate_limit_retry_after_seconds(limiter.current_limits)
    except Exception:
        # Keep the 429 response available if limiter storage is unavailable.
        return None


def _format_rate_limit_wait(seconds):
    seconds = max(1, int(seconds))
    if seconds < 60:
        return f"{seconds} segundos"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        unit = "minuto" if minutes == 1 else "minutos"
        return f"{minutes} {unit}" + (f" y {seconds} segundos" if seconds else "")
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        unit = "hora" if hours == 1 else "horas"
        return f"{hours} {unit}" + (f" y {minutes} minutos" if minutes else "")
    days, hours = divmod(hours, 24)
    unit = "día" if days == 1 else "días"
    return f"{days} {unit}" + (f" y {hours} horas" if hours else "")


@app.errorhandler(429)
def ratelimit_error(e):
    # Rutas API: devolver JSON (consumido por JS del frontend).
    if request.path.startswith("/api/"):
        retry_after = _current_rate_limit_retry_after_seconds()
        auth_route = request.path in AUTH_POST_PATHS
        message = (
            "Has realizado demasiados intentos."
            if auth_route else "Has alcanzado un límite temporal de análisis."
        )
        payload = {"error": message + " Espera antes de volver a intentarlo."}
        headers = {"Cache-Control": "no-store"}
        if retry_after is not None and retry_after > 0:
            wait = _format_rate_limit_wait(retry_after)
            payload["error"] = message + f" Podrás volver a intentarlo en {wait}."
            payload["retry_after_seconds"] = retry_after
            headers["Retry-After"] = str(retry_after)
        return jsonify(payload), 429, headers
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
    """Legacy URL: never assert a paid/confirmed S01 request during C1."""
    response = send_from_directory("static", "asesoramiento-confirmado.html")
    response.status_code = 503
    response.headers["Cache-Control"] = "no-store"
    return response

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
    """C2: no presentar importes heredados como ofertas S01 mientras está congelado."""
    response = jsonify({
        "code": "s01_quotes_suspended",
        "message": "Los presupuestos y pagos de asesoramiento están suspendidos.",
    })
    response.status_code = 503
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/asesoramiento/solicitar", methods=["POST"])
@login_required
@limiter.limit("3 per hour")
def advisory_solicitar():
    """Recibe solicitud para revisión; C1 no presupone oferta, cobro o plazo."""
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


# ── PAYPAL LEGACY: INTERFAZ INERTE / SIN PROVEEDOR ───────────────────────────
# Mantener símbolos para tests y rutas históricas; NO RESTAURAR E/S aquí.
# Los IDs de órdenes/capturas en fiscal_advisory_requests se conservan.
def _paypal_get_access_token() -> str:
    """Retirado: no se llama a ningún endpoint OAuth de PayPal."""
    refuse_advisory_financial_operation()


def _paypal_create_order(advisory: "FiscalAdvisoryRequest") -> dict:
    """Retirado: jamás crear una nueva orden PayPal."""
    refuse_advisory_financial_operation()


def _paypal_capture_order(order_id: str) -> dict:
    """Retirado: jamás solicitar una captura PayPal."""
    refuse_advisory_financial_operation()


def _on_payment_completed(
    advisory: "FiscalAdvisoryRequest",
    amount_cents: int,
    currency: str,
    provider: str,
    capture_note: str,
) -> None:
    """Finalizador financiero legacy deshabilitado permanentemente."""
    refuse_advisory_financial_operation()


# ── ADMIN: ENVIAR PRESUPUESTO ─────────────────────────────────────────────────

@app.route("/api/admin/asesoramiento/solicitudes/<int:req_id>/enviar-presupuesto", methods=["POST"])
@require_fiscal_advisor
@advisory_financial_prefreeze()
def advisory_enviar_presupuesto(req_id):
    """Rafa introduce el precio y el sistema envía el link de pago al cliente."""

    data = request.get_json(silent=True) or {}

    # S01: el importe introducido es el honorario de Rafa, NO el precio final.
    # Se calcula en céntimos exactos; el 30 % queda registrado por separado.
    try:
        s01_quote = calculate_s01_quote(data.get("amount_euros"))
    except QuotePricingError as exc:
        return jsonify({"error": f"Importe inválido: {exc}"}), 400
    amount_cents = s01_quote.total_cents

    # El mismo bloqueo de fila que utiliza la reserva Checkout S01.
    # Nunca sobrescribir snapshots o limpiar evidencia cuando existan
    # órdenes, pagos, aceptaciones o intentos (también inciertos).
    advisory = (
        FiscalAdvisoryRequest.query.filter_by(id=req_id)
        .with_for_update().first_or_404()
    )
    if advisory.status not in ("submitted", "quote_sent"):
        db.session.rollback()
        return jsonify({"error": f"No se puede enviar presupuesto en estado '{advisory.status}'."}), 409

    if (
        advisory.paypal_order_id is not None
        or advisory.paypal_capture_id is not None
        or advisory.stripe_checkout_session_id is not None
        or advisory.stripe_payment_intent_id is not None
        or advisory.payment_provider is not None
        or advisory.amount_paid is not None
        or advisory.paid_at is not None
        or advisory.quote_accepted_at is not None
        or S01StripeCheckoutAttempt.query.filter_by(advisory_id=req_id).first() is not None
    ):
        db.session.rollback()
        return jsonify({
            "error": "Existe actividad financiera o un presupuesto aceptado. "
                     "No se puede sustituir: requiere conciliación previa."
        }), 409

    quote_message = (data.get("message") or "").strip()[:2000] or None

    import secrets as _secrets
    from datetime import timedelta

    now                          = datetime.utcnow()
    advisory.quoted_amount       = amount_cents
    advisory.rafa_fee_cents      = s01_quote.rafa_fee_cents
    advisory.commission_cents    = s01_quote.commission_cents
    advisory.commission_rate_bps = COMMISSION_RATE_BPS
    advisory.quoted_by_user_id   = current_user.id
    advisory.quote_message       = quote_message
    advisory.quote_sent_at       = now
    advisory.quote_expires_at    = now + timedelta(days=30)
    advisory.payment_link_token  = _secrets.token_urlsafe(32)
    advisory.status              = "quote_sent"
    history_note = f"Presupuesto enviado: €{amount_cents / 100:.2f} a {advisory.email}"
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
        detail     = (f"Rafa: {s01_quote.rafa_fee_cents / 100:.2f} €; "
                      f"comisión: {s01_quote.commission_cents / 100:.2f} €; "
                      f"total: {amount_cents / 100:.2f} € a {advisory.email}"),
    ))
    db.session.commit()

    payment_url = f"{_APP_BASE_URL.rstrip('/')}/pagar/{advisory.payment_link_token}"
    email_ok    = _send_advisory_quote_email(advisory, payment_url)

    return jsonify({
        "ok":           True,
        "payment_url":  payment_url,
        "rafa_fee_cents": s01_quote.rafa_fee_cents,
        "commission_cents": s01_quote.commission_cents,
        "total_cents": amount_cents,
        "email_sent":   email_ok,
        "email_to":     advisory.email,
        # Si email_sent es False el expediente ya está guardado; el admin puede reenviar.
        "email_warning": None if email_ok else (
            f"El presupuesto se guardó correctamente pero el email a {advisory.email} "
            "no pudo enviarse. Revisa los logs de Railway."
        ),
    })



# ── S01 C1: GESTIÓN INTERNA SIN OPERACIONES FINANCIERAS ─────────────────────
# Las rutas heredadas /enviar-presupuesto, /mensaje, /estado, /nota, /is-test
# y DELETE continúan bajo PREFREEZE. C1 sólo habilita nuevas rutas limitadas;
# jamás emite presupuestos, enlaces, mensajes al cliente ni llamadas a Stripe.
_C1_SESSION_KEY = "_s01_c1_admin_csrf"


def _c1_response(payload, status=200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def _c1_csrf_ok():
    from hmac import compare_digest
    record = session.get(_C1_SESSION_KEY)
    supplied = request.headers.get("X-S01-C1-CSRF")
    origin = request.headers.get("Origin")
    if origin is not None and origin != request.host_url.rstrip("/"):
        return False
    return (
        isinstance(record, dict)
        and record.get("user_id") == current_user.id
        and isinstance(record.get("token"), str)
        and isinstance(supplied, str)
        and compare_digest(record["token"], supplied)
    )


@app.route("/api/admin/asesoramiento/gestion-token", methods=["GET"])
@require_fiscal_advisor
@limiter.limit("30 per minute")
def admin_c1_management_token():
    existing = session.get(_C1_SESSION_KEY)
    if not isinstance(existing, dict) or existing.get("user_id") != current_user.id:
        session[_C1_SESSION_KEY] = {
            "user_id": current_user.id,
            "token": secrets.token_urlsafe(32),
        }
    return _c1_response({"csrf_token": session[_C1_SESSION_KEY]["token"]})


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>/gestion/nota", methods=["POST"])
@require_fiscal_advisor
@limiter.limit("30 per minute")
def admin_c1_add_internal_note(request_id):
    if not _c1_csrf_ok():
        return _c1_response({"error": "Solicitud no autorizada."}, 403)
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("nota"), str):
        return _c1_response({"error": "Nota inválida."}, 400)
    note_text = data["nota"].strip()[:2000]
    if not note_text:
        return _c1_response({"error": "La nota no puede estar vacía."}, 400)
    advisory = FiscalAdvisoryRequest.query.get_or_404(request_id)
    author = (current_user.full_name or current_user.email or "Asesor").strip()
    note = AdvisoryInternalNote(
        request_id=advisory.id,
        author_id=current_user.id,
        author_name=author,
        text=note_text,
    )
    db.session.add(note)
    advisory.updated_at = datetime.utcnow()
    db.session.commit()
    return _c1_response({"ok": True, "note": note.to_dict()})


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>/gestion/estado", methods=["POST"])
@require_fiscal_advisor
@limiter.limit("30 per minute")
def admin_c1_change_nonfinancial_state(request_id):
    if not _c1_csrf_ok():
        return _c1_response({"error": "Solicitud no autorizada."}, 403)
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("status"), str):
        return _c1_response({"error": "Estado inválido."}, 400)
    new_status = data["status"]
    if new_status not in C2_TARGET_STATES:
        return _c1_response({"error": "Solo se permiten estados internos sin aviso al cliente."}, 503)
    if not isinstance(data.get("note", ""), str):
        return _c1_response({"error": "Nota inválida."}, 400)
    note = data.get("note", "").strip()[:1000]
    try:
        status, unchanged = c2_change_internal_state(
            request_id=request_id,
            new_status=new_status,
            actor_id=current_user.id,
            note=note,
        )
    except C2ProtectedState:
        return _c1_response({"error": "Expediente protegido por historial financiero o estado previo."}, 409)
    # Sin correos, pagos, facturas o proveedores. La API legacy sigue bajo freeze.
    return _c1_response({
        "ok": True, "status": status,
        "status_label": FiscalAdvisoryRequest.STATUS_LABELS[status],
        "unchanged": unchanged,
    })


# ── ENVIAR MENSAJE SIN PRESUPUESTO ───────────────────────────────────────────

@app.route("/api/admin/asesoramiento/solicitudes/<int:req_id>/mensaje", methods=["POST"])
@require_fiscal_advisor
@advisory_financial_prefreeze()
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
    response = send_from_directory("static", "pagar.html")
    response.headers["Cache-Control"] = "no-store"
    return response


# ── API: INFO DEL PRESUPUESTO (para la página /pagar/<token>) ────────────────

@app.route("/api/pago/info/<token>", methods=["GET"])
@limiter.limit("30 per minute")
@advisory_financial_prefreeze()
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


# ── PAYPAL LEGACY: TUMBSTONES COMPATIBLES, SIN LÓGICA DE COBRO ────────────
# PREFREEZE sigue siendo la primera barrera observable de estas rutas.
# Las funciones debajo no contienen lectura de argumentos, SQL ni proveedor.

@app.route("/api/pago/iniciar/<token>", methods=["POST"])
@limiter.limit("10 per hour")
@advisory_financial_prefreeze()
def pago_iniciar(token):
    """Antiguo inicio de PayPal: deshabilitado también sin el decorador."""
    refuse_advisory_financial_operation()


@app.route("/api/pago/paypal/capture", methods=["GET"])
@limiter.limit("30 per minute")
@advisory_financial_prefreeze(html=True)
def pago_paypal_capture():
    """Callback antiguo: nunca ejecutar una segunda captura."""
    refuse_advisory_financial_operation()


@app.route("/api/webhooks/paypal", methods=["POST"])
@limiter.limit("120 per minute")
@advisory_financial_prefreeze()
def paypal_webhook():
    """Webhook retirado: 503 y sin ACK, sin parseo ni llamadas a PayPal."""
    refuse_advisory_financial_operation()


@app.route("/api/webhooks/stripe", methods=["POST"])
@limiter.limit("60 per minute")
@advisory_financial_prefreeze()
def stripe_webhook():
    """Webhook de Stripe — solo este endpoint puede marcar un pago como confirmado."""
    # Fail closed: neither missing SDK/credentials nor an unsigned payload can
    # acknowledge or process a financial event. Never fall back to json.loads.
    if (not _stripe_available or not (_STRIPE_SECRET_KEY or "").strip()
            or not (_STRIPE_WEBHOOK_SECRET or "").strip()):
        app.logger.error("stripe_webhook_unavailable provider_configuration_incomplete")
        return jsonify({"error": "Webhook unavailable."}), 503

    payload    = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    if not sig_header:
        app.logger.warning("stripe_webhook_signature_missing")
        return jsonify({"error": "Invalid request."}), 400

    try:
        _stripe_module.api_key = _STRIPE_SECRET_KEY
        event = _stripe_module.Webhook.construct_event(
            payload, sig_header, _STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, _stripe_module.error.SignatureVerificationError):
        # Do not log exception strings: SDK messages may include payload data.
        app.logger.warning("stripe_webhook_signature_invalid")
        return jsonify({"error": "Invalid request."}), 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        # stripe-python returns StripeObject after verified parsing; its
        # .get() is not supported. Convert without bypassing signature checks.
        if not isinstance(session_obj, dict):
            session_obj = session_obj.to_dict()
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
        app.logger.error("Aviso de confirmación advisory fallido | solicitud #%s | tipo=%s", advisory.id, type(exc).__name__)


def _send_advisory_internal_notification(advisory: "FiscalAdvisoryRequest"):
    """Aviso mínimo de nueva solicitud; los datos del caso se consultan en el panel protegido.

    Evitar duplicar en correos personales/Resend relatos fiscales, contacto,
    importes e información de facturación. La función no cambia destinatarios.
    """
    if not resend.api_key or not _ADVISORY_NOTIFY_EMAILS:
        return
    panel_url = f"{_APP_BASE_URL}/admin/asesoramiento"
    text = (
        f"Hay una nueva solicitud de asesoramiento fiscal.\n\n"
        f"Referencia: #{advisory.id}\n"
        f"Consulta los detalles en el panel protegido de asesoramiento.\n"
        f"Panel: {panel_url}"
    )
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      _ADVISORY_NOTIFY_EMAILS,
            "subject": f"[Asesoramiento] Nueva solicitud #{advisory.id}",
            "text":    text,
        })
    except Exception as exc:
        app.logger.error("Aviso interno advisory fallido | solicitud #%s | tipo=%s", advisory.id, type(exc).__name__)


def _send_advisory_message_email(advisory: "FiscalAdvisoryRequest", mensaje: str) -> bool:
    """Email al cliente con un mensaje del asesor, sin presupuesto ni link de pago.
    Devuelve True si el envío fue aceptado por Resend, False en caso contrario.
    """
    if not resend.api_key:
        app.logger.error(
            "RESEND_API_KEY no configurada — email de mensaje NO enviado "
            "(advisory_id=%s)", advisory.id
        )
        return False

    html, text = advisory_message_email(advisory, mensaje)

    app.logger.info(
        "Enviando email de mensaje | advisory_id=%s",
        advisory.id,
    )
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [advisory.email],
            "subject": "Mensaje sobre tu solicitud de asesoramiento fiscal",
            "html":    html,
            "text":    text,
        })
        app.logger.info(
            "Email de mensaje aceptado por Resend | advisory_id=%s",
            advisory.id,
        )
        return True
    except Exception as exc:
        app.logger.error(
            "ERROR enviando email de mensaje | advisory_id=%s | tipo=%s",
            advisory.id, type(exc).__name__,
        )
        return False


def _send_advisory_quote_email(advisory: "FiscalAdvisoryRequest", payment_url: str):
    """Email al cliente con el presupuesto y el link de pago.
    Devuelve True si el envío fue aceptado por Resend, False en caso contrario.
    """
    if not resend.api_key:
        app.logger.error(
            "RESEND_API_KEY no configurada — email de presupuesto NO enviado "
            "(advisory_id=%s)", advisory.id
        )
        return False

    html, text = advisory_quote_email(advisory, payment_url)
    amount_str = f"{advisory.quoted_amount / 100:.2f}" if advisory.quoted_amount else "?"
    subject    = f"Tu presupuesto de asesoramiento fiscal — {amount_str} €"

    app.logger.info(
        "Enviando email de presupuesto | advisory_id=%s",
        advisory.id,
    )
    try:
        resend.Emails.send({
            "from":    _RESEND_FROM_DISPLAY,
            "to":      [advisory.email],
            "subject": subject,
            "html":    html,
            "text":    text,
        })
        app.logger.info(
            "Email de presupuesto aceptado por Resend | advisory_id=%s",
            advisory.id,
        )
        return True
    except Exception as exc:
        app.logger.error(
            "ERROR enviando email de presupuesto | advisory_id=%s | tipo=%s",
            advisory.id, type(exc).__name__,
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
        app.logger.error("Confirmación de pago advisory fallida | solicitud #%s | tipo=%s", advisory.id, type(exc).__name__)


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
        app.logger.error("Aviso interno de pago advisory fallido | solicitud #%s | tipo=%s", advisory.id, type(exc).__name__)


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
            "Se habría enviado estado=%s (solicitud #%s).",
            advisory.status, advisory.id,
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
            "[advisory email] Enviado estado=%s (solicitud #%s).",
            advisory.status, advisory.id,
        )
    except Exception as exc:
        app.logger.error(
            "[advisory email] Error enviando estado=%s solicitud #%s: tipo=%s",
            advisory.status, advisory.id, type(exc).__name__,
        )


@app.route("/api/asesoramiento/files/<int:request_id>", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
@advisory_financial_prefreeze()
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
    # One backend source of truth for financial evidence, including legacy.
    # UI is advisory only; every POST recalculates under row lock.
    d["c1_state_editable"] = c2_can_change_state(advisory)
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
@advisory_financial_prefreeze()
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
@advisory_financial_prefreeze()
def admin_advisory_set_is_test(request_id):
    """Marca o desmarca una solicitud como 'prueba'. Solo admins."""
    advisory      = FiscalAdvisoryRequest.query.get_or_404(request_id)
    data          = request.get_json(silent=True) or {}
    advisory.is_test = bool(data.get("is_test", False))
    db.session.commit()
    return jsonify({"ok": True, "is_test": advisory.is_test})


@app.route("/api/admin/asesoramiento/solicitudes/<int:request_id>/nota", methods=["POST"])
@require_fiscal_advisor
@advisory_financial_prefreeze()
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
@advisory_financial_prefreeze()
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
    marketing_consent = data.get("marketing_consent") is True  # solo opt-in explícito

    # Validación
    if not name:
        return jsonify({"error": "El nombre es obligatorio."}), 400
    if not email_val or "@" not in email_val:
        return jsonify({"error": "El email no es válido."}), 400
    if not legal_accepted:
        return jsonify({"error": "Debes aceptar la política de privacidad."}), 400

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
        marketing_consent = marketing_consent,
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
