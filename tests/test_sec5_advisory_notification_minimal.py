"""Regresión SEC5: el aviso interno de asesoramiento no contiene datos del caso.

Se extrae la función de app.py mediante AST para probar la ruta real sin
importar Flask, arrancar servicios, conectar PostgreSQL ni enviar correos.
No se usan datos reales ni claves de proveedores.
"""

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


_SOURCE = Path(__file__).resolve().parents[1] / "fiscal_app_export" / "app.py"


class _AdvisoryWithPrivateFields:
    id = 314
    full_name = "NOMBRE_PRIVADO_DE_PRUEBA"
    email = "privado@example.invalid"
    phone = "+34000000000"
    case_description = "RELATO_FISCAL_PRIVADO_DE_PRUEBA"
    tax_year = 2025
    amount_paid = 19900
    billing_nif = "NIF_PRIVADO_DE_PRUEBA"

    def __getattribute__(self, name):
        # El correo debe consultar la referencia del caso, NUNCA otros datos.
        if name != "id":
            raise AssertionError(f"El aviso intenta consultar un dato personal: {name}")
        return object.__getattribute__(self, name)


def _notification_env(*, api_key="test-only", recipients=("asesor@example.invalid",)):
    source = ast.parse(_SOURCE.read_text(encoding="utf-8"), filename=str(_SOURCE))
    functions = [
        node
        for node in source.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_send_advisory_internal_notification"
    ]
    assert len(functions) == 1

    mailer = Mock()
    logger = Mock()
    scope = {
        "resend": SimpleNamespace(api_key=api_key, Emails=mailer),
        "_ADVISORY_NOTIFY_EMAILS": list(recipients),
        "_RESEND_FROM_DISPLAY": "Servicio <notificaciones@example.invalid>",
        "_APP_BASE_URL": "https://example.invalid",
        "app": SimpleNamespace(logger=logger),
    }
    isolated_ast = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(isolated_ast, str(_SOURCE), "exec"), scope)
    return scope["_send_advisory_internal_notification"], mailer, logger


def test_new_request_email_contains_only_case_reference_and_protected_panel_link():
    notify, mailer, logger = _notification_env()
    notify(_AdvisoryWithPrivateFields())
    mailer.send.assert_called_once()
    payload = mailer.send.call_args.args[0]

    assert payload["to"] == ["asesor@example.invalid"]
    assert payload["subject"] == "[Asesoramiento] Nueva solicitud #314"
    assert "Referencia: #314" in payload["text"]
    assert "https://example.invalid/admin/asesoramiento" in payload["text"]
    assert "NOMBRE_PRIVADO_DE_PRUEBA" not in str(payload)
    assert "RELATO_FISCAL_PRIVADO_DE_PRUEBA" not in str(payload)
    assert "privado@example.invalid" not in str(payload)
    assert "NIF_PRIVADO_DE_PRUEBA" not in str(payload)
    logger.error.assert_not_called()


@pytest.mark.parametrize(
    ("api_key", "recipients"),
    [
        ("", ("asesor@example.invalid",)),
        ("test-only", ()),
    ],
)
def test_new_request_notification_is_inert_when_delivery_not_configured(api_key, recipients):
    notify, mailer, logger = _notification_env(api_key=api_key, recipients=recipients)
    notify(_AdvisoryWithPrivateFields())
    mailer.send.assert_not_called()
    logger.error.assert_not_called()


def test_provider_failure_is_logged_without_rethrowing_or_logging_case_data():
    notify, mailer, logger = _notification_env()
    mailer.send.side_effect = RuntimeError("fallo sintético de Resend")
    notify(_AdvisoryWithPrivateFields())
    logger.error.assert_called_once()
    assert "NOMBRE_PRIVADO_DE_PRUEBA" not in str(logger.error.call_args)
    assert "RELATO_FISCAL_PRIVADO_DE_PRUEBA" not in str(logger.error.call_args)
