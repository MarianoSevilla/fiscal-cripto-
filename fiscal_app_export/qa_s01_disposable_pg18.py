"""Disposable PostgreSQL 18 functional acceptance in one Railway LAB one-shot.

No public HTTP server, no remote DB, no Railway volumes, no reused client data.
Uses only a localhost Unix socket and directories removed on process exit.
This service is NOT the live S01 lab web and NEVER targets Postgres-Im3h.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import io
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch


PROJECT_ID = "5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e"
ENVIRONMENT_ID = "3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8"
SERVICE_ID = "47fa01c4-777e-4d7f-87b2-5b698341ff93"
MIGRATION_BASE = "m6n7o8p9q0r1"
MIGRATION_HEAD = "z9a0b1c2d3e4"
FORBIDDEN_KEYS = (
    "DATABASE_URL", "TARGET_DATABASE_URL", "S01_SCHEMA_BOOTSTRAP_APPROVAL",
    "S01_RECOVERY_WRITE_APPROVAL", "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
    "RESEND_API_KEY", "GOOGLE_CLIENT_SECRET",
)


class QARefused(RuntimeError):
    pass


def validate_railway_one_shot(env: dict[str, str]) -> None:
    expected = {
        "RAILWAY_PROJECT_ID": PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": ENVIRONMENT_ID,
        "RAILWAY_SERVICE_ID": SERVICE_ID,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
    }
    for name, value in expected.items():
        if env.get(name) != value:
            raise QARefused("WRONG_IDENTITY_" + name)
    if any(env.get(k) for k in FORBIDDEN_KEYS):
        raise QARefused("EXTERNAL_DB_OR_PROVIDER_VARIABLE")
    if any((env.get(k) or "").strip() for k in (
        "RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL",
        "APP_BASE_URL", "PGHOST", "PGPORT",
    )):
        raise QARefused("PUBLIC_OR_EXTERNAL_ORIGIN")
    if env.get("S01_QA_DISPOSABLE_APPROVAL") != (
        "S01-QA-EPHEMERAL-ONLY:" + SERVICE_ID
    ):
        raise QARefused("EXACT_QA_APPROVAL_ABSENT")


def selftest() -> None:
    baseline = {
        "RAILWAY_PROJECT_ID": PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": ENVIRONMENT_ID,
        "RAILWAY_SERVICE_ID": SERVICE_ID,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "S01_QA_DISPOSABLE_APPROVAL": "S01-QA-EPHEMERAL-ONLY:" + SERVICE_ID,
    }
    validate_railway_one_shot(baseline)
    for k, bad in (
        ("RAILWAY_SERVICE_ID", "212f4f52-b349-4387-a046-9f6b08237d2e"),
        ("RAILWAY_PROJECT_ID", "e04f04a8-3aae-4aed-9073-638601f8ca30"),
        ("RAILWAY_ENVIRONMENT_ID", "912b2cae-38a8-4900-a2d0-13f85e749971"),
        ("DATABASE_URL", "postgresql://forbidden@postgres-im3h.railway.internal/railway"),
        ("TARGET_DATABASE_URL", "postgresql://forbidden@postgres.railway.internal/railway"),
        ("RESEND_API_KEY", "x"),
        ("STRIPE_SECRET_KEY", "x"),
        ("RAILWAY_PUBLIC_DOMAIN", "some.public.example"),
        ("APP_BASE_URL", "https://public.example"),
        ("S01_QA_DISPOSABLE_APPROVAL", "not-authorized"),
    ):
        test = dict(baseline, **{k: bad})
        try:
            validate_railway_one_shot(test)
        except QARefused:
            pass
        else:
            raise AssertionError("Guard accepted invalid " + k)
    print("S01 EPHEMERAL QA GUARDS: PASS (identity, target, providers, public and approval)")


@contextmanager
def ephemeral_postgresql():
    # Postgres image runs as uid postgres; no attached Railway volume is used.
    with tempfile.TemporaryDirectory(prefix="s01-qa-no-volume-") as td:
        root = Path(td)
        data = root / "postgres"
        sockdir = root / "socket"
        artifacts = root / "artifacts"
        sockdir.mkdir(mode=0o700)
        artifacts.mkdir(mode=0o700)
        pgctl = "/usr/lib/postgresql/18/bin/pg_ctl"
        initdb = "/usr/lib/postgresql/18/bin/initdb"
        subprocess.run([
            initdb, "-D", str(data), "-U", "postgres",
            "--auth-local=trust", "--auth-host=reject", "--no-instructions",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logfile = root / "pg-server.log"
        started = False
        try:
            subprocess.run([
                pgctl, "-D", str(data), "-l", str(logfile), "-w",
                "-o", "-c listen_addresses='' -c unix_socket_directories="
                + str(sockdir) + " -p 55439", "start",
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            started = True
            import psycopg2
            conn = psycopg2.connect(dbname="postgres", user="postgres",
                                    host=str(sockdir), port=55439)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT current_database(), current_setting('server_version_num'), (pg_catalog.pg_control_system()).system_identifier::text")
                    db, ver, ident = cursor.fetchone()
                    if db != "postgres" or not ver.startswith("18") or not ident:
                        raise QARefused("NOT_LOCAL_POSTGRESQL18")
                    cursor.execute("SHOW listen_addresses")
                    if cursor.fetchone()[0] != "":
                        raise QARefused("POSTGRES_NOT_UNIX_ONLY")
            finally:
                conn.close()
            yield root, sockdir
        finally:
            if started:
                subprocess.run([pgctl, "-D", str(data), "-m", "immediate",
                                "-w", "stop"], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _login(app, email):
    client = app.test_client()
    res = client.post("/api/login", json={
        "email": email, "password": "CI-only-fictitious-24",
    })
    assert res.status_code == 200, ("LOGIN", res.status_code)
    assert client.get("/api/me").json["user"]["email"] == email
    return client


def exercise_real_pg(root: Path, socket_dir: Path, original_env: dict[str, str]) -> None:
    # App modules get ONLY a synthetic testing environment, never Railway
    # metadata or provider keys. All DB access is via THIS Unix socket.
    os.environ.clear()
    os.environ.update({
        "PATH": original_env.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(root),
        "TMPDIR": str(root / "artifacts"),
        "FLASK_ENV": "testing",
        "DATABASE_URL": "postgresql+psycopg2://postgres@/postgres?host="
        + str(socket_dir) + "&port=55439",
        "SECRET_KEY": "s01-ephemeral-fixture-key-never-real",
        "ADMIN_EMAILS": "",
        "FISCAL_ADVISOR_EMAILS": "",
        "RESEND_API_KEY": "",
        "ENABLE_ADVISORY_UPLOADS": "false",
        "ENABLE_ADVISORY_STATUS_EMAILS": "false",
        "PROCESSING_ERROR_EMAILS_ENABLED": "false",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    tempfile.tempdir = os.environ["TMPDIR"]
    app_path = Path(__file__).resolve().parent
    sys.path.insert(0, str(app_path))
    sys.path.insert(0, str(app_path / "tests"))
    from flask_migrate import stamp, upgrade
    from app import app, db, limiter
    from models import User, FifoReport, FiscalAdvisoryRequest, AdvisoryInternalNote
    from qa_s01_functional_synthetic_ci import BITVAVO_CSV
    from lab_isolation import LAB_IDENTITY, lab_request_denial

    assert app.config["RUNTIME_MODE"] == "testing"
    assert app.config["SQLALCHEMY_DATABASE_URI"].startswith(
        "postgresql+psycopg2://postgres@/postgres?host=")
    assert LAB_IDENTITY.db_hostname == "postgres-im3h.railway.internal"
    assert lab_request_denial(host="s01-lab-web.railway.internal:8080",
                              path="/api/analizar", method="POST") is not None

    app.config.update(TESTING=True, RATELIMIT_ENABLED=False,
                      SESSION_COOKIE_SECURE=False)
    limiter.enabled = False
    with app.app_context():
        db.create_all()
        directory = str(app_path / "migrations")
        stamp(directory=directory, revision=MIGRATION_BASE)
        upgrade(directory=directory, revision=MIGRATION_HEAD)
        from sqlalchemy import text
        with db.engine.connect() as conn:
            assert conn.dialect.name == "postgresql"
            rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert rev == MIGRATION_HEAD, rev
            h = conn.execute(text("SHOW listen_addresses")).scalar_one()
            assert h == "", "Remote TCP listener must be disabled"

        for role, email in (("user", "usuario@example.invalid"),
                            ("fiscal_advisor", "asesor@example.invalid")):
            u = User(email=email, full_name="S01 Usuario ficticio", role=role,
                     email_verified_at=datetime(2024, 1, 1), is_active=True)
            u.set_password("CI-only-fictitious-24")
            db.session.add(u)
            db.session.flush()
            if role == "user":
                user_id = u.id
        c = FiscalAdvisoryRequest(
            user_id=user_id, full_name="Caso ficticio S01 en PG18",
            email="usuario@example.invalid", tax_residence_country="España",
            tax_year=2024, service_type="presupuesto_personalizado",
            case_description="Sólo datos ficticios, sin clientes ni proveedores.",
            status="submitted")
        db.session.add(c)
        db.session.commit()
        case_id = c.id

    # The app uses the UNIX socket; forbid Python-based TCP and provider I/O.
    original_connect = socket.socket.connect

    def allow_unix_only(self, addr):
        if isinstance(addr, str) and addr.startswith(str(socket_dir)):
            return original_connect(self, addr)
        raise AssertionError("S01 QA forbids outbound or incoming TCP connect")

    with patch.object(socket.socket, "connect", allow_unix_only), \
         patch("requests.sessions.Session.request",
               side_effect=AssertionError("S01 QA forbids HTTP providers")) as requests, \
         patch("resend.Emails.send",
               side_effect=AssertionError("S01 QA forbids email")) as resend:
        guest = app.test_client()
        assert guest.get("/api/me").json["user"] is None
        assert guest.get("/dashboard").status_code == 302
        assert guest.post("/api/login", json={
            "email": "usuario@example.invalid", "password": "not-the-password",
        }).status_code == 401
        client = _login(app, "usuario@example.invalid")
        assert client.get("/dashboard").status_code == 200
        assert client.get("/api/admin/asesoramiento/solicitudes").status_code in (401, 403)

        result = client.post("/api/analizar", data={
            "csv": (io.BytesIO(BITVAVO_CSV.encode("utf-8")), "s01-pg18-fake.csv"),
            "nombre": "Cliente ficticio PG18",
            "ejercicio": "2024", "exchange": "bitvavo",
        }, content_type="multipart/form-data")
        assert result.status_code == 200, ("FIFO_HTTP", result.status_code)
        payload = result.get_json()
        assert payload["ok"] and isinstance(payload["operaciones"], list)
        token = payload["token"]
        assert re.fullmatch(r"[A-Za-z0-9_-]+\.pdf", token)

        advisor = _login(app, "asesor@example.invalid")
        assert advisor.get("/api/descargar/" + token).status_code == 403
        pdf = client.get("/api/descargar/" + token)
        assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
        assert client.get("/api/descargar/" + token).status_code == 403

        items = advisor.get("/api/admin/asesoramiento/solicitudes")
        assert items.status_code == 200
        assert case_id in [x["id"] for x in items.get_json()]
        csrf_result = advisor.get("/api/admin/asesoramiento/gestion-token")
        assert csrf_result.status_code == 200
        csrf = csrf_result.json["csrf_token"]
        note_url = ("/api/admin/asesoramiento/solicitudes/" + str(case_id)
                    + "/gestion/nota")
        state_url = ("/api/admin/asesoramiento/solicitudes/" + str(case_id)
                     + "/gestion/estado")
        assert advisor.post(note_url, json={"nota": "no token"}).status_code == 403
        assert advisor.post(note_url, json={"nota": "Nota PG18 ficticia"},
                            headers={"X-S01-C1-CSRF": csrf}).status_code == 200
        assert advisor.post(state_url, json={"status": "under_review"},
                            headers={"X-S01-C1-CSRF": csrf}).status_code == 200
        assert advisor.post(state_url, json={"status": "paid"},
                            headers={"X-S01-C1-CSRF": csrf}).status_code == 503
        assert advisor.post("/api/admin/asesoramiento/solicitudes/"
                            + str(case_id) + "/enviar-presupuesto",
                            json={}).status_code == 503
        assert advisor.post("/api/pago/iniciar/ci-token",
                            json={}).status_code == 503

        with app.app_context():
            reports = FifoReport.query.filter_by(user_id=user_id, exchange="bitvavo").all()
            assert len(reports) == 1 and reports[0].status == "generated"
            assert reports[0].downloaded_at is not None
            obj = db.session.get(FiscalAdvisoryRequest, case_id)
            assert obj.status == "under_review" and obj.quoted_amount is None
            assert obj.amount_paid is None and obj.paypal_capture_id is None
            assert AdvisoryInternalNote.query.filter_by(request_id=case_id).count() == 1
        requests.assert_not_called()
        resend.assert_not_called()


def main() -> None:
    if len(sys.argv) > 1:
        if sys.argv[1:] != ["--selftest"]:
            raise SystemExit(2)
        selftest()
        return
    original = dict(os.environ)
    try:
        validate_railway_one_shot(original)
    except QARefused as exc:
        print("S01 EPHEMERAL PG18: NO-GO (" + str(exc) + ")", flush=True)
        raise SystemExit(1) from None
    try:
        with ephemeral_postgresql() as (root, sockdir):
            exercise_real_pg(root, sockdir, original)
    except Exception:
        # Never print exception payloads: they may include DB URI, CSV or tokens.
        print("S01 EPHEMERAL PG18: NO-GO (REDACTED; ONE-SHOT; NO RETRY)", flush=True)
        raise SystemExit(1) from None
    print("S01 EPHEMERAL PG18: PASS (isolated localhost PG18; real Flask FIFO/PDF/"
          "advisor; no providers; transient database and PDF files deleted)",
          flush=True)


if __name__ == "__main__":
    main()
