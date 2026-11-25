"""Test-mode-only Stripe Checkout boundary for the credits pilot.

No price is trusted from the browser. Checkout amounts and credit grants come
from the server-side package table; successful grants are made only after
signature validation of an authenticated Stripe event.
"""
from credit_ledger import confirm_test_payment, flag_refund_for_review, CreditError


def checkout_session_params(*, purchase, base_url: str) -> dict:
    """Build fixed-price, one-time Checkout params; does not call Stripe."""
    from urllib.parse import urlsplit

    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CreditError("Se requiere un origen HTTPS válido.")
    if purchase.status != "pending":
        raise CreditError("Esta compra no está pendiente.")
    return {
        "mode": "payment",
        "payment_method_types": ["card"],
        "line_items": [{
            "price_data": {
                "currency": "eur", "unit_amount": purchase.amount_cents,
                "product_data": {"name": f"Créditos FIFO · {purchase.package_key}"},
            },
            "quantity": 1,
        }],
        "metadata": {"credits_purchase_id": purchase.id},
        "payment_intent_data": {"metadata": {"credits_purchase_id": purchase.id}},
        "success_url": base_url.rstrip("/") + "/account?credits_purchase=pending",
        "cancel_url": base_url.rstrip("/") + "/account?credits_purchase=cancelled",
    }


def process_signed_test_event(*, stripe_module, payload: bytes, signature: str,
                              webhook_secret: str) -> bool:
    """Verify signature and grant credits only from a paid test-mode Session.

    Browser success redirects are intentionally not part of this function.
    The connected Stripe test account must configure these event types only
    after the feature has separately been approved for a pilot.
    """
    if not webhook_secret or not webhook_secret.startswith("whsec_"):
        raise CreditError("Webhook de créditos no configurado.")
    try:
        event = stripe_module.Webhook.construct_event(payload, signature, webhook_secret)
        if hasattr(event, "to_dict"):
            event = event.to_dict()
    except Exception as exc:
        # Normalize parsing, signature, and payload errors without echoing body.
        raise CreditError("Firma del evento de pago no válida.") from exc
    if event.get("livemode") is not False:
        raise CreditError("Los pagos reales están desactivados en el piloto.")
    event_type = event.get("type")
    if event_type == "charge.refunded":
        charge = (event.get("data") or {}).get("object") or {}
        payment_intent = charge.get("payment_intent")
        if isinstance(payment_intent, dict):
            payment_intent = payment_intent.get("id")
        return flag_refund_for_review(
            event_id=event.get("id", ""), payment_intent_id=payment_intent or "",
            event_type=event_type,
        )
    if event_type not in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        return False
    data = event.get("data") or {}
    session = data.get("object") or {}
    metadata = session.get("metadata") or {}
    purchase_id = metadata.get("credits_purchase_id")
    payment_intent = session.get("payment_intent")
    if (not isinstance(purchase_id, str) or session.get("mode") != "payment"
            or session.get("status") != "complete" or session.get("payment_status") != "paid"
            or session.get("livemode") is not False):
        raise CreditError("La sesión de Checkout no confirma un pago de prueba válido.")
    if not isinstance(payment_intent, str):
        payment_intent = (payment_intent or {}).get("id")
    return confirm_test_payment(
        purchase_id=purchase_id,
        event_id=event.get("id", ""),
        session_id=session.get("id", ""),
        payment_intent_id=payment_intent or "",
        amount_cents=session.get("amount_total"),
        currency=session.get("currency", ""),
        livemode=event.get("livemode"),
    )
