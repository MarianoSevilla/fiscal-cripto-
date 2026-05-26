"""
Modelos de base de datos — Herramienta Fiscal Cripto
"""

import json
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from flask_bcrypt import Bcrypt

db = SQLAlchemy()
bcrypt = Bcrypt()


class User(UserMixin, db.Model):
    """Usuario registrado en la aplicación."""

    __tablename__ = "users"

    id                = db.Column(db.Integer, primary_key=True)
    email             = db.Column(db.String(254), unique=True, nullable=False, index=True)
    full_name         = db.Column(db.String(150), nullable=True)   # Nombre y apellidos
    password_hash     = db.Column(db.String(128), nullable=True)   # None para cuentas OAuth
    google_id         = db.Column(db.String(128), nullable=True, unique=True, index=True)
    plan              = db.Column(db.String(20), default="free", nullable=False)  # free | pro
    role              = db.Column(db.String(20), default="user", nullable=False)  # user | admin | fiscal_advisor
    is_active         = db.Column(db.Boolean, default=True, nullable=False)
    email_verified_at = db.Column(db.DateTime, nullable=True)      # None = pendiente de verificar
    created_at        = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login                = db.Column(db.DateTime, nullable=True)
    nif                       = db.Column(db.String(20), nullable=True)   # NIF/NIE/CIF — dato fiscal sensible
    comms_opted_out           = db.Column(db.Boolean, default=False, nullable=False)
    comms_unsubscribe_token   = db.Column(db.String(64), nullable=True, unique=True, index=True)

    def set_password(self, plaintext: str) -> None:
        """Hashea la contraseña con bcrypt (cost factor 12)."""
        self.password_hash = bcrypt.generate_password_hash(plaintext, rounds=12).decode("utf-8")

    def check_password(self, plaintext: str) -> bool:
        """Verifica la contraseña contra el hash almacenado. Devuelve False en cuentas OAuth sin password."""
        if not self.password_hash:
            return False
        return bcrypt.check_password_hash(self.password_hash, plaintext)

    def __repr__(self) -> str:
        return f"<User {self.email} plan={self.plan}>"


class FifoReport(db.Model):
    """Registro de cada informe FIFO generado — solo metadata, el PDF no se almacena."""

    __tablename__ = "fifo_reports"

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    exchange        = db.Column(db.String(50),  nullable=False)
    fiscal_year     = db.Column(db.Integer,     nullable=False)
    csv_rows        = db.Column(db.Integer,     nullable=True)   # filas del CSV (sin cabecera)
    distinct_assets = db.Column(db.Integer,     nullable=True)   # activos distintos en el informe
    processing_ms   = db.Column(db.Integer,     nullable=True)   # tiempo de procesamiento
    status          = db.Column(db.String(20),  nullable=False, default="generated")  # generated | failed
    error_type      = db.Column(db.String(100), nullable=True)   # tipo de error si status=failed
    created_at      = db.Column(db.DateTime,    default=datetime.utcnow, nullable=False)
    downloaded_at   = db.Column(db.DateTime,    nullable=True)   # NULL hasta que el usuario descarga

    # ── FASE 2A: telemetría estratégica ──────────────────────────────────────
    fifo_operations   = db.Column(db.Integer, nullable=True)   # ventas+swaps con resultado fiscal
    fifo_swaps        = db.Column(db.Integer, nullable=True)   # solo swaps (subset de operations)
    fifo_rendimientos = db.Column(db.Integer, nullable=True)   # staking / intereses / rebates
    fifo_movimientos  = db.Column(db.Integer, nullable=True)   # compras+ventas+swaps procesados
    fifo_advertencias = db.Column(db.Integer, nullable=True)   # warnings totales del motor
    fifo_desconocidas = db.Column(db.Integer, nullable=True)   # ops sin lotes previos (sin coste)

    resultado_neto    = db.Column(db.Float,      nullable=True)   # ganancias_brutas + perdidas_brutas
    ganancias_brutas  = db.Column(db.Float,      nullable=True)   # suma de ganancias (>=0)
    perdidas_brutas   = db.Column(db.Float,      nullable=True)   # suma de pérdidas (<0, valor negativo)

    fiscal_years_str  = db.Column(db.String(50), nullable=True)   # ejercicio raw: "2024", "2023,2024", "all"

    def __repr__(self) -> str:
        return f"<FifoReport user={self.user_id} exchange={self.exchange} year={self.fiscal_year}>"


