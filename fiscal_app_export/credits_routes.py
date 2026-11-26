"""Authenticated, disabled-by-default HTTP boundary for FIFO credit pilot."""
import os
import re
import secrets
import tempfile
from datetime import datetime
from uuid import UUID
from sqlalchemy import text

from flask import Blueprint, current_app, jsonify, request, session, g
from flask_login import current_user, login_required
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from credit_file_quote import inspect_credit_uploads
from credit_ledger import (
    CreditError, balance, create_purchase, reserve_analysis, attach_checkout_session,
    begin_analysis, release_analysis, release_processing_analysis,
    settle_analysis, recover_analysis, quarantine_unknown_analysis,
)
from credit_execution import try_acquire_analysis_lock
from credit_pricing import PACKAGES, quote_analysis
from credits_stripe import checkout_session_params, process_signed_test_event
from credit_artifacts import load_artifact, store_artifact, _key as _artifact_key
from models import db, CreditPurchase, CreditAnalysis
from models import CreditReportArtifact

credits_bp = Blueprint("credits", __name__)
_CSRF_SESSION_KEY = "credits_csrf_v1"
CREDITS_EXECUTION_HEAD = "b4c5d6e7f8a9"


def _pilot_ready() -> bool:
    secret = (current_app.config.get("STRIPE_CREDITS_TEST_SECRET") or "").strip()
    try:
        _artifact_key(current_app.config.get("FIFO_CREDITS_REPORT_KEY"))
        key_ok = True
    except ValueError:
        key_ok = False
    configured = bool(current_app.config.get("CREDITS_ENABLED")
                       and current_app.config.get("CREDITS_TEST_MODE")
                       and secret.startswith("sk_test_") and key_ok
                       and (current_app.config.get("STRIPE_CREDITS_TEST_WEBHOOK_SECRET") or "").strip().startswith("whsec_"))
    if not configured:
        return False
    # The recovery migration is required before any credit endpoint can be
    # enabled. Test-only SQLite fixtures model the latest ORM schema directly.
    if current_app.testing and db.engine.dialect.name == "sqlite":
        return True
    try:
        revisions = db.session.execute(
            text("SELECT version_num FROM public.alembic_version")
        ).scalars().all()
        return revisions == [CREDITS_EXECUTION_HEAD]
    except Exception:
        db.session.rollback()
        return False


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
        # Prefer the header so a client disconnect or malformed multipart body
        # cannot force Flask to parse the upload before the reservation lock is
        # acquired. Form-only legacy clients remain supported as a fallback.
        analysis_id = request.headers.get("X-Credit-Analysis-ID", "") or request.form.get("credit_analysis_id", "")
        if not analysis_id:
            return jsonify({"ok": False, "result_type": "processing_error",
                            "error": "Autoriza primero el análisis y confirma el saldo disponible."}), 402
        try:
            execution_lock = try_acquire_analysis_lock(
                user_id=current_user.id, analysis_id=analysis_id,
            )
        except (ValueError, TypeError):
            return jsonify({"ok": False, "result_type": "processing_error",
                            "error": "La referencia de autorización no es válida."}), 400
        except Exception:
            db.session.rollback()
            return jsonify({"ok": False, "result_type": "processing_error",
                            "credit_state": "unknown",
                            "error": "No se puede confirmar el estado de la ejecución. No repitas el análisis; inténtalo de nuevo más tarde."}), 503
        if execution_lock is None:
            return jsonify({"ok": False, "result_type": "processing_error",
                            "credit_state": "processing",
                            "error": "Este análisis ya está en curso. Espera a que termine antes de reintentarlo."}), 409
        g.credit_execution_lock = execution_lock
        analysis = CreditAnalysis.query.filter_by(
            id=analysis_id, user_id=current_user.id
        ).first()
        if analysis is None:
            return jsonify({"ok": False, "result_type": "processing_error",
                            "error": "La autorización no existe para esta cuenta."}), 404
        if analysis.status == "consumed":
            return _reused_result_response(analysis)
        if analysis.status == "processing":
            try:
                recovered = recover_analysis(
                    analysis_id=analysis.id, user_id=current_user.id,
                    execution_lock=execution_lock,
                )
                return jsonify({"ok": False, "result_type": "credit_state_unknown",
                                "credit_state": recovered.status,
                                "error": "La ejecución anterior se interrumpió y su resultado es incierto. El saldo queda bloqueado hasta revisarlo con soporte."}), 409
            except Exception:
                db.session.rollback()
                return jsonify({"ok": False, "result_type": "credit_state_unknown",
                                "credit_state": "unknown",
                                "error": "No se pudo conciliar la ejecución anterior. No repitas el análisis; contacta con soporte."}), 503
        if analysis.status != "reserved":
            message = ("El saldo está bloqueado para revisión. Contacta con soporte antes de continuar."
                       if analysis.status in {"execution_unknown", "settlement_unknown"}
                       else "Esta autorización ya se cerró. Vuelve a cotizar los archivos.")
            return jsonify({"ok": False, "result_type": "processing_error",
                            "credit_state": analysis.status, "error": message}), 409
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
        try:
            analysis = begin_analysis(
                analysis_id=analysis.id, user_id=current_user.id,
                execution_lock=execution_lock,
            )
        except Exception:
            db.session.rollback()
            return jsonify({"ok": False, "result_type": "processing_error",
                            "credit_state": "reserved",
                            "error": "No se pudo iniciar el análisis. La reserva sigue pendiente; consulta su estado antes de reintentar."}), 503
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
                                execution_lock=g.credit_execution_lock,
                                result_type=result_type)
                data.update({"credit_analysis_id": analysis.id,
                             "credits_charged": analysis.charged_credits,
                             "credit_correction_used": bool(analysis.correction_of_id),
                             "balance": balance(current_user.id),
                             "download_url": f"/api/credits/analyses/{analysis.id}/download"})
            else:
                release_processing_analysis(
                    analysis_id=analysis.id, user_id=current_user.id,
                    execution_lock=g.credit_execution_lock,
                )
                data = data if isinstance(data, dict) else {"error": "No se ha completado el análisis."}
                data.update({"credit_message": "No se han consumido créditos. Tu saldo permanece intacto",
                             "balance": balance(current_user.id)})
            response.set_data(current_app.json.dumps(data))
            response.headers["Content-Type"] = "application/json"
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error("[CREDITS_SETTLEMENT] state unresolved type=%s", type(exc).__name__)
            known_analysis = None
            try:
                known_analysis = CreditAnalysis.query.filter_by(
                    id=analysis.id, user_id=current_user.id
                ).first()
            except Exception:
                db.session.rollback()
            if known_analysis and known_analysis.status == "consumed":
                data = {"ok": False, "result_type": "processing_error",
                        "error": "El análisis terminó, pero la respuesta no se pudo completar. Puedes recuperar el documento adquirido.",
                        "credit_message": f"Se han consumido {known_analysis.charged_credits} créditos; el estado está confirmado.",
                        "credits_charged": known_analysis.charged_credits,
                        "credit_analysis_id": analysis.id,
                        "download_url": f"/api/credits/analyses/{analysis.id}/download",
                        "balance": balance(current_user.id)}
                response.status_code = 500
            else:
                released = False
                try:
                    release_processing_analysis(
                        analysis_id=analysis.id, user_id=current_user.id,
                        execution_lock=g.credit_execution_lock,
                    )
                    released = True
                except Exception:
                    db.session.rollback()
                if released:
                    data = {"ok": False, "result_type": "processing_error",
                            "error": "No se pudo guardar el resultado adquirido. Reintenta el análisis.",
                            "credit_message": "No se han consumido créditos. Tu saldo permanece intacto",
                            "balance": balance(current_user.id)}
                else:
                    try:
                        quarantine_unknown_analysis(
                            analysis_id=analysis.id, user_id=current_user.id
                        )
                    except Exception:
                        db.session.rollback()
                    data = {"ok": False, "result_type": "credit_state_unknown",
                            "credit_message": "No se ha podido confirmar el estado de los créditos. No repitas el análisis y contacta con soporte."}
                    response.status_code = 503
            response.set_data(current_app.json.dumps(data))
            response.headers["Content-Type"] = "application/json"
        response.headers["Cache-Control"] = "no-store, private"
        return response

    @app.teardown_request
    def _release_credit_execution_lock(_error=None):
        lock = getattr(g, "credit_execution_lock", None)
        if lock is not None:
            try:
                lock.release()
            except Exception as exc:
                current_app.logger.warning(
                    "[CREDITS_EXECUTION_LOCK] release failed type=%s", type(exc).__name__
                )


