"""S01 Stripe TEST: concurrencia real de DOS procesos independientes en PG18.

Solo GitHub Actions, contenedor Postgres local. DSN/DBNAME hardcoded.
Sin Stripe API, correos, facturas, Railway, ni datos de producción.
Comprueba que el bloqueo SELECT FOR UPDATE se ve como 'Lock' en pg_stat_activity
antes de liberar los dos workers simultáneos, y que hay 1 sola confirmación.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sys
import time
from uuid import uuid4

from flask import Flask
import psycopg2
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from advisory_s01_stripe_test_events import (  # noqa: E402
    S01EventRejected, S01EventStorageError, process_signed_s01_test_webhook,
)
from models import (  # noqa: E402
    db, FiscalAdvisoryRequest, FiscalAdvisoryStatusHistory,
    S01StripeCheckoutAttempt, S01StripeEventReceipt,
)

DB_NAME = "s01_pg18_multiprocess_ci"
PG = {
    "host": "127.0.0.1", "port": 5432, "user": "postgres",
    "password": "ci-only-test-password",
}
SECRET = "whsec_s01_pg18_synthetic_secret"

def _guard():
    # Evita incluso ejecutar accidentalmente el runner desde un portátil o Railway.
    assert os.environ.get("GITHUB_ACTIONS") == "true", "GitHub Actions only"
    assert os.environ.get("CI") == "true", "CI only"
    assert os.environ.get("FLASK_ENV") == "testing", "TEST environment only"
    assert DB_NAME == "s01_pg18_multiprocess_ci" and PG["host"] == "127.0.0.1"


def _dsn(application_name: str) -> str:
    assert application_name.isascii() and application_name.replace("_", "").isalnum()
    return (
        "postgresql+psycopg2://postgres:ci-only-test-password@"
        f"127.0.0.1:5432/{DB_NAME}?application_name={application_name}"
    )


def _flask(name: str) -> Flask:
    app = Flask("s01_pg18_" + name)
    app.config.update(
        SQLALCHEMY_DATABASE_URI=_dsn(name),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    )
    db.init_app(app)
    return app


def _signed(advisory_id: int, attempt_id: str, scenario: str, *,
            event_suffix: str = "one", pi_override: str | None = None,
            amount_override: int | None = None) -> dict:
    token = ("A" * 36) + (str(advisory_id).zfill(7))
    sid = f"cs_test_pg18_{scenario}"
    pi = pi_override or f"pi_pg18_{scenario}"
    obj = {
        "id": sid, "livemode": False, "mode": "payment", "status": "complete",
        "payment_status": "paid",
        "amount_total": 26000 if amount_override is None else amount_override,
        "currency": "eur", "client_reference_id": str(advisory_id),
        "payment_intent": pi,
        "metadata": {
            "s01_attempt_id": attempt_id,
            "s01_advisory_id": str(advisory_id),
            "s01_quote_sha256": hashlib.sha256(token.encode()).hexdigest(),
        },
    }
    payload = json.dumps({
        "id": f"evt_pg18_{scenario}_{event_suffix}",
        "type": "checkout.session.completed",
        "livemode": False, "data": {"object": obj},
    }, separators=(",", ":")).encode()
    stamp = int(time.time())
    mac = hmac.new(SECRET.encode(), str(stamp).encode() + b"." + payload,
                   hashlib.sha256).hexdigest()
    return {
        "payload": payload, "signature": f"t={stamp},v1={mac}",
        "webhook_secret": SECRET,
    }


def _seed(app: Flask, scenario: str, *, pinned_pi: bool = False) -> tuple[int, str]:
    with app.app_context():
        a = FiscalAdvisoryRequest(
            full_name="Expediente sintético",
            email="pg18-synthetic@example.invalid",
            tax_residence_country="España", tax_year=2025,
            service_type="presupuesto_personalizado",
            case_description="Caso ficticio para test de concurrencia",
            status="quote_sent", is_test=True,
            payment_link_token=("A" * 36) + str(
                # ID se completa tras flush. Ver actualización posterior.
                "not-used"
            ),
            quoted_amount=26000, rafa_fee_cents=20000,
            commission_cents=6000, commission_rate_bps=3000,
            stripe_checkout_session_id=f"cs_test_pg18_{scenario}",
        )
        db.session.add(a)
        db.session.flush()
        token = "A" * 36 + str(a.id).zfill(7)
        a.payment_link_token = token
        aid = str(uuid4())
        db.session.add(S01StripeCheckoutAttempt(
            id=aid, advisory_id=a.id,
            quote_fingerprint=hashlib.sha256(token.encode()).hexdigest(),
            idempotency_key="s01-checkout-v1-" + aid,
            expected_amount_cents=26000,
            currency="eur", status="ready",
            checkout_session_id=f"cs_test_pg18_{scenario}",
            payment_intent_id=(f"pi_pg18_{scenario}" if pinned_pi else None),
        ))
        db.session.commit()
        val = (a.id, aid)
        db.session.remove()
        return val


def _worker(slot: int, scenario: str, event: dict, started, go, done) -> None:
    os.environ["FLASK_ENV"] = "testing"
    name = f"s01_pg18_worker_{slot}_{scenario}"
    try:
        app = _flask(name)
        with app.app_context():
            # Anuncia READY después de abrir la conexión real, nunca antes.
            db.session.connection()
            started.put((slot, "ready"))
            if not go.wait(timeout=35):
                raise RuntimeError("Worker did not receive start signal")
            try:
                outcome = process_signed_s01_test_webhook(**event)
                done.put((slot, "ok", outcome))
            except (S01EventRejected, S01EventStorageError) as exc:
                done.put((slot, "blocked", type(exc).__name__))
            finally:
                db.session.remove()
    except BaseException as exc:
        done.put((slot, "ERROR", f"{type(exc).__name__}: {exc}"))


def _inspect(app: Flask, advisory_id: int, attempt_id: str) -> dict:
    with app.app_context():
        db.session.expire_all()
        advisory = db.session.get(FiscalAdvisoryRequest, advisory_id)
        attempt = db.session.get(S01StripeCheckoutAttempt, attempt_id)
        result = dict(
            advisory=advisory.status,
            paid=advisory.amount_paid,
            provider=advisory.payment_provider,
            advisory_pi=advisory.stripe_payment_intent_id,
            attempt=attempt.status,
            attempt_pi=attempt.payment_intent_id,
            history=FiscalAdvisoryStatusHistory.query.filter_by(
                request_id=advisory_id, status="paid_received"
            ).count(),
            event_count=S01StripeEventReceipt.query.filter_by(
                attempt_id=attempt_id
            ).count(),
        )
        db.session.remove()
        return result


def _lock_waiters(scenario: str) -> int:
    conn = psycopg2.connect(dbname=DB_NAME, **PG)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM pg_stat_activity
                WHERE datname = %s
                  AND application_name IN (%s, %s)
                  AND wait_event_type = 'Lock'
            """, (DB_NAME, f"s01_pg18_worker_0_{scenario}",
                   f"s01_pg18_worker_1_{scenario}"))
            return cursor.fetchone()[0]
    finally:
        conn.close()