class ProcessingError(db.Model):
    """Registro enriquecido de errores de procesamiento de CSV."""

    __tablename__ = "processing_errors"

    id                 = db.Column(db.Integer,    primary_key=True)
    created_at         = db.Column(db.DateTime,   default=datetime.utcnow, nullable=False, index=True)
    user_id            = db.Column(db.Integer,    db.ForeignKey("users.id"), nullable=True)
    email              = db.Column(db.String(254), nullable=True)
    exchange           = db.Column(db.String(50),  nullable=True, index=True)
    parser             = db.Column(db.String(100), nullable=True)
    stage              = db.Column(db.String(50),  nullable=True)
    error_type         = db.Column(db.String(100), nullable=True)
    message_short      = db.Column(db.String(500), nullable=True)
    traceback_short    = db.Column(db.Text,        nullable=True)
    fingerprint        = db.Column(db.String(64),  nullable=True, index=True)
    csv_filename       = db.Column(db.String(255), nullable=True)
    csv_size           = db.Column(db.Integer,     nullable=True)
    auto_email_sent    = db.Column(db.Boolean,     default=False, nullable=False)
    auto_email_sent_at = db.Column(db.DateTime,    nullable=True)
    email_send_error   = db.Column(db.String(500), nullable=True)
    user_replied       = db.Column(db.Boolean,     default=False, nullable=False)
    resolved           = db.Column(db.Boolean,     default=False, nullable=False, index=True)
    resolved_at        = db.Column(db.DateTime,    nullable=True)

    def __repr__(self) -> str:
        return f"<ProcessingError id={self.id} exchange={self.exchange} type={self.error_type}>"


