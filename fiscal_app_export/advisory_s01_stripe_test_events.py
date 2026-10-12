"""S01: conciliación ATÓMICA de evento Stripe firmado, exclusivamente TEST.

NO existe endpoint HTTP, tarea ni hook que invoque esta función. Ni el webhook
legacy ni PREFREEZE utilizan este módulo. No conectar en producción.
Este código nunca crea sesiones, cobra, reembolsa, factura ni envía correo.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import os
import re
from typing import Any

import stripe

from models import (
    db, FiscalAdvisoryRequest, FiscalAdvisoryStatusHistory,
    S01StripeCheckoutAttempt, S01StripeEventReceipt,
)


class S01EventRejected(ValueError):
    """Evidencia ausente o incompatible: no confirmar ni acusar como procesado."""


class S01EventStorageError(RuntimeError):
    """Error transaccional: se requiere reintento/concilación, no HTTP 2xx."""


def _require_test_environment(secret: str) -> None:
    if os.environ.get("FLASK_ENV") != "testing":
        raise S01EventRejected("Solo se permiten pruebas aisladas")
    if not isinstance(secret, str) or not secret.startswith("whsec_") or len(secret) < 12:
        raise S01EventRejected("Falta un secreto de webhook de pruebas")


def _mapping(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    f = getattr(obj, "to_dict_recursive", None)
    if callable(f):
        o = f()
        if isinstance(o, dict):
            return o
    raise S01EventRejected("Objeto Stripe no reconocible")


def _event_signed(*, payload: bytes, signature: str, secret: str) -> dict:
    """Verifica HMAC y antigüedad vía el SDK oficial; sin peticiones de red."""
    _require_test_environment(secret)
    if (not isinstance(payload, bytes) or not payload or len(payload) > 65536
            or not isinstance(signature, str) or not signature.strip()
            or len(signature) > 4096):
        raise S01EventRejected("Firma o carga de evento inválida")
    try:
        event = stripe.Webhook.construct_event(payload, signature, secret)
        doc = _mapping(event)
    except (ValueError, stripe.error.SignatureVerificationError, S01EventRejected):
        raise S01EventRejected("Firma Stripe inválida") from None
    except Exception:
        # No se hace ACK si la verificación fallase de forma inesperada.
        raise S01EventRejected("No se pudo verificar Stripe") from None
    if doc.get("livemode") is not False:
        raise S01EventRejected("Evento Live prohibido")
    eid = doc.get("id")
    if not isinstance(eid, str) or not re.fullmatch(r"evt_[a-zA-Z0-9_]{3,251}", eid):
        raise S01EventRejected("ID de evento inválido")
    if doc.get("type") != "checkout.session.completed":
        raise S01EventRejected("Evento fuera del contrato S01")
    data = _mapping(doc.get("data"))
    session = _mapping(data.get("object"))
    return {"event_id": eid, "session": session}


def _validate_session(session: dict) -> tuple[str, str, str, int, str]:
    if session.get("livemode") is not False:
        raise S01EventRejected("Checkout Live rechazado")
    sid = session.get("id")
    if not isinstance(sid, str) or not re.fullmatch(r"cs_test_[a-zA-Z0-9_]{3,230}", sid):
        raise S01EventRejected("Checkout TEST inválido")
    if session.get("mode") != "payment" or session.get("status") != "complete" or session.get("payment_status") != "paid":
        raise S01EventRejected("Pago no confirmado")
    amount = session.get("amount_total")
    if type(amount) is not int or not (100 <= amount <= 99_999_999):
        raise S01EventRejected("Importe inválido")
    if session.get("currency") != "eur":
        raise S01EventRejected("Divisa inválida")
    pi = session.get("payment_intent")
    if not isinstance(pi, str) or not re.fullmatch(r"pi_[a-zA-Z0-9_]{3,252}", pi):
        raise S01EventRejected("PaymentIntent inválido")
    metadata = _mapping(session.get("metadata"))
    attempt_id = metadata.get("s01_attempt_id")
    advisory_id = metadata.get("s01_advisory_id")
    quote_hash = metadata.get("s01_quote_sha256")
    if not isinstance(attempt_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", attempt_id):
        raise S01EventRejected("Intento no identificable")
    if not isinstance(advisory_id, str) or not re.fullmatch(r"[1-9][0-9]*", advisory_id):
        raise S01EventRejected("Expediente no identificable")
    if not isinstance(quote_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", quote_hash):
        raise S01EventRejected("Huella de presupuesto inválida")
    if session.get("client_reference_id") != advisory_id:
        raise S01EventRejected("Referencia cliente no coincide")
    return attempt_id, advisory_id, sid, amount, pi


def _assert_correlated(*, advisory, attempt, session: dict,
                       amount: int, pi: str, attempt_id: str,
                       advisory_id: str, sid: str) -> None:
    if advisory is None or attempt is None or advisory.is_test is not True:
        raise S01EventRejected("Expediente de pruebas no encontrado")
    if attempt.id != attempt_id or attempt.advisory_id != advisory.id:
        raise S01EventRejected("Intento no asociado al expediente")
    if str(advisory.id) != advisory_id:
        raise S01EventRejected("ID expediente inconsistente")
    if not isinstance(advisory.payment_link_token, str):
        raise S01EventRejected("Presupuesto sin token")
    hash_now = sha256(advisory.payment_link_token.encode("utf-8")).hexdigest()
    metadata = _mapping(session["metadata"])
    if attempt.quote_fingerprint != hash_now or metadata.get("s01_quote_sha256") != hash_now:
        raise S01EventRejected("Presupuesto reemplazado o huella distinta")
    if attempt.checkout_session_id != sid or advisory.stripe_checkout_session_id != sid:
        raise S01EventRejected("Checkout no registrado en ambas tablas")
    if (attempt.currency != "eur" or attempt.expected_amount_cents != amount
            or advisory.quoted_amount != amount or advisory.currency not in (None, "eur")):
        raise S01EventRejected("Importe/divisa no coincide con el presupuesto")
    fee, commission, rate = (
        advisory.rafa_fee_cents, advisory.commission_cents,
        advisory.commission_rate_bps,
    )
    if (type(fee) is not int or type(commission) is not int or
            type(rate) is not int or fee < 100 or rate != 3000 or
            commission != (fee * 30 + 50) // 100 or fee + commission != amount):
        raise S01EventRejected("Desglose comercial no coincide")
    if attempt.idempotency_key != "s01-checkout-v1-" + attempt.id:
        raise S01EventRejected("Clave de intento alterada")
    if attempt.payment_intent_id not in (None, pi) or advisory.stripe_payment_intent_id not in (None, pi):
        raise S01EventRejected("PaymentIntent diferente")
    if advisory.paypal_order_id or advisory.paypal_capture_id:
        raise S01EventRejected("Actividad PayPal previa requiere conciliación")


def process_signed_s01_test_webhook(*, payload: bytes, signature: str,
                                    webhook_secret: str) -> str:
    """Confirma el pago de S01 y el recibo de Stripe EN UNA SOLA TRANSACCIÓN.

    Se asume PostgreSQL con SELECT FOR UPDATE para verdadera concurrencia.
    SQLite usado en unit tests prueba únicamente secuencialidad. El cierre
    del flujo PREFREEZE requiere un contrato HTTP y pruebas PG18 adicionales.
    """
    event = _event_signed(payload=payload, signature=signature,
                          secret=webhook_secret)
    session = event["session"]
    attempt_id, advisory_id, sid, amount, pi = _validate_session(session)
    event_id = event["event_id"]

    try:
        # Primer bloqueo: expediente; mismo orden que la reserva Checkout.
        advisory = (
            db.session.query(FiscalAdvisoryRequest)
            .filter_by(id=int(advisory_id)).with_for_update().one_or_none()
        )
        attempt = (
            db.session.query(S01StripeCheckoutAttempt)
            .filter_by(id=attempt_id).with_for_update().one_or_none()
        )
        _assert_correlated(
            advisory=advisory, attempt=attempt, session=session, amount=amount,
            pi=pi, attempt_id=attempt_id, advisory_id=advisory_id, sid=sid,
        )

        receipt = db.session.get(S01StripeEventReceipt, event_id)
        if receipt is not None:
            if (receipt.attempt_id != attempt_id or
                    receipt.event_type != "checkout.session.completed"):
                raise S01EventRejected("ID de evento reutilizado con otros datos")
            if (attempt.status != "paid" or advisory.status != "paid_received"
                    or advisory.payment_provider != "stripe"
                    or advisory.amount_paid != amount
                    or advisory.stripe_payment_intent_id != pi
                    or attempt.payment_intent_id != pi):
                raise S01EventRejected("Recibo existente con estado incongruente")
            db.session.rollback()
            return "duplicate"

        if (attempt.status == "paid" and advisory.status == "paid_received"
                and advisory.payment_provider == "stripe"
                and advisory.amount_paid == amount
                and advisory.stripe_payment_intent_id == pi
                and attempt.payment_intent_id == pi):
            # Evento distinto del mismo pago: no duplicar cambio de estado.
            db.session.add(S01StripeEventReceipt(
                stripe_event_id=event_id, attempt_id=attempt.id,
                event_type="checkout.session.completed",
            ))
            db.session.commit()
            return "already_paid"

        if attempt.status != "ready" or advisory.status != "quote_sent" or advisory.paid_at is not None:
            raise S01EventRejected("Pago potencial sin conciliación previa")

        # Un solo COMMIT: intento + expediente + historia + deduplicación.
        attempt.status = "paid"
        attempt.payment_intent_id = pi
        advisory.status = "paid_received"
        advisory.amount_paid = amount
        advisory.currency = "eur"
        advisory.payment_provider = "stripe"
        advisory.stripe_payment_intent_id = pi
        advisory.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.session.add(S01StripeEventReceipt(
            stripe_event_id=event_id, attempt_id=attempt.id,
            event_type="checkout.session.completed",
        ))
        db.session.add(FiscalAdvisoryStatusHistory(
            request_id=advisory.id,
            status="paid_received",
            changed_by=None,
            note="Stripe Checkout TEST confirmado mediante evento firmado.",
        ))
        db.session.commit()
        return "paid"
    except S01EventRejected:
        db.session.rollback()
        raise
    except Exception:
        db.session.rollback()
        raise S01EventStorageError("Fallo de transacción financiera S01") from None
