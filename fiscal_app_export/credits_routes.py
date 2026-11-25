"""Authenticated, disabled-by-default HTTP boundary for FIFO credit pilot."""
import os
import re
import secrets
import tempfile
from datetime import datetime
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request, session, g
from flask_login import current_user, login_required
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from credit_file_quote import inspect_credit_uploads
from credit_ledger import (
    CreditError, balance, create_purchase, reserve_analysis, attach_checkout_session,
    release_analysis, settle_analysis, quarantine_unknown_analysis,
)
from credit_pricing import PACKAGES, quote_analysis
from credits_stripe import checkout_session_params, process_signed_test_event
from credit_artifacts import load_artifact, store_artifact, _key as _artifact_key
from models import db, CreditPurchase, CreditAnalysis
from models import CreditReportArtifact

credits_bp = Blueprint("credits", __name__)
_CSRF_SESSION_KEY = "credits_csrf_v1"


def _pilot_ready() -> bool:
    secret = (current_app.config.get("STRIPE_CREDITS_TEST_SECRET") or "").strip()
    try:
        _artifact_key(current_app.config.get("FIFO_CREDITS_REPORT_KEY"))
        key_ok = True
    except ValueError:
        key_ok = False
    return bool(current_app.config.get("CREDITS_ENABLED")
                and current_app.config.get("CREDITS_TEST_MODE")
                and secret.startswith("sk_test_") and key_ok
                and (current_app.config.get("STRIPE_CREDITS_TEST_WEBHOOK_SECRET") or "").strip().startswith("whsec_"))


@credits_bp.app_context_processor
def _credits_template_context():
    """Render the same server-side readiness gate used by the API boundary."""
    return {"credits_pilot_enabled": _pilot_ready()}


def _csrf_ok() -> bool:
    token = request.headers.get("X-Credits-CSRF", "")
    expected = session.get(_CSRF_SESSION_KEY, "")
    return bool(expected and secrets.compare_digest(token, expected))


def _serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt="fifo-credit-quote-v1")


def _previously_acquired(user_id: int, exchange: str, years: str, fingerprint: str):
    return (CreditAnalysis.query.join(CreditReportArtifact,
                                      CreditReportArtifact.analysis_id == CreditAnalysis.id)
            .filter(CreditAnalysis.user_id == user_id,
                    CreditAnalysis.status == "consumed",
                    CreditAnalysis.exchange == exchange,
                    CreditAnalysis.fiscal_years == years,
                    CreditAnalysis.file_fingerprint == fingerprint,
                    CreditReportArtifact.expires_at > datetime.utcnow())
            .order_by(CreditAnalysis.created_at.desc()).first())


def _reused_result_response(analysis):
    return jsonify({
        "already_acquired": True,
        "result_type": analysis.result_type,
        "download_url": f"/api/credits/analyses/{analysis.id}/download",
        "message": "Este mismo análisis ya fue adquirido. Puedes volver a descargar el documento sin coste adicional.",
    })