@credits_bp.get("/api/credits/status")
@login_required
def status():
    return jsonify({"enabled": _pilot_ready(), "balance": balance(current_user.id) if _pilot_ready() else None})


@credits_bp.get("/api/credits/csrf")
@login_required
def csrf_token():
    session[_CSRF_SESSION_KEY] = secrets.token_urlsafe(32)
    return jsonify({"csrf_token": session[_CSRF_SESSION_KEY]})


@credits_bp.get("/api/credits/analyses/pending")
@login_required
def pending_analyses():
    if not _pilot_ready():
        return jsonify({"enabled": False, "operations": []})
    rows = (CreditAnalysis.query.filter(
        CreditAnalysis.user_id == current_user.id,
        CreditAnalysis.status.in_(
            ("reserved", "processing", "execution_unknown", "settlement_unknown")
        ),
    ).order_by(CreditAnalysis.created_at.desc()).limit(10).all())
    return jsonify({"enabled": True, "operations": [
        {"id": row.id, "status": row.status, "exchange": row.exchange,
         "fiscal_years": row.fiscal_years,
         "reserved_credits": row.reserved_credits,
         "created_at": row.created_at.isoformat() if row.created_at else None}
        for row in rows
    ]})


@credits_bp.post("/api/credits/analyses/<analysis_id>/recover")
@login_required
def recover_credit_analysis(analysis_id):
    if not _pilot_ready():
        return jsonify({"error": "La recuperación de créditos está desactivada."}), 404
    if not _csrf_ok():
        return jsonify({"error": "Autorización de sesión caducada. Recarga la página."}), 403
    try:
        UUID(analysis_id)
        execution_lock = try_acquire_analysis_lock(
            user_id=current_user.id, analysis_id=analysis_id,
        )
    except (ValueError, TypeError):
        return jsonify({"error": "Referencia de análisis no válida."}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"status": "unknown",
                        "message": "No se pudo consultar la operación. No repitas el análisis."}), 503
    if execution_lock is None:
        return jsonify({"status": "processing",
                        "message": "El análisis sigue en curso. Espera antes de volver a comprobarlo."}), 409
    try:
        analysis = recover_analysis(
            analysis_id=analysis_id, user_id=current_user.id,
            execution_lock=execution_lock,
        )
    except CreditError:
        db.session.rollback()
        return jsonify({"error": "No se ha podido recuperar esta operación."}), 404
    except Exception:
        db.session.rollback()
        return jsonify({"status": "unknown",
                        "message": "No se pudo conciliar la operación. Contacta con soporte."}), 503
    finally:
        try:
            execution_lock.release()
        except Exception as exc:
            current_app.logger.warning(
                "[CREDITS_EXECUTION_LOCK] recovery release failed type=%s",
                type(exc).__name__,
            )
    if analysis.status == "released":
        return jsonify({"status": "released",
                        "message": "Se liberó la reserva que no había iniciado. Tu saldo está disponible de nuevo.",
                        "balance": balance(current_user.id)})
    if analysis.status == "consumed":
        return jsonify({"status": "consumed",
                        "message": "El análisis ya se completó. Puedes recuperar el documento sin coste adicional.",
                        "download_url": f"/api/credits/analyses/{analysis.id}/download"})
    if analysis.status in {"execution_unknown", "settlement_unknown"}:
        return jsonify({"status": analysis.status,
                        "message": "No se puede confirmar el resultado de la ejecución. El saldo está bloqueado para revisión; contacta con soporte antes de repetir."}), 409
    return jsonify({"status": analysis.status,
                    "message": "La operación no requiere recuperación."})


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
