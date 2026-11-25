from datetime import datetime, timedelta
from uuid import uuid4
import hashlib

import pytest
from flask import Flask

from models import db, User, CreditWallet, CreditLedgerEntry, CreditPurchase
from credit_ledger import (
    CreditError, balance, create_purchase, confirm_test_payment,
    reserve_analysis, settle_analysis, release_analysis, attach_checkout_session,
    quarantine_unknown_analysis,
)


@pytest.fixture
def ctx(tmp_path):
    app = Flask("credit-ledger-test")
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "credits.sqlite"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        TESTING=True,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        user = User(email="credits-synthetic@example.invalid", is_active=True)
        db.session.add(user)
        db.session.commit()
        yield user.id
        db.session.remove()
        db.drop_all()


def _buy(user_id, *, package="basic"):
    purchase = create_purchase(user_id=user_id, package_key=package)
    attach_checkout_session(purchase_id=purchase.id, session_id="cs_test_synthetic_1")
    assert confirm_test_payment(
        purchase_id=purchase.id, event_id="evt_synthetic_1",
        session_id="cs_test_synthetic_1", payment_intent_id="pi_synthetic_1",
        amount_cents=purchase.amount_cents, currency="eur", livemode=False,
    )
    return purchase


def _reserve(user_id, *, key=None, correction_of_id=None, credits=100):
    return reserve_analysis(
        user_id=user_id, idempotency_key=key or str(uuid4()),
        exchange="binance", fiscal_years="2025", csv_rows=442,
        file_count=1, file_fingerprint=hashlib.sha256(b"synthetic").hexdigest(),
        max_credits=credits, correction_of_id=correction_of_id,
    )


def test_test_payment_grants_once_only_after_verified_test_event(ctx):
    purchase = create_purchase(user_id=ctx, package_key="basic")
    attach_checkout_session(purchase_id=purchase.id, session_id="cs_test_synthetic_1")
    assert balance(ctx)["available"] == 0
    with pytest.raises(CreditError):
        confirm_test_payment(
            purchase_id=purchase.id, event_id="evt_live",
            session_id="cs_live", payment_intent_id="pi_live",
            amount_cents=purchase.amount_cents, currency="eur", livemode=True,
        )
    assert confirm_test_payment(
        purchase_id=purchase.id, event_id="evt_synthetic_1",
        session_id="cs_test_synthetic_1", payment_intent_id="pi_synthetic_1",
        amount_cents=purchase.amount_cents, currency="eur", livemode=False,
    )
    assert not confirm_test_payment(
        purchase_id=purchase.id, event_id="evt_synthetic_replay",
        session_id="cs_test_synthetic_1", payment_intent_id="pi_synthetic_1",
        amount_cents=purchase.amount_cents, currency="eur", livemode=False,
    )
    assert balance(ctx)["available"] == 110
    assert CreditLedgerEntry.query.count() == 1


def test_authorized_definitive_and_provisional_runs_settle_once(ctx):
    _buy(ctx, package="standard")
    for kind in ("definitive", "provisional"):
        analysis = _reserve(ctx, credits=100)
        settled = settle_analysis(analysis_id=analysis.id, user_id=ctx, result_type=kind)
        assert settled.charged_credits == 100
        assert settle_analysis(analysis_id=analysis.id, user_id=ctx, result_type=kind).charged_credits == 100
    assert balance(ctx) == {"available": 30, "reserved": 0, "frozen": False}


def test_processing_error_releases_reservation_and_preserves_full_balance(ctx):
    _buy(ctx, package="basic")
    analysis = _reserve(ctx, credits=100)
    assert balance(ctx)["available"] == 10
    release_analysis(analysis_id=analysis.id, user_id=ctx)
    release_analysis(analysis_id=analysis.id, user_id=ctx)
    assert balance(ctx) == {"available": 110, "reserved": 0, "frozen": False}
    assert analysis.charged_credits == 0


def test_failed_analysis_does_not_settle_and_insufficient_balance_fails_closed(ctx):
    _buy(ctx, package="basic")
    with pytest.raises(CreditError):
        _reserve(ctx, credits=111)
    assert balance(ctx)["available"] == 110
    analysis = _reserve(ctx, credits=100)
    with pytest.raises(CreditError):
        settle_analysis(analysis_id=analysis.id, user_id=ctx, result_type="processing_error")
    assert balance(ctx)["reserved"] == 100
    release_analysis(analysis_id=analysis.id, user_id=ctx)
    assert balance(ctx)["available"] == 110


def test_idempotent_authorization_does_not_reserve_twice(ctx):
    _buy(ctx, package="basic")
    key = "browser-retry-uuid"
    first = _reserve(ctx, key=key, credits=100)
    again = _reserve(ctx, key=key, credits=100)
    assert first.id == again.id
    assert balance(ctx) == {"available": 10, "reserved": 100, "frozen": False}
    assert CreditLedgerEntry.query.filter_by(entry_type="reserve").count() == 1


def test_one_free_correction_within_thirty_days_is_not_charged(ctx):
    _buy(ctx, package="basic")
    original = _reserve(ctx, credits=50)
    settle_analysis(analysis_id=original.id, user_id=ctx, result_type="definitive")
    before = balance(ctx)
    correction = _reserve(ctx, correction_of_id=original.id, credits=100)
    assert correction.reserved_credits == 0
    settle_analysis(analysis_id=correction.id, user_id=ctx, result_type="provisional")
    assert correction.charged_credits == 0
    assert balance(ctx) == before
    with pytest.raises(CreditError):
        _reserve(ctx, correction_of_id=original.id, credits=50)


def test_refund_freezes_wallet_without_guessing_or_going_negative(ctx):
    purchase = _buy(ctx, package="basic")
    # Spend 105 of 110; only five purchased credits remain.
    analysis = _reserve(ctx, credits=105)
    settle_analysis(analysis_id=analysis.id, user_id=ctx, result_type="definitive")
    from credit_ledger import flag_refund_for_review
    assert flag_refund_for_review(event_id="evt_refund_synthetic",
                                  payment_intent_id="pi_synthetic_1")
    assert not flag_refund_for_review(event_id="evt_refund_synthetic",
                                      payment_intent_id="pi_synthetic_1")
    assert balance(ctx) == {"available": 5, "reserved": 0, "frozen": True}
    with pytest.raises(CreditError):
        _reserve(ctx, credits=1)


def test_unconfirmed_settlement_quarantines_wallet_and_blocks_new_charges(ctx):
    _buy(ctx, package="basic")
    analysis = _reserve(ctx, credits=50)
    assert quarantine_unknown_analysis(analysis_id=analysis.id, user_id=ctx)
    assert analysis.status == "settlement_unknown"
    assert balance(ctx) == {"available": 60, "reserved": 50, "frozen": True}
    with pytest.raises(CreditError):
        _reserve(ctx, credits=10)