def register_analysis_hooks(app):
    """Gate the existing FIFO HTTP analyses only when the pilot is enabled."""
    analysis_endpoints = {
        "analizar", "analizar_binance_multi", "analizar_kucoin", "analizar_bitget",
    }

    @app.before_request
    def _require_authorized_credit_run():
        if not _pilot_ready() or request.endpoint not in analysis_endpoints:
            return None
        if not current_user.is_authenticated:
            return None  # let the existing @login_required contract respond
        analysis_id = request.form.get("credit_analysis_id") or request.headers.get("X-Credit-Analysis-ID", "")
        analysis = CreditAnalysis.query.filter_by(
            id=analysis_id, user_id=current_user.id, status="reserved"
        ).first() if current_user.is_authenticated and analysis_id else None
        if analysis is None:
            return jsonify({"ok": False, "result_type": "processing_error",
                            "error": "Autoriza primero el análisis y confirma el saldo disponible."}), 402
        try:
            evidence = inspect_credit_uploads(request.files.getlist("csv") or request.files.getlist("files"))
            exchange = {"analizar_binance_multi": "binance",
                        "analizar_kucoin": "kucoin",
                        "analizar_bitget": "bitget"}.get(
                            request.endpoint, (request.form.get("exchange") or "").strip().lower())
            years = (request.form.get("ejercicio") or "all").strip() or "all"
            # Quoting requires the client to send the exact fiscal-year token.
            if (evidence["fingerprint"] != analysis.file_fingerprint
                    or evidence["rows"] != analysis.csv_rows
                    or evidence["files"] != analysis.file_count
                    or exchange != analysis.exchange
                    or years != analysis.fiscal_years):
                release_analysis(analysis_id=analysis.id, user_id=current_user.id)
                return jsonify({"ok": False, "result_type": "processing_error",
                                "error": "Los archivos o el ejercicio cambiaron desde la autorización. Vuelve a validarlos.",
                                "credit_message": "No se han consumido créditos. Tu saldo permanece intacto",
                                "balance": balance(current_user.id)}), 409
        except (ValueError, CreditError):
            try:
                release_analysis(analysis_id=analysis.id, user_id=current_user.id)
                return jsonify({"ok": False, "result_type": "processing_error",
                                "error": "No se ha podido verificar el archivo autorizado. Vuelve a validarlo.",
                                "credit_message": "No se han consumido créditos. Tu saldo permanece intacto",
                                "balance": balance(current_user.id)}), 400
            except Exception:
                db.session.rollback()
                return jsonify({"ok": False, "result_type": "credit_state_unknown",
                                "error": "No se ha podido confirmar el estado de la reserva. No repitas el análisis; contacta con soporte."}), 503
        g.credit_analysis = analysis
        return None

    @app.after_request
    def _settle_authorized_credit_run(response):
        analysis = getattr(g, "credit_analysis", None)
        if analysis is None:
            return response
        data = response.get_json(silent=True)
        result_type = data.get("result_type") if isinstance(data, dict) else None
        try:
            if result_type in {"definitive", "provisional"}:
                if result_type == "definitive":
                    token = data.get("token") if isinstance(data, dict) else None
                    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]+\.pdf", token):
                        raise CreditError("No se encuentra el PDF definitivo generado.")
                    path = os.path.join(tempfile.gettempdir(), token)
                    if os.path.commonpath((os.path.realpath(path), os.path.realpath(os.path.dirname(path)))) != os.path.realpath(os.path.dirname(path)):
                        raise CreditError("Ruta de PDF no válida.")
                    with open(path, "rb") as stream:
                        pdf_bytes = stream.read()
                else:
                    draft = data.get("borrador_fifo") or data.get("borrador_binance")
                    if not isinstance(draft, dict):
                        raise CreditError("No se encuentra el diagnóstico provisional.")
                    from binance_diagnostico_pdf import generar_pdf_diagnostico_binance
                    pdf_bytes = generar_pdf_diagnostico_binance(draft)
                store_artifact(
                    analysis_id=analysis.id, user_id=current_user.id,
                    pdf_bytes=pdf_bytes,
                    encoded_key=current_app.config["FIFO_CREDITS_REPORT_KEY"],
                )
                settle_analysis(analysis_id=analysis.id, user_id=current_user.id,
                                result_type=result_type)
                data.update({"credit_analysis_id": analysis.id,
                             "credits_charged": analysis.charged_credits,
                             "credit_correction_used": bool(analysis.correction_of_id),
                             "balance": balance(current_user.id),
                             "download_url": f"/api/credits/analyses/{analysis.id}/download"})
            else:
                release_analysis(analysis_id=analysis.id, user_id=current_user.id)
                data = data if isinstance(data, dict) else {"error": "No se ha completado el análisis."}
                data.update({"credit_message": "No se han consumido créditos. Tu saldo permanece intacto",
                             "balance": balance(current_user.id)})
            response.set_data(current_app.json.dumps(data))
            response.headers["Content-Type"] = "application/json"
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error("[CREDITS_SETTLEMENT] state unresolved type=%s", type(exc).__name__)
            try:
                release_analysis(analysis_id=analysis.id, user_id=current_user.id)
                release_confirmed = True
            except Exception:
                db.session.rollback()
                release_confirmed = False
            known_analysis = None
            known_balance = None
            if not release_confirmed:
                try:
                    known_analysis = CreditAnalysis.query.filter_by(
                        id=analysis.id, user_id=current_user.id
                    ).first()
                    if known_analysis and known_analysis.status in {"consumed", "released"}:
                        known_balance = balance(current_user.id)
                        release_confirmed = True  # terminal transaction state is known
                    elif known_analysis and known_analysis.status == "reserved":
                        quarantine_unknown_analysis(
                            analysis_id=analysis.id, user_id=current_user.id
                        )
                except Exception:
                    db.session.rollback()
            data = data if isinstance(data, dict) else {}
            if release_confirmed and known_analysis and known_analysis.status == "consumed":
                data["credit_message"] = f"Se han consumido {known_analysis.charged_credits} créditos; el estado del saldo está confirmado."
                data["credits_charged"] = known_analysis.charged_credits
                data["credit_analysis_id"] = analysis.id
                data["download_url"] = f"/api/credits/analyses/{analysis.id}/download"
                data["balance"] = known_balance
            elif release_confirmed:
                data["credit_message"] = "No se han consumido créditos. Tu saldo permanece intacto"
                data["balance"] = balance(current_user.id)
            else:
                data["credit_message"] = "No se ha podido confirmar el estado de los créditos. No repitas el análisis y contacta con soporte."
            response.set_data(current_app.json.dumps(data))
            response.headers["Content-Type"] = "application/json"
            response.status_code = 503 if not release_confirmed else 500
        response.headers["Cache-Control"] = "no-store, private"
        return response


