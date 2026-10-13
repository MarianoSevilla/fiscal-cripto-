"""C1: isolated non-financial S01 management while quotes/payments stay frozen."""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("SECRET_KEY", "c1-local-fictional-test-only-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///" + tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False).name)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app, db  # noqa: E402
from models import User, FiscalAdvisoryRequest, AdvisoryInternalNote, FiscalAdvisoryStatusHistory, AdvisoryAuditLog  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    app.config.update(TESTING=True, RATELIMIT_ENABLED=False,
                      WTF_CSRF_ENABLED=False, SESSION_COOKIE_SECURE=False)
    with app.app_context():
        db.create_all()
        advisor = User(email="c1-advisor@example.invalid", full_name="C1 Advisor",
                       role="fiscal_advisor", email_verified_at=datetime.utcnow())
        advisor.set_password("c1-only-test-pass")
        ordinary = User(email="c1-client@example.invalid", full_name="C1 Client",
                        role="user", email_verified_at=datetime.utcnow())
        ordinary.set_password("c1-only-test-pass")
        db.session.add_all((advisor, ordinary))
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


def _client(ctx, email="c1-advisor@example.invalid"):
    c = ctx.test_client()
    response = c.post("/api/login", json={"email": email, "password": "c1-only-test-pass"})
    assert response.status_code == 200, response.get_json()
    return c


def _create(ctx):
    with ctx.app_context():
        item = FiscalAdvisoryRequest(
            full_name="Persona sintética C1", email="c1-client@example.invalid",
            tax_residence_country="España", tax_year=2025,
            service_type="presupuesto_personalizado",
            case_description="Caso ficticio sin datos fiscales reales.", status="submitted",
        )
        db.session.add(item)
        db.session.commit()
        item_id = item.id
        db.session.remove()
    return item_id


def _token(client):
    res = client.get("/api/admin/asesoramiento/gestion-token")
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "no-store"
    return {"X-S01-C1-CSRF": res.get_json()["csrf_token"]}


def test_c1_notes_are_internal_no_email_or_payment(ctx):
    aid = _create(ctx)
    c = _client(ctx)
    headers = _token(c)
    with patch("app._send_advisory_quote_email") as send_quote, \
         patch("app._send_advisory_message_email") as send_message:
        r = c.post(f"/api/admin/asesoramiento/solicitudes/{aid}/gestion/nota",
                   json={"nota": "Revisión interna sin importes ni enlace."}, headers=headers)
    assert r.status_code == 200, r.get_json()
    send_quote.assert_not_called()
    send_message.assert_not_called()
    with ctx.app_context():
        assert AdvisoryInternalNote.query.filter_by(request_id=aid).count() == 1
        item = FiscalAdvisoryRequest.query.get(aid)
        assert item.quoted_amount is None
        assert item.payment_link_token is None
        assert item.quote_accepted_at is None


def test_c1_restricted_status_and_audit(ctx):
    aid = _create(ctx)
    c = _client(ctx)
    headers = _token(c)
    endpoint = f"/api/admin/asesoramiento/solicitudes/{aid}/gestion/estado"
    r = c.post(endpoint, json={"status": "under_review", "note": "Valoración interna."},
               headers=headers)
    assert r.status_code == 200, r.get_json()
    with ctx.app_context():
        assert FiscalAdvisoryRequest.query.get(aid).status == "under_review"
    for status in ("quote_sent", "paid_received", "completed", "refunded", "cancelled", "archived"):
        r = c.post(endpoint, json={"status": status}, headers=headers)
        assert r.status_code == 503, (status, r.get_json())
    with ctx.app_context():
        assert FiscalAdvisoryRequest.query.get(aid).status == "under_review"


def test_c1_existing_financial_evidence_blocks_status_but_keeps_notes(ctx):
    aid = _create(ctx)
    with ctx.app_context():
        item = FiscalAdvisoryRequest.query.get(aid)
        item.payment_link_token = "preserved-historical-c1-token"
        item.paypal_order_id = "legacy-order-must-remain"
        db.session.commit()
    c = _client(ctx)
    headers = _token(c)
    r = c.post(f"/api/admin/asesoramiento/solicitudes/{aid}/gestion/estado",
               json={"status": "under_review"}, headers=headers)
    assert r.status_code == 409
    r = c.post(f"/api/admin/asesoramiento/solicitudes/{aid}/gestion/nota",
               json={"nota": "Revisión sin cambiar historial."}, headers=headers)
    assert r.status_code == 200
    with ctx.app_context():
        item = FiscalAdvisoryRequest.query.get(aid)
        assert item.status == "submitted"
        assert item.paypal_order_id == "legacy-order-must-remain"
        assert item.payment_link_token == "preserved-historical-c1-token"


def test_c1_csrf_and_role_denials(ctx):
    aid = _create(ctx)
    c = _client(ctx)
    endpoint = f"/api/admin/asesoramiento/solicitudes/{aid}/gestion/nota"
    assert c.post(endpoint, json={"nota": "blocked"}).status_code == 403
    assert c.post(endpoint, json={"nota": "blocked"},
                  headers={"X-S01-C1-CSRF": "invalid"}).status_code == 403
    headers = _token(c)
    assert c.post(endpoint, json={"nota": "blocked"}, headers={
        **headers, "Origin": "https://attacker.invalid",
    }).status_code == 403
    other = _client(ctx, "c1-client@example.invalid")
    assert other.get("/api/admin/asesoramiento/gestion-token").status_code == 403
    assert other.post(endpoint, json={"nota": "blocked"}, headers=headers).status_code == 403


