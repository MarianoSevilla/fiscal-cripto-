"""U01 -> S01 retirement regression: isolated legacy endpoint is fail-closed.

Previously U01 verified sanitized logs when a PayPal order was created.
The business decision is now to remove ALL PayPal order creation, so the
correct acceptance criterion is no provider/network/SQL/PII side effects.
"""
import ast
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask
from werkzeug.exceptions import ServiceUnavailable

SYNTHETIC_TOKEN = "u01-fictitious-payment-token-never-production"
SYNTHETIC_EMAIL = "u01-fictitious@example.invalid"
SENSITIVE = f"PayPal sensitive token: {SYNTHETIC_TOKEN}; {SYNTHETIC_EMAIL}"


class PayPalRetirementSafeLoggingTests(unittest.TestCase):
    def setUp(self):
        self.flask_app = Flask("u01-retired-paypal-isolated")
        self.flask_app.config["TESTING"] = True
        self.query = Mock()
        self.session = Mock()
        self.provider = Mock()
        self.refuse = Mock(side_effect=ServiceUnavailable(
            description="Advisory financial operations suspended."
        ))
        namespace = {
            "app": self.flask_app,
            "_PAYPAL_ENABLED": True,  # Even a forced legacy toggle cannot pay
            "FiscalAdvisoryRequest": SimpleNamespace(query=self.query),
            "db": SimpleNamespace(session=self.session),
            "_paypal_create_order": self.provider,
            "refuse_advisory_financial_operation": self.refuse,
        }
        path = Path(__file__).resolve().parents[1] / "app.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        handler = copy.deepcopy(next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "pago_iniciar"
        ))
        # Deliberately strip PREFREEZE, auth and rate limits:
        # the retired handler MUST remain safe by itself.
        handler.decorator_list = []
        module = ast.Module(body=[handler], type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(path), "exec"), namespace)
        self.flask_app.add_url_rule(
            "/api/pago/iniciar/<token>",
            view_func=namespace["pago_iniciar"],
            methods=["POST"],
        )
        self.client = self.flask_app.test_client()

    def _request_and_assert(self, token=SYNTHETIC_TOKEN):
        with patch("requests.sessions.Session.request",
                   side_effect=AssertionError("PayPal provider call forbidden")), \
             patch.object(self.flask_app.logger, "error") as log_error:
            response = self.client.post(
                "/api/pago/iniciar/" + token,
                headers={"User-Agent": "synthetic"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(SYNTHETIC_EMAIL, response.get_data(as_text=True))
        self.assertNotIn(SYNTHETIC_TOKEN, response.get_data(as_text=True))
        self.assertNotIn(SENSITIVE, response.get_data(as_text=True))
        self.provider.assert_not_called()
        self.query.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.rollback.assert_not_called()
        log_error.assert_not_called()
        return response

    def test_original_u01_token_does_not_create_order(self):
        self._request_and_assert()
        self.refuse.assert_called_once_with()

    def test_fake_provider_success_cannot_be_reached(self):
        self.provider.return_value = {
            "order_id": "U01-SYNTHETIC-ORDER",
            "approval_url": "https://provider.example.invalid/approve",
        }
        response = self._request_and_assert()
        self.assertNotIn("redirect_url", response.get_data(as_text=True))

    def test_fake_provider_timeout_cannot_be_reached(self):
        self.provider.side_effect = TimeoutError(SENSITIVE)
        self._request_and_assert()

    def test_fake_provider_http_error_cannot_be_reached(self):
        self.provider.side_effect = RuntimeError(SENSITIVE)
        self._request_and_assert()

    def test_fake_commit_failure_cannot_be_reached(self):
        self.session.commit.side_effect = RuntimeError(SENSITIVE)
        self._request_and_assert()

    def test_no_token_is_returned_after_suspension(self):
        self._request_and_assert("fictional-legacy-token-variant")

    def test_repeated_requests_do_not_retry_provider(self):
        for _ in range(3):
            self._request_and_assert()
        self.assertEqual(self.refuse.call_count, 3)


if __name__ == "__main__":
    unittest.main()