class Contacto(db.Model):
    """Mensaje recibido a través del formulario de contacto."""

    __tablename__ = "contactos"

    id            = db.Column(db.Integer, primary_key=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    nombre        = db.Column(db.String(80),  nullable=False)
    email         = db.Column(db.String(255), nullable=False)
    tipo_consulta = db.Column(db.String(50),  nullable=False)
    mensaje       = db.Column(db.Text,        nullable=False)
    ip            = db.Column(db.String(45),  nullable=True)
    user_agent    = db.Column(db.Text,        nullable=True)
    estado        = db.Column(db.String(20),  default="nuevo", nullable=False)

    def __repr__(self) -> str:
        return f"<Contacto {self.email} tipo={self.tipo_consulta}>"


class FiscalAdvisoryRequest(db.Model):
    __tablename__ = "fiscal_advisory_requests"

    STATUS_LABELS = {
        "pending_payment":   "Pendiente de pago",
        "paid_received":     "Solicitud recibida",
        "under_review":      "En revisión",
        "waiting_user_info": "Esperando información",
        "in_progress":       "En curso",
        "completed":         "Finalizado",
        "cancelled":         "Cancelado",
        "refunded":          "Reembolsado",
    }
    SERVICE_LABELS = {
        "revision_basica":   "Revisión fiscal básica",
        "revision_avanzada": "Revisión fiscal avanzada",
        "caso_complejo":     "Caso complejo / valoración personalizada",
    }

    id                         = db.Column(db.Integer, primary_key=True)
    user_id                    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    full_name                  = db.Column(db.String(150), nullable=False)
    email                      = db.Column(db.String(254), nullable=False)
    phone                      = db.Column(db.String(30), nullable=True)
    tax_residence_country      = db.Column(db.String(100), nullable=False)
    tax_year                   = db.Column(db.Integer, nullable=False)
    service_type               = db.Column(db.String(50), nullable=False)
    operation_types            = db.Column(db.Text, nullable=True)   # JSON array
    exchanges                  = db.Column(db.Text, nullable=True)
    operation_volume           = db.Column(db.String(50), nullable=True)
    current_situation          = db.Column(db.Text, nullable=True)   # JSON array
    case_description           = db.Column(db.Text, nullable=False)
    status                     = db.Column(db.String(30), nullable=False, default="pending_payment", index=True)
    stripe_checkout_session_id = db.Column(db.String(255), nullable=True, unique=True)
    stripe_payment_intent_id   = db.Column(db.String(255), nullable=True)
    amount_paid                = db.Column(db.Integer, nullable=True)   # céntimos
    currency                   = db.Column(db.String(3), nullable=True, default="eur")
    assigned_to                = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    internal_notes             = db.Column(db.Text, nullable=True)
    created_at                 = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at                 = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    files          = db.relationship("FiscalAdvisoryFile",          backref="request",  lazy=True, cascade="all, delete-orphan")
    status_history = db.relationship("FiscalAdvisoryStatusHistory", backref="request",  lazy=True, cascade="all, delete-orphan")
    notes          = db.relationship("AdvisoryInternalNote",         backref="advisory", lazy=True, cascade="all, delete-orphan")

    def get_operation_types(self):
        try: return json.loads(self.operation_types) if self.operation_types else []
        except: return []

    def get_current_situation(self):
        try: return json.loads(self.current_situation) if self.current_situation else []
        except: return []

    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    def service_label(self):
        return self.SERVICE_LABELS.get(self.service_type, self.service_type)

    def to_dict(self, full=False):
        d = {
            "id": self.id, "user_id": self.user_id,
            "full_name": self.full_name, "email": self.email,
            "tax_year": self.tax_year, "service_type": self.service_type,
            "service_label": self.service_label(),
            "status": self.status, "status_label": self.status_label(),
            "amount_paid": self.amount_paid, "currency": self.currency,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if full:
            d.update({
                "phone": self.phone,
                "tax_residence_country": self.tax_residence_country,
                "operation_types": self.get_operation_types(),
                "exchanges": self.exchanges,
                "operation_volume": self.operation_volume,
                "current_situation": self.get_current_situation(),
                "case_description": self.case_description,
                "internal_notes": self.internal_notes,
                "assigned_to": self.assigned_to,
                "stripe_checkout_session_id": self.stripe_checkout_session_id,
            })
        return d


class FiscalAdvisoryFile(db.Model):
    __tablename__ = "fiscal_advisory_files"

    id          = db.Column(db.Integer, primary_key=True)
    request_id  = db.Column(db.Integer, db.ForeignKey("fiscal_advisory_requests.id"), nullable=False, index=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    file_name   = db.Column(db.String(255), nullable=False)
    file_path   = db.Column(db.String(512), nullable=False)
    file_type   = db.Column(db.String(100), nullable=True)
    file_size   = db.Column(db.Integer, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FiscalAdvisoryStatusHistory(db.Model):
    __tablename__ = "fiscal_advisory_status_history"

    id         = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("fiscal_advisory_requests.id"), nullable=False, index=True)
    status     = db.Column(db.String(30), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    note       = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class AdvisoryInternalNote(db.Model):
    """Nota interna por solicitud — solo visible para admin/asesor fiscal."""

    __tablename__ = "advisory_internal_notes"

    id          = db.Column(db.Integer, primary_key=True)
    request_id  = db.Column(db.Integer, db.ForeignKey("fiscal_advisory_requests.id"), nullable=False, index=True)
    author_id   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    author_name = db.Column(db.String(150), nullable=True)   # denormalizado para lectura rápida
    text        = db.Column(db.Text, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "author_name": self.author_name or "Admin",
            "text":        self.text,
            "created_at":  self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<AdvisoryInternalNote request={self.request_id} author={self.author_name}>"


class CommunicationCampaign(db.Model):
    """Campaña de email marketing — una por envío masivo."""

    __tablename__ = "communication_campaigns"

    id               = db.Column(db.Integer, primary_key=True)
    subject          = db.Column(db.String(500), nullable=False)
    body             = db.Column(db.Text, nullable=False)
    preview_text     = db.Column(db.String(200), nullable=True)
    status           = db.Column(db.String(20), default="draft", nullable=False, index=True)
    # draft | queued | sending | sent | partial_success | failed | cancelled
    created_by_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sent_at          = db.Column(db.DateTime, nullable=True)
    recipients_count  = db.Column(db.Integer, default=0, nullable=False)
    error_message     = db.Column(db.Text, nullable=True)
    idempotency_key   = db.Column(db.String(64), unique=True, nullable=True)
    # Recipient segment: "all" | "verified" | "unverified"
    recipient_segment = db.Column(db.String(20), default="all", nullable=False)

    deliveries = db.relationship("CommunicationDelivery", backref="campaign", lazy="dynamic")

    def sent_count(self) -> int:
        return self.deliveries.filter_by(status="sent").count()

    def failed_count(self) -> int:
        return self.deliveries.filter_by(status="failed").count()

    def pending_count(self) -> int:
        return self.deliveries.filter_by(status="pending").count()

    def to_dict(self, with_stats: bool = False) -> dict:
        d = {
            "id":               self.id,
            "subject":          self.subject,
            "body":             self.body,
            "preview_text":     self.preview_text or "",
            "status":           self.status,
            "created_by_id":    self.created_by_id,
            "created_at":       self.created_at.isoformat() if self.created_at else None,
            "sent_at":          self.sent_at.isoformat() if self.sent_at else None,
            "recipients_count":  self.recipients_count,
            "idempotency_key":   self.idempotency_key,
            "error_message":     self.error_message,
            "recipient_segment": self.recipient_segment or "all",
        }
        if with_stats:
            d["stats"] = {
                "sent":    self.sent_count(),
                "failed":  self.failed_count(),
                "pending": self.pending_count(),
            }
        return d

    def __repr__(self) -> str:
        return f"<CommunicationCampaign id={self.id} status={self.status}>"


class CommunicationDelivery(db.Model):
    """Registro de entrega individual por usuario dentro de una campaña."""

    __tablename__ = "communication_deliveries"

    id          = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("communication_campaigns.id"), nullable=False, index=True)
    user_id     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    email       = db.Column(db.String(254), nullable=False)
    status      = db.Column(db.String(20), default="pending", nullable=False)
    # pending | sent | failed | skipped
    provider_id = db.Column(db.String(200), nullable=True)
    sent_at     = db.Column(db.DateTime, nullable=True)
    error       = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.Index("ix_comms_delivery_campaign_status", "campaign_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "campaign_id": self.campaign_id,
            "user_id":     self.user_id,
            "email":       self.email,
            "status":      self.status,
            "provider_id": self.provider_id or "",
            "sent_at":     self.sent_at.isoformat() if self.sent_at else None,
            "error":       self.error or "",
        }

    def __repr__(self) -> str:
        return f"<CommunicationDelivery campaign={self.campaign_id} email={self.email} status={self.status}>"
