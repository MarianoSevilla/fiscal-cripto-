import base64
import hashlib
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from flask import Flask

from models import db, User, CreditWallet
from credit_ledger import reserve_analysis, begin_analysis, settle_analysis
from credit_execution import try_acquire_analysis_lock
from credit_artifacts import store_artifact, load_artifact


KEY = base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")


@pytest.fixture
def ctx(tmp_path):
    app = Flask("credit-artifact-test")
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "artifacts.sqlite"),
                      SQLALCHEMY_TRACK_MODIFICATIONS=False, TESTING=True)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        first = User(email="artifact-owner@example.invalid", is_active=True)
        second = User(email="artifact-other@example.invalid", is_active=True)
        db.session.add_all([first, second]); db.session.flush()
        db.session.add(CreditWallet(user_id=first.id, available_credits=10))
        db.session.commit()
        analysis = reserve_analysis(
            user_id=first.id, idempotency_key=str(uuid4()), exchange="kraken",
            fiscal_years="2025", csv_rows=442, file_count=1,
            file_fingerprint=hashlib.sha256(b"synthetic").hexdigest(), max_credits=5,
        )
        yield first.id, second.id, analysis.id
        db.session.remove(); db.drop_all()


def test_report_is_authenticated_encrypted_repeatable_and_expiring(ctx):
    owner, other, analysis_id = ctx
    lock = try_acquire_analysis_lock(user_id=owner, analysis_id=analysis_id)
    assert lock is not None
    begin_analysis(analysis_id=analysis_id, user_id=owner, execution_lock=lock)
    pdf = b"%PDF-1.4\nsynthetic private report\n"
    created = datetime(2026, 1, 1)
    artifact = store_artifact(analysis_id=analysis_id, user_id=owner,
                              pdf_bytes=pdf, encoded_key=KEY, now=created)
    assert pdf not in artifact.ciphertext
    assert load_artifact(analysis_id=analysis_id, user_id=owner,
                         encoded_key=KEY, now=created + timedelta(days=1)) is None
    settle_analysis(analysis_id=analysis_id, user_id=owner, execution_lock=lock,
                    result_type="definitive")
    lock.release()
    assert load_artifact(analysis_id=analysis_id, user_id=other,
                         encoded_key=KEY, now=created + timedelta(days=1)) is None
    assert load_artifact(analysis_id=analysis_id, user_id=owner,
                         encoded_key=KEY, now=created + timedelta(days=1)) == pdf
    assert load_artifact(analysis_id=analysis_id, user_id=owner,
                         encoded_key=KEY, now=created + timedelta(days=366)) is None


def test_wrong_encryption_key_fails_closed(ctx):
    owner, _, analysis_id = ctx
    lock = try_acquire_analysis_lock(user_id=owner, analysis_id=analysis_id)
    assert lock is not None
    begin_analysis(analysis_id=analysis_id, user_id=owner, execution_lock=lock)
    store_artifact(analysis_id=analysis_id, user_id=owner,
                   pdf_bytes=b"%PDF-1.4\nx", encoded_key=KEY)
    settle_analysis(analysis_id=analysis_id, user_id=owner, execution_lock=lock,
                    result_type="provisional")
    lock.release()
    wrong = base64.urlsafe_b64encode(b"b" * 32).decode().rstrip("=")
    with pytest.raises(Exception):
        load_artifact(analysis_id=analysis_id, user_id=owner, encoded_key=wrong)
