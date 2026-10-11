"""U01: exercise the original payment handler with Flask and synthetic doubles.

Compile only pago_iniciar from its AST, without importing app.py: application
imports bootstrap the database and can inherit production environment variables.
The isolated Flask app tests HTTP serialization; DB/provider calls are mocks.
"""

import ast
import copy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request


SYNTHETIC_TOKEN = "u01-fictitious-payment-token-never-production"
SYNTHETIC_URL = f"https://payments.example.invalid/pagar/{SYNTHETIC_TOKEN}"
SYNTHETIC_EMAIL = "u01-fictitious@example.invalid"
SENSITIVE_MESSAGE = (
    f"provider error: token={SYNTHETIC_TOKEN}; "
    f"payment_url={SYNTHETIC_URL}; email={SYNTHETIC_EMAIL}"
)
GENERIC_ERROR = "No se pudo conectar con PayPal. Inténtalo de nuevo."


class PayPalSafeLoggingTests(unittest.TestCase):
    def setUp(self):
        self.flask_app = Flask("u01-isolated-payment")
        self.flask_app.config["TESTING"] = True
        self.advisory = SimpleNamespace(
            id=701,
            status="quote_sent",
            quote_expires_at=datetime.utcnow() + timedelta(days=1),
            paypal_order_id=None,
            quote_accepted_at=None,
            quote_acceptance_ip=None,
            quote_acceptance_user_agent=None,
        )
        self.query = Mock()
        self.query.filter_by.return_value = self.query
        self.query.with_for_update.return_value = self.query
        self.query.first.return_value = self.advisory
        self.db_session = Mock()
        self.create_order = Mock()
        namespace = {
            "app": self.flask_app,
            "_PAYPAL_ENABLED": True,
            "FiscalAdvisoryRequest": SimpleNamespace(query=self.query),
            "db": SimpleNamespace(session=self.db_session),
            "_paypal_create_order": self.create_order,
            "datetime": datetime,
            "jsonify": jsonify,
            "request": request,
        }
        source = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        handler = copy.deepcopy(
            next(node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == "pago_iniciar")
        )
        handler.decorator_list = []
        module = ast.Module(body=[handler], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(source), "exec"), namespace)
        self.flask_app.add_url_rule(
            "/api/pago/iniciar/<token>",
            view_func=namespace["pago_iniciar"],
            methods=["POST"],
        )
        self.client = self.flask_app.test_client()
        # Fail closed if a test accidentally starts using a real provider.
        self.network_guard = patch(
            "socket.socket", side_effect=AssertionError("U01 tests forbid network")
        )
        self.network_guard.start()
        self.addCleanup(self.network_guard.stop)

    def _post(self):
        return self.client.post(
            f"/api/pago/iniciar/{SYNTHETIC_TOKEN}",
            headers={"User-Agent": "U01 synthetic client"},
        )

    def _assert_safe_failure(self, response, logs, expected_category):
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json(), {"error": GENERIC_ERROR})
        self.assertEqual(len(logs.records), 1)
        record = logs.records[0]
        # Check format arguments and exception metadata as well as rendered text.
        emitted = repr(vars(record)) + response.get_data(as_text=True)
        for forbidden in (SYNTHETIC_TOKEN, SYNTHETIC_URL,
                          SYNTHETIC_EMAIL, SENSITIVE_MESSAGE):
            self.assertNotIn(forbidden, emitted)
        self.assertEqual(
            record.getMessage(),
            f"paypal_create_order_failed advisory_id=701 "
            f"error_category={expected_category}",
        )
        self.assertIsNone(record.exc_info)
        self.assertIsNone(record.exc_text)
        self.assertIsNone(record.stack_info)
        self.db_session.rollback.assert_called_once_with()
        self.db_session.commit.assert_not_called()
        self.create_order.assert_called_once_with(self.advisory)

    def test_provider_error_does_not_leak_sensitive_message(self):
        self.create_order.side_effect = RuntimeError(SENSITIVE_MESSAGE)
        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()
        self._assert_safe_failure(response, logs, "unexpected_error")
        self.assertIsNone(self.advisory.paypal_order_id)

    def test_exception_class_name_is_not_logged_without_allowlisting(self):
        sensitive_type = type(
            f"Error_{SYNTHETIC_TOKEN}_{SYNTHETIC_EMAIL}", (Exception,), {}
        )
        self.create_order.side_effect = sensitive_type(SENSITIVE_MESSAGE)
        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()
        self._assert_safe_failure(response, logs, "unexpected_error")

    def test_http_error_keeps_safe_diagnostic_category(self):
        http_error = type("HTTPError", (Exception,), {})
        self.create_order.side_effect = http_error(SENSITIVE_MESSAGE)
        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()
        self._assert_safe_failure(response, logs, "http_error")

    def test_timeout_keeps_safe_diagnostic_category(self):
        timeout_error = type("ReadTimeout", (Exception,), {})
        self.create_order.side_effect = timeout_error(SENSITIVE_MESSAGE)
        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()
        self._assert_safe_failure(response, logs, "timeout")

    def test_logging_does_not_reload_expired_advisory_after_rollback(self):
        class ExpiringAdvisory(SimpleNamespace):
            @property
            def id(self):
                if getattr(self, "expired", False):
                    raise AssertionError("Logging must not reload an expired ORM row")
                return 701

        fields = vars(self.advisory).copy()
        del fields["id"]
        self.advisory = ExpiringAdvisory(**fields)
        self.query.first.return_value = self.advisory
        self.db_session.rollback.side_effect = lambda: setattr(
            self.advisory, "expired", True
        )
        self.create_order.side_effect = RuntimeError(SENSITIVE_MESSAGE)
        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()
        self._assert_safe_failure(response, logs, "unexpected_error")

    def test_malformed_provider_result_preserves_error_and_rollback(self):
        self.create_order.return_value = {}
        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()
        self._assert_safe_failure(response, logs, "invalid_response")

    def test_commit_failure_preserves_rollback_and_generic_response(self):
        self.create_order.return_value = {
            "order_id": "U01-SYNTHETIC-ORDER",
            "approval_url": "https://provider.example.invalid/approve",
        }
        self.db_session.commit.side_effect = RuntimeError(SENSITIVE_MESSAGE)
        with self.assertLogs(self.flask_app.logger, level="ERROR") as logs:
            response = self._post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json(), {"error": GENERIC_ERROR})
        self.db_session.commit.assert_called_once_with()
        self.db_session.rollback.assert_called_once_with()
        self.assertEqual(
            logs.records[0].getMessage(),
            "paypal_create_order_failed advisory_id=701 "
            "error_category=unexpected_error",
        )
        self.assertIsNone(logs.records[0].exc_info)
        emitted = repr(vars(logs.records[0])) + response.get_data(as_text=True)
        for forbidden in (SYNTHETIC_TOKEN, SYNTHETIC_URL,
                          SYNTHETIC_EMAIL, SENSITIVE_MESSAGE):
            self.assertNotIn(forbidden, emitted)

    def test_success_preserves_order_commit_and_redirect_response(self):
        approval_url = "https://provider.example.invalid/approve/U01-SYNTHETIC-ORDER"
        self.create_order.return_value = {
            "order_id": "U01-SYNTHETIC-ORDER",
            "approval_url": approval_url,
        }
        with patch.object(self.flask_app.logger, "error") as log_error:
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(), {"ok": True, "redirect_url": approval_url}
        )
        self.assertEqual(self.advisory.paypal_order_id, "U01-SYNTHETIC-ORDER")
        self.assertIsNotNone(self.advisory.quote_accepted_at)
        self.assertEqual(self.advisory.quote_acceptance_user_agent,
                         "U01 synthetic client")
        self.query.filter_by.assert_called_once_with(
            payment_link_token=SYNTHETIC_TOKEN
        )
        self.query.with_for_update.assert_called_once_with()
        self.create_order.assert_called_once_with(self.advisory)
        self.db_session.commit.assert_called_once_with()
        self.db_session.rollback.assert_not_called()
        log_error.assert_not_called()


if __name__ == "__main__":
    unittest.main()