@credits_bp.get("/api/credits/status")
@login_required
def status():
    return jsonify({"enabled": _pilot_ready(), "balance": balance(current_user.id) if _pilot_ready() else None})


@credits_bp.get("/api/credits/csrf")
@login_required
def csrf_token():
    session[_CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
    return jsonify({"csrf_token": session[_CSRF_SESSION_KEY]})


@credits_bp.post("/api/credits/quote")
@login_required
def quote():
    if not _pilot_ready():
        return jsonify({"error": "El piloto de créditos está desactivado."}), 404
    try:
        evidence = inspect_credit_uploads(request.files.getlist("csv") or request.files.getlist("files"))
        quote_data = quote_analysis(rows=evidence["rows"], files=evidence["files"])
    except ValueError as exc:
        return jsonify({"error": str(exc), "credits_consumed": 0}), 400
    exchange = (request.form.get("exchange") or "").strip().lower()
    years = (request.form.get("fiscal_years") or "").strip()
    if not re.fullmatch(r"[a-z0-9_-]{2,20}", exchange) or not re.fullmatch(r"(?:all|20[0-9]{2}(?:,20[0-9]{2})*)", years):
        return jsonify({"error": "Selecciona un exchange y ejercicios válidos."}), 400
    # Do not charge twice for an identical, already acquired result while its
    # encrypted artifact is still available. A different file set, exchange,
    # or exercise remains a separately quoted analysis.
    prior = _previously_acquired(current_user.id, exchange, years, evidence["fingerprint"])
    if prior:
        return _reused_result_response(prior)
    correction_of_id = (request.form.get("correction_of_id") or "").strip() or None
    correction_free = False
    if correction_of_id:
        parent = CreditAnalysis.query.filter_by(
            id=correction_of_id, user_id=current_user.id, status="consumed"
        ).first()
        if (not parent or parent.correction_of_id is not None
                or parent.correction_expires_at < datetime.utcnow()):
            return jsonify({"error": "La ventana de corrección gratuita ha caducado."}), 409
        prior_correction = CreditAnalysis.query.filter_by(correction_of_id=parent.id).first()
        if not prior_correction:
            correction_free = True
        else:
            # The free allowance is per acquired result. This is a new charged
            # analysis; the client receives that fact in its quote.
            correction_of_id = None
    maximum = 0 if correction_free else quote_data.max_credits
    token = _serializer().dumps({
        "uid": current_user.id, "exchange": exchange, "years": years,
        "rows": evidence["rows"], "files": evidence["files"],
        "fingerprint": evidence["fingerprint"],
        "row_credits": quote_data.row_credits,
        "complexity_credits": quote_data.complexity_credits,
        "max_credits": maximum, "correction_of_id": correction_of_id,
        "correction_free": correction_free,
    })
    return jsonify({
        "quote_token": token, "rows": evidence["rows"], "files": evidence["files"],
        "row_credits": quote_data.row_credits,
        "complexity_credits": quote_data.complexity_credits,
        "max_credits": maximum, "correction_free": correction_free,
        "balance": balance(current_user.id),
        "packages": PACKAGES,
        "expires_in_seconds": 900,
    })


@credits_bp.post("/api/credits/authorize")
@login_required
def authorize_analysis():
    if not _pilot_ready():
        return jsonify({"error": "El piloto de créditos está desactivado."}), 404
    if not _csrf_ok():
        return jsonify({"error": "Autorización de sesión caducada. Recarga la página."}), 403
    body = request.get_json(silent=True) or {}
    token = body.get("quote_token")
    idem = request.headers.get("Idempotency-Key", "")
    if not isinstance(token, str) or not 1 <= len(token) <= 5000:
        return jsonify({"error": "La cotización ha caducado. Vuelve a validar los archivos."}), 400
    try:
        UUID(idem)
        data = _serializer().loads(token, max_age=900)
    except (ValueError, BadSignature, SignatureExpired):
        return jsonify({"error": "La cotización ha caducado. Vuelve a validar los archivos."}), 400
    if data.get("uid") != current_user.id:
        return jsonify({"error": "La cotización no pertenece a esta cuenta."}), 403
    try:
        analysis = reserve_analysis(
            user_id=current_user.id, idempotency_key=idem,
            exchange=data["exchange"], fiscal_years=data["years"],
            csv_rows=data["rows"], file_count=data["files"],
            file_fingerprint=data["fingerprint"], max_credits=data["max_credits"],
            correction_of_id=data.get("correction_of_id"),
        )
    except CreditError as exc:
        db.session.rollback()
        prior = _previously_acquired(current_user.id, data["exchange"], data["years"], data["fingerprint"])
        if prior:
            return _reused_result_response(prior)
        return jsonify({"error": str(exc), "balance": balance(current_user.id)}), 409
    return jsonify({"analysis_id": analysis.id, "reserved_credits": analysis.reserved_credits,
                    "balance": balance(current_user.id)}), 201


@credits_bp.get("/api/credits/packages")
@login_required
def packages():
    return jsonify({"enabled": _pilot_ready(), "packages": PACKAGES if _pilot_ready() else []})


@credits_bp.get("/api/credits/analyses/<analysis_id>/download")
@login_required
def download_acquired_report(analysis_id):
    if not _pilot_ready():
        return jsonify({"error": "La descarga de informes de créditos está desactivada."}), 404
    try:
        pdf_bytes = load_artifact(
            analysis_id=analysis_id, user_id=current_user.id,
            encoded_key=current_app.config["FIFO_CREDITS_REPORT_KEY"],
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("[CREDITS_DOWNLOAD] report decrypt failed type=%s", type(exc).__name__)
        return jsonify({"error": "No se ha podido verificar el documento. Contacta con soporte."}), 503
    if pdf_bytes is None:
        return jsonify({"error": "Documento no disponible, caducado o sin autorización."}), 404
    response = current_app.response_class(
        pdf_bytes, mimetype="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resultado_fifo_{analysis_id[:8]}.pdf"'},
    )
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@credits_bp.post("/api/credits/purchases/<package_key>")
@login_required
def purchase(package_key):
    if not _pilot_ready():
        return jsonify({"error": "Las compras de créditos están desactivadas."}), 404
    if not _csrf_ok():
        return jsonify({"error": "Autorización de sesión caducada. Recarga la página."}), 403
    idem = request.headers.get("Idempotency-Key", "")
    try:
        UUID(idem)
    except (ValueError, TypeError):
        return jsonify({"error": "Clave de compra no válida."}), 400
    try:
        purchase_row = create_purchase(user_id=current_user.id, package_key=package_key,
                                       idempotency_key=idem)
        import stripe
        client = stripe.StripeClient(current_app.config["STRIPE_CREDITS_TEST_SECRET"])
        params = checkout_session_params(purchase=purchase_row,
                                         base_url=current_app.config["APP_BASE_URL"])
        checkout = client.v1.checkout.sessions.create(
            params, options={"idempotency_key": "credits-checkout-v1-" + purchase_row.id}
        )
        if not str(checkout.id).startswith("cs_test_") or not str(checkout.url).startswith("https://"):
            raise CreditError("Stripe no devolvió una sesión de pago de prueba válida.")
        attach_checkout_session(purchase_id=purchase_row.id, session_id=checkout.id)
        return jsonify({"checkout_url": checkout.url, "purchase_id": purchase_row.id}), 201
    except CreditError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning("[CREDITS_CHECKOUT] test checkout unavailable type=%s", type(exc).__name__)
        return jsonify({"error": "No se ha podido preparar el pago de prueba. No se han concedido créditos."}), 503


@credits_bp.post("/api/webhooks/stripe-credits-test")
def test_webhook():
    if not _pilot_ready():
        return jsonify({"error": "Webhook de créditos desactivado."}), 404
    secret = (current_app.config.get("STRIPE_CREDITS_TEST_WEBHOOK_SECRET") or "").strip()
    if not secret.startswith("whsec_"):
        return jsonify({"error": "Webhook no configurado."}), 503
    try:
        handled = process_signed_test_event(
            stripe_module=__import__("stripe"), payload=request.get_data(cache=False),
            signature=request.headers.get("Stripe-Signature", ""),
            webhook_secret=secret,
        )
    except CreditError:
        db.session.rollback()
        return jsonify({"error": "Evento de pago no válido."}), 400
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("[CREDITS_WEBHOOK] event processing failed type=%s", type(exc).__name__)
        return jsonify({"error": "No se ha podido confirmar el evento."}), 500
    return jsonify({"received": True, "handled": bool(handled)}), 200
