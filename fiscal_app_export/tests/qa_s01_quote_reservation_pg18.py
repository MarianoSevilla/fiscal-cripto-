"""S01 AUD-001: PG18 real quote reissue vs Checkout reservation contention.

Exclusive GitHub CI test. Two independent spawned processes use separate SQL
connections and the actual undecorated quote handler / real S01 _reserve.
No provider calls, real emails, external services, customer data or deploy.
PREFREEZE is never disabled in any public application route.
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime, timedelta
import multiprocessing as mp
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

from flask import Flask, jsonify, request
import psycopg2
from psycopg2 import sql
from sqlalchemy import event as sqlalchemy_event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from advisory_s01_checkout import S01CheckoutBlocked  # noqa: E402
from advisory_s01_pricing import (  # noqa: E402
    calculate_s01_quote, QuotePricingError, COMMISSION_RATE_BPS,
)
from advisory_s01_test_orchestrator import _reserve  # noqa: E402
from models import (  # noqa: E402
    db, User, FiscalAdvisoryRequest, FiscalAdvisoryStatusHistory,
    AdvisoryAuditLog, S01StripeCheckoutAttempt,
)

HOST = "127.0.0.1"
PORT = 5432
USER = "postgres"
PASSWORD = "ci-only-test-password"
NAME = "s01_quote_reservation_pg18_ci"
URI = f"postgresql+psycopg2://{USER}:{PASSWORD}@{HOST}:{PORT}/{NAME}"
ROUTE = "/__ci_synthetic__/advisory/<int:req_id>/quote"
BASE_URL = "https://checkout-s01.example.invalid"
ORIGINAL_AMOUNT = 26000
UPDATED_AMOUNT = 29900


def _guard():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("CI") != "true"
            or os.environ.get("FLASK_ENV") != "testing"):
        raise RuntimeError("Solo GitHub Actions en modo testing")
    if (HOST, PORT, NAME) != ("127.0.0.1", 5432, "s01_quote_reservation_pg18_ci"):
        raise RuntimeError("Destino PG fuera de la base aislada permitida")


def _admin():
    _guard()
    return psycopg2.connect(
        host=HOST, port=PORT, user=USER, password=PASSWORD,
        dbname="postgres", connect_timeout=5,
    )


def _db_create():
    conn = _admin()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version_num')::integer")
            version = cur.fetchone()[0]
            assert 180000 <= version < 190000, f"Se exige PostgreSQL 18: {version}"
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(NAME)))
    finally:
        conn.close()


def _db_drop():
    conn = _admin()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
                .format(sql.Identifier(NAME))
            )
    finally:
        conn.close()


def _app():
    _guard()
    app = Flask("s01-aud001-pg18-quote-reservation")
    app.config.update(
        TESTING=True, SQLALCHEMY_DATABASE_URI=URI,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    return app


def _install_real_quote_handler(app, mail_calls):
    """Execute the actual handler AST; remove decorators only inside CI."""
    source = ROOT / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    fn = copy.deepcopy(next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "advisory_enviar_presupuesto"
    ))
    assert any("advisory_financial_prefreeze" in ast.unparse(d)
               for d in fn.decorator_list), "Producción debe seguir PREFREEZE"
    fn.decorator_list = []
    ast.fix_missing_locations(fn)

    def fake_mail(_advisory, _url):
        mail_calls.append("synthetic-mail-not-sent")
        return True

    namespace = {
        "db": db,
        "request": request,
        "jsonify": jsonify,
        "FiscalAdvisoryRequest": FiscalAdvisoryRequest,
        "FiscalAdvisoryStatusHistory": FiscalAdvisoryStatusHistory,
        "AdvisoryAuditLog": AdvisoryAuditLog,
        "S01StripeCheckoutAttempt": S01StripeCheckoutAttempt,
        "calculate_s01_quote": calculate_s01_quote,
        "QuotePricingError": QuotePricingError,
        "COMMISSION_RATE_BPS": COMMISSION_RATE_BPS,
        "current_user": SimpleNamespace(id=1),
        "datetime": datetime,
        "_APP_BASE_URL": "https://ci.example.invalid",
        "_send_advisory_quote_email": fake_mail,
    }
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), "exec"),
         namespace)
    app.add_url_rule(
        ROUTE, view_func=namespace["advisory_enviar_presupuesto"],
        methods=["POST"],
    )


def _seed():
    token = uuid4().hex + "ABCD1234567"
    item = FiscalAdvisoryRequest(
        full_name="Persona ficticia",
        email="s01-pg18-quote@example.invalid",
        tax_residence_country="España",
        tax_year=2025,
        service_type="presupuesto_personalizado",
        case_description="Expediente inventado de CI",
        status="quote_sent", is_test=True,
        quoted_amount=ORIGINAL_AMOUNT,
        rafa_fee_cents=20000, commission_cents=6000,
        commission_rate_bps=3000,
        payment_link_token=token,
        quote_expires_at=datetime.utcnow() + timedelta(days=5),
    )
    db.session.add(item)
    db.session.commit()
    advisory_id = item.id
    db.session.remove()
    return advisory_id, token


def _worker(role, advisory_id, token, holding,
            entered, acquired, release, output):
    """Each spawned process has a fresh engine, Flask app and PG connection."""
    try:
        _guard()
        app = _app()
        mail_calls = []
        with app.app_context():
            assert db.engine.url.host == HOST and db.engine.url.database == NAME
            if role == "quote":
                _install_real_quote_handler(app, mail_calls)

            def before_sql(conn, cursor, statement, params, context, many):
                query = statement.lower()
                if ("fiscal_advisory_requests" in query
                        and "for update" in query):
                    entered.set()

            def after_sql(conn, cursor, statement, params, context, many):
                query = statement.lower()
                if ("fiscal_advisory_requests" in query
                        and "for update" in query):
                    acquired.set()
                    if holding and not release.wait(timeout=16):
                        raise RuntimeError("Lock de PostgreSQL no liberado")

            sqlalchemy_event.listen(db.engine, "before_cursor_execute", before_sql)
            sqlalchemy_event.listen(db.engine, "after_cursor_execute", after_sql)
            try:
                if role == "quote":
                    response = app.test_client().post(
                        ROUTE.replace("<int:req_id>", str(advisory_id)),
                        json={"amount_euros": 230, "message": "Actualización CI"},
                    )
                    result = ("quote", response.status_code,
                              len(mail_calls))
                else:
                    try:
                        reservation, _params = _reserve(
                            advisory_id=advisory_id, token=token,
                            now_ts=int(time.time()), base_url=BASE_URL,
                        )
                        result = ("reserved", reservation.attempt_id)
                    except S01CheckoutBlocked:
                        result = ("blocked",)
                output.put(("ok", result))
            finally:
                sqlalchemy_event.remove(db.engine, "before_cursor_execute", before_sql)
                sqlalchemy_event.remove(db.engine, "after_cursor_execute", after_sql)
                db.session.remove()
                db.engine.dispose()
    except Exception as exc:
        output.put(("error", role, type(exc).__name__, str(exc)[:220]))


def _race(first_role, advisory_id, token):
    ctx = mp.get_context("spawn")
    acquired_first = ctx.Event()
    entered_first = ctx.Event()
    entered_second = ctx.Event()
    acquired_second = ctx.Event()
    release = ctx.Event()
    result_queue = ctx.Queue()
    first = ctx.Process(
        target=_worker,
        args=(first_role, advisory_id, token, True, entered_first,
              acquired_first, release, result_queue),
    )
    second_role = "reserve" if first_role == "quote" else "quote"
    second = ctx.Process(
        target=_worker,
        args=(second_role, advisory_id, token, False, entered_second,
              acquired_second, release, result_queue),
    )
    first.start()
    try:
        assert acquired_first.wait(timeout=14), "El primer proceso no obtuvo SELECT FOR UPDATE"
        second.start()
        assert entered_second.wait(timeout=14), "El segundo proceso no intentó bloquear la misma fila"
        # El segundo proceso está en el SELECT FOR UPDATE de PostgreSQL.
        # No puede adquirirlo mientras el primero mantenga su transacción.
        assert not acquired_second.wait(timeout=0.5), (
            "Se adquirió la misma fila durante el lock del otro proceso"
        )
    finally:
        release.set()
    try:
        for proc in (first, second):
            if proc.pid is None:
                continue
            proc.join(timeout=25)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5)
                raise AssertionError("Deadlock/timeout PG18 durante carrera")
            assert proc.exitcode == 0, ("Worker terminó con error", proc.exitcode)
        outcomes = [result_queue.get(timeout=5) for _ in (first, second)]
        assert all(item[0] == "ok" for item in outcomes), outcomes
        return [item[1] for item in outcomes]
    finally:
        release.set()
        for proc in (first, second):
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=5)
        result_queue.close()
        result_queue.join_thread()


def _verify(advisory_id, token, first_role, outcomes):
    db.session.remove()
    advisory = db.session.get(FiscalAdvisoryRequest, advisory_id)
    attempts = S01StripeCheckoutAttempt.query.filter_by(advisory_id=advisory_id).all()
    history = FiscalAdvisoryStatusHistory.query.filter_by(request_id=advisory_id).count()
    audit = AdvisoryAuditLog.query.filter_by(request_id=advisory_id).count()
    assert advisory is not None
    assert advisory.paypal_order_id is None and advisory.paypal_capture_id is None
    assert advisory.stripe_checkout_session_id is None
    assert advisory.stripe_payment_intent_id is None
    assert advisory.payment_provider is None and advisory.amount_paid is None
    assert advisory.paid_at is None
    if first_role == "quote":
        assert sorted(x[0] for x in outcomes) == ["blocked", "quote"], outcomes
        assert ("quote", 200, 1) in outcomes, outcomes
        assert advisory.payment_link_token != token
        assert advisory.quoted_amount == UPDATED_AMOUNT
        assert (advisory.rafa_fee_cents, advisory.commission_cents) == (23000, 6900)
        assert not attempts and history == 1 and audit == 1
    else:
        assert sorted(x[0] for x in outcomes) == ["quote", "reserved"], outcomes
        assert ("quote", 409, 0) in outcomes, outcomes
        assert advisory.payment_link_token == token
        assert advisory.quoted_amount == ORIGINAL_AMOUNT
        assert (advisory.rafa_fee_cents, advisory.commission_cents) == (20000, 6000)
        assert len(attempts) == 1 and attempts[0].status == "creating"
        assert attempts[0].expected_amount_cents == ORIGINAL_AMOUNT
        assert history == 0 and audit == 0
    db.session.remove()


def main():
    _guard()
    _db_create()
    app = None
    try:
        app = _app()
        with app.app_context():
            db.create_all()
            db.session.add(User(
                id=1, email="fictitious-advisor@example.invalid",
                full_name="Asesor inventado", role="fiscal_advisor",
            ))
            db.session.commit()
            for first_role in ("quote", "reserve"):
                for _ in range(2):
                    advisory_id, token = _seed()
                    observed = _race(first_role, advisory_id, token)
                    _verify(advisory_id, token, first_role, observed)
            db.session.remove()
            db.engine.dispose()
        print(
            "S01 AUD-001 PG18: quote-first old-token Checkout blocked PASS; "
            "reserve-first quote 409 PASS; committed attempt/evidence PASS; "
            "two-process row locking and synthetic mail PASS",
            flush=True,
        )
    finally:
        if app is not None:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        _db_drop()


if __name__ == "__main__":
    main()
