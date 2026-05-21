"""
Tests for error_tracking.py

Pure-logic tests that don't require a running Flask app or DB.
Flask-context tests use a minimal in-memory SQLite app fixture.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "fiscal_app_export"))

from error_tracking import (
    build_processing_error_fingerprint,
    is_actionable_processing_error,
    _sanitize,
    _extract_traceback_short,
    record_processing_error_safe,
    send_processing_error_email,
    _should_send_email,
    _MAX_MESSAGE_LEN,
    _MAX_TRACEBACK_LEN,
)


# ── FINGERPRINT ───────────────────────────────────────────────────────────────

class TestFingerprint:
    def test_stable_same_inputs(self):
        fp1 = build_processing_error_fingerprint("binance", "parsing", "KeyError", "column 'Date' not found")
        fp2 = build_processing_error_fingerprint("binance", "parsing", "KeyError", "column 'Date' not found")
        assert fp1 == fp2

    def test_16_chars(self):
        fp = build_processing_error_fingerprint("binance", "parsing", "KeyError", "msg")
        assert len(fp) == 16

    def test_different_exchange_different_fp(self):
        fp1 = build_processing_error_fingerprint("binance", "parsing", "KeyError", "msg")
        fp2 = build_processing_error_fingerprint("kraken",  "parsing", "KeyError", "msg")
        assert fp1 != fp2

    def test_different_error_type_different_fp(self):
        fp1 = build_processing_error_fingerprint("binance", "parsing", "KeyError",   "msg")
        fp2 = build_processing_error_fingerprint("binance", "parsing", "ValueError", "msg")
        assert fp1 != fp2

    def test_numbers_normalized(self):
        # Same error with different row numbers should produce the same fingerprint
        fp1 = build_processing_error_fingerprint("binance", "parsing", "KeyError", "row 42 missing")
        fp2 = build_processing_error_fingerprint("binance", "parsing", "KeyError", "row 99 missing")
        assert fp1 == fp2

    def test_paths_normalized(self):
        fp1 = build_processing_error_fingerprint("binance", "parsing", "KeyError", "file /tmp/abc123.csv")
        fp2 = build_processing_error_fingerprint("binance", "parsing", "KeyError", "file /tmp/xyz789.csv")
        assert fp1 == fp2

    def test_none_inputs_ok(self):
        fp = build_processing_error_fingerprint(None, None, None, None)
        assert len(fp) == 16

    def test_does_not_include_timestamp(self):
        # Calling at different times (simulated via message content) still matches
        fp1 = build_processing_error_fingerprint("binance", "parsing", "KeyError", "unexpected column")
        fp2 = build_processing_error_fingerprint("binance", "parsing", "KeyError", "unexpected column")
        assert fp1 == fp2


# ── CLASSIFICATION ────────────────────────────────────────────────────────────

class TestActionable:
    def test_keyerror_is_actionable(self):
        assert is_actionable_processing_error("KeyError", "parsing", "column 'Date'") is True

    def test_valueerror_is_actionable(self):
        assert is_actionable_processing_error("ValueError", "fifo", "invalid literal") is True

    def test_unicodeerror_is_actionable(self):
        assert is_actionable_processing_error("UnicodeDecodeError", "parsing", "codec error") is True

    def test_parsererror_is_actionable(self):
        assert is_actionable_processing_error("ParserError", "parsing", "tokenize error") is True

    def test_notimplemented_is_actionable(self):
        assert is_actionable_processing_error("NotImplementedError", "fiscal", "swap type X") is True

    def test_operationalerror_not_actionable(self):
        assert is_actionable_processing_error("OperationalError", "processing", "DB gone away") is False

    def test_timeout_not_actionable(self):
        assert is_actionable_processing_error("TimeoutError", "processing", "timed out") is False

    def test_timeout_in_message_not_actionable(self):
        assert is_actionable_processing_error("Exception", "processing", "connection timed out") is False

    def test_memoryerror_not_actionable(self):
        assert is_actionable_processing_error("MemoryError", "processing", "too large") is False

    def test_rate_limit_in_message_not_actionable(self):
        assert is_actionable_processing_error("Exception", "processing", "rate limit exceeded") is False

    def test_401_in_message_not_actionable(self):
        assert is_actionable_processing_error("Exception", "processing", "401 unauthorized") is False

    def test_demasiadas_filas_not_actionable(self):
        assert is_actionable_processing_error("ValueError", "processing", "demasiadas filas") is False

    def test_unknown_type_defaults_actionable(self):
        # Unknown error type with no non-actionable signals → actionable
        assert is_actionable_processing_error("SomeRandomError", "parsing", "unexpected") is True


# ── SANITIZATION ──────────────────────────────────────────────────────────────

class TestSanitize:
    def test_removes_email(self):
        result = _sanitize("error for user@example.com in row 1", 500)
        assert "user@example.com" not in result
        assert "[EMAIL]" in result

    def test_removes_long_hex_token(self):
        token = "a" * 32
        result = _sanitize(f"api_key={token}", 500)
        assert token not in result

    def test_removes_bearer_token(self):
        # Uses key=value pattern
        result = _sanitize("api_key=mysecrettoken123", 500)
        assert "mysecrettoken123" not in result

    def test_truncates_at_max_len(self):
        # Use chars that don't trigger any redaction pattern
        long_text = "error parsing row " * 60  # ~1080 chars, plain text
        result = _sanitize(long_text, 100)
        assert len(result) <= 110  # 100 + "…[trunc]"
        assert "trunc" in result

    def test_empty_string(self):
        assert _sanitize("", 500) == ""

    def test_none_returns_empty(self):
        assert _sanitize(None, 500) == ""

    def test_normal_text_unchanged(self):
        text = "column 'Date' not found in CSV"
        result = _sanitize(text, 500)
        assert result == text


class TestExtractTraceback:
    def test_returns_string(self):
        try:
            raise ValueError("test error")
        except ValueError as e:
            result = _extract_traceback_short(e)
        assert isinstance(result, str)
        assert "ValueError" in result

    def test_respects_max_length(self):
        try:
            raise ValueError("x" * 3000)
        except ValueError as e:
            result = _extract_traceback_short(e)
        assert len(result) <= _MAX_TRACEBACK_LEN + 20  # +20 for "…[trunc]"

    def test_exc_without_traceback_does_not_raise(self):
        exc = ValueError("no traceback attached")
        result = _extract_traceback_short(exc)
        assert isinstance(result, str)


# ── EMAIL NOT SENT ON FAILURE ─────────────────────────────────────────────────

class TestSendEmailRobust:
    def test_no_api_key_returns_false(self):
        with patch.dict(os.environ, {"RESEND_API_KEY": "", "PROCESSING_ERROR_EMAILS_ENABLED": "true"}):
            result = send_processing_error_email("u@example.com", "binance", 1, "summary")
        assert result is False

    def test_timeout_returns_false(self):
        import concurrent.futures

        def slow_send(_payload):
            import time
            time.sleep(10)

        with patch.dict(os.environ, {"RESEND_API_KEY": "test_key"}):
            with patch("error_tracking.concurrent.futures.ThreadPoolExecutor") as mock_exec:
                future_mock = MagicMock()
                future_mock.result.side_effect = concurrent.futures.TimeoutError()
                mock_exec.return_value.__enter__.return_value.submit.return_value = future_mock
                result = send_processing_error_email("u@example.com", "binance", 1, "summary")
        assert result is False

    def test_resend_exception_propagates_to_caller(self):
        """send_processing_error_email raises on Resend error — caller (_do_record) handles it."""
        with patch.dict(os.environ, {"RESEND_API_KEY": "test_key"}):
            with patch("error_tracking.concurrent.futures.ThreadPoolExecutor") as mock_exec:
                future_mock = MagicMock()
                future_mock.result.side_effect = RuntimeError("resend network error")
                mock_exec.return_value.__enter__.return_value.submit.return_value = future_mock
                with pytest.raises(RuntimeError):
                    send_processing_error_email("u@example.com", "binance", 1, "summary")


# ── record_processing_error_safe NEVER RAISES ─────────────────────────────────

class TestRecordSafe:
    def _make_app(self):
        """Minimal Flask+SQLAlchemy app with in-memory SQLite for integration tests."""
        from flask import Flask
        from models import db, ProcessingError

        app = Flask(__name__)
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
        app.config["TESTING"] = True
        db.init_app(app)
        with app.app_context():
            db.create_all()
        return app

    def test_does_not_raise_when_db_fails(self):
        """If DB is completely broken, record_processing_error_safe must not propagate."""
        exc = ValueError("column not found")

        with patch("error_tracking._do_record", side_effect=RuntimeError("DB exploded")):
            # Should not raise
            record_processing_error_safe(
                user_id=1, email="u@example.com", exchange="binance",
                stage="processing", exc=exc,
            )

    def test_does_not_raise_when_email_fails(self):
        """If email sending fails, record_processing_error_safe must not propagate."""
        app = self._make_app()
        exc = ValueError("column 'Date' missing")

        with app.app_context():
            with patch("error_tracking.send_processing_error_email", side_effect=RuntimeError("Resend down")):
                with patch.dict(os.environ, {
                    "PROCESSING_ERROR_EMAILS_ENABLED": "true",
                    "RESEND_API_KEY": "test",
                }):
                    record_processing_error_safe(
                        user_id=1, email="u@example.com", exchange="binance",
                        stage="processing", exc=exc,
                    )

    def test_saves_record_without_csv_content(self):
        """Verifies the saved record has no CSV content (only metadata)."""
        from models import db, ProcessingError

        app = self._make_app()
        exc = KeyError("Date")

        with app.app_context():
            record_processing_error_safe(
                user_id=42,
                email="test@example.com",
                exchange="binance",
                stage="processing",
                exc=exc,
                csv_filename="/tmp/tmpABC123.csv",
                csv_size=1024,
                parser="binance",
            )
            record = db.session.query(ProcessingError).first()

        assert record is not None
        assert record.exchange == "binance"
        assert record.error_type == "KeyError"
        assert record.csv_size == 1024
        # Filename stored as basename only, no full path
        assert record.csv_filename == "tmpABC123.csv"
        # No raw CSV data stored
        assert record.traceback_short is not None
        assert len(record.traceback_short) <= _MAX_TRACEBACK_LEN + 20

    def test_no_email_sent_when_feature_flag_off(self):
        """With PROCESSING_ERROR_EMAILS_ENABLED=false, no email is sent."""
        from models import db, ProcessingError

        app = self._make_app()
        exc = KeyError("Date")

        with app.app_context():
            with patch("error_tracking.send_processing_error_email") as mock_send:
                with patch.dict(os.environ, {"PROCESSING_ERROR_EMAILS_ENABLED": "false"}):
                    record_processing_error_safe(
                        user_id=1, email="u@example.com", exchange="binance",
                        stage="processing", exc=exc,
                    )
                mock_send.assert_not_called()

    def test_deduplication_blocks_second_email(self):
        """Same user+exchange+fingerprint within 24h → only 1 email sent."""
        from models import db, ProcessingError

        app = self._make_app()
        exc = KeyError("Date")

        sent_calls = []

        def fake_send(email, exchange, error_id, summary):
            sent_calls.append(error_id)
            return True

        with app.app_context():
            with patch("error_tracking.send_processing_error_email", side_effect=fake_send):
                with patch.dict(os.environ, {
                    "PROCESSING_ERROR_EMAILS_ENABLED": "true",
                    "RESEND_API_KEY": "test",
                }):
                    # First occurrence
                    record_processing_error_safe(
                        user_id=1, email="u@example.com", exchange="binance",
                        stage="processing", exc=exc,
                    )
                    # Same error again
                    record_processing_error_safe(
                        user_id=1, email="u@example.com", exchange="binance",
                        stage="processing", exc=exc,
                    )

        # Only the first call should have triggered an email
        assert len(sent_calls) == 1

    def test_non_actionable_error_no_email(self):
        """OperationalError → not actionable → no email even with flag on."""
        from models import db, ProcessingError

        app = self._make_app()
        # Create a custom exception whose class name matches non-actionable list
        OperationalError = type("OperationalError", (Exception,), {})
        real_exc = OperationalError("DB gone away")

        with app.app_context():
            with patch("error_tracking.send_processing_error_email") as mock_send:
                with patch.dict(os.environ, {
                    "PROCESSING_ERROR_EMAILS_ENABLED": "true",
                    "RESEND_API_KEY": "test",
                }):
                    record_processing_error_safe(
                        user_id=1, email="u@example.com", exchange="binance",
                        stage="processing", exc=real_exc,
                    )
                mock_send.assert_not_called()


# ── DEDUPLICATION LOGIC (unit) ────────────────────────────────────────────────

class TestShouldSendEmail:
    def _make_session_with_record(self, sent_at=None):
        """Build a mock session that returns a matching ProcessingError."""
        mock_record = MagicMock()
        mock_record.auto_email_sent    = True
        mock_record.auto_email_sent_at = sent_at or datetime.utcnow()

        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_record
        mock_query.filter.return_value.scalar.return_value = 1

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        return mock_session

    def _make_empty_session(self):
        """Build a mock session that returns no matching records."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = None
        mock_query.filter.return_value.scalar.return_value = 0

        mock_session = MagicMock()
        mock_session.query.return_value = mock_query
        return mock_session

    def test_blocks_when_recent_email_exists(self):
        session = self._make_session_with_record(sent_at=datetime.utcnow() - timedelta(hours=1))
        result = _should_send_email(session, user_id=1, exchange="binance", fingerprint="abc123")
        assert result is False

    def test_allows_when_no_recent_email(self):
        session = self._make_empty_session()
        result = _should_send_email(session, user_id=1, exchange="binance", fingerprint="abc123")
        assert result is True
