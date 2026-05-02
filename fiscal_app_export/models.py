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

    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    plan       = db.Column(db.String(20), default="free", nullable=False)  # free | pro
    is_active  = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    def set_password(self, plaintext: str) -> None:
        """Hashea la contraseña con bcrypt (cost factor 12)."""
        self.password_hash = bcrypt.generate_password_hash(plaintext, rounds=12).decode("utf-8")

    def check_password(self, plaintext: str) -> bool:
        """Verifica la contraseña contra el hash almacenado."""
        return bcrypt.check_password_hash(self.password_hash, plaintext)

    def __repr__(self) -> str:
        return f"<User {self.email} plan={self.plan}>"
