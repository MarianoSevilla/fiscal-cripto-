"""Small authenticated U04 panel/actions; no unsigned evidence or force-paid."""
import secrets
from urllib.parse import urlsplit
from flask import Blueprint, request, jsonify, session, current_app
from flask_login import current_user
from auth import require_fiscal_advisor, require_roles
from models import db, FiscalAdvisoryRequest as Advisory
from paypal_models import PayPalPaymentAttempt as Attempt, PayPalPaymentEvent as Event
from paypal_payments import PaymentConflict

def register(app, factory, sender):
    bp = Blueprint("paypal_u04", __name__)
    @bp.route("/api/admin/paypal/cuarentena")
    @require_fiscal_advisor
    def quarantine():
        events = Event.query.filter_by(kind="quarantine", attempt_id=None).order_by(Event.created_at.desc()).limit(100).all()
        links = {e.correlation_event_id for e in Event.query.filter(Event.correlation_event_id.in_([e.id for e in events])).all()} if events else set()
        return jsonify([{"id": e.id, "provider_event_id": e.provider_event_id,
                         "paypal_order_id": e.paypal_order_id, "paypal_capture_id": e.paypal_capture_id,
                         "created_at": e.created_at, "correlated": e.id in links} for e in events])
    @bp.route("/api/admin/asesoramiento/solicitudes/<int:ident>/paypal")
    @require_fiscal_advisor
    def detail(ident):
        parent = db.session.get(Advisory, ident)
        if not parent:
            return jsonify({"error": "Expediente no encontrado."}), 404
        session.setdefault("u04_csrf", secrets.token_urlsafe(32))
        items = []
        for a in Attempt.query.filter_by(advisory_id=ident).order_by(Attempt.created_at).all():
            d = a.snapshot()
            d.update(customer_notification_state=a.customer_notification_state,
                     owner_notification_state=a.owner_notification_state,
                     created_at=a.created_at, uncertain_at=a.uncertain_at,
                     last_observed_at=a.last_observed_at, resolved_at=a.resolved_at,
                     resolution_reason=a.resolution_reason)
            d["events"] = [{"id": e.id, "kind": e.kind, "source": e.source,
                            "authenticated": e.authenticated, "contract_valid": e.contract_valid,
                            "created_at": e.created_at, "correlation_event_id": e.correlation_event_id}
                           for e in Event.query.filter_by(attempt_id=a.id).order_by(Event.created_at).all()]
            items.append(d)
        return jsonify({"hold": parent.paypal_review_hold, "generation": parent.paypal_quote_generation,
                        "attempts": items, "csrf_token": session["u04_csrf"],
                        "legacy_current_order": parent.paypal_order_id if not parent.paypal_quote_generation and not parent.paid_at else None,
                        "writes_enabled": app.config["PAYPAL_FINANCIAL_WRITES_ENABLED"]})
    def csrf():
        expected = session.get("u04_csrf", "")
        received = request.headers.get("X-U04-CSRF", "")
        origin = request.headers.get("Origin")
        if not expected or not secrets.compare_digest(expected, received) or origin and urlsplit(origin).netloc != request.host:
            raise PaymentConflict("csrf")
    @bp.route("/api/admin/paypal/attempts/<uuid:ident>/consultar", methods=["POST"])
    @require_fiscal_advisor
    def consult(ident):
        try:
            csrf()
            service = factory()
            state = service.recover(str(ident), actor=current_user.id)
            if state == "RECONCILED":
                service.notify(str(ident), sender)
            return jsonify({"state": state})
        except PaymentConflict:
            db.session.rollback()
            return jsonify({"error": "Operación bloqueada; comprueba la evidencia y la sesión."}), 409
        except Exception:
            db.session.rollback()
            current_app.logger.error("paypal_admin_get_failed error_category=recovery_pending")
            return jsonify({"error": "No se pudo completar la consulta. Se conserva el bloqueo."}), 502
    @bp.route("/api/admin/paypal/attempts/<uuid:ident>/cerrar-sin-captura", methods=["POST"])
    @require_roles("admin")
    def close(ident):
        try:
            csrf()
            factory().close_uncaptured(str(ident), actor=current_user.id)
            return jsonify({"state": "CLOSED_NO_CHARGE"})
        except PaymentConflict:
            db.session.rollback()
            return jsonify({"error": "No hay evidencia suficiente para cerrar sin cobro."}), 409
        except Exception:
            db.session.rollback()
            current_app.logger.error("paypal_admin_close_failed error_category=resolution_pending")
            return jsonify({"error": "No se ha liberado la operación."}), 502
    @bp.route("/api/admin/paypal/attempts/<uuid:ident>/resolver-completada", methods=["POST"])
    @require_roles("admin")
    def complete_reviewed(ident):
        try:
            csrf()
            if (request.get_json(silent=True) or {}).get("quote_generation_verified") is not True:
                raise PaymentConflict("quote_review_required")
            service=factory()
            state=service.recover(str(ident), actor=current_user.id, manual_completion=True)
            if state != "RECONCILED":
                raise PaymentConflict("completed_evidence_required")
            service.notify(str(ident),sender)
            return jsonify({"state":state})
        except (PaymentConflict, ValueError):
            db.session.rollback()
            return jsonify({"error":"No hay evidencia completa de captura y presupuesto. Se conserva el bloqueo."}),409
        except Exception:
            db.session.rollback()
            current_app.logger.error("paypal_review_completion_failed error_category=resolution_pending")
            return jsonify({"error":"No se pudo acreditar el cobro. Se conserva el bloqueo."}),502
    @bp.route("/api/admin/asesoramiento/solicitudes/<int:ident>/paypal/adoptar-completada", methods=["POST"])
    @require_roles("admin")
    def adopt(ident):
        try:
            csrf()
            data = request.get_json(silent=True) or {}
            if data.get("quote_evidence_verified") is not True:
                raise PaymentConflict("quote_evidence_required")
            service = factory()
            attempt = service.adopt_current_completed(ident, data.get("quote_reference"), actor=current_user.id)
            service.notify(attempt, sender)
            return jsonify({"state": "RECONCILED"})
        except (PaymentConflict, ValueError):
            db.session.rollback()
            return jsonify({"error": "Presupuesto u operación sin evidencia suficiente. Se conserva la retención."}), 409
        except Exception:
            db.session.rollback()
            current_app.logger.error("paypal_legacy_adoption_failed error_category=resolution_pending")
            return jsonify({"error": "No se pudo completar la comprobación. Se conserva la retención."}), 502
    @bp.route("/api/admin/paypal/attempts/<uuid:ident>/cerrar-terminal-verificada", methods=["POST"])
    @require_roles("admin")
    def terminal_close(ident):
        try:
            csrf()
            data = request.get_json(silent=True) or {}
            if data.get("provider_no_charge_and_no_inflight_verified") is not True:
                raise PaymentConflict("provider_evidence_required")
            factory().close_terminal_verified(str(ident), data.get("provider_reference"), actor=current_user.id)
            return jsonify({"state": "CLOSED_NO_CHARGE"})
        except (PaymentConflict, ValueError):
            db.session.rollback()
            return jsonify({"error": "La consulta y la evidencia del proveedor no permiten liberar esta orden."}), 409
        except Exception:
            db.session.rollback()
            current_app.logger.error("paypal_terminal_close_failed error_category=resolution_pending")
            return jsonify({"error": "No se pudo verificar el cierre. Se conserva el bloqueo."}), 502
    @bp.route("/api/admin/asesoramiento/solicitudes/<int:ident>/paypal/cerrar-historica-verificada", methods=["POST"])
    @require_roles("admin")
    def legacy_close(ident):
        try:
            csrf()
            data = request.get_json(silent=True) or {}
            if data.get("quote_evidence_verified") is not True or data.get("complete_legacy_scope_no_charge_verified") is not True:
                raise PaymentConflict("legacy_scope_evidence_required")
            factory().adopt_current_closed(ident, data.get("quote_reference"), data.get("provider_reference"), actor=current_user.id)
            return jsonify({"state": "CLOSED_NO_CHARGE"})
        except (PaymentConflict, ValueError):
            db.session.rollback()
            return jsonify({"error": "No se ha acreditado el cierre completo del histórico. Se conserva la retención."}), 409
        except Exception:
            db.session.rollback()
            current_app.logger.error("paypal_legacy_close_failed error_category=resolution_pending")
            return jsonify({"error": "No se pudo verificar el cierre histórico. Se conserva la retención."}), 502
    app.register_blueprint(bp)
