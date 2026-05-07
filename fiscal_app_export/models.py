"""
Modelos de base de datos — Herramienta Fiscal Cripto
"""

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
    password_hash     = db.Column(db.String(128), nullable=True)   # None para cuentas OAuth
    google_id         = db.Column(db.String(128), nullable=True, unique=True, index=True)
    plan              = db.Column(db.String(20), default="free", nullable=False)  # free | pro
    is_active         = db.Column(db.Boolean, default=True, nullable=False)
    email_verified_at = db.Column(db.DateTime, nullable=True)      # None = pendiente de verificar
    created_at        = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login        = db.Column(db.DateTime, nullable=True)

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

    def __repr__(self) -> str:
        return f"<FifoReport user={self.user_id} exchange={self.exchange} year={self.fiscal_year}>"
