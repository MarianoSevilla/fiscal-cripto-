"""Synthetic PostgreSQL-compatible SQLAlchemy checks for a READ-ONLY privacy scope.

This is NOT a live privacy route or a deletion/blocking implementation.
"""
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from models import (
    db, User, FifoReport, ProcessingError, Contacto,
    FiscalAdvisoryRequest, S01StripeCheckoutAttempt, S01StripeEventReceipt,
    S01StripeNotificationOutbox,
)
from privacy_scope_probe import (
    MODELS, SUBJECT_FIELDS, ACTOR_FIELDS, EMAIL_CANDIDATES,
    inventory_verified_user_synthetic,
)


@pytest.fixture
def synthetic_database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    db.Model.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        db.Model.metadata.drop_all(engine)
        engine.dispose()


def _account(session, email):
    user = User(email=email, role="user", is_active=True)
    session.add(user)
    session.flush()
    return user


def _case(session, user, email):
    entry = FiscalAdvisoryRequest(
        user_id=user.id, full_name="Fixture", email=email,
        tax_residence_country="ES", tax_year=2025,
        service_type="revision_basica", case_description="test-only",
    )
    session.add(entry)
    session.flush()
    return entry


def test_all_17_orm_models_included_without_guessing_unlinked_records():
    actual = {t.name for t in db.Model.metadata.tables.values()}
    declared = {model.__tablename__ for model in MODELS}
    assert actual == declared and len(actual) == 17
    for model, cols in {**SUBJECT_FIELDS, **ACTOR_FIELDS, **EMAIL_CANDIDATES}.items():
        assert model.__tablename__ in actual
        for col in cols:
            assert col in model.__table__.columns


def test_probe_only_counts_and_does_not_cross_accounts_or_mutate(synthetic_database):
    s = synthetic_database
    a = _account(s, "subject@examples.test")
    b = _account(s, "other@examples.test")
    s.add_all([
        FifoReport(user_id=a.id, exchange="binance", fiscal_year=2025),
        FifoReport(user_id=b.id, exchange="bitvavo", fiscal_year=2025),
        ProcessingError(user_id=a.id, email=a.email, exchange="binance"),
        ProcessingError(user_id=None, email=a.email, exchange="kraken"),
        Contacto(nombre="Fixture", email=a.email, tipo_consulta="otros", mensaje="test"),
    ])
    ca = _case(s, a, a.email)
    # Deliberately duplicate A's email on a case tied to B. This MUST remain
    # a candidate, never an inferred owner-based payment or deletion.
    cb = _case(s, b, a.email)
    sa = S01StripeCheckoutAttempt(
        id="11111111-1111-4111-8111-111111111111",
        advisory_id=ca.id, quote_fingerprint="a"*64,
        idempotency_key="test-attempt-a", expected_amount_cents=12000,
        status="reserved",
    )
    sb = S01StripeCheckoutAttempt(
        id="22222222-2222-4222-8222-222222222222",
        advisory_id=cb.id, quote_fingerprint="b"*64,
        idempotency_key="test-attempt-b", expected_amount_cents=12000,
        status="reserved",
    )
    s.add_all([sa, sb])
    s.flush()
    s.add_all([
        S01StripeEventReceipt(
            stripe_event_id="evt_fixture_a", attempt_id=sa.id,
            event_type="checkout.session.completed",
        ),
        S01StripeEventReceipt(
            stripe_event_id="evt_fixture_b", attempt_id=sb.id,
            event_type="checkout.session.completed",
        ),
        S01StripeNotificationOutbox(
            attempt_id=sa.id, kind="customer_payment_confirmed",
            delivery_key="fixture-a-confirmed", status="pending",
        ),
    ])
    s.commit()
    before = s.execute(select(func.count()).select_from(FifoReport)).scalar_one()
    before_email = s.get(User, a.id).email

    scope = inventory_verified_user_synthetic(
        s, user_id=a.id, original_email=a.email
    )

    assert scope["tables_modeled"] == 17
    assert scope["verified_subject_refs"]["fifo_reports.user_id"] == 1
    assert scope["verified_subject_refs"]["processing_errors.user_id"] == 1
    assert scope["copied_email_candidates"]["processing_errors.email"] == 2
    assert scope["copied_email_candidates"]["contactos.email"] == 1
    assert scope["copied_email_candidates"]["fiscal_advisory_requests.email"] == 2
    assert scope["indirect_case_refs"]["s01_stripe_checkout_attempts"] == 1
    assert scope["indirect_case_refs"]["s01_stripe_event_receipts"] == 1
    assert scope["indirect_case_refs"]["s01_stripe_notification_outbox"] == 1
    assert not scope["delete_permitted"]
    assert not scope["blocking_proven"]
    assert not scope["external_systems_checked"]
    assert s.get(User, a.id).email == before_email
    assert s.get(User, b.id).is_active
    assert s.execute(select(func.count()).select_from(FifoReport)).scalar_one() == before
    assert not s.dirty
    assert a.email not in repr(scope)