def _race(app: Flask, scenario: str, advisory_id: int,
          attempt_id: str, left: dict, right: dict) -> list[tuple]:
    ctx = mp.get_context("spawn")  # evita heredar sesiones DB tras fork
    started, done, go = ctx.Queue(), ctx.Queue(), ctx.Event()
    lock_conn = psycopg2.connect(dbname=DB_NAME, **PG)
    procs = []
    try:
        lock_conn.autocommit = False
        with lock_conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM fiscal_advisory_requests WHERE id=%s FOR UPDATE",
                (advisory_id,),
            )
            assert cur.fetchone() == (advisory_id,)
        for slot, payload in enumerate([left, right]):
            proc = ctx.Process(
                target=_worker,
                args=(slot, scenario, payload, started, go, done),
            )
            proc.start()
            procs.append(proc)
        ready = [started.get(timeout=25) for _ in range(2)]
        assert {x[0] for x in ready} == {0, 1}
        assert all(x[1] == "ready" for x in ready), ready
        go.set()
        deadline = time.monotonic() + 18
        while _lock_waiters(scenario) < 2 and time.monotonic() < deadline:
            time.sleep(0.075)
        assert _lock_waiters(scenario) == 2, (
            f"Two independent PG backend row-lock waiters not observed: {scenario}"
        )
        # Demostrado el bloqueo real en PG18: ahora compiten en el COMMIT.
        lock_conn.commit()
        results = [done.get(timeout=30) for _ in range(2)]
        results.sort()
        for proc in procs:
            proc.join(timeout=10)
            assert proc.exitcode == 0, f"Worker {proc.pid}: {proc.exitcode}"
        assert all(r[1] != "ERROR" for r in results), results
        return results
    finally:
        go.set()
        lock_conn.rollback()
        lock_conn.close()
        for proc in procs:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)


