"""S01 closeout: integrated FIFO + roles + internal advisory with synthetic-only data.

Run ONLY inside GitHub Actions on an ephemeral SQLite DB created by
qa_flask_navigation.real_flask(). No real Railway, customer data, provider,
production / staging DB, external network, or email is permitted.
This does NOT unblock any route in the real S01 lab deployment.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
from datetime import datetime
from unittest.mock import patch


def _stop_unless_isolated_ci() -> None:
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("CI") != "true"
            or os.environ.get("FLASK_ENV") != "testing"):
        raise RuntimeError("S01 functional smoke is CI/testing only")
    if (os.environ.get("DATABASE_URL")
            or any(k.startswith("RAILWAY_") for k in os.environ)
            or any(os.environ.get(k) for k in (
                "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
                "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
                "RESEND_API_KEY", "GOOGLE_CLIENT_SECRET",
            ))):
        raise RuntimeError("S01 functional smoke refuses DB/provider credentials")


_STOP_MSG = "S01 CI refused any outbound network/email/provider access"
BITVAVO_CSV = (
    "Timezone,Date,Time,Type,Currency,Amount,Quote Currency,"
    "Quote Price,Received / Paid Currency,Received / Paid Amount,"
    "Fee currency,Fee amount,Status,Transaction ID,Address\n"
    "UTC,2024-06-15,10:00:00,buy,BTC,0.01,EUR,"
    "30000,EUR,-300,EUR,-0.30,Completed,ci-fictional-buy,\n"
    "UTC,2024-09-01,12:00:00,sell,BTC,0.005,EUR,"
    "32000,EUR,160,EUR,-0.16,Completed,ci-fictional-sell,\n"
)


def _login(flask_app, identity_email: str, password: str):
    client = flask_app.test_client()
    reply = client.post("/api/login", json={
        "email": identity_email, "password": password,
    })
    assert reply.status_code == 200, (identity_email, reply.status_code)
    who = client.get("/api/me")
    assert who.status_code == 200 and who.json["user"]["email"] == identity_email
    return client


def _assert_real_lab_remains_fail_closed() -> None:
    from lab_isolation import LAB_IDENTITY, lab_request_denial
    assert LAB_IDENTITY.db_hostname == "postgres-im3h.railway.internal"
    assert lab_request_denial(
        host="s01-lab-web.railway.internal:8080",
        path="/healthz", method="GET",
    ) is None
    for path, method in (
        ("/api/login", "POST"),
        ("/dashboard", "GET"),
        ("/api/analizar", "POST"),
        ("/api/descargar/fake.pdf", "GET"),
        ("/api/admin/asesoramiento/solicitudes", "GET"),
        ("/api/admin/asesoramiento/gestion-token", "GET"),
        ("/api/webhooks/stripe", "POST"),
        ("/api/webhooks/paypal", "POST"),
        ("/api/asesoramiento/solicitar", "POST"),
    ):
        assert lab_request_denial(
            host="s01-lab-web.railway.internal:8080", path=path, method=method,
        ) == (503, "S01 lab route not explicitly permitted")


def main() -> None:
    _stop_unless_isolated_ci()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from qa_flask_navigation import real_flask
    # Never open an external socket; this server is bound on loopback only.
    with real_flask() as (flask_app, identities, origin):
        from app import db
        from models import User, FifoReport, FiscalAdvisoryRequest, AdvisoryInternalNote
        assert origin.startswith("http://127.0.0.1:")
        assert flask_app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
        assert flask_app.config["RUNTIME_MODE"] == "testing"
        assert os.environ["RESEND_API_KEY"] == ""
        assert flask_app.config["SESSION_COOKIE_SECURE"] is False
        assert flask_app.config["TESTING"] is True

        with flask_app.app_context():
            for role, user_id in identities.items():
                u = db.session.get(User, user_id)
                assert u.email.endswith("@example.invalid"), role
                u.email_verified_at = datetime(2024, 1, 1)
                u.set_password("CI-only-fictitious-24")
            case = FiscalAdvisoryRequest(
                user_id=identities["usuario"],
                full_name="S01 Caso inventado para prueba funcional",
                email="usuario@example.invalid",
                tax_residence_country="España",
                tax_year=2024,
                service_type="presupuesto_personalizado",
                case_description="Datos completamente ficticios sin clientes reales.",
                status="submitted",
            )
            db.session.add(case)
            db.session.commit()
            case_id = case.id

        # Patches are armed after the loopback server starts. test_client uses
        # Flask dispatch directly; no HTTP socket is required for a request.
        with (
            patch.object(socket.socket, "connect", side_effect=AssertionError(_STOP_MSG)) as network,
            patch("requests.sessions.Session.request", side_effect=AssertionError(_STOP_MSG)) as requests,
            patch("resend.Emails.send", side_effect=AssertionError(_STOP_MSG)) as resend,
        ):
            guest = flask_app.test_client()
            assert guest.get("/api/me").json["user"] is None
            assert guest.get("/dashboard").status_code == 302
            assert guest.post(
                "/api/login", json={"email": "usuario@example.invalid",
                                     "password": "no"}
            ).status_code == 401
            user = _login(flask_app, "usuario@example.invalid", "CI-only-fictitious-24")
            assert user.get("/dashboard").status_code == 200
            assert user.get("/api/admin/asesoramiento/solicitudes").status_code in (401, 403)
            assert user.get("/api/admin/asesoramiento/gestion-token").status_code in (401, 403)

            # Inbound CSV is generated inside this test and is NEVER from a real user.
            result = user.post(
                "/api/analizar",
                data={
                    "csv": (io.BytesIO(BITVAVO_CSV.encode("utf-8")), "s01-ci-bitvavo.csv"),
                    "nombre": "Titular ficticio CI",
                    "ejercicio": "2024",
                    "exchange": "bitvavo",
                },
                content_type="multipart/form-data",
            )
            assert result.status_code == 200, ("FIFO", result.status_code, result.get_json())
            payload = result.get_json()
            assert payload["ok"] is True
            assert isinstance(payload["resumen"], dict)
            assert isinstance(payload["operaciones"], list)
            assert re.fullmatch(r"[a-zA-Z0-9_-]+\.pdf", payload["token"])
            token = payload["token"]
            with flask_app.app_context():
                records = FifoReport.query.filter_by(user_id=identities["usuario"],
                                                       exchange="bitvavo").all()
                assert len(records) == 1 and records[0].status == "generated"
                report_id = records[0].id

            # A different authenticated user cannot read another user's PDF.
            advisor = _login(flask_app, "asesor@example.invalid", "CI-only-fictitious-24")
            stolen = advisor.get("/api/descargar/" + token)
            assert stolen.status_code == 403
            pdf = user.get("/api/descargar/" + token)
            assert pdf.status_code == 200, ("pdf", pdf.status_code)
            assert pdf.data.startswith(b"%PDF")
            assert user.get("/api/descargar/" + token).status_code == 403
            with flask_app.app_context():
                assert db.session.get(FifoReport, report_id).downloaded_at is not None

            list_result = advisor.get("/api/admin/asesoramiento/solicitudes")
            assert list_result.status_code == 200
            assert case_id in [v["id"] for v in list_result.get_json()]
            token_resp = advisor.get("/api/admin/asesoramiento/gestion-token")
            assert token_resp.status_code == 200
            csrf = token_resp.json["csrf_token"]
            note_url = ("/api/admin/asesoramiento/solicitudes/"
                        + str(case_id) + "/gestion/nota")
            state_url = ("/api/admin/asesoramiento/solicitudes/"
                         + str(case_id) + "/gestion/estado")
            assert advisor.post(note_url, json={"nota": "CI sin CSRF"}).status_code == 403
            note = advisor.post(note_url, json={"nota": "Nota interna ficticia CI"},
                                headers={"X-S01-C1-CSRF": csrf})
            assert note.status_code == 200, ("note", note.status_code, note.get_json())
            state = advisor.post(state_url, json={"status": "under_review"},
                                 headers={"X-S01-C1-CSRF": csrf})
            assert state.status_code == 200, ("state", state.status_code, state.get_json())
            assert advisor.post(state_url, json={"status": "paid"},
                                headers={"X-S01-C1-CSRF": csrf}).status_code == 503
            assert advisor.post(
                "/api/admin/asesoramiento/solicitudes/"
                + str(case_id) + "/enviar-presupuesto", json={},
            ).status_code == 503
            assert advisor.post("/api/pago/iniciar/ci-never-valid", json={}).status_code == 503
            with flask_app.app_context():
                fresh = db.session.get(FiscalAdvisoryRequest, case_id)
                assert fresh.status == "under_review"
                assert fresh.quoted_amount is None and fresh.amount_paid is None
                assert fresh.paypal_capture_id is None and fresh.payment_link_token is None
                assert AdvisoryInternalNote.query.filter_by(request_id=case_id).count() == 1

            network.assert_not_called()
            requests.assert_not_called()
            resend.assert_not_called()

        _assert_real_lab_remains_fail_closed()
    print("S01 FUNCTIONAL SYNTHETIC CI: PASS; auth, FIFO Bitvavo/PDF token, "
          "advisor role/CSRF/note/status, payments/email/egress denied; "
          "LAB endpoints remain blocked; temporary SQLite only")


if __name__ == "__main__":
    main()
