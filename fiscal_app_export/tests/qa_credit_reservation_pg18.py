"""Real Flask + Binance FIFO credit lifecycle on disposable PostgreSQL 18.

This script is guarded to run only inside the dedicated GitHub Actions PG18 job.
Synthetic child processes terminate at specific request cuts; PostgreSQL must
release their session advisory locks and the real recovery route must reconcile.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
DB = "credits_reservation_recovery_ci"
HOST, PORT, USER, PASSWORD = "127.0.0.1", 5432, "postgres", "ci-only-test-password"


def _guard() -> None:
    if not (os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("CI") == "true"
            and os.environ.get("FLASK_ENV") == "testing"):
        raise RuntimeError("Credits PostgreSQL acceptance is CI-only")
    if (HOST, PORT, DB, USER) != (
            "127.0.0.1", 5432, "credits_reservation_recovery_ci", "postgres"):
        raise RuntimeError("Non-local PostgreSQL is forbidden")


def _admin():
    _guard()
    return psycopg2.connect(host=HOST, port=PORT, user=USER,
                            password=PASSWORD, dbname="postgres", connect_timeout=5)


def _database(*, create: bool) -> None:
    conn = _admin()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version_num')::integer")
            version = cur.fetchone()[0]
            if not 180000 <= version < 190000:
                raise AssertionError(f"Expected PostgreSQL 18, got {version}")
            if create:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
            else:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(DB)))
    finally:
        conn.close()


def _run_program(program: str) -> str:
    env = os.environ.copy()
    env.update({
        "CI": "true", "GITHUB_ACTIONS": "true", "FLASK_ENV": "testing",
        "SECRET_KEY": "CI-ONLY-credit-reservation-test-secret-9xYp4",
        "DATABASE_URL": f"postgresql+psycopg2://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB}",
        "FIFO_CREDITS_ENABLED": "true", "FIFO_CREDITS_TEST_MODE": "true",
        "STRIPE_CREDITS_TEST_SECRET": "sk_test_synthetic_only",
        "STRIPE_CREDITS_TEST_WEBHOOK_SECRET": "whsec_synthetic_ci_only",
        "FIFO_CREDITS_REPORT_KEY": base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("="),
        "APP_BASE_URL": "https://marianosevilla.com",
        "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
    })
    for name in (
        "RAILWAY_ENVIRONMENT_ID", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_ID", "RAILWAY_DEPLOYMENT_ID", "RAILWAY_PUBLIC_DOMAIN",
        "RAILWAY_PRIVATE_DOMAIN", "PORT", "SERVER_SOFTWARE", "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET", "RESEND_API_KEY",
    ):
        env.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=ROOT, env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=240, check=False,
    )
    if result.returncode:
        raise AssertionError(
            f"PostgreSQL database={DB}, rc={result.returncode}\n{result.stdout[-8000:]}"
        )
    return result.stdout


PROGRAM = r"""
import csv, hashlib, hmac, io, json, os, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

assert os.path.isfile(os.path.join(os.getcwd(), "app.py"))
from app import app
from models import db, User, CreditWallet, CreditAnalysis, CreditLedgerEntry
from credit_ledger import create_purchase, attach_checkout_session, balance
from credits_stripe import checkout_session_params
import app as application

app.config.update(TESTING=True, RATELIMIT_ENABLED=False, WTF_CSRF_ENABLED=False)

with app.app_context():
    assert db.engine.dialect.name == "postgresql"
    db.create_all()
    with db.engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.exec_driver_sql("INSERT INTO alembic_version(version_num) VALUES ('b4c5d6e7f8a9')")
    owner = User(email="credits-owner-pg18@example.invalid", full_name="Synthetic owner",
                 role="user", plan="free", is_active=True)
    other = User(email="credits-other-pg18@example.invalid", full_name="Synthetic other",
                 role="user", plan="free", is_active=True)
    db.session.add_all([owner, other]); db.session.flush()
    owner_id, other_id = owner.id, other.id
    db.session.add_all([CreditWallet(user_id=owner_id), CreditWallet(user_id=other_id)])
    db.session.commit()

