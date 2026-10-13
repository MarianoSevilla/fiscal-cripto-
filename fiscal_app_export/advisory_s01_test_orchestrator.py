"""Orquestación S01 exclusivamente en TEST y para expedientes sintéticos.

No registra rutas Flask ni usa el SDK Stripe directamente. El proveedor se
inyecta y se simula en pruebas. Nunca emite facturas, correos ni transfers.
No activar hasta integrar PREFREEZE, firma de webhooks y conciliación completa.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from advisory_s01_checkout import (
    S01CheckoutBlocked,
    S01Reservation,
    build_test_checkout_request,
)
from models import FiscalAdvisoryRequest, S01StripeCheckoutAttempt, db


@dataclass(frozen=True)
class TestCheckoutLink:
    attempt_id: str
    session_id: str
    url: str


@dataclass(frozen=True)
class S01AcceptanceIntent:
    """Trusted synthetic HTTP handler has validated CSRF + exact-price consent.

    Does not itself establish customer identity or terms (G06/G07 pending).
    """
    total_cents: int
    accepted_at_ts: int


def _test_only(*, key: str) -> None:
    # TESTING de Flask no es una barrera: dependemos del entorno de arranque,
    # la clave sk_test_ y una reserva de expediente sintético (is_test=True).
    if os.environ.get("FLASK_ENV") != "testing":
        raise S01CheckoutBlocked("Solo disponible en entorno aislado de pruebas")
    if not isinstance(key, str) or not key.startswith("sk_test_") or len(key) <= len("sk_test_"):
        raise S01CheckoutBlocked("Se requiere clave Stripe TEST, nunca Live")


def _expires_ts(value: datetime | None) -> int:
    if not isinstance(value, datetime):
        raise S01CheckoutBlocked("Presupuesto sin vencimiento")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


def _test_origin(url: str) -> None:
    """No permitir un retorno a producción durante pruebas sintéticas."""
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        raise S01CheckoutBlocked("Origen de pruebas inválido") from None
    host = (parsed.hostname or "").lower()
    if host in {"marianosevilla.com", "www.marianosevilla.com"}:
        raise S01CheckoutBlocked("No redirigir pruebas a producción")
    if not (host.endswith(".invalid") or
            (host.endswith(".up.railway.app") and "staging" in host)):
        raise S01CheckoutBlocked("Origen de pruebas no permitido")


def _reserve(*, advisory_id: int, token: str, now_ts: int,
             base_url: str, acceptance: S01AcceptanceIntent | None = None
             ) -> tuple[S01Reservation, dict]:
    """Reserva bajo bloqueo SQL, COMMIT antes de cualquier salida a Stripe."""
    if type(advisory_id) is not int or advisory_id <= 0:
        raise S01CheckoutBlocked("ID de expediente inválido")
    if not isinstance(token, str):
        raise S01CheckoutBlocked("Token inválido")
    if type(now_ts) is not int or now_ts <= 0:
        raise S01CheckoutBlocked("Hora inválida")
    _test_origin(base_url)

    try:
        advisory = (
            db.session.query(FiscalAdvisoryRequest)
            .filter_by(id=advisory_id, payment_link_token=token)
            .with_for_update()
            .first()
        )
        if advisory is None or advisory.status != "quote_sent" or advisory.is_test is not True:
            raise S01CheckoutBlocked("Expediente no apto para Checkout TEST")
        if (advisory.stripe_checkout_session_id or advisory.stripe_payment_intent_id or
                advisory.paypal_order_id or advisory.paypal_capture_id or advisory.paid_at or
                advisory.payment_provider is not None or advisory.amount_paid is not None):
            raise S01CheckoutBlocked("Hay actividad financiera previa: requiere conciliación")
        if advisory.quote_accepted_at is None and acceptance is None:
            raise S01CheckoutBlocked("El presupuesto no está aceptado: consentimiento obligatorio")
        if acceptance is not None:
            if (type(acceptance) is not S01AcceptanceIntent
                    or advisory.quote_accepted_at is not None
                    or type(acceptance.total_cents) is not int
                    or type(acceptance.accepted_at_ts) is not int
                    or acceptance.accepted_at_ts != now_ts
                    or acceptance.total_cents != advisory.quoted_amount):
                raise S01CheckoutBlocked("Consentimiento o importe no verificables")
        if S01StripeCheckoutAttempt.query.filter_by(advisory_id=advisory_id).first():
            raise S01CheckoutBlocked("Intento ya reservado: nunca crear un segundo Checkout")
        if any(type(v) is not int for v in (
                advisory.rafa_fee_cents, advisory.commission_cents,
                advisory.quoted_amount, advisory.commission_rate_bps)):
            raise S01CheckoutBlocked("Desglose incompleto")
        if advisory.commission_rate_bps != 3000:
            raise S01CheckoutBlocked("Comisión inesperada")
        reservation = S01Reservation(
            attempt_id=str(uuid4()),
            advisory_id=advisory.id,
            quote_token=advisory.payment_link_token,
            rafa_fee_cents=advisory.rafa_fee_cents,
            commission_cents=advisory.commission_cents,
            total_cents=advisory.quoted_amount,
            quote_expires_at_ts=_expires_ts(advisory.quote_expires_at),
            customer_email=advisory.email,
        )
        params = build_test_checkout_request(
            reservation=reservation, base_url=base_url, now_ts=now_ts
        )
        # G07 atomicity: only after all validations have succeeded, record
        # acceptance AND insert the durable Checkout reservation in ONE commit.
        # A preparatory failure rolls back both, never leaving an orphan.
        if acceptance is not None:
            advisory.quote_accepted_at = datetime.fromtimestamp(
                acceptance.accepted_at_ts, timezone.utc
            ).replace(tzinfo=None)
            advisory.quote_acceptance_user_agent = "S01 OFFLINE SYNTHETIC TEST"
        attempt = S01StripeCheckoutAttempt(
            id=reservation.attempt_id,
            advisory_id=advisory.id,
            quote_fingerprint=reservation.quote_fingerprint,
            idempotency_key=reservation.idempotency_key,
            expected_amount_cents=reservation.total_cents,
            currency="eur",
            # 'creating' es deliberadamente incierto tras la reserva: caída
            # antes/durante/después de la llamada no autoriza otro intento.
            status="creating",
        )
        db.session.add(attempt)
        db.session.commit()
        return reservation, params
    except S01CheckoutBlocked:
        db.session.rollback()
        raise
    except IntegrityError:
        db.session.rollback()
        raise S01CheckoutBlocked("Intento concurrente detectado; operación bloqueada") from None
    except Exception:
        db.session.rollback()
        raise S01CheckoutBlocked("Reserva no confirmada; no contactar con Stripe") from None


def _session_mapping(raw: object) -> dict:
    if isinstance(raw, dict):
        return dict(raw)
    # stripe-python 16 puede entregar StripeObject con to_dict().
    # to_dict_recursive es un fallback para implementaciones anteriores.
    # Si la conversión falla, nunca se acepta ni se reintenta la sesión.
    for method in ("to_dict", "to_dict_recursive"):
        converter = getattr(raw, method, None)
        if callable(converter):
            try:
                converted = converter()
            except Exception:
                raise S01CheckoutBlocked("Respuesta Stripe no verificable") from None
            if isinstance(converted, dict):
                return dict(converted)
    raise S01CheckoutBlocked("Respuesta Stripe no verificable")


def _validate_created(raw: object, reservation: S01Reservation) -> TestCheckoutLink:
    session = _session_mapping(raw)
    ident = session.get("id")
    if (not isinstance(ident, str) or not ident.startswith("cs_test_") or
            session.get("livemode") is not False or session.get("mode") != "payment" or
            session.get("status") != "open" or session.get("payment_status") != "unpaid"):
        raise S01CheckoutBlocked("Sesión Stripe TEST no apta")
    if (type(session.get("amount_total")) is not int or
            session["amount_total"] != reservation.total_cents or
            session.get("currency") != "eur" or
            session.get("client_reference_id") != str(reservation.advisory_id)):
        raise S01CheckoutBlocked("Importe/divisa o expediente no coinciden")
    m = session.get("metadata")
    if (not isinstance(m, dict) or
            m.get("s01_attempt_id") != reservation.attempt_id or
            m.get("s01_advisory_id") != str(reservation.advisory_id) or
            m.get("s01_quote_sha256") != reservation.quote_fingerprint):
        raise S01CheckoutBlocked("Sesión no coincide con la reserva")
    url = session.get("url")
    if not isinstance(url, str):
        raise S01CheckoutBlocked("Stripe no devolvió enlace")
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != "checkout.stripe.com" or
                parts.username or parts.password or not parts.path.startswith("/c/pay/")):
            raise S01CheckoutBlocked("Destino de Checkout no autorizado")
    except ValueError:
        raise S01CheckoutBlocked("Destino de Checkout inválido") from None
    return TestCheckoutLink(
        attempt_id=reservation.attempt_id,
        session_id=ident,
        url=url,
    )


def _mark_uncertain(attempt_id: str) -> None:
    """Mejor esfuerzo: si falla, el estado anterior 'creating' sigue bloqueando."""
    try:
        attempt = (
            db.session.query(S01StripeCheckoutAttempt)
            .filter_by(id=attempt_id).with_for_update().first()
        )
        if attempt and attempt.status == "creating":
            attempt.status = "uncertain"
        db.session.commit()
    except Exception:
        db.session.rollback()


def create_synthetic_checkout(*, advisory_id: int, token: str,
                              now_ts: int, base_url: str, stripe_test_key: str,
                              provider: object,
                              acceptance: S01AcceptanceIntent | None = None
                              ) -> TestCheckoutLink:
    """TEST ONLY. El proveedor expone create_session(params=..., idempotency_key=...).

    El proveedor se invoca UNA VEZ, DESPUÉS de persistir la reserva. Tras un
    timeout no se reintenta, ni con la misma idempotency_key: el caso se bloquea
    hasta una futura conciliación autorizada.
    """
    _test_only(key=stripe_test_key)
    if provider is None or not callable(getattr(provider, "create_session", None)):
        raise S01CheckoutBlocked("Adaptador de pruebas ausente")

    reservation, params = _reserve(
        advisory_id=advisory_id, token=token, now_ts=now_ts, base_url=base_url,
        acceptance=acceptance,
    )
    try:
        raw = provider.create_session(
            params=params, idempotency_key=reservation.idempotency_key,
        )
        link = _validate_created(raw, reservation)
    except Exception:
        _mark_uncertain(reservation.attempt_id)
        raise S01CheckoutBlocked("Resultado del proveedor incierto; no repetir el cobro") from None

    try:
        attempt = (
            db.session.query(S01StripeCheckoutAttempt)
            .filter_by(id=reservation.attempt_id).with_for_update().first()
        )
        if attempt is None or attempt.status != "creating" or attempt.checkout_session_id:
            raise S01CheckoutBlocked("Estado de intento no conciliable")
        attempt.checkout_session_id = link.session_id
        attempt.status = "ready"
        # En la misma transacción, una referencia para el webhook futuro.
        advisory = (
            db.session.query(FiscalAdvisoryRequest)
            .filter_by(id=advisory_id).with_for_update().first()
        )
        if (advisory is None or advisory.status != "quote_sent" or
                advisory.is_test is not True or
                advisory.payment_link_token != token or
                advisory.quoted_amount != reservation.total_cents or
                advisory.rafa_fee_cents != reservation.rafa_fee_cents or
                advisory.commission_cents != reservation.commission_cents or
                advisory.commission_rate_bps != 3000 or
                advisory.paypal_order_id or advisory.paypal_capture_id or
                advisory.stripe_payment_intent_id or advisory.paid_at or
                advisory.stripe_checkout_session_id):
            raise S01CheckoutBlocked("El presupuesto cambió antes de registrar Checkout")
        advisory.stripe_checkout_session_id = link.session_id
        db.session.commit()
    except Exception:
        db.session.rollback()
        _mark_uncertain(reservation.attempt_id)
        raise S01CheckoutBlocked("Checkout creado pero confirmación local incierta") from None

    return link
