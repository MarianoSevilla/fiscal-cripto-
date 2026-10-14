"""C2-R01: actual PostgreSQL 18 row-lock races on synthetic internal S01 state.

CI-only, ephemeral DB, two spawned processes and separate physical connections.
No real customer information, provider SDK, network clients or Railway URLs.
The subject under test is the same c2_change_internal_state imported in app.py.
"""
from __future__ import annotations

from datetime import datetime
import multiprocessing as mp
import os
from pathlib import Path
import sys

import psycopg2
from psycopg2 import sql
from flask import Flask
from sqlalchemy import event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from advisory_s01_c2_management import (  # noqa: E402
    c2_can_change_state, c2_change_internal_state, C2ProtectedState,
)
from models import (  # noqa: E402
    db, User, FiscalAdvisoryRequest, FiscalAdvisoryStatusHistory,
    AdvisoryAuditLog,
)

HOST = "127.0.0.1"
PORT = 5432
PASSWORD = "ci-only-test-password"
NAME = "s01_c2_internal_ci_pg18"
DATABASE_URL = (
    f"postgresql+psycopg2://postgres:{PASSWORD}@{HOST}:{PORT}/{NAME}"
)


def _guard():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("CI") != "true"
            or os.environ.get("FLASK_ENV") != "testing"
            or HOST != "127.0.0.1" or PORT != 5432
            or NAME != "s01_c2_internal_ci_pg18"):
        raise RuntimeError("C2 PG18 is allowed only in isolated GitHub CI")


def _admin():
    _guard()
    return psycopg2.connect(
        host=HOST, port=PORT, user="postgres", password=PASSWORD,
        dbname="postgres", connect_timeout=5,
    )


def _create_db():
    con = _admin()
    try:
        con.autocommit = True
        with con.cursor() as cursor:
            cursor.execute("SELECT current_setting('server_version_num')::integer")
            ver = cursor.fetchone()[0]
            assert 180000 <= ver < 190000, f"PostgreSQL 18 required: {ver}"
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(NAME)))
    finally:
        con.close()


def _drop_db():
    con = _admin()
    try:
        con.autocommit = True
        with con.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
                           .format(sql.Identifier(NAME)))
    finally:
        con.close()


