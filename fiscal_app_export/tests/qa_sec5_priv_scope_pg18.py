"""SEC5-PRIV: count-only ORM scope check in disposable PostgreSQL 18 CI.

This is NOT a retention decision, legal block or erasure procedure. Never use
against real users or databases; create/drop only a dedicated CI database.
"""
import os
import sys
from pathlib import Path

import psycopg2
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS))

from models import (
    db, User, FifoReport, ProcessingError, Contacto, FiscalAdvisoryRequest,
    S01StripeCheckoutAttempt, S01StripeEventReceipt,
    S01StripeNotificationOutbox, AdvisoryAuditLog,
)
from privacy_scope_probe import (
    MODELS, SUBJECT_FIELDS, ACTOR_FIELDS, EMAIL_CANDIDATES,
    inventory_verified_user_synthetic, inventory_deactivated_user_synthetic,
)

HOST = "127.0.0.1"
DB = "sec5_priv_scope_ci"
CI_PASSWORD = "ci-only-test-password"
POSTGRES_URL = (
    "postgresql+psycopg2://postgres:ci-only-test-password"
    "@127.0.0.1:5432/sec5_priv_scope_ci"
)


def _connect_admin():
    return psycopg2.connect(
        host=HOST, port=5432, dbname="postgres", user="postgres",
        password=CI_PASSWORD, connect_timeout=5,
        options="-c statement_timeout=5000",
    )


