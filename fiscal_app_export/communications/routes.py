"""
Admin routes for the communications module.
All /admin/* and /api/admin/comunicaciones/* endpoints live here.
Public: /unsubscribe (page) and /api/unsubscribe (action).
"""
import os
from flask import abort, jsonify, request, current_app
from flask_login import login_required, current_user

from models import db, User, CommunicationCampaign, CommunicationDelivery
from .service import (
    VALID_SEGMENTS,
    count_eligible_recipients,
    count_eligible_recipients_all_segments,
    create_campaign_draft,
    update_campaign_draft,
    send_test_email,
    dispatch_campaign,
)
from . import comms_bp

# Build admin set at import time — same logic as app.py's ADMIN_EMAILS
_ADMIN_EMAILS = frozenset(
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
)


def _is_admin() -> bool:
    return (
        current_user.is_authenticated
        and current_user.email.strip().lower() in _ADMIN_EMAILS
    )


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
    if recipient_segment not in VALID_SEGMENTS:
        recipient_segment = "all"

    if not subject:
        return jsonify({"error": "El asunto es obligatorio."}), 400
    if not body:
        return jsonify({"error": "El contenido es obligatorio."}), 400
    if len(subject) > 500:
        return jsonify({"error": "El asunto no puede superar 500 caracteres."}), 400

    campaign = create_campaign_draft(subject, body, preview_text, current_user.id, recipient_segment)
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
    update_campaign_draft(
        campaign,
        subject=data.get("subject"),
        body=data.get("body"),
        preview_text=data.get("preview_text"),
        recipient_segment=data.get("recipient_segment"),
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

    recipient_count = count_eligible_recipients(campaign.recipient_segment or "all")
    if recipient_count == 0:
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
