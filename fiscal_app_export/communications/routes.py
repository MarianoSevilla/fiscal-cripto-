"""
Admin routes for the communications module.
All /admin/* and /api/admin/comunicaciones/* endpoints live here.
Public: /unsubscribe (page) and /api/unsubscribe (action).
"""
from flask import abort, jsonify, request, current_app
from flask_login import login_required, current_user

from models import db, User, CommunicationCampaign, CommunicationDelivery, ProcessingError
from .service import (
    VALID_SEGMENTS,
    count_eligible_recipients,
    count_eligible_recipients_all_segments,
    create_campaign_draft,
    update_campaign_draft,
    delete_campaign,
    send_test_email,
    dispatch_campaign,
)
from . import comms_bp
from auth import _role_is_admin

# Alias local — mantiene intactos todos los if not _is_admin(): abort(404)
# sin cambiar el comportamiento (abort 404 en comunicaciones se preserva intencionadamente).
_is_admin = _role_is_admin


# ── PROCESSING ERROR CONTACT CONTEXT ─────────────────────────────────────────

@comms_bp.route("/api/admin/processing-errors/<int:error_id>/contact-context")
@login_required
def api_processing_error_contact_context(error_id: int):
    """
    Returns contact context for a processing error so the admin can compose
    a targeted follow-up email in /admin/comunicaciones.

    Only accessible by admins. Resolves the real email server-side — never
    exposed in /stats HTML.
    """
    if not _is_admin():
        abort(404)

    err = ProcessingError.query.get_or_404(error_id)

    if not err.email:
        return jsonify({"error": "Este error no tiene email asociado."}), 404

    exchange_display = (err.exchange or "tu exchange").capitalize()
    subject = f"Hemos corregido el problema al procesar tu archivo de {exchange_display}"
    body = (
        f"Hola,\n\n"
        f"Te escribimos porque detectamos que intentaste generar tu informe utilizando "
        f"un archivo de {exchange_display} y la herramienta devolvió un error durante el procesamiento.\n\n"
        f"Hemos revisado el problema y ya está corregido.\n\n"
        f"Puedes volver a subir el mismo archivo y generar el informe de nuevo. "
        f"No necesitas modificar el CSV.\n\n"
        f"Si al volver a intentarlo observas cualquier comportamiento extraño, "
        f"responde a este correo y lo revisaremos.\n\n"
        f"Un saludo,\n\nMariano Sevilla"
    )

    return jsonify({
        "id":             err.id,
        "email":          err.email,
        "email_masked":   _mask_email_local(err.email),
        "exchange":       err.exchange or "",
        "error_type":     err.error_type or "",
        "stage":          err.stage or "",
        "message_short":  err.message_short or "",
        "fingerprint":    (err.fingerprint or "")[:8],
        "email_enviado":  bool(err.auto_email_sent),
        "resuelto":       bool(err.resolved),
        "subject":        subject,
        "body":           body,
    })


def _mask_email_local(email: str) -> str:
    """Returns a masked version of the email (user@domain → u***@domain)."""
    if not email or "@" not in email:
        return email or ""
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


# ── PAGE ROUTES ───────────────────────────────────────────────────────────────

@comms_bp.route("/admin/comunicaciones", strict_slashes=False)
@login_required
def admin_comms_page():
    if not _is_admin():
        abort(404)
    return current_app.send_static_file("admin-comunicaciones.html")


@comms_bp.route("/unsubscribe", strict_slashes=False)
def unsubscribe_page():
    return current_app.send_static_file("unsubscribe.html")


# ── RECIPIENTS ────────────────────────────────────────────────────────────────

@comms_bp.route("/api/admin/comunicaciones/recipients/count")
@login_required
def api_recipients_count():
    if not _is_admin():
        abort(404)
    segment = request.args.get("segment", "all")
    if segment not in VALID_SEGMENTS:
        segment = "all"
    return jsonify({"count": count_eligible_recipients(segment), "segment": segment})


@comms_bp.route("/api/admin/comunicaciones/recipients/counts")
@login_required
def api_recipients_counts():
    """Returns counts for all three segments at once — reduces round-trips."""
    if not _is_admin():
        abort(404)
    return jsonify(count_eligible_recipients_all_segments())