def _guard():
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("FLASK_ENV") != "testing"
        or os.environ.get("SEC5_PRIV_SCOPE_PG18_ONLY") != "1"
    ):
        raise RuntimeError("SEC5-PRIV PG18 scope: CI-only gate closed")
    with _connect_admin() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT current_database(), current_user, "
            "current_setting('server_version_num')::int"
        )
        name, role, version = cur.fetchone()
        if (name, role, version // 10000) != ("postgres", "postgres", 18):
            raise RuntimeError("SEC5-PRIV PG18 scope: wrong CI database")


def _seed(session):
    a = User(email="subject_a@example.invalid", role="user", is_active=True)
    b = User(email="subject_b@example.invalid", role="user", is_active=True)
    session.add_all((a, b))
    session.flush()
    session.add_all((
        FifoReport(user_id=a.id, exchange="binance", fiscal_year=2025),
        FifoReport(user_id=b.id, exchange="bitvavo", fiscal_year=2025),
        ProcessingError(user_id=a.id, email=a.email, exchange="binance"),
        ProcessingError(user_id=None, email=a.email, exchange="kraken"),
        Contacto(nombre="Fictitious", email=a.email,
                 tipo_consulta="otros", mensaje="test only"),
    ))
    case_a = FiscalAdvisoryRequest(
        user_id=a.id, full_name="Synthetic A", email=a.email,
        tax_residence_country="ES", tax_year=2025,
        service_type="revision_basica", case_description="Synthetic A",
    )
    # Identical copied email is NOT identity or financial ownership.
    case_b = FiscalAdvisoryRequest(
        user_id=b.id, full_name="Synthetic B", email=a.email,
        quoted_by_user_id=a.id,
        tax_residence_country="ES", tax_year=2025,
        service_type="revision_basica", case_description="Synthetic B",
    )
    session.add_all((case_a, case_b))
    session.flush()
    attempt_a = S01StripeCheckoutAttempt(
        id="11111111-1111-4111-8111-111111111111",
        advisory_id=case_a.id, quote_fingerprint="a" * 64,
        idempotency_key="ci-scope-a", expected_amount_cents=12000,
        status="reserved",
    )
    attempt_b = S01StripeCheckoutAttempt(
        id="22222222-2222-4222-8222-222222222222",
        advisory_id=case_b.id, quote_fingerprint="b" * 64,
        idempotency_key="ci-scope-b", expected_amount_cents=13000,
        status="reserved",
    )
    session.add_all((attempt_a, attempt_b))
    session.flush()
    session.add_all((
        S01StripeEventReceipt(
            stripe_event_id="evt_ci_scope_a", attempt_id=attempt_a.id,
            event_type="checkout.session.completed",
        ),
        S01StripeEventReceipt(
            stripe_event_id="evt_ci_scope_b", attempt_id=attempt_b.id,
            event_type="checkout.session.completed",
        ),
        S01StripeNotificationOutbox(
            attempt_id=attempt_a.id, kind="customer_payment_confirmed",
            delivery_key="ci-scope-a-notification", status="pending",
        ),
        S01StripeNotificationOutbox(
            attempt_id=attempt_b.id, kind="customer_payment_confirmed",
            delivery_key="ci-scope-b-notification", status="pending",
        ),
        AdvisoryAuditLog(request_id=case_a.id, action="quote_sent",
                         detail="Synthetic A"),
        AdvisoryAuditLog(request_id=case_b.id, admin_id=a.id,
                         action="quote_sent", detail="Synthetic B"),
    ))
    session.commit()
    return a.id, b.id, case_a.id, case_b.id


def _test_count_only_read_only(engine, a_id, b_id):
    declared = {m.__tablename__ for m in MODELS}
    actual = set(db.Model.metadata.tables)
    assert len(actual) == 17 and actual == declared
    for model, columns in {**SUBJECT_FIELDS, **ACTOR_FIELDS, **EMAIL_CANDIDATES}.items():
        assert all(col in model.__table__.columns for col in columns)

    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        scope = inventory_verified_user_synthetic(
            session, user_id=a_id, original_email="subject_a@example.invalid"
        )
        assert scope["tables_modeled"] == 17
        assert scope["verified_subject_refs"]["fifo_reports.user_id"] == 1
        assert scope["verified_subject_refs"]["fiscal_advisory_requests.user_id"] == 1
        assert scope["copied_email_candidates"]["processing_errors.email"] == 2
        assert scope["copied_email_candidates"]["fiscal_advisory_requests.email"] == 2
        assert scope["staff_actor_refs"]["fiscal_advisory_requests.quoted_by_user_id"] == 1
        assert scope["staff_actor_refs"]["advisory_audit_log.admin_id"] == 1
        assert scope["indirect_case_refs"]["s01_stripe_checkout_attempts"] == 1
        assert scope["indirect_case_refs"]["s01_stripe_event_receipts"] == 1
        assert scope["indirect_case_refs"]["s01_stripe_notification_outbox"] == 1
        assert scope["indirect_case_refs"]["advisory_audit_log"] == 1
        assert scope["no_direct_fk"] == ("incidents", "resources")
        assert not scope["delete_permitted"]
        assert not scope["blocking_proven"]
        assert not scope["external_systems_checked"]
        assert "subject_a@example.invalid" not in repr(scope)
        assert session.get(User, b_id).email == "subject_b@example.invalid"
        assert not session.new and not session.dirty and not session.deleted

    # PostgreSQL itself must reject a write during the read-only review.
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        try:
            session.execute(text("UPDATE users SET full_name='forbidden' WHERE id=:uid"),
                            {"uid": a_id})
        except DBAPIError as exc:
            assert getattr(exc.orig, "pgcode", None) == "25006"
        else:
            raise AssertionError("READ ONLY review allowed an UPDATE")

    with Session(engine) as session:
        assert session.get(User, a_id).full_name is None
        assert session.get(User, b_id).email == "subject_b@example.invalid"
        assert session.execute(select(FifoReport).where(
            FifoReport.user_id == b_id
        )).scalar_one().exchange == "bitvavo"


def _test_inactive_account_gap(engine, a_id, b_id):
    """Legacy account deletion loses original email; only ID links remain."""
    with Session(engine) as session:
        a = session.get(User, a_id)
        a.email = f"deleted_{a_id}@deleted"
        a.password_hash = None
        a.google_id = None
        a.full_name = None
        a.nif = None
        a.is_active = False
        session.commit()

    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        try:
            inventory_verified_user_synthetic(
                session, user_id=a_id, original_email="subject_a@example.invalid"
            )
        except ValueError:
            pass
        else:
            raise AssertionError("active-only probe accepted deactivated account")

        for marker in (None, "", "APPROVED", True):
            try:
                inventory_deactivated_user_synthetic(
                    session, user_id=a_id, manual_evidence=marker
                )
            except PermissionError:
                pass
            else:
                raise AssertionError("unverified manual review marker accepted")

        scope = inventory_deactivated_user_synthetic(
            session, user_id=a_id,
            manual_evidence="SYNTHETIC_MANUAL_IDENTITY_REVIEW_ONLY"
        )
        assert scope["direct_id_references"]["fifo_reports.user_id"] == 1
        assert scope["direct_id_references"]["fiscal_advisory_requests.user_id"] == 1
        assert scope["staff_actor_references"]["fiscal_advisory_requests.quoted_by_user_id"] == 1
        assert scope["staff_actor_references"]["advisory_audit_log.admin_id"] == 1
        assert scope["case_fk_references"]["s01_stripe_checkout_attempts"] == 1
        assert scope["case_fk_references"]["s01_stripe_event_receipts"] == 1
        assert scope["case_fk_references"]["s01_stripe_notification_outbox"] == 1
        assert scope["case_log_unverified_candidates"] == 1
        assert scope["copied_email_candidates"] is None
        assert scope["original_email_unavailable"]
        assert scope["requires_external_identity_proof"]
        assert not scope["scope_complete"]
        assert not scope["delete_permitted"]
        assert not scope["blocking_proven"]
        assert not scope["external_systems_checked"]
        assert "subject_a@example.invalid" not in repr(scope)
        assert session.get(User, b_id).is_active
        assert session.get(User, b_id).email == "subject_b@example.invalid"
        assert not session.new and not session.dirty and not session.deleted

    with Session(engine) as session:
        try:
            inventory_deactivated_user_synthetic(
                session, user_id=b_id,
                manual_evidence="SYNTHETIC_MANUAL_IDENTITY_REVIEW_ONLY"
            )
        except ValueError:
            pass
        else:
            raise AssertionError("active B account accepted as deactivated")


def main():
    _guard()
    created = False
    admin = _connect_admin()
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            # No IF NOT EXISTS: fail rather than touch any pre-existing DB.
            cur.execute("CREATE DATABASE sec5_priv_scope_ci")
        created = True
        engine = create_engine(
            POSTGRES_URL, connect_args={
                "connect_timeout": 5, "options": "-c statement_timeout=5000"
            },
        )
        try:
            db.Model.metadata.create_all(engine)
            with Session(engine) as session:
                a, b, _, _ = _seed(session)
            _test_count_only_read_only(engine, a, b)
            _test_inactive_account_gap(engine, a, b)
            print("SEC5_PRIV_SCOPE_PG18: PASS")
        finally:
            engine.dispose()
    finally:
        if created:
            with admin.cursor() as cur:
                cur.execute("DROP DATABASE sec5_priv_scope_ci WITH (FORCE)")
        admin.close()


if __name__ == "__main__":
    main()
