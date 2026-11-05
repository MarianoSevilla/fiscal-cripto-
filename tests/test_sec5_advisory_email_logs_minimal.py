"""SEC5: no registrar PII ni texto de excepciones del proveedor de correo.

Pruebas sintéticas sobre las funciones reales de app.py extraídas mediante AST.
No arrancan Flask, PostgreSQL, Stripe ni realizan envíos con Resend.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "fiscal_app_export" / "app.py"
PRIVATE_EMAIL = "cliente-privado@example.invalid"
PRIVATE_NAME = "NOMBRE_PRIVADO_ENVIADO"
PRIVATE_CASE = "RELATO_FISCAL_PRIVADO_ENVIADO"
PRIVATE_TOKEN = "TOKEN_PAGO_PRIVADO"


SEND_FUNCTIONS = (
    "_send_advisory_confirmation_email",
    "_send_advisory_internal_notification",
    "_send_advisory_message_email",
    "_send_advisory_quote_email",
    "_send_advisory_payment_confirmed_email",
    "_send_advisory_payment_internal_notification",
    "_send_advisory_status_update_email",
)


def _functions_for_test(*, configured=True, status_enabled=True):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in SEND_FUNCTIONS
    ]
    assert len(functions) == len(SEND_FUNCTIONS)

    mailer = Mock()
    logger = Mock()
    deps = {
        "resend": SimpleNamespace(
            api_key="fake-key" if configured else "", Emails=mailer
        ),
        "app": SimpleNamespace(logger=logger),
        "_ADVISORY_NOTIFY_EMAILS": ["interno@example.invalid"],
        "_RESEND_FROM_DISPLAY": "Portal <servicio@example.invalid>",
        "_APP_BASE_URL": "https://example.invalid",
        "_ADVISORY_STATUS_EMAILS_ENABLED": status_enabled,
        "advisory_confirmation_email": lambda request: ("html", "text"),
        "advisory_message_email": lambda request, msg: ("html", "text"),
        "advisory_quote_email": lambda request, url: ("html", "text"),
        "advisory_payment_confirmed_email": lambda request: ("html", "text"),
        "advisory_payment_internal_email": lambda request: ("html", "text"),
        "advisory_status_email": lambda request, note, app_base_url: ("html", "text"),
    }
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), deps)
    return deps, mailer, logger


def _test_request():
    return SimpleNamespace(
        id=314,
        email=PRIVATE_EMAIL,
        full_name=PRIVATE_NAME,
        case_description=PRIVATE_CASE,
        status="under_review",
        quoted_amount=5000,
        amount_paid=5000,
    )


def _invoke(function, request):
    if function == "_send_advisory_message_email":
        return request and function, ("Mensaje privado",)
    if function == "_send_advisory_quote_email":
        return function, (f"https://example.invalid/pago?token={PRIVATE_TOKEN}",)
    return function, ()


def _assert_no_private_data_in_logs(logger):
    captured = repr(logger.method_calls)
    for secret in (PRIVATE_EMAIL, PRIVATE_NAME, PRIVATE_CASE, PRIVATE_TOKEN):
        assert secret not in captured, f"PII filtrada en logs ({secret[:8]})"


@pytest.mark.parametrize("func_name", SEND_FUNCTIONS)
@pytest.mark.parametrize("provider_fails", [False, True])
def test_advisory_mail_does_not_log_pii_or_vendor_exception(func_name, provider_fails):
    deps, mailer, logger = _functions_for_test()
    request = _test_request()
    if provider_fails:
        mailer.send.side_effect = RuntimeError(
            f"Fallo proveedor {PRIVATE_EMAIL} {PRIVATE_NAME} {PRIVATE_CASE} {PRIVATE_TOKEN}"
        )
    else:
        mailer.send.return_value = SimpleNamespace(
            id=f"id-{PRIVATE_EMAIL}-{PRIVATE_TOKEN}"
        )

    func = deps[func_name]
    _, args = _invoke(func_name, request)
    func(request, *args)
    mailer.send.assert_called_once()
    _assert_no_private_data_in_logs(logger)

    # La operación mantiene su comportamiento: una llamada real (falsa) al
    # proveedor con el correo necesario; se minimizan únicamente los logs.
    payload = mailer.send.call_args.args[0]
    if func_name != "_send_advisory_internal_notification":
        assert payload["to"] == [PRIVATE_EMAIL]


@pytest.mark.parametrize(
    "func_name",
    ("_send_advisory_message_email", "_send_advisory_quote_email"),
)
def test_mail_configuration_failures_keep_only_case_id_in_logs(func_name):
    deps, mailer, logger = _functions_for_test(configured=False)
    _, args = _invoke(func_name, _test_request())
    assert deps[func_name](_test_request(), *args) is False
    mailer.send.assert_not_called()
    logger.error.assert_called_once()
    _assert_no_private_data_in_logs(logger)
    assert "314" in repr(logger.error.call_args)


def test_disabled_status_notification_never_logs_email_address():
    deps, mailer, logger = _functions_for_test(status_enabled=False)
    deps["_send_advisory_status_update_email"](_test_request())
    mailer.send.assert_not_called()
    logger.info.assert_called_once()
    _assert_no_private_data_in_logs(logger)
