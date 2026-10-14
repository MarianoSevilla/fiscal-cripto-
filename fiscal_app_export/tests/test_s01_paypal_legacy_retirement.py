"""S01: impedir cualquier reactivación del legado PayPal.

No se ejecutan llamadas externas. Pruebas AST fail-closed sobre las rutas
históricas, los símbolos de compatibilidad y los identificadores retenidos.
"""
import ast
from pathlib import Path

from models import FiscalAdvisoryRequest

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
GUARD = "refuse_advisory_financial_operation"
HELPERS = (
    "_paypal_get_access_token",
    "_paypal_create_order",
    "_paypal_capture_order",
    "_on_payment_completed",
)
ROUTES = ("pago_iniciar", "pago_paypal_capture", "paypal_webhook")


def _tree():
    return ast.parse(APP_PATH.read_text(encoding="utf-8"))


def _function(name):
    funcs = [x for x in _tree().body if isinstance(x, ast.FunctionDef) and x.name == name]
    assert len(funcs) == 1, f"Se esperaba exactamente una definición de {name}"
    return funcs[0]


def _assert_no_body_except_deny(func):
    # Ignorar docstring, exigir primera y única expresión ejecutable.
    body = list(func.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body.pop(0)
    assert len(body) == 1, f"{func.name}: logic residual could accept money"
    expr = body[0]
    assert isinstance(expr, ast.Expr) and isinstance(expr.value, ast.Call)
    assert isinstance(expr.value.func, ast.Name)
    assert expr.value.func.id == GUARD
    assert not expr.value.args and not expr.value.keywords


def test_paypal_helpers_and_routes_contain_no_executable_provider_code():
    for name in HELPERS + ROUTES:
        _assert_no_body_except_deny(_function(name))


def test_all_retired_routes_still_frozen_and_keep_original_urls():
    expected = {
        "pago_iniciar": "/api/pago/iniciar/<token>",
        "pago_paypal_capture": "/api/pago/paypal/capture",
        "paypal_webhook": "/api/webhooks/paypal",
    }
    for name, url in expected.items():
        fun = _function(name)
        decorators = [ast.unparse(x) for x in fun.decorator_list]
        assert any("app.route" in d and repr(url) in d for d in decorators)
        assert any(d.startswith("advisory_financial_prefreeze(") for d in decorators)
    assert any("html=True" in ast.unparse(x)
               for x in _function("pago_paypal_capture").decorator_list)


def test_paypal_runtime_secrets_and_network_endpoints_no_longer_loaded():
    source = APP_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "_PAYPAL_CLIENT_SECRET",
        "_PAYPAL_CLIENT_ID",
        "_PAYPAL_BASE_URL",
        "_PAYPAL_WEBHOOK_ID",
        "api-m.paypal.com",
        "api-m.sandbox.paypal.com",
        "/v1/oauth2/token",
        "/v2/checkout/orders",
        "verify-webhook-signature",
        "requests.post(",
    ):
        assert forbidden not in source, f"PayPal legacy networking: {forbidden}"
    assignments = [
        node for node in _tree().body if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_PAYPAL_ENABLED"
                for t in node.targets)
    ]
    assert len(assignments) == 1
    assert isinstance(assignments[0].value, ast.Constant)
    assert assignments[0].value.value is False


def test_legacy_paypal_payment_evidence_is_still_mapped_readable():
    from sqlalchemy import String
    for field in ("paypal_order_id", "paypal_capture_id", "payment_provider"):
        column = FiscalAdvisoryRequest.__table__.columns[field]
        assert isinstance(column.type, String)
        assert column.nullable
    # Mantener datos históricos también en serialización del expediente.
    model = (ROOT / "models.py").read_text(encoding="utf-8")
    for field in ("paypal_order_id", "paypal_capture_id"):
        assert f'"{field}": self.{field}' in model


def test_stripe_and_prefreeze_integrations_are_preserved():
    source = APP_PATH.read_text(encoding="utf-8")
    webhook = _function("stripe_webhook")
    decorators = [ast.unparse(x) for x in webhook.decorator_list]
    assert any("advisory_financial_prefreeze" in x for x in decorators)
    assert "Webhook.construct_event" in ast.get_source_segment(source, webhook)
    assert "STRIPE_WEBHOOK_SECRET" in ast.get_source_segment(source, webhook)
    for name in ("advisory_enviar_presupuesto", "pago_info"):
        assert any("advisory_financial_prefreeze" in ast.unparse(x)
                   for x in _function(name).decorator_list)
