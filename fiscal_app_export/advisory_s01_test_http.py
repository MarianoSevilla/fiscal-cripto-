"""Receptor HTTP sintético de S01: factory NO registrada por la aplicación.

Seguridad estructural: app.py NUNCA importa este módulo. El blueprint solo
existe en Flask TESTING aislado, con FLASK_ENV=testing y endpoint sintético.
No expone rutas de producción, no crea pagos, no envía correos ni facturas.
"""
import os

from flask import Blueprint, current_app, jsonify, request

from advisory_s01_stripe_test_events import (
    S01EventRejected,
    S01EventSignatureRejected,
    S01EventStorageError,
    process_signed_s01_test_webhook,
)

MAX_STRIPE_EVENT_BYTES = 65536


def build_s01_synthetic_webhook_blueprint(*, webhook_secret: str) -> Blueprint:
    """Factory únicamente para harness Flask TEST. Nunca llamar desde app.py."""
    if os.environ.get("FLASK_ENV") != "testing":
        raise RuntimeError("S01 synthetic HTTP forbidden outside testing")

    bp = Blueprint("s01_synthetic_payment_webhooks", __name__)

    @bp.post("/__synthetic__/s01/stripe/webhook")
    def receive_synthetic_s01_stripe():
        # Comprobar en CADA petición, no solo al crear el Blueprint.
        if os.environ.get("FLASK_ENV") != "testing" or not current_app.testing:
            return jsonify({"error": "unavailable"}), 503
        if (not isinstance(webhook_secret, str)
                or not webhook_secret.startswith("whsec_")
                or len(webhook_secret) < 12):
            return jsonify({"error": "unavailable"}), 503

        if (request.content_length is not None
                and request.content_length > MAX_STRIPE_EVENT_BYTES):
            return jsonify({"error": "payload_too_large"}), 413
        # Lectura acotada incluso si falta Content-Length. Nunca JSON parse
        # sin autenticar o acceso a request.json.
        raw = request.stream.read(MAX_STRIPE_EVENT_BYTES + 1)
        if len(raw) > MAX_STRIPE_EVENT_BYTES:
            return jsonify({"error": "payload_too_large"}), 413

        sig = request.headers.get("Stripe-Signature", "")
        try:
            result = process_signed_s01_test_webhook(
                payload=raw,
                signature=sig,
                webhook_secret=webhook_secret,
            )
        except S01EventSignatureRejected:
            return jsonify({"error": "invalid_signature"}), 400
        except S01EventRejected:
            # No ACK positivo de pagos cuya evidencia no cuadra;
            # Stripe reintentaría en un receptor real.
            return jsonify({"error": "requires_reconciliation"}), 409
        except S01EventStorageError:
            return jsonify({"error": "retry_later"}), 503
        except Exception:
            # Fallo inesperado: no perder el evento con HTTP 200.
            return jsonify({"error": "retry_later"}), 503

        if result not in ("paid", "duplicate", "already_paid"):
            return jsonify({"error": "retry_later"}), 503
        return jsonify({"result": result}), 200

    return bp
