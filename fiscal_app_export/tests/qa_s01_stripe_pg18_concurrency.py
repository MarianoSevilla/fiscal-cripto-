"""S01: carrera multiproceso real sobre PostgreSQL 18 efímero de Required CI.

Seis carreras independientes: dos procesos por pago, firmas HMAC sintéticas.
No se conecta con proveedores, RailWay, MERU ni datos de usuarios reales.
Ejecutar SOLO como paso de postgres-bootstrap de GitHub Actions.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from flask import Flask
import psycopg2
from psycopg2 import sql
from sqlalchemy import event as sqlalchemy_event

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from models import (  # noqa: E402
    db, FiscalAdvisoryRequest, FiscalAdvisoryStatusHistory,
    S01StripeCheckoutAttempt, S01StripeEventReceipt,
    S01StripeNotificationOutbox,
)

DB_NAME = "s01_concurrency_pg18_ci"
CI_USER = "postgres"
CI_PASSWORD = "ci-only-test-password"
CI_HOST = "127.0.0.1"
CI_PORT = 5432
DATABASE_URL = (
    f"postgresql+psycopg2://{CI_USER}:{CI_PASSWORD}"
    f"@{CI_HOST}:{CI_PORT}/{DB_NAME}"
)
SECRET = "whsec_s01_pg18_synthetic_only"
AMOUNT = 26000


def _guard() -> None:
    # Ningún parámetro admite sobreescribir host, puerto, usuario ni DB.
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("CI") != "true"
            or os.environ.get("FLASK_ENV") != "testing"):
        raise RuntimeError("S01 PG18 requiere CI GitHub y FLASK_ENV=testing")
    if (CI_HOST != "127.0.0.1" or CI_PORT != 5432
            or DB_NAME != "s01_concurrency_pg18_ci"):
        raise RuntimeError("Prohibida una conexión PostgreSQL no local")


def _admin_connection():
    _guard()
    return psycopg2.connect(
        host=CI_HOST, port=CI_PORT, user=CI_USER,
        password=CI_PASSWORD, dbname="postgres",
        connect_timeout=5,
    )


def _create_test_database():
    conn = _admin_connection()
    try:
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('server_version_num')::integer"
            )
            version = cursor.fetchone()[0]
            if not (180000 <= version < 190000):
                raise AssertionError("Se exige PostgreSQL 18 efímero")
            cursor.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME))
            )
    finally:
        conn.close()


def _drop_test_database():
    conn = _admin_connection()
    try:
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(DB_NAME)
                )
            )
    finally:
        conn.close()


def _app():
    _guard()
    app = Flask("s01-stripe-pg18-multiprocess")
    app.config.update(
        SQLALCHEMY_DATABASE_URI=DATABASE_URL,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)
    return app


def _seed_synthetic(status="ready"):
    # Se crea en el proceso principal y se COMMITA antes de lanzar workers.
    token = uuid4().hex + "xYz01234567"
    sid = "cs_test_" + uuid4().hex
    pi = "pi_" + uuid4().hex
    advisory = FiscalAdvisoryRequest(
        full_name="Persona ficticia de CI",
        email="pg18-s01@example.invalid",
        tax_residence_country="España",
        tax_year=2025, service_type="presupuesto_personalizado",
        case_description="Solo fixture sintética de concurrencia.",
        is_test=True, status="quote_sent",
        quoted_amount=AMOUNT, rafa_fee_cents=20000,
        commission_cents=6000, commission_rate_bps=3000,
        payment_link_token=token,
        stripe_checkout_session_id=sid,
    )
    db.session.add(advisory)
    db.session.flush()
    attempt_id = str(uuid4())
    db.session.add(S01StripeCheckoutAttempt(
        id=attempt_id, advisory_id=advisory.id,
        quote_fingerprint=hashlib.sha256(token.encode("ascii")).hexdigest(),
        idempotency_key="s01-checkout-v1-" + attempt_id,
        expected_amount_cents=AMOUNT, currency="eur",
        status=status, checkout_session_id=sid,
    ))
    db.session.commit()
    return {
        "advisory_id": advisory.id, "attempt_id": attempt_id,
        "token": token, "sid": sid, "pi": pi,
    }


def _signed(fixture, event_id, *, pi=None, amount=AMOUNT):
    obj = {
        "id": fixture["sid"], "livemode": False, "mode": "payment",
        "status": "complete", "payment_status": "paid",
        "amount_total": amount, "currency": "eur",
        "client_reference_id": str(fixture["advisory_id"]),
        "payment_intent": pi or fixture["pi"],
        "metadata": {
            "s01_attempt_id": fixture["attempt_id"],
            "s01_advisory_id": str(fixture["advisory_id"]),
            "s01_quote_sha256": hashlib.sha256(
                fixture["token"].encode("ascii")
            ).hexdigest(),
        },
    }
    doc = {
        "id": event_id, "object": "event", "livemode": False,
        "type": "checkout.session.completed", "data": {"object": obj},
    }
    payload = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    stamp = str(int(time.time()))
    digest = hmac.new(
        SECRET.encode("utf-8"), stamp.encode("utf-8") + b"." + payload,
        hashlib.sha256,
    ).hexdigest()
    return {
        "payload": payload, "signature": f"t={stamp},v1={digest}",
        "webhook_secret": SECRET,
    }


def _worker(barrier, result_queue, signed_event):
    """Cada proceso abre su propia app y conexión SQL real, sin fork de pool."""
    try:
        _guard()
        from advisory_s01_stripe_test_events import (
            S01EventRejected, process_signed_s01_test_webhook,
        )
        app = _app()
        with app.app_context():
            if db.engine.url.host != CI_HOST or db.engine.url.database != DB_NAME:
                raise AssertionError("Motor SQL fuera del contenedor local")

            def hold_first_lock(conn, cursor, statement, parameters, context, many):
                statement_low = statement.lower()
                if ("fiscal_advisory_requests" in statement_low
                        and "for update" in statement_low):
                    # Aumenta el solapamiento mientras se mantiene el lock
                    # real de PostgreSQL; no altera la transacción de la app.
                    time.sleep(0.3)

            sqlalchemy_event.listen(
                db.engine, "after_cursor_execute", hold_first_lock
            )
            barrier.wait(timeout=15)
            try:
                outcome = process_signed_s01_test_webhook(**signed_event)
                result_queue.put(("ok", outcome))
            except S01EventRejected:
                result_queue.put(("rejected", ""))
            finally:
                sqlalchemy_event.remove(
                    db.engine, "after_cursor_execute", hold_first_lock
                )
                db.session.remove()
                db.engine.dispose()
    except Exception as exc:
        result_queue.put(("error", type(exc).__name__ + ": " + str(exc)[:200]))


def _run_pair(signed_one, signed_two):
    ctx = mp.get_context("spawn")  # fuerza conexiones nuevas por proceso
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    procs = [
        ctx.Process(target=_worker, args=(barrier, results, event))
        for event in (signed_one, signed_two)
    ]
    for proc in procs:
        proc.start()
    try:
        for proc in procs:
            proc.join(timeout=25)
        for proc in procs:
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)
                raise AssertionError("Deadlock o timeout en webhook concurrente")
            if proc.exitcode != 0:
                raise AssertionError("Subproceso financiero salió con error")
        observed = [results.get(timeout=3) for _ in procs]
        if any(item[0] == "error" for item in observed):
            raise AssertionError(f"Fallo de worker PG18: {observed!r}")
        return sorted(observed)
    finally:
        for proc in procs:
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=5)
        results.close()
        results.join_thread()


def _verify(fixture, *, receipts: int, status: str, allowed_pi=None):
    db.session.remove()  # evita identity-map caché tras commits de otros procesos
    advisory = db.session.get(FiscalAdvisoryRequest, fixture["advisory_id"])
    attempt = db.session.get(S01StripeCheckoutAttempt, fixture["attempt_id"])
    assert advisory is not None and attempt is not None
    assert advisory.status == status
    assert attempt.status == ("paid" if status == "paid_received" else "uncertain")
    assert (
        db.session.query(S01StripeEventReceipt)
        .filter_by(attempt_id=attempt.id).count()
    ) == receipts
    assert (
        db.session.query(FiscalAdvisoryStatusHistory)
        .filter_by(request_id=advisory.id, status="paid_received").count()
    ) == (1 if status == "paid_received" else 0)
    rows = db.session.query(S01StripeNotificationOutbox).filter_by(
        attempt_id=attempt.id,
    ).all()
    assert len(rows) == (2 if status == "paid_received" else 0)
    assert len({row.kind for row in rows}) == len(rows)
    assert all(row.status == "pending" and row.sent_at is None for row in rows)
    if status == "paid_received":
        expected = allowed_pi if allowed_pi is not None else {fixture["pi"]}
        assert advisory.payment_provider == "stripe"
        assert advisory.amount_paid == AMOUNT
        assert advisory.currency == "eur"
        assert advisory.paid_at is not None
        assert advisory.stripe_payment_intent_id in expected
        assert attempt.payment_intent_id == advisory.stripe_payment_intent_id
    else:
        assert advisory.amount_paid is None
        assert advisory.payment_provider is None
        assert advisory.paid_at is None
        assert attempt.payment_intent_id is None
    db.session.remove()


def _rollback_probe():
    from advisory_s01_stripe_test_events import (
        S01EventStorageError, process_signed_s01_test_webhook,
    )
    item = _seed_synthetic()
    signed = _signed(item, "evt_" + uuid4().hex)

    def block_history_insert(conn, cursor, statement, params, context, many):
        if ("insert into fiscal_advisory_status_history"
                in statement.lower()):
            raise RuntimeError("CI synthetic INSERT failure")

    sqlalchemy_event.listen(
        db.engine, "before_cursor_execute", block_history_insert
    )
    try:
        try:
            process_signed_s01_test_webhook(**signed)
            raise AssertionError("Un error SQL debería abortar el cobro")
        except S01EventStorageError:
            pass
    finally:
        sqlalchemy_event.remove(
            db.engine, "before_cursor_execute", block_history_insert
        )
    db.session.remove()
    advisory = db.session.get(FiscalAdvisoryRequest, item["advisory_id"])
    assert advisory.status == "quote_sent" and advisory.amount_paid is None
    attempt = db.session.get(S01StripeCheckoutAttempt, item["attempt_id"])
    assert attempt.status == "ready"
    assert db.session.query(S01StripeEventReceipt).filter_by(
        attempt_id=attempt.id
    ).count() == 0
    assert db.session.query(FiscalAdvisoryStatusHistory).filter_by(
        request_id=advisory.id, status="paid_received"
    ).count() == 0
    assert db.session.query(S01StripeNotificationOutbox).filter_by(
        attempt_id=attempt.id
    ).count() == 0
    db.session.remove()
    assert process_signed_s01_test_webhook(**signed) == "paid"
    _verify(item, receipts=1, status="paid_received")


def main():
    _guard()
    _create_test_database()
    app = None
    try:
        app = _app()
        with app.app_context():
            assert db.engine.dialect.name == "postgresql"
            db.create_all()
            db.session.remove()

            # Repetición de carreras, cada vez con fixture distinta.
            for repetition in range(2):
                first = _seed_synthetic()
                e = _signed(first, "evt_" + uuid4().hex)
                result = _run_pair(e, e)
                assert result == [("ok", "duplicate"), ("ok", "paid")], (
                    "Dos confirmaciones simultáneas no fueron idempotentes",
                    repetition, result,
                )
                _verify(first, receipts=1, status="paid_received")

                second = _seed_synthetic()
                a = _signed(second, "evt_" + uuid4().hex)
                b = _signed(second, "evt_" + uuid4().hex)
                result = _run_pair(a, b)
                assert result == [("ok", "already_paid"), ("ok", "paid")], (
                    "Dos IDs de evento para el mismo pago duplicaron la historia",
                    repetition, result,
                )
                _verify(second, receipts=2, status="paid_received")

                third = _seed_synthetic()
                competing_pi = "pi_" + uuid4().hex
                a = _signed(third, "evt_" + uuid4().hex)
                b = _signed(third, "evt_" + uuid4().hex, pi=competing_pi)
                result = _run_pair(a, b)
                assert result == [("ok", "paid"), ("rejected", "")], (
                    "Dos PaymentIntents distintos se aceptaron para un expediente",
                    repetition, result,
                )
                _verify(
                    third, receipts=1, status="paid_received",
                    allowed_pi={third["pi"], competing_pi},
                )

            uncertain = _seed_synthetic(status="uncertain")
            e = _signed(uncertain, "evt_" + uuid4().hex)
            assert _run_pair(e, e) == [
                ("rejected", ""), ("rejected", "")
            ]
            _verify(uncertain, receipts=0, status="quote_sent")
            _rollback_probe()

            db.session.remove()
            db.engine.dispose()
        print(
            "S01 PG18: same-event race PASS; different-event same-PI PASS; "
            "conflicting PaymentIntents PASS; uncertain-state blocking PASS; "
            "transaction rollback and retry PASS (synthetic-only)",
            flush=True,
        )
    finally:
        if app is not None:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        _drop_test_database()


if __name__ == "__main__":
    main()
