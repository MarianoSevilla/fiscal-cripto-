"""Verifica la composición S01 + PREFREEZE + firma Stripe, sin red/DB."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app.py"
STATIC = Path(__file__).resolve().parents[1] / "static" / "pagar.html"


def _func(tree, name):
    return next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _decorator_label(node):
    node = node.func if isinstance(node, ast.Call) else node
    return ast.unparse(node)


def test_prefreeze_is_innermost_stripe_webhook_decorator():
    """Flask invoca limiter que, a su vez, invoca el bloqueo ANTES del handler."""
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    fun = _func(tree, "stripe_webhook")
    decorators = [_decorator_label(x) for x in fun.decorator_list]
    assert decorators[-1] == "advisory_financial_prefreeze"
    assert decorators[0].startswith("app.route")
    assert "limiter.limit" in decorators[1]
    webhook_source = ast.get_source_segment(APP.read_text(encoding="utf-8"), fun)
    assert "Webhook.construct_event" in webhook_source
    assert "_STRIPE_WEBHOOK_SECRET" in webhook_source
    assert "json.loads(payload)" not in webhook_source
    assert 'return "", 200' not in webhook_source.split("Webhook.construct_event")[0]


def test_payment_completion_and_legacy_paypal_helpers_are_refused():
    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for name in (
        "_on_payment_completed",
        "_paypal_get_access_token",
        "_paypal_create_order",
        "_paypal_capture_order",
    ):
        fun = _func(tree, name)
        statements = [x for x in fun.body if not isinstance(x, ast.Expr) or not isinstance(x.value, ast.Constant)]
        assert statements
        first = statements[0]
        assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
        assert isinstance(first.value.func, ast.Name)
        assert first.value.func.id == "refuse_advisory_financial_operation"


def test_quote_and_old_payment_routes_are_frozen():
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    for name in (
        "advisory_enviar_presupuesto", "advisory_enviar_mensaje",
        "pago_iniciar", "pago_info", "pago_paypal_capture",
        "paypal_webhook", "stripe_webhook", "admin_advisory_change_status",
        "admin_advisory_delete",
    ):
        decorators = [_decorator_label(x) for x in _func(tree, name).decorator_list]
        assert "advisory_financial_prefreeze" in decorators
    html = STATIC.read_text(encoding="utf-8")
    assert "Pagos temporalmente suspendidos" in html
    assert "iniciarPago()" not in html
    assert "Pagar con PayPal" not in html


def test_no_checkout_route_exposed_by_s01_orchestrator():
    source = (APP.parent / "advisory_s01_test_orchestrator.py").read_text(encoding="utf-8")
    assert "@app.route(" not in source
    assert "@bp.route(" not in source
    assert "stripe.checkout.Session.create" not in source
    assert "resend.Emails.send" not in source
