"""
Tests for incident management — Sprint 2.5 of the Observability architecture.

Tests the full lifecycle of Incident creation, deduplication, regression
detection, and historical backfill. All tests use an isolated in-memory
SQLite DB via the same _make_app() pattern used in test_error_tracking.py.
"""
import os
import sys
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fiscal_app_export"))

from error_tracking import (
    backfill_incidents_from_processing_errors,
    build_processing_error_fingerprint,
    record_processing_error_safe,
)

# ── SHARED HELPERS ─────────────────────────────────────────────────────────────

_ENV_NO_EMAIL = {"PROCESSING_ERROR_EMAILS_ENABLED": "false"}


def _make_app():
    """Minimal Flask+SQLAlchemy app backed by an in-memory SQLite DB.

    Each call returns a fresh app with a clean, empty schema — no shared state
    between test methods.
    """
    from flask import Flask
    from models import db

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = True
    db.init_app(app)
    with app.app_context():
        db.create_all()
    return app


# ── TESTS 1–7: UPSERT LIFECYCLE ───────────────────────────────────────────────


class TestIncidentUpsert:
    """Core upsert logic exercised through the public record_processing_error_safe() API."""

    def _record(self, **kwargs):
        """Minimal call to record_processing_error_safe with emails disabled."""
        defaults = {
            "exchange": "binance",
            "stage": "classify",
            "exc": KeyError("'Date' column not found"),
            "parser": "ClasificadorBinance",
        }
        defaults.update(kwargs)
        with patch.dict(os.environ, _ENV_NO_EMAIL):
            record_processing_error_safe(**defaults)

    def test_first_error_creates_incident(self):
        """Test 1: first ProcessingError for a fingerprint creates exactly one Incident."""
        from models import db, Incident

        app = _make_app()
        with app.app_context():
            self._record()

            assert db.session.query(Incident).count() == 1
            inc = db.session.query(Incident).first()
            assert inc.exchange == "binance"
            assert inc.stage == "classify"
            assert inc.error_type == "KeyError"
            assert inc.status == "nueva"
            assert inc.event_count == 1
            assert inc.regression_count == 0
            assert inc.first_seen_at is not None
            assert inc.last_seen_at is not None

    def test_second_identical_error_no_duplicate(self):
        """Test 2: second ProcessingError with the same fingerprint does not create a second Incident."""
        from models import db, Incident

        app = _make_app()
        with app.app_context():
            self._record()
            self._record()
            assert db.session.query(Incident).count() == 1

    def test_second_error_increments_event_count(self):
        """Test 3: second error with the same fingerprint increments event_count to 2."""
        from models import db, Incident

        app = _make_app()
        with app.app_context():
            self._record()
            self._record()
            db.session.expire_all()
            assert db.session.query(Incident).first().event_count == 2

    def test_first_seen_at_immutable(self):
        """Test 4: first_seen_at is fixed at creation and never changed by subsequent events."""
        from models import db, Incident

        app = _make_app()
        with app.app_context():
            self._record()
            first_seen_before = db.session.query(Incident).first().first_seen_at

            self._record()
            db.session.expire_all()
            first_seen_after = db.session.query(Incident).first().first_seen_at

            assert first_seen_before == first_seen_after

    def test_last_seen_at_updated(self):
        """Test 5: last_seen_at reflects the most recent event; event_count confirms the update ran."""
        from models import db, Incident

        app = _make_app()
        with app.app_context():
            self._record()
            last_seen_after_first = db.session.query(Incident).first().last_seen_at

            self._record()
            db.session.expire_all()
            inc = db.session.query(Incident).first()

            assert inc.last_seen_at >= last_seen_after_first
            assert inc.event_count == 2  # independent proof the second call was processed

    def test_closed_incident_becomes_regression(self):
        """Test 6: a new event arriving on a 'cerrada' incident changes its status to 'regresion'."""
        from models import db, Incident

        app = _make_app()
        with app.app_context():
            self._record()

            inc = db.session.query(Incident).first()
            inc.status = "cerrada"
            db.session.commit()

            self._record()
            db.session.expire_all()

            assert db.session.query(Incident).first().status == "regresion"

    def test_regression_increments_regression_count(self):
        """Test 7: the regression transition also increments regression_count."""
        from models import db, Incident

        app = _make_app()
        with app.app_context():
            self._record()

            inc = db.session.query(Incident).first()
            inc.status = "cerrada"
            db.session.commit()

            self._record()
            db.session.expire_all()
            inc = db.session.query(Incident).first()

            assert inc.regression_count == 1
            assert inc.event_count == 2


# ── TEST 8: MODEL PROPERTY ─────────────────────────────────────────────────────


