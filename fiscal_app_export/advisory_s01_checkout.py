"""S01 Checkout TEST: contrato verificable, sin efectos secundarios de proveedor.

NO registra rutas ni ejecuta pagos. Solo construye parámetros de Checkout y
valida objetos previamente autenticados por el webhook oficial de Stripe.
La reserva duradera (modelo S01StripeCheckoutAttempt) deberá COMMITARSE antes
de toda solicitud futura a Stripe. Resultado incierto: bloqueo y conciliación.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from urllib.parse import urlsplit
from uuid import UUID


class S01CheckoutBlocked(ValueError):
    """No es seguro crear ni confirmar una sesión de Checkout."""


@dataclass(frozen=True)
class S01Reservation:
    attempt_id: str
    advisory_id: int
    quote_token: str
    rafa_fee_cents: int
    commission_cents: int
    total_cents: int
    quote_expires_at_ts: int
    customer_email: str

    @property
    def quote_fingerprint(self) -> str:
        return sha256(self.quote_token.encode("ascii")).hexdigest()

    @property
    def idempotency_key(self) -> str:
        # Estable, único por reserva: nunca regenerar tras fallo ambiguo.
        return "s01-checkout-v1-" + self.attempt_id


def _valid_reservation(reservation: S01Reservation) -> None:
    if not isinstance(reservation, S01Reservation):
        raise S01CheckoutBlocked("Reserva de Checkout inválida")
    try:
        uid = UUID(reservation.attempt_id)
    except (ValueError, AttributeError, TypeError):
        raise S01CheckoutBlocked("ID de intento inválido") from None
    if uid.version != 4 or str(uid) != reservation.attempt_id:
        raise S01CheckoutBlocked("Se exige un UUIDv4 canónico")
    if isinstance(reservation.advisory_id, bool) or not isinstance(reservation.advisory_id, int) or reservation.advisory_id < 1:
        raise S01CheckoutBlocked("Identificador de expediente inválido")
    if not isinstance(reservation.quote_token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", reservation.quote_token):
        raise S01CheckoutBlocked("Token del presupuesto inválido")
    cents = (reservation.rafa_fee_cents, reservation.commission_cents, reservation.total_cents)
    if any(isinstance(v, bool) or not isinstance(v, int) for v in cents):
        raise S01CheckoutBlocked("Importes no enteros")
    fee, commission, total = cents
    if fee < 100 or commission < 0 or total < 100 or total > 99_999_999:
        raise S01CheckoutBlocked("Importes fuera de rango")
    # Redondeo HALF_UP para céntimos positivos: (fee * 30 + 50) // 100.
    if commission != (fee * 30 + 50) // 100 or total != fee + commission:
        raise S01CheckoutBlocked("Desglose del 30 % incoherente")
    if not isinstance(reservation.customer_email, str) or len(reservation.customer_email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", reservation.customer_email):
        raise S01CheckoutBlocked("Correo del cliente inválido")
    if isinstance(reservation.quote_expires_at_ts, bool) or not isinstance(reservation.quote_expires_at_ts, int):
        raise S01CheckoutBlocked("Vencimiento inválido")


def build_test_checkout_request(*, reservation: S01Reservation, base_url: str, now_ts: int) -> dict:
    """Produce parámetros Stripe Checkout *sin contactar al proveedor*.

    Apto exclusivamente para entorno TEST. Ninguna ruta lo invoca todavía.
    Apple Pay y Google Pay se muestran, si son elegibles, sobre 'card' en
    Stripe-hosted Checkout; no requieren un método independiente.
    """
    _valid_reservation(reservation)
    if isinstance(now_ts, bool) or not isinstance(now_ts, int):
        raise S01CheckoutBlocked("Reloj inválido")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise S01CheckoutBlocked("Se exige origen HTTPS sin parámetros")
    if not isinstance(base_url, str) or any(c.isspace() for c in base_url):
        raise S01CheckoutBlocked("URL base inválida")

    # Checkout exige expiración entre 30 minutos y 24 horas.
    expires = min(reservation.quote_expires_at_ts, now_ts + 86400)
    if expires < now_ts + 1800:
        raise S01CheckoutBlocked("Presupuesto caducado o con validez insuficiente")
    ref = str(reservation.advisory_id)
    fingerprint = reservation.quote_fingerprint
    stem = base_url.rstrip("/") + "/pagar/" + reservation.quote_token
    metadata = {
        "s01_attempt_id": reservation.attempt_id,
        "s01_advisory_id": ref,
        "s01_quote_sha256": fingerprint,
    }
    return {
        "mode": "payment",
        "payment_method_types": ["card"],
        "client_reference_id": ref,
        "customer_email": reservation.customer_email,
        "line_items": [{
            "price_data": {
                "currency": "eur",
                "unit_amount": reservation.total_cents,
                "product_data": {"name": "Asesoramiento fiscal personalizado"},
            },
            "quantity": 1,
        }],
        "metadata": metadata,
        "payment_intent_data": {"metadata": metadata.copy()},
        # No afirmar pago recibido por visitar una página de éxito.
        "success_url": stem + "?stripe_return=1&session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": stem + "?cancelado=1",
        "expires_at": expires,
    }


def verify_test_checkout_paid(*, session: dict, reservation: S01Reservation, expected_session_id: str) -> str:
    """Comprueba un Checkout ya autentificado por firma y previamente conciliado.

    Solo devuelve PaymentIntent ID; NO modifica expedientes ni confirma
    contablemente el cobro. El caller futuro debe validar la firma, estado del
    intento bajo bloqueo transaccional y deduplicación del evento ANTES.
    """
    _valid_reservation(reservation)
    if not isinstance(session, dict) or not isinstance(expected_session_id, str) or not expected_session_id.startswith("cs_test_"):
        raise S01CheckoutBlocked("Sesión de prueba no reconocida")
    if session.get("id") != expected_session_id or session.get("livemode") is not False:
        raise S01CheckoutBlocked("Sesión distinta o no pertenece a TEST")
    if session.get("mode") != "payment" or session.get("status") != "complete" or session.get("payment_status") != "paid":
        raise S01CheckoutBlocked("Checkout aún no pagado")
    amount = session.get("amount_total")
    if isinstance(amount, bool) or type(amount) is not int or amount != reservation.total_cents or session.get("currency") != "eur":
        raise S01CheckoutBlocked("Importe o divisa no coinciden")
    if session.get("client_reference_id") != str(reservation.advisory_id):
        raise S01CheckoutBlocked("Expediente distinto")
    m = session.get("metadata")
    if not isinstance(m, dict) or m.get("s01_attempt_id") != reservation.attempt_id or m.get("s01_advisory_id") != str(reservation.advisory_id) or m.get("s01_quote_sha256") != reservation.quote_fingerprint:
        raise S01CheckoutBlocked("Presupuesto o intento distinto")
    pi = session.get("payment_intent")
    if not isinstance(pi, str) or not pi.startswith("pi_"):
        raise S01CheckoutBlocked("PaymentIntent no identificable")
    return pi