def login(client, user_id):
    now = int(time.time())
    with app.app_context():
        identity = db.session.get(User, user_id).get_id()
    with client.session_transaction() as sess:
        sess["_user_id"] = identity
        sess["_fresh"] = True
        sess["auth_started_at"] = now
        sess["auth_last_activity_at"] = now

def csv_bytes(marker="BASE", purchase=True):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["ID de usuario", "Tiempo", "Cuenta", "Operación", "Moneda", "Cambio", "Observación"])
    if purchase:
        writer.writerows([
            ["123", "2024-01-02 10:00:00", "Spot", "Buy Crypto With Fiat", "BTC", "0.02", "Wallet/BUY-" + marker],
            ["123", "2024-01-02 10:00:00", "Spot", "Buy Crypto With Fiat", "EUR", "-600", "Wallet/BUY-" + marker],
        ])
    writer.writerows([
        ["123", "2025-02-02 10:00:00", "Spot", "Sell Crypto To Fiat", "BTC", "-0.01", "Wallet/SELL-" + marker],
        ["123", "2025-02-02 10:00:00", "Spot", "Sell Crypto To Fiat", "EUR", "400", "Wallet/SELL-" + marker],
    ])
    return stream.getvalue().encode("utf-8")

CSV = csv_bytes()
PROVISIONAL_CSV = csv_bytes("PROVISIONAL", purchase=False)
ERROR_CSV = b"ID de usuario,Tiempo,Cuenta,Operacion\n1,2025-01-01,Spot,broken\n"

def quote_and_authorize(client, raw, *, year="2025"):
    quote = client.post("/api/credits/quote", data={
        "exchange": "binance", "fiscal_years": year,
        "csv": (io.BytesIO(raw), "binance-synthetic.csv"),
    }, content_type="multipart/form-data")
    assert quote.status_code == 200, quote.get_data(as_text=True)[:400]
    if quote.json.get("already_acquired"):
        return None, quote.json
    token = client.get("/api/credits/csrf").json["csrf_token"]
    authorized = client.post("/api/credits/authorize", json={"quote_token": quote.json["quote_token"]},
        headers={"X-Credits-CSRF": token, "Idempotency-Key": str(uuid4())})
    return authorized, quote.json

def authorize(client, raw, *, year="2025"):
    response, quote = quote_and_authorize(client, raw, year=year)
    assert response is not None and response.status_code == 201, (
        response.status_code if response else "already acquired",
        response.get_data(as_text=True)[:400] if response else quote,
    )
    return response.json["analysis_id"]

def submit(client, analysis_id, raw, *, filename="binance-synthetic.csv"):
    return client.post("/api/binance/analizar", data={
        "credit_analysis_id": analysis_id, "nombre": "Synthetic test",
        "ejercicio": "2025", "alcance_datos": "solo_binance",
        "csv": (io.BytesIO(raw), filename),
    }, content_type="multipart/form-data",
       headers={"X-Credit-Analysis-ID": analysis_id})