def _app():
    _guard()
    app = Flask("s01-c2-pg18-fixture")
    app.config.update(
        TESTING=True, SQLALCHEMY_DATABASE_URI=DATABASE_URL,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    return app


def _seed():
    request = FiscalAdvisoryRequest(
        full_name="Ejemplo inventado", email="c2-multiprocess@example.invalid",
        tax_residence_country="España", tax_year=2025,
        service_type="presupuesto_personalizado",
        case_description="Expediente sintético de concurrencia PG18",
        status="submitted",
    )
    db.session.add(request)
    db.session.commit()
    ident = request.id
    db.session.remove()
    return ident


def _worker(role, request_id, entered, acquired, release, hold, result):
    try:
        _guard()
        app = _app()
        with app.app_context():
            def before(conn, cursor, statement, params, context, many):
                if ("fiscal_advisory_requests" in statement.lower()
                        and "for update" in statement.lower()):
                    entered.set()

            def after(conn, cursor, statement, params, context, many):
                if ("fiscal_advisory_requests" in statement.lower()
                        and "for update" in statement.lower()):
                    acquired.set()
                    if hold and not release.wait(timeout=18):
                        raise RuntimeError("C2 PG18 release timeout")

            event.listen(db.engine, "before_cursor_execute", before)
            event.listen(db.engine, "after_cursor_execute", after)
            try:
                if role in ("commit_evidence", "rollback_evidence"):
                    item = (FiscalAdvisoryRequest.query.filter_by(id=request_id)
                            .with_for_update().first_or_404())
                    # Representative partially persisted legacy quote field.
                    item.quote_expires_at = datetime(2027, 1, 1)
                    db.session.flush()
                    if role == "commit_evidence":
                        db.session.commit()
                    else:
                        db.session.rollback()
                    result.put(("ok", role))
                elif role == "transition":
                    try:
                        status, unchanged = c2_change_internal_state(
                            request_id=request_id,
                            new_status="under_review",
                            actor_id=1,
                            note="Solo revisión ficticia",
                        )
                        result.put(("ok", role, status, unchanged))
                    except C2ProtectedState:
                        result.put(("ok", role, "protected"))
                else:
                    raise AssertionError("Invalid worker role")
            finally:
                event.remove(db.engine, "before_cursor_execute", before)
                event.remove(db.engine, "after_cursor_execute", after)
                db.session.remove()
                db.engine.dispose()
    except Exception as exc:
        result.put(("error", role, type(exc).__name__, str(exc)[:200]))


def _race(request_id, first_role, expected_transition):
    context = mp.get_context("spawn")
    first_entered, first_acquired = context.Event(), context.Event()
    second_entered, second_acquired = context.Event(), context.Event()
    release = context.Event()
    outcomes = context.Queue()
    first = context.Process(
        target=_worker,
        args=(first_role, request_id, first_entered, first_acquired,
              release, True, outcomes),
    )
    second = context.Process(
        target=_worker,
        args=("transition", request_id, second_entered, second_acquired,
              release, False, outcomes),
    )
    first.start()
    try:
        assert first_acquired.wait(timeout=14), "First PG18 row lock not acquired"
        second.start()
        assert second_entered.wait(timeout=14), "Second PG18 row lock not attempted"
        assert not second_acquired.wait(timeout=0.6), (
            "Concurrent PG18 transaction acquired locked advisory row"
        )
    finally:
        release.set()
    try:
        for worker in (first, second):
            worker.join(timeout=25)
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
                raise AssertionError("C2 PG18 process timeout")
            assert worker.exitcode == 0
        values = [outcomes.get(timeout=5), outcomes.get(timeout=5)]
        assert all(v[0] == "ok" for v in values), values
        expected = ("ok", "transition", expected_transition) if expected_transition == "protected" else (
            "ok", "transition", "under_review", False
        )
        assert expected in values, values
    finally:
        release.set()
        for worker in (first, second):
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=5)
        outcomes.close()
        outcomes.join_thread()


def main():
    _guard()
    _create_db()
    app = None
    try:
        app = _app()
        with app.app_context():
            db.create_all()
            db.session.add(User(id=1, email="c2-advisor@example.invalid",
                                full_name="Synthetic Reviewer", role="fiscal_advisor"))
            db.session.commit()
            for first_role, expected in (
                ("commit_evidence", "protected"),
                ("rollback_evidence", "under_review"),
            ):
                for _ in range(2):
                    request_id = _seed()
                    _race(request_id, first_role, expected)
                    db.session.remove()
                    item = db.session.get(FiscalAdvisoryRequest, request_id)
                    history = FiscalAdvisoryStatusHistory.query.filter_by(request_id=request_id).count()
                    audit = AdvisoryAuditLog.query.filter_by(request_id=request_id).count()
                    if first_role == "commit_evidence":
                        assert item.status == "submitted"
                        assert item.quote_expires_at == datetime(2027, 1, 1)
                        assert not c2_can_change_state(item)
                        assert history == 0 and audit == 0
                    else:
                        assert item.status == "under_review"
                        assert item.quote_expires_at is None
                        assert history == 1 and audit == 1
                    assert item.payment_link_token is None
                    assert item.paypal_order_id is None
                    assert item.stripe_checkout_session_id is None
                    assert item.quote_accepted_at is None
                    assert item.paid_at is None and item.amount_paid is None
                    db.session.remove()
            db.engine.dispose()
        print(
            "C2-R01 PG18: two-process SELECT FOR UPDATE blocking PASS; "
            "partial evidence committed then transition rejected PASS; "
            "failed evidence transaction rolled back then transition allowed PASS; "
            "zero provider/email/finance effects PASS", flush=True,
        )
    finally:
        if app is not None:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        _drop_db()


if __name__ == "__main__":
    main()