def test_fail_closed_for_inactive_account_or_unverified_email(synthetic_database):
    s = synthetic_database
    a = _account(s, "active@examples.test")
    s.commit()
    for bad in (-1, True, "1", 0):
        with pytest.raises(ValueError):
            inventory_verified_user_synthetic(
                s, user_id=bad, original_email=a.email
            )
    with pytest.raises(ValueError):
        inventory_verified_user_synthetic(s, user_id=a.id, original_email="other@examples.test")
    a.is_active = False
    s.commit()
    with pytest.raises(ValueError):
        inventory_verified_user_synthetic(s, user_id=a.id, original_email=a.email)


def test_deactivated_scope_cannot_recover_lost_email_or_authorize_erasure(synthetic_database):
    """Same ID reaches FKs, but historic email-only records remain ambiguous."""
    s = synthetic_database
    a = _account(s, "inactive@example.invalid")
    b = _account(s, "other@example.invalid")
    s.add_all([
        FifoReport(user_id=a.id, exchange="bitvavo", fiscal_year=2025),
        ProcessingError(user_id=None, email=a.email, exchange="binance"),
        Contacto(nombre="Synthetic", email=a.email,
                 tipo_consulta="otros", mensaje="test"),
    ])
    ca = _case(s, a, a.email)
    _case(s, b, a.email)  # historical email collision: not A's case
    s.commit()
    a_id, b_id = a.id, b.id
    a.email = f"deleted_{a_id}@deleted"
    a.is_active = False
    s.commit()

    from privacy_scope_probe import inventory_deactivated_user_synthetic
    with pytest.raises(ValueError):
        inventory_verified_user_synthetic(
            s, user_id=a_id, original_email="inactive@example.invalid"
        )
    with pytest.raises(PermissionError):
        inventory_deactivated_user_synthetic(
            s, user_id=a_id, manual_evidence="APPROVED"
        )
    scope = inventory_deactivated_user_synthetic(
        s, user_id=a_id,
        manual_evidence="SYNTHETIC_MANUAL_IDENTITY_REVIEW_ONLY"
    )
    assert scope["direct_id_references"]["fifo_reports.user_id"] == 1
    assert scope["direct_id_references"]["fiscal_advisory_requests.user_id"] == 1
    assert scope["copied_email_candidates"] is None
    assert scope["requires_external_identity_proof"]
    assert not scope["scope_complete"] and not scope["delete_permitted"]
    assert "inactive@example.invalid" not in repr(scope)
    assert s.get(User, b_id).is_active
    with pytest.raises(ValueError):
        inventory_deactivated_user_synthetic(
            s, user_id=b_id,
            manual_evidence="SYNTHETIC_MANUAL_IDENTITY_REVIEW_ONLY"
        )
