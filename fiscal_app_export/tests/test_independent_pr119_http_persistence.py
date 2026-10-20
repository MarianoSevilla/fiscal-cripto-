"""Independent HTTP persistence gate on synthetic SQLite, no production access."""
import csv
import io
import pathlib
import sys

APP_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from contextlib import contextmanager
from tempfile import TemporaryDirectory
import os

@contextmanager
def real_flask():
    with TemporaryDirectory(prefix="ms-audit-fiscal-") as directory:
        os.environ["FLASK_ENV"] = "testing"
        os.environ["DATABASE_URL"] = "sqlite:///" + str(pathlib.Path(directory) / "audit.sqlite")
        os.environ["SECRET_KEY"] = "ci-fiscal-audit-only-secret"
        os.environ["ADMIN_EMAILS"] = ""
        os.environ["FISCAL_ADVISOR_EMAILS"] = ""
        os.environ["RESEND_API_KEY"] = ""
        from app import app, db, limiter
        from models import User
        assert app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
        app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
        limiter.enabled = False
        with app.app_context():
            db.create_all()
            user = User(email="audit-user@example.invalid", full_name="Synthetic Audit", role="user", is_active=True)
            db.session.add(user)
            db.session.commit()
            user_id = user.id
        try:
            yield app, {"usuario": user_id}, None
        finally:
            with app.app_context():
                db.session.remove()
                db.drop_all()


def csv_bytes(cols, row):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(cols)
    w.writerow(row)
    return out.getvalue().encode("utf-8")


def test_a01_bitvavo_real_http_422_failed_report_no_pdf():
    from models import db, FifoReport, User
    headers = [
        "Timezone", "Date", "Time", "Type", "Currency", "Amount",
        "Quote Currency", "Quote Price", "Received / Paid Currency",
        "Received / Paid Amount", "Fee currency", "Fee amount",
        "Status", "Transaction ID", "Address",
    ]
    bad = [
        "UTC", "2025-01-01", "10:00:00", "buy", "BTC", "2",
        "EUR", "100", "EUR", "unparseable", "EUR", "0",
        "Completed", "transaction1", "",
    ]
    # Flask real, login cookie through the app's own session mechanism,
    # and actual database writes against a disposable SQLite file.
    with real_flask() as (app, identities, _origin):
        uid = identities["usuario"]
        with app.test_client() as client:
            with app.app_context():
                identity = db.session.get(User, uid).get_id()
                before = FifoReport.query.filter_by(user_id=uid).count()
            with client.session_transaction() as session:
                session["_user_id"] = identity
                session["_fresh"] = True
            resp = client.post(
                "/api/analizar",
                data={
                    "csv": (io.BytesIO(csv_bytes(headers, bad)), "bad-bitvavo.csv"),
                    "exchange": "bitvavo",
                    "ejercicio": "2025",
                    "nombre": "Caso sintetico",
                },
                content_type="multipart/form-data",
            )
            assert resp.status_code == 422, (resp.status_code, resp.get_json())
            result = resp.get_json()
            assert isinstance(result, dict) and "Datos fiscales no seguros" in result.get("error", "")
            assert result.get("ok") is not True
            assert not result.get("token")
            assert not result.get("resumen")
            assert not result.get("operaciones")
            assert resp.mimetype == "application/json"
            with app.app_context():
                records = FifoReport.query.filter_by(user_id=uid).all()
                assert len(records) == before + 1, [(r.status, r.exchange) for r in records]
                created = records[-1]
                assert created.status == "failed", created.status
                assert created.exchange == "bitvavo"
                assert not FifoReport.query.filter_by(user_id=uid, status="generated").count()
