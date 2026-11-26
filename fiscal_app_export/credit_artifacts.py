"""Authenticated encryption and bounded retention for acquired PDF reports."""
import base64
import os
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import delete, select

from models import db, CreditAnalysis, CreditReportArtifact

ARTIFACT_RETENTION_DAYS = 365
_AAD_PREFIX = b"marianosevilla-fifo-credit-report-v1:"


def _key(raw: str | None) -> tuple[bytes, str]:
    if not isinstance(raw, str) or not raw:
        raise ValueError("Cifrado de informes no configurado")
    try:
        encoded = raw.encode("ascii")
        key = base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))
    except Exception as exc:
        raise ValueError("Clave de cifrado de informes inválida") from exc
    if len(key) != 32:
        raise ValueError("La clave de informes debe decodificar a 32 bytes")
    return key, "aes256gcm-v1"


def store_artifact(*, analysis_id: str, user_id: int, pdf_bytes: bytes,
                   encoded_key: str, now: datetime | None = None) -> CreditReportArtifact:
    key, version = _key(encoded_key)
    analysis = db.session.execute(
        select(CreditAnalysis).where(CreditAnalysis.id == analysis_id,
                                    CreditAnalysis.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if not analysis or analysis.status != "processing" or not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("Documento no elegible para persistencia")
    now = now or datetime.utcnow()
    nonce = os.urandom(12)
    aad = _AAD_PREFIX + f"{analysis_id}:{user_id}".encode("ascii")
    ciphertext = nonce + AESGCM(key).encrypt(nonce, pdf_bytes, aad)
    artifact = CreditReportArtifact(
        analysis_id=analysis_id, ciphertext=ciphertext, key_version=version,
        created_at=now, expires_at=now + timedelta(days=ARTIFACT_RETENTION_DAYS),
    )
    db.session.add(artifact)
    db.session.execute(delete(CreditReportArtifact).where(CreditReportArtifact.expires_at < now))
    db.session.commit()
    return artifact


def load_artifact(*, analysis_id: str, user_id: int, encoded_key: str,
                  now: datetime | None = None) -> bytes | None:
    key, version = _key(encoded_key)
    analysis = CreditAnalysis.query.filter_by(id=analysis_id, user_id=user_id,
                                              status="consumed").first()
    if not analysis:
        return None
    artifact = CreditReportArtifact.query.filter_by(analysis_id=analysis_id).first()
    now = now or datetime.utcnow()
    if not artifact or artifact.expires_at <= now:
        if artifact:
            db.session.delete(artifact)
            db.session.commit()
        return None
    if artifact.key_version != version or len(artifact.ciphertext) < 29:
        raise ValueError("Versión o contenido del documento no válido")
    nonce, ciphertext = artifact.ciphertext[:12], artifact.ciphertext[12:]
    aad = _AAD_PREFIX + f"{analysis_id}:{user_id}".encode("ascii")
    return AESGCM(key).decrypt(nonce, ciphertext, aad)