def signed_event(purchase, session_id, event_id, payment_intent):
    event = {"id": event_id, "livemode": False,
        "type": "checkout.session.completed", "data": {"object": {
            "id": session_id, "livemode": False, "mode": "payment",
            "status": "complete", "payment_status": "paid",
            "amount_total": purchase.amount_cents, "currency": "eur",
            "payment_intent": payment_intent,
            "metadata": {"credits_purchase_id": purchase.id},
        }}}
    payload = json.dumps(event, separators=(",", ":")).encode()
    stamp = int(time.time())
    secret = app.config["STRIPE_CREDITS_TEST_WEBHOOK_SECRET"]
    digest = hmac.new(secret.encode(), str(stamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
    return payload, f"t={stamp},v1={digest}"

def buy_synthetically(client, user_id, suffix):
    with app.app_context():
        purchase = create_purchase(user_id=user_id, package_key="standard",
                                    idempotency_key="pg18-synthetic-" + suffix)
        session_id = "cs_test_synthetic_" + suffix
        attach_checkout_session(purchase_id=purchase.id, session_id=session_id)
        params = checkout_session_params(purchase=purchase, base_url="https://marianosevilla.com")
        assert params["mode"] == "payment" and "subscription_data" not in params
    payload, signature = signed_event(purchase, session_id, "evt_synthetic_" + suffix,
                                      "pi_synthetic_" + suffix)
    headers = {"Stripe-Signature": signature, "Content-Type": "application/json"}
    result = client.post("/api/webhooks/stripe-credits-test", data=payload, headers=headers)
    assert result.status_code == 200 and result.json["handled"] is True, result.get_data(as_text=True)
    duplicate = client.post("/api/webhooks/stripe-credits-test", data=payload, headers=headers)
    assert duplicate.status_code == 200 and duplicate.json["handled"] is False

def csrf(client):
    return client.get("/api/credits/csrf").json["csrf_token"]

owner_client = app.test_client(); login(owner_client, owner_id)
other_client = app.test_client(); login(other_client, other_id)
buy_synthetically(owner_client, owner_id, "owner")
buy_synthetically(other_client, other_id, "other")
with app.app_context():
    assert balance(owner_id)["available"] == 230
    assert CreditLedgerEntry.query.filter_by(user_id=owner_id, entry_type="purchase").count() == 1

# Real authenticated HTTP -> upload quote -> authorization -> Binance classifier,
# FIFO engine and PDF -> settlement -> encrypted, owner-only repeat downloads.
definitive_id = authorize(owner_client, CSV)
definitive = submit(owner_client, definitive_id, CSV)
assert definitive.status_code == 200, definitive.get_data(as_text=True)[:800]
assert definitive.json["result_type"] == "definitive"
assert len(definitive.json["operaciones"]) == 1
assert abs(definitive.json["resumen"]["resultado_neto"] - 100.0) < 0.01
assert definitive.json["credits_charged"] == 50
report_url = definitive.json["download_url"]
for _ in range(2):
    downloaded = owner_client.get(report_url)
    assert downloaded.status_code == 200 and downloaded.mimetype == "application/pdf"
    assert downloaded.data.startswith(b"%PDF-") and len(downloaded.data) > 1000
assert other_client.get(report_url).status_code == 404
with app.app_context():
    assert balance(owner_id) == {"available": 180, "reserved": 0, "frozen": False}
    persisted_definitive = db.session.get(CreditAnalysis, definitive_id)
    assert persisted_definitive.status == "consumed"
    assert persisted_definitive.execution_started_at is not None

# Real missing-inventory response is provisional, has no tax figures, and its
# diagnostic PDF is retained encrypted for the purchased operation.
provisional_id = authorize(owner_client, PROVISIONAL_CSV)
provisional = submit(owner_client, provisional_id, PROVISIONAL_CSV)
assert provisional.status_code == 422, provisional.get_data(as_text=True)[:800]
assert provisional.json["result_type"] == "provisional"
assert provisional.json["borrador_binance"]["no_es_informe_fiscal"] is True
assert provisional.json["borrador_binance"]["ganancias_y_perdidas_eur"] is None
assert provisional.json["credits_charged"] == 50
provisional_download = owner_client.get(provisional.json["download_url"])
assert provisional_download.status_code == 200 and provisional_download.data.startswith(b"%PDF-")

# A malformed Binance file releases its reservation. The restored balance must
# be verified before the response states that no credit was consumed.
error_id = authorize(owner_client, ERROR_CSV)
error = submit(owner_client, error_id, ERROR_CSV)
assert error.status_code in (400, 500), (error.status_code, error.get_data(as_text=True)[:600])
assert error.json["credit_message"] == "No se han consumido créditos. Tu saldo permanece intacto"
assert error.json["balance"] == {"available": 130, "reserved": 0, "frozen": False}

# After authorization and before sending any file: read state and reclaim once.
never_sent_id = authorize(owner_client, csv_bytes("NEVER-SENT"))
with app.app_context():
    never_sent = db.session.get(CreditAnalysis, never_sent_id)
    assert never_sent.status == "reserved"
    assert never_sent.execution_started_at is None
pending = owner_client.get("/api/credits/analyses/pending")
assert any(row["id"] == never_sent_id and row["status"] == "reserved"
           for row in pending.json["operations"])
recovered = owner_client.post(f"/api/credits/analyses/{never_sent_id}/recover",
                              headers={"X-Credits-CSRF": csrf(owner_client)})
assert recovered.status_code == 200 and recovered.json["status"] == "released"
assert recovered.json["balance"]["reserved"] == 0

# An interrupted multipart upload can end before its closing boundary. The
# analysis ID header lets the route acquire the operation lock before Flask
# parses that body; the user can then release the still-unstarted reservation.
upload_cut_id = authorize(owner_client, csv_bytes("UPLOAD-CUT"))
truncated_upload = (
    b'--credit-upload-cut\r\n'
    b'Content-Disposition: form-data; name="csv"; filename="partial.csv"\r\n'
    b'Content-Type: text/csv\r\n\r\n'
    b'not,a,valid,binance,export\r\n1,2025'
)
upload_cut = owner_client.post(
    "/api/binance/analizar", data=truncated_upload,
    content_type="multipart/form-data; boundary=credit-upload-cut",
    headers={"X-Credit-Analysis-ID": upload_cut_id},
)
assert upload_cut.status_code >= 400
upload_recovered = owner_client.post(
    f"/api/credits/analyses/{upload_cut_id}/recover",
    headers={"X-Credits-CSRF": csrf(owner_client)},
)
assert upload_recovered.status_code == 200
assert upload_recovered.json["status"] == "released"
assert upload_recovered.json["balance"]["reserved"] == 0

# Same operation retry is rejected by the session lock; a new authorization for
# identical files is rejected even after the original entered processing.
concurrent_raw = csv_bytes("CONCURRENT")
concurrent_id = authorize(owner_client, concurrent_raw)
real_pdf = application.generar_pdf
entered_pdf, finish_pdf = threading.Event(), threading.Event()
def paused_pdf(*args, **kwargs):
    result = real_pdf(*args, **kwargs)
    entered_pdf.set()
    if not finish_pdf.wait(30):
        raise RuntimeError("test synchronization timeout")
    return result
application.generar_pdf = paused_pdf

def run_first_attempt():
    client = app.test_client(); login(client, owner_id)
    response = submit(client, concurrent_id, concurrent_raw)
    return response.status_code, response.json

try:
    with ThreadPoolExecutor(max_workers=1) as pool:
        first_future = pool.submit(run_first_attempt)
        assert entered_pdf.wait(30), "first execution did not reach the real PDF generator"
        retry = submit(owner_client, concurrent_id, concurrent_raw)
        assert retry.status_code == 409 and retry.json["credit_state"] == "processing"
        duplicate_authorization, _ = quote_and_authorize(owner_client, concurrent_raw)
        assert duplicate_authorization.status_code == 409
        with app.app_context():
            assert CreditLedgerEntry.query.filter_by(user_id=owner_id, entry_type="reserve").count() == 5
            assert balance(owner_id)["reserved"] == 50
        finish_pdf.set()
        first_status, first_json = first_future.result(timeout=45)
        assert first_status == 200 and first_json["result_type"] == "definitive"
finally:
    finish_pdf.set()
    application.generar_pdf = real_pdf

# A child dies after receiving the request and while preflight validation is
# reading the upload, before begin_analysis commits. Its session lock disappears.
validation_id = authorize(owner_client, csv_bytes("VALIDATION-CUT"))
CHILD_VALIDATION = r'''
import io, os, sys, time
sys.path.insert(0, __CREDIT_QA_APP_ROOT__)
from app import app
import credits_routes
uid = int(os.environ["CREDIT_QA_USER_ID"])
client = app.test_client(); now = int(time.time())
with client.session_transaction() as s:
 s["_user_id"] = os.environ["CREDIT_QA_USER_IDENTITY"]; s["_fresh"] = True
 s["auth_started_at"] = now; s["auth_last_activity_at"] = now
def cut(files):
 next(f for f in files if f.filename).stream.read(1)
 os._exit(91)
credits_routes.inspect_credit_uploads = cut
client.post("/api/binance/analizar", data={
 "credit_analysis_id": os.environ["CREDIT_QA_ANALYSIS_ID"], "nombre":"Synthetic",
 "ejercicio":"2025", "alcance_datos":"solo_binance",
 "csv": (io.BytesIO(os.environ["CREDIT_QA_CSV"].encode()), "crash.csv")},
 content_type="multipart/form-data",
 headers={"X-Credit-Analysis-ID": os.environ["CREDIT_QA_ANALYSIS_ID"]})
os._exit(1)
'''

def launch_cut(program, user_id, analysis_id, raw, exit_code):
    os.environ["CREDIT_QA_USER_ID"] = str(user_id)
    os.environ["CREDIT_QA_ANALYSIS_ID"] = analysis_id
    os.environ["CREDIT_QA_CSV"] = raw.decode()
    with app.app_context():
        os.environ["CREDIT_QA_USER_IDENTITY"] = db.session.get(User, user_id).get_id()
    env = os.environ.copy()
    app_root = env["PYTHONPATH"]
    program = program.replace("__CREDIT_QA_APP_ROOT__", repr(app_root))
    if "__CREDIT_QA_APP_ROOT__" in program:
        raise AssertionError("crash-worker application root placeholder was not resolved")
    for name in ("RAILWAY_ENVIRONMENT_ID", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID",
                 "RAILWAY_SERVICE_ID", "RAILWAY_DEPLOYMENT_ID", "RAILWAY_PUBLIC_DOMAIN",
                 "RAILWAY_PRIVATE_DOMAIN", "PORT", "SERVER_SOFTWARE", "STRIPE_SECRET_KEY",
                 "STRIPE_WEBHOOK_SECRET", "RESEND_API_KEY"):
        env.pop(name, None)
    child = subprocess.run([sys.executable, "-c", program],
                           cwd=app_root, env=env, text=True,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=45)
    assert child.returncode == exit_code, (child.returncode, child.stdout[-800:])
    return child.stdout

launch_cut(CHILD_VALIDATION, owner_id, validation_id, CSV, 91)
validation_recovered = owner_client.post(
    f"/api/credits/analyses/{validation_id}/recover",
    headers={"X-Credits-CSRF": csrf(owner_client)})
assert validation_recovered.status_code == 200
assert validation_recovered.json["status"] == "released"

# Terminate after the real FIFO work and PDF construction started. The outcome
# is uncertain: retain reserved credits, record the state and freeze the wallet.
unknown_id = authorize(other_client, csv_bytes("FIFO-CRASH"))
CHILD_FIFO_CRASH = r'''
import io, os, sys, time
sys.path.insert(0, __CREDIT_QA_APP_ROOT__)
from app import app
import app as application
uid = int(os.environ["CREDIT_QA_USER_ID"])
client = app.test_client(); now = int(time.time())
with client.session_transaction() as s:
 s["_user_id"] = os.environ["CREDIT_QA_USER_IDENTITY"]; s["_fresh"] = True
 s["auth_started_at"] = now; s["auth_last_activity_at"] = now
real = application.generar_pdf
def cut(*args, **kwargs):
 result = real(*args, **kwargs)
 os._exit(92)
application.generar_pdf = cut
client.post("/api/binance/analizar", data={
 "credit_analysis_id": os.environ["CREDIT_QA_ANALYSIS_ID"], "nombre":"Synthetic",
 "ejercicio":"2025", "alcance_datos":"solo_binance",
 "csv": (io.BytesIO(os.environ["CREDIT_QA_CSV"].encode()), "crash.csv")},
 content_type="multipart/form-data",
 headers={"X-Credit-Analysis-ID": os.environ["CREDIT_QA_ANALYSIS_ID"]})
os._exit(1)
'''
launch_cut(CHILD_FIFO_CRASH, other_id, unknown_id, CSV, 92)
unknown_recovered = other_client.post(
    f"/api/credits/analyses/{unknown_id}/recover",
    headers={"X-Credits-CSRF": csrf(other_client)})
assert unknown_recovered.status_code == 409
assert unknown_recovered.json["status"] == "execution_unknown"
with app.app_context():
    assert balance(other_id) == {"available": 180, "reserved": 50, "frozen": True}
    assert CreditLedgerEntry.query.filter_by(user_id=other_id, entry_type="release").count() == 0
    assert db.session.get(CreditAnalysis, unknown_id).execution_started_at is not None

# Terminate after settlement commits but before the HTTP response. The consumed
# result must remain recoverable as a free repeat download, never another debit.
post_settlement_id = authorize(owner_client, csv_bytes("SETTLED-RESPONSE-CUT"))
CHILD_POST_SETTLEMENT = r'''
import io, os, sys, time
sys.path.insert(0, __CREDIT_QA_APP_ROOT__)
from app import app
import credits_routes
uid = int(os.environ["CREDIT_QA_USER_ID"])
client = app.test_client(); now = int(time.time())
with client.session_transaction() as s:
 s["_user_id"] = os.environ["CREDIT_QA_USER_IDENTITY"]; s["_fresh"] = True
 s["auth_started_at"] = now; s["auth_last_activity_at"] = now
real = credits_routes.settle_analysis
def settle_then_die(**kwargs):
 result = real(**kwargs)
 os._exit(93)
credits_routes.settle_analysis = settle_then_die
client.post("/api/binance/analizar", data={
 "credit_analysis_id": os.environ["CREDIT_QA_ANALYSIS_ID"], "nombre":"Synthetic",
 "ejercicio":"2025", "alcance_datos":"solo_binance",
 "csv": (io.BytesIO(os.environ["CREDIT_QA_CSV"].encode()), "settled.csv")},
 content_type="multipart/form-data",
 headers={"X-Credit-Analysis-ID": os.environ["CREDIT_QA_ANALYSIS_ID"]})
os._exit(1)
'''
launch_cut(CHILD_POST_SETTLEMENT, owner_id, post_settlement_id, CSV, 93)
with app.app_context():
    assert CreditAnalysis.query.filter_by(id=post_settlement_id, status="consumed").count() == 1
    assert CreditLedgerEntry.query.filter_by(reference_id=post_settlement_id,
                                               entry_type="settle").count() == 1
post_cut = owner_client.post(f"/api/credits/analyses/{post_settlement_id}/recover",
                             headers={"X-Credits-CSRF": csrf(owner_client)})
assert post_cut.status_code == 200 and post_cut.json["status"] == "consumed"
assert owner_client.get(post_cut.json["download_url"]).data.startswith(b"%PDF-")

with app.app_context():
    assert balance(owner_id) == {"available": 30, "reserved": 0, "frozen": False}
    assert CreditLedgerEntry.query.filter_by(user_id=owner_id, entry_type="reserve").count() == 8
    assert CreditLedgerEntry.query.filter_by(user_id=owner_id, entry_type="settle").count() == 4
    assert CreditLedgerEntry.query.filter_by(user_id=owner_id, entry_type="release").count() == 4
print("CREDITS_REAL_FLASK_FIFO_PG18: PASS synthetic-webhook definitive provisional error recovery concurrency crash-cuts downloads")
"""


def main() -> None:
    _guard()
    _database(create=True)
    try:
        print(_run_program(PROGRAM).strip())
    finally:
        _database(create=False)


if __name__ == "__main__":
    main()