class TestIncidentModel:
    """Pure property test — no DB or Flask context required."""

    def test_inc_id_format(self):
        """Test 8: inc_id returns 'INC-' followed by the zero-padded id (min 4 digits)."""
        from models import Incident

        cases = {1: "INC-0001", 7: "INC-0007", 42: "INC-0042", 9999: "INC-9999", 10000: "INC-10000"}
        for id_val, expected in cases.items():
            inc = Incident()
            inc.id = id_val
            assert inc.inc_id == expected, f"id={id_val}: expected {expected}, got {inc.inc_id}"


# ── TESTS 9–10: BACKFILL ───────────────────────────────────────────────────────


class TestBackfill:
    """backfill_incidents_from_processing_errors() creates and deduplicates correctly."""

    def _insert_error(self, db, exchange, stage, error_type, message, created_at):
        """Insert a ProcessingError directly — bypasses _upsert_incident to simulate history."""
        from models import ProcessingError

        fp = build_processing_error_fingerprint(exchange, stage, error_type, message)
        db.session.add(ProcessingError(
            exchange=exchange,
            stage=stage,
            error_type=error_type,
            message_short=message,
            fingerprint=fp,
            created_at=created_at,
            auto_email_sent=False,
            user_replied=False,
            resolved=False,
        ))
        db.session.commit()
        return fp

    def test_backfill_creates_incidents_from_errors(self):
        """Test 9: backfill groups existing processing_errors by fingerprint into Incidents."""
        from models import db, Incident

        app = _make_app()
        t0 = datetime(2026, 1, 1, 10, 0, 0)
        t1 = datetime(2026, 1, 1, 11, 0, 0)
        t2 = datetime(2026, 1, 1, 12, 0, 0)

        with app.app_context():
            # fingerprint A: 2 events — coinbase KeyError
            fp_a = self._insert_error(db, "coinbase", "processing", "KeyError", "'Price' not found", t0)
            self._insert_error(db, "coinbase", "processing", "KeyError", "'Price' not found", t1)
            # fingerprint B: 1 event — binance ValueError
            fp_b = self._insert_error(db, "binance", "processing", "ValueError", "invalid literal for float", t2)

            inserted, skipped = backfill_incidents_from_processing_errors()

            assert inserted == 2
            assert skipped == 0
            assert db.session.query(Incident).count() == 2

            inc_a = db.session.query(Incident).filter_by(fingerprint=fp_a).one()
            assert inc_a.event_count == 2
            assert inc_a.exchange == "coinbase"
            assert inc_a.status == "nueva"
            assert inc_a.first_seen_at == t0
            assert inc_a.last_seen_at == t1

            inc_b = db.session.query(Incident).filter_by(fingerprint=fp_b).one()
            assert inc_b.event_count == 1
            assert inc_b.exchange == "binance"
            assert inc_b.first_seen_at == t2
            assert inc_b.last_seen_at == t2

    def test_backfill_is_idempotent(self):
        """Test 10: running backfill a second time inserts 0 and skips all existing incidents."""
        from models import db, Incident

        app = _make_app()
        t0 = datetime(2026, 1, 1, 10, 0, 0)
        t1 = datetime(2026, 1, 1, 11, 0, 0)

        with app.app_context():
            self._insert_error(db, "coinbase", "processing", "KeyError", "'Price' not found", t0)
            self._insert_error(db, "binance", "processing", "ValueError", "invalid literal", t1)

            inserted1, skipped1 = backfill_incidents_from_processing_errors()
            assert inserted1 == 2
            assert skipped1 == 0

            inserted2, skipped2 = backfill_incidents_from_processing_errors()
            assert inserted2 == 0
            assert skipped2 == 2

            assert db.session.query(Incident).count() == 2


# ── TEST 11: RESILIENCE ────────────────────────────────────────────────────────


class TestUpsertRobustness:
    """_upsert_incident failure must never prevent ProcessingError from being saved."""

    def test_upsert_failure_does_not_break_processing_error_record(self):
        """Test 11: if _upsert_incident raises, the ProcessingError is still committed to DB."""
        from models import db, Incident, ProcessingError

        app = _make_app()
        exc = KeyError("'Date' column not found")

        with app.app_context():
            with patch("error_tracking._upsert_incident", side_effect=RuntimeError("incident DB exploded")):
                with patch.dict(os.environ, _ENV_NO_EMAIL):
                    record_processing_error_safe(
                        exchange="binance",
                        stage="classify",
                        exc=exc,
                        parser="ClasificadorBinance",
                    )

            # ProcessingError persisted despite _upsert_incident failing
            assert db.session.query(ProcessingError).count() == 1
            record = db.session.query(ProcessingError).first()
            assert record.exchange == "binance"
            assert record.error_type == "KeyError"

            # No Incident was created (upsert was patched out)
            assert db.session.query(Incident).count() == 0