def test_c1_legacy_financial_endpoints_are_always_blocked(ctx):
    aid = _create(ctx)
    c = _client(ctx)
    frozen = [
        ("post", f"/api/admin/asesoramiento/solicitudes/{aid}/enviar-presupuesto"),
        ("post", f"/api/admin/asesoramiento/solicitudes/{aid}/mensaje"),
        ("post", f"/api/admin/asesoramiento/solicitudes/{aid}/estado"),
        ("post", "/api/pago/iniciar/synthetic"),
        ("get", "/api/pago/info/synthetic"),
    ]
    with patch("app._send_advisory_quote_email") as email, \
         patch("app._paypal_create_order") as paypal:
        for method, path in frozen:
            response = getattr(c, method)(path)
            assert response.status_code == 503, (method, path)
    email.assert_not_called()
    paypal.assert_not_called()


def test_c1_admin_ui_contains_no_payment_actions():
    html = (Path(__file__).resolve().parents[1] /
            "static" / "admin-asesoramiento.html").read_text(encoding="utf-8")
    assert "Operativa S01 temporalmente suspendida" in html
    assert "enviar-presupuesto" not in html
    assert "Reenviar link de pago" not in html
    assert "getC1ManagementToken" in html
    assert "/gestion/nota" in html
    assert "/gestion/estado" in html



@pytest.mark.parametrize("field,value", [
    ("commission_rate_bps", 3000),
    ("quoted_by_user_id", 1),
    ("quote_message", "Presupuesto ficticio"),
    ("quote_expires_at", datetime(2027, 1, 1)),
    ("quote_acceptance_ip", "192.0.2.8"),
    ("quote_acceptance_user_agent", "Synthetic browser"),
])
def test_c2_partial_financial_trace_blocks_state_but_keeps_evidence(ctx, field, value):
    aid = _create(ctx)
    with ctx.app_context():
        adv = db.session.get(FiscalAdvisoryRequest, aid)
        setattr(adv, field, value)
        db.session.commit()
    c = _client(ctx)
    headers = _token(c)
    detail = c.get(f"/api/admin/asesoramiento/solicitudes/{aid}").get_json()
    assert detail["c1_state_editable"] is False
    res = c.post(f"/api/admin/asesoramiento/solicitudes/{aid}/gestion/estado",
                 json={"status": "under_review"}, headers=headers)
    assert res.status_code == 409
    with ctx.app_context():
        adv = db.session.get(FiscalAdvisoryRequest, aid)
        assert adv.status == "submitted"
        assert getattr(adv, field) == value
        assert AdvisoryAuditLog.query.filter_by(request_id=aid).count() == 0


@pytest.mark.parametrize("evidence_type", ("status_history", "audit_log"))
def test_c2_historical_financial_evidence_blocks_even_without_columns(ctx, evidence_type):
    aid = _create(ctx)
    with ctx.app_context():
        if evidence_type == "status_history":
            db.session.add(FiscalAdvisoryStatusHistory(request_id=aid, status="quote_sent"))
        else:
            db.session.add(AdvisoryAuditLog(
                request_id=aid, admin_id=None,
                action=AdvisoryAuditLog.ACTION_QUOTE_SENT,
                detail="Synthetic former quotation",
            ))
        db.session.commit()
    c = _client(ctx)
    headers = _token(c)
    assert c.get(f"/api/admin/asesoramiento/solicitudes/{aid}").get_json()["c1_state_editable"] is False
    res = c.post(f"/api/admin/asesoramiento/solicitudes/{aid}/gestion/estado",
                 json={"status": "under_review"}, headers=headers)
    assert res.status_code == 409
    with ctx.app_context():
        assert db.session.get(FiscalAdvisoryRequest, aid).status == "submitted"


@pytest.mark.parametrize("target", ("pendiente_info", "waiting_user_info"))
def test_c2_cannot_claim_user_contact_without_message(ctx, target):
    aid = _create(ctx)
    c = _client(ctx)
    headers = _token(c)
    with patch("app._send_advisory_message_email") as email:
        res = c.post(f"/api/admin/asesoramiento/solicitudes/{aid}/gestion/estado",
                     json={"status": target}, headers=headers)
    assert res.status_code == 503
    email.assert_not_called()
    with ctx.app_context():
        assert db.session.get(FiscalAdvisoryRequest, aid).status == "submitted"


def test_c2_old_pending_state_can_return_to_internal_review(ctx):
    aid = _create(ctx)
    with ctx.app_context():
        db.session.get(FiscalAdvisoryRequest, aid).status = "waiting_user_info"
        db.session.commit()
    c = _client(ctx)
    headers = _token(c)
    assert c.get(f"/api/admin/asesoramiento/solicitudes/{aid}").get_json()["c1_state_editable"] is True
    assert c.post(f"/api/admin/asesoramiento/solicitudes/{aid}/gestion/estado",
                  json={"status": "under_review"}, headers=headers).status_code == 200


def test_c2_legacy_price_api_does_not_leak_amounts(ctx):
    c = ctx.test_client()
    res = c.get("/api/asesoramiento/precios")
    assert res.status_code == 503
    assert res.headers["Cache-Control"] == "no-store"
    data = res.get_json()
    assert data["code"] == "s01_quotes_suspended"
    assert "amount_cents" not in res.get_data(as_text=True)
    html = (Path(__file__).resolve().parents[1] /
            "static" / "asesoramiento-fiscal.html").read_text(encoding="utf-8")
    assert "Presupuestos suspendidos" in html
    assert "Cargando..." not in html
    assert "fetch('/api/asesoramiento/precios')" not in html


def test_c2_source_of_truth_ui(ctx):
    html = (Path(__file__).resolve().parents[1] /
            "static" / "admin-asesoramiento.html").read_text(encoding="utf-8")
    assert "d.c1_state_editable === true" in html
    assert "['submitted','under_review'].includes(k)" in html
    assert "comunicación al cliente suspendida" in html