# ── CAMPAIGNS LIST & DETAIL ───────────────────────────────────────────────────

@comms_bp.route("/api/admin/comunicaciones/campaigns")
@login_required
def api_campaigns_list():
    if not _is_admin():
        abort(404)
    campaigns = (
        CommunicationCampaign.query
        .order_by(CommunicationCampaign.created_at.desc())
        .limit(200)
        .all()
    )
    return jsonify([c.to_dict(with_stats=True) for c in campaigns])


@comms_bp.route("/api/admin/comunicaciones/campaigns/<int:campaign_id>")
@login_required
def api_campaign_detail(campaign_id):
    if not _is_admin():
        abort(404)
    campaign = CommunicationCampaign.query.get_or_404(campaign_id)
    return jsonify(campaign.to_dict(with_stats=True))


@comms_bp.route("/api/admin/comunicaciones/campaigns/<int:campaign_id>/status")
@login_required
def api_campaign_status(campaign_id):
    """Polling endpoint for live progress during send."""
    if not _is_admin():
        abort(404)
    campaign = CommunicationCampaign.query.get_or_404(campaign_id)
    return jsonify({
        "campaign_id":    campaign_id,
        "status":         campaign.status,
        "recipients_count": campaign.recipients_count,
        "sent":           campaign.sent_count(),
        "failed":         campaign.failed_count(),
        "pending":        campaign.pending_count(),
    })


# ── DELIVERIES (error log) ────────────────────────────────────────────────────

@comms_bp.route("/api/admin/comunicaciones/campaigns/<int:campaign_id>/deliveries")
@login_required
def api_campaign_deliveries(campaign_id):
    """
    Returns deliveries for a campaign, optionally filtered by ?status=failed|sent|…
    Capped at 500 rows — sufficient for any realistic campaign.
    """
    if not _is_admin():
        abort(404)
    CommunicationCampaign.query.get_or_404(campaign_id)
    status_filter = request.args.get("status")
    q = CommunicationDelivery.query.filter_by(campaign_id=campaign_id)
    if status_filter:
        q = q.filter_by(status=status_filter)
    deliveries = q.order_by(CommunicationDelivery.id.asc()).limit(500).all()
    return jsonify([d.to_dict() for d in deliveries])


# ── DELETE CAMPAIGN ───────────────────────────────────────────────────────────

@comms_bp.route("/api/admin/comunicaciones/campaigns/<int:campaign_id>", methods=["DELETE"])
@login_required
def api_delete_campaign(campaign_id):
    """
    Hard-delete a campaign and its deliveries.
    Blocked if in-flight (sending/queued) or if sent with real deliveries.
    """
    if not _is_admin():
        abort(404)
    CommunicationCampaign.query.get_or_404(campaign_id)  # 404 before service call
    ok, error = delete_campaign(campaign_id)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": error}), 409


# ── DRAFT CRUD ────────────────────────────────────────────────────────────────

@comms_bp.route("/api/admin/comunicaciones/drafts", methods=["POST"])
@login_required
def api_create_draft():
    if not _is_admin():
        abort(404)
    data              = request.get_json(silent=True) or {}
    subject           = (data.get("subject") or "").strip()
    body              = (data.get("body") or "").strip()
    preview_text      = (data.get("preview_text") or "").strip()
    recipient_segment = (data.get("recipient_segment") or "all").strip()
    individual_email     = (data.get("individual_email") or "").strip() or None
    processing_error_id  = data.get("processing_error_id") or None
    if recipient_segment not in VALID_SEGMENTS:
        recipient_segment = "all"

    if not subject:
        return jsonify({"error": "El asunto es obligatorio."}), 400
    if not body:
        return jsonify({"error": "El contenido es obligatorio."}), 400
    if len(subject) > 500:
        return jsonify({"error": "El asunto no puede superar 500 caracteres."}), 400
    if recipient_segment == "individual" and not individual_email:
        return jsonify({"error": "individual_email es obligatorio para el segmento individual."}), 400

    # Validate processing_error_id belongs to a real error (best-effort, no abort)
    if processing_error_id:
        try:
            processing_error_id = int(processing_error_id)
        except (TypeError, ValueError):
            processing_error_id = None

    campaign = create_campaign_draft(
        subject, body, preview_text, current_user.id, recipient_segment,
        individual_email, processing_error_id
    )
    return jsonify(campaign.to_dict()), 201