def _expect_paid(app: Flask, advisory_id: int, attempt_id: str,
                 scenario: str, *, receipts: int) -> None:
    state = _inspect(app, advisory_id, attempt_id)
    assert state == {
        "advisory": "paid_received",
        "paid": 26000, "provider": "stripe",
        "advisory_pi": f"pi_pg18_{scenario}",
        "attempt": "paid",
        "attempt_pi": f"pi_pg18_{scenario}",
        "history": 1, "event_count": receipts,
    }, state


def _scenario_races(app: Flask) -> None:
    scenario = "same"
    req, attempt = _seed(app, scenario)
    payload = _signed(req, attempt, scenario)
    results = _race(app, scenario, req, attempt, payload, payload)
    assert sorted(r[2] for r in results) == ["duplicate", "paid"], results
    _expect_paid(app, req, attempt, scenario, receipts=1)
    print("PG18 SAME signed event ×2 concurrent processes: 1 paid + 1 duplicate")

    scenario = "distinct"
    req, attempt = _seed(app, scenario)
    results = _race(app, scenario, req, attempt,
                    _signed(req, attempt, scenario, event_suffix="one"),
                    _signed(req, attempt, scenario, event_suffix="two"))
    assert sorted(r[2] for r in results) == ["already_paid", "paid"], results
    _expect_paid(app, req, attempt, scenario, receipts=2)
    print("PG18 DIFFERENT signed event IDs for same PI: 1 paid + 1 already_paid")

    scenario = "amount"
    req, attempt = _seed(app, scenario)
    results = _race(app, scenario, req, attempt,
                    _signed(req, attempt, scenario),
                    _signed(req, attempt, scenario, event_suffix="bad",
                            amount_override=27000))
    assert sorted(r[1] for r in results) == ["blocked", "ok"], results
    _expect_paid(app, req, attempt, scenario, receipts=1)
    print("PG18 malicious/incorrect amount during race: blocked, 1 paid")

    scenario = "intent"
    req, attempt = _seed(app, scenario, pinned_pi=True)
    results = _race(app, scenario, req, attempt,
                    _signed(req, attempt, scenario),
                    _signed(req, attempt, scenario, event_suffix="other",
                            pi_override="pi_synthetic_conflicting"))
    assert sorted(r[1] for r in results) == ["blocked", "ok"], results
    _expect_paid(app, req, attempt, scenario, receipts=1)
    print("PG18 conflicting pre-pinned PaymentIntent: rejected, 1 paid")


def _rollback_and_retry(app: Flask) -> None:
    scenario = "rollback"
    req, attempt = _seed(app, scenario)
    evt = _signed(req, attempt, scenario)
    c = psycopg2.connect(dbname=DB_NAME, **PG)
    c.autocommit = True
    try:
        with c.cursor() as cur:
            cur.execute("""
                CREATE FUNCTION s01_ci_refuse_history() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'synthetic forced rollback';
                END; $$;
            """)
            cur.execute("""
                CREATE TRIGGER s01_ci_refuse_history_trigger
                BEFORE INSERT ON fiscal_advisory_status_history
                FOR EACH ROW EXECUTE FUNCTION s01_ci_refuse_history()
            """)
        with app.app_context():
            try:
                process_signed_s01_test_webhook(**evt)
            except S01EventStorageError:
                pass
            else:
                raise AssertionError("A forced PG18 failure was ACKed")
            db.session.remove()
        state = _inspect(app, req, attempt)
        assert (state["advisory"], state["attempt"], state["history"],
                state["event_count"]) == ("quote_sent", "ready", 0, 0), state
    finally:
        with c.cursor() as cur:
            cur.execute("DROP TRIGGER IF EXISTS s01_ci_refuse_history_trigger ON fiscal_advisory_status_history")
            cur.execute("DROP FUNCTION IF EXISTS s01_ci_refuse_history()")
        c.close()
    with app.app_context():
        assert process_signed_s01_test_webhook(**evt) == "paid"
        db.session.remove()
    _expect_paid(app, req, attempt, scenario, receipts=1)
    print("PG18 forced history INSERT failure: atomic rollback + safe replay")


def main() -> None:
    _guard()
    admin = psycopg2.connect(dbname="postgres", **PG)
    admin.autocommit = True
    created = False
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
            created = True
        app = _flask("s01_pg18_coordinator")
        with app.app_context():
            db.create_all()  # solely in fresh transient DB, no Alembic migration
            db.session.remove()
        _scenario_races(app)
        _rollback_and_retry(app)
        print("S01_PG18_MULTIPROCESS_PASS: 4 races + 1 forced rollback/replay")
    finally:
        if created:
            with admin.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(DB_NAME)))
        admin.close()


if __name__ == "__main__":
    main()