@comms_bp.route("/api/admin/comunicaciones/drafts/<int:campaign_id>", methods=["PATCH"])
@login_required
def api_update_draft(campaign_id):
    if not _is_admin():
        abort(404)
    campaign = CommunicationCampaign.query.get_or_404(campaign_id)
    if campaign.status != "draft":
        return jsonify({"error": f"Solo se puede editar un borrador. Estado actual: {campaign.status}."}), 409
    data = request.get_json(silent=True) or {}
    proc_err_id = data.get("processing_error_id")
    if proc_err_id is not None:
        try:
            proc_err_id = int(proc_err_id)
        except (TypeError, ValueError):
            proc_err_id = None
    update_campaign_draft(
        campaign,
        subject=data.get("subject"),
        body=data.get("body"),
        preview_text=data.get("preview_text"),
        recipient_segment=data.get("recipient_segment"),
        individual_email=data.get("individual_email"),
        processing_error_id=proc_err_id,
    )
    return jsonify(campaign.to_dict())


# ── SEND TEST ─────────────────────────────────────────────────────────────────

@comms_bp.route("/api/admin/comunicaciones/drafts/<int:campaign_id>/send-test", methods=["POST"])
@login_required
def api_send_test(campaign_id):
    if not _is_admin():
        abort(404)
    campaign = CommunicationCampaign.query.get_or_404(campaign_id)
    result   = send_test_email(campaign, current_user.email)
    if result["ok"]:
        return jsonify({"ok": True, "sent_to": current_user.email})
    return jsonify({"ok": False, "error": result.get("error", "Error desconocido.")}), 500


# ── SEND CAMPAIGN ─────────────────────────────────────────────────────────────

@comms_bp.route("/api/admin/comunicaciones/drafts/<int:campaign_id>/send", methods=["POST"])
@login_required
def api_send_campaign(campaign_id):
    if not _is_admin():
        abort(404)

    campaign = CommunicationCampaign.query.get_or_404(campaign_id)

    if campaign.status != "draft":
        return jsonify({
            "error": f"Esta campaña ya está en estado '{campaign.status}' y no se puede reenviar."
        }), 409

    data = request.get_json(silent=True) or {}
    if not data.get("confirm"):
        return jsonify({"error": "Se requiere confirmación explícita (confirm: true)."}), 400

    seg = campaign.recipient_segment or "all"
    if seg == "individual" and not campaign.individual_email:
        return jsonify({"error": "Esta campaña individual no tiene email de destinatario."}), 400
    recipient_count = count_eligible_recipients(seg)
    if recipient_count == 0 and seg != "individual":
        return jsonify({"error": "No hay destinatarios elegibles para el segmento seleccionado."}), 400

    # Transition to queued before launching thread — prevents double dispatch
    campaign.status           = "queued"
    campaign.recipients_count = recipient_count
    db.session.commit()

    dispatch_campaign(campaign.id, current_app.app_context())

    return jsonify({
        "ok":               True,
        "campaign_id":      campaign.id,
        "status":           campaign.status,
        "recipients_count": recipient_count,
    })


# ── UNSUBSCRIBE ────────────────────────────────────────────────────────────────

@comms_bp.route("/api/unsubscribe", methods=["POST"])
def api_unsubscribe():
    data  = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()

    if not token or len(token) > 64:
        return jsonify({"error": "Token inválido."}), 400

    user = User.query.filter_by(comms_unsubscribe_token=token).first()
    if not user:
        # Return success to avoid token enumeration
        return jsonify({"ok": True, "message": "Desuscripción procesada."})

    user.comms_opted_out = True
    db.session.commit()

    return jsonify({
        "ok":      True,
        "message": "Desuscripción confirmada.",
        "email":   user.email,
    })
