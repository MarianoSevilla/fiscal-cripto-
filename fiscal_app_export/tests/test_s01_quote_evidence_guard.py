"""S01-AUD-001: reenviar presupuestos no puede destruir evidencia financiera.

Se extrae la función real de app.py sin sus decoradores *solo* para tests,
con ORM SQLite efímero y correo simulado; producción sigue PREFREEZE 503.
"""
import ast
import copy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from flask import Flask, jsonify, request
import pytest

from advisory_s01_pricing import (
    calculate_s01_quote, QuotePricingError, COMMISSION_RATE_BPS,
)
from models import (
    db, User, FiscalAdvisoryRequest, FiscalAdvisoryStatusHistory,
    AdvisoryAuditLog, S01StripeCheckoutAttempt,
)

ROUTE = "/__synthetic__/advisor/<int:req_id>/quote"
ORIGINAL_TOKEN = "A" * 43


@pytest.fixture
def isolated_quote(tmp_path):
    app = Flask("s01-quote-evidence-test")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(tmp_path / "s01_quote.sqlite"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    email = Mock(return_value=True)
    app_py = Path(__file__).resolve().parents[1] / "app.py"
    module = ast.parse(app_py.read_text(encoding="utf-8"))
    fn = copy.deepcopy(next(
        x for x in module.body if isinstance(x, ast.FunctionDef)
        and x.name == "advisory_enviar_presupuesto"
    ))
    fn.decorator_list = []
    ast.fix_missing_locations(fn)
    namespace = dict(
        db=db,
        request=request,
        jsonify=jsonify,
        FiscalAdvisoryRequest=FiscalAdvisoryRequest,
        FiscalAdvisoryStatusHistory=FiscalAdvisoryStatusHistory,
        AdvisoryAuditLog=AdvisoryAuditLog,
        S01StripeCheckoutAttempt=S01StripeCheckoutAttempt,
        calculate_s01_quote=calculate_s01_quote,
        QuotePricingError=QuotePricingError,
        COMMISSION_RATE_BPS=COMMISSION_RATE_BPS,
        current_user=SimpleNamespace(id=1),
        datetime=datetime,
        _APP_BASE_URL="https://example.invalid",
        _send_advisory_quote_email=email,
    )
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(app_py), "exec"), namespace)
    app.add_url_rule(
        ROUTE, view_func=namespace["advisory_enviar_presupuesto"], methods=["POST"],
    )

    with app.app_context():
        db.create_all()
        db.session.add(User(
            id=1, email="fictitious-advisor@example.invalid",
            full_name="Asesor ficticio", role="fiscal_advisor",
        ))
        db.session.flush()
        item = FiscalAdvisoryRequest(
            full_name="Cliente ficticio",
            email="fictitious-client@example.invalid",
            case_description="Caso sintético de seguridad S01",
            tax_residence_country="España",
            tax_year=2025,
            service_type="presupuesto_personalizado",
            status="quote_sent",
            quoted_amount=26000,
            rafa_fee_cents=20000,
            commission_cents=6000,
            commission_rate_bps=3000,
            payment_link_token=ORIGINAL_TOKEN,
        )
        db.session.add(item)
        db.session.commit()
        yield app, item.id, email
        db.session.remove()
        db.drop_all()


def _quote(app, advisory_id, *, fee=230):
    return app.test_client().post(
        ROUTE.replace("<int:req_id>", str(advisory_id)),
        json={"amount_euros": fee, "message": "Cotización revisada sintética"},
    )


def _record(advisory_id):
    db.session.expire_all()
    a = db.session.get(FiscalAdvisoryRequest, advisory_id)
    return {
        "status": a.status, "paypal_order_id": a.paypal_order_id,
        "paypal_capture_id": a.paypal_capture_id,
        "stripe_checkout_session_id": a.stripe_checkout_session_id,
        "stripe_payment_intent_id": a.stripe_payment_intent_id,
        "payment_provider": a.payment_provider,
        "amount_paid": a.amount_paid, "paid_at": a.paid_at,
        "quote_accepted_at": a.quote_accepted_at,
        "quote_token": a.payment_link_token,
        "quoted_amount": a.quoted_amount,
        "rafa_fee_cents": a.rafa_fee_cents,
        "commission_cents": a.commission_cents,
        "commission_rate_bps": a.commission_rate_bps,
        "history": FiscalAdvisoryStatusHistory.query.filter_by(
            request_id=advisory_id
        ).count(),
        "audit": AdvisoryAuditLog.query.filter_by(request_id=advisory_id).count(),
    }


@pytest.mark.parametrize("field,value", [
    ("paypal_order_id", "ORDER_SYNTHETIC_UNCERTAIN"),
    ("paypal_capture_id", "CAPTURE_SYNTHETIC_PAST"),
    ("stripe_checkout_session_id", "cs_test_prior_attempt"),
    ("stripe_payment_intent_id", "pi_synthetic_prior"),
    ("payment_provider", "paypal"),
    ("payment_provider", "stripe"),
    ("amount_paid", 0),  # 0 means recorded, not absence
    ("amount_paid", 26000),
    ("paid_at", datetime(2026, 10, 1)),
    ("quote_accepted_at", datetime(2026, 10, 1)),
])
def test_prior_financial_evidence_forbids_reissue_and_preserves_everything(
    isolated_quote, field, value,
):
    app, advisory_id, email = isolated_quote
    advisory = db.session.get(FiscalAdvisoryRequest, advisory_id)
    setattr(advisory, field, value)
    db.session.commit()
    before = _record(advisory_id)
    res = _quote(app, advisory_id)
    assert res.status_code == 409
    assert "conciliación" in res.get_json()["error"]
    assert _record(advisory_id) == before
    email.assert_not_called()


@pytest.mark.parametrize("status", ["reserved", "creating", "ready", "uncertain", "paid", "closed"])
def test_any_checkout_attempt_forbids_quote_replacement(
    isolated_quote, status,
):
    app, advisory_id, email = isolated_quote
    attempt_id = str(uuid4())
    db.session.add(S01StripeCheckoutAttempt(
        id=attempt_id, advisory_id=advisory_id,
        quote_fingerprint="a" * 64,
        idempotency_key="s01-checkout-v1-" + attempt_id,
        expected_amount_cents=26000,
        currency="eur", status=status,
    ))
    db.session.commit()
    before = _record(advisory_id)
    res = _quote(app, advisory_id)
    assert res.status_code == 409
    assert _record(advisory_id) == before
    assert S01StripeCheckoutAttempt.query.filter_by(advisory_id=advisory_id).one().status == status
    email.assert_not_called()


def test_normal_quote_reissue_without_financial_activity_remains_possible(isolated_quote):
    app, advisory_id, email = isolated_quote
    res = _quote(app, advisory_id)
    assert res.status_code == 200
    advisory = db.session.get(FiscalAdvisoryRequest, advisory_id)
    db.session.refresh(advisory)
    assert (advisory.rafa_fee_cents, advisory.commission_cents, advisory.quoted_amount) == (
        23000, 6900, 29900,
    )
    assert advisory.payment_link_token != ORIGINAL_TOKEN
    assert FiscalAdvisoryStatusHistory.query.filter_by(request_id=advisory_id).count() == 1
    assert AdvisoryAuditLog.query.filter_by(request_id=advisory_id).count() == 1
    email.assert_called_once()


def test_bad_amount_never_changes_stored_quote(isolated_quote):
    app, advisory_id, email = isolated_quote
    before = _record(advisory_id)
    assert _quote(app, advisory_id, fee="12.345").status_code == 400
    assert _record(advisory_id) == before
    email.assert_not_called()


def test_status_and_missing_request_remain_blocked(isolated_quote):
    app, advisory_id, email = isolated_quote
    a = db.session.get(FiscalAdvisoryRequest, advisory_id)
    a.status = "paid_received"
    db.session.commit()
    before = _record(advisory_id)
    assert _quote(app, advisory_id).status_code == 409
    assert _record(advisory_id) == before
    assert _quote(app, 99999999).status_code == 404
    email.assert_not_called()


def test_real_quote_handler_locks_before_financial_guard_and_never_erases_paypal():
    path = Path(__file__).resolve().parents[1] / "app.py"
    root = ast.parse(path.read_text(encoding="utf-8"))
    handler = next(x for x in root.body if isinstance(x, ast.FunctionDef)
                   and x.name == "advisory_enviar_presupuesto")
    source = ast.get_source_segment(path.read_text(encoding="utf-8"), handler)
    assert ".with_for_update()" in source
    assert source.index(".with_for_update()") < source.index("advisory.paypal_order_id is not None")
    assert source.index("S01StripeCheckoutAttempt.query.filter_by") < source.index("advisory.quoted_amount       =")
    assert "advisory.paypal_order_id     = None" not in source
    assert "advisory.paypal_capture_id   = None" not in source
    assert "refuse_advisory_financial_operation" not in source
    assert any("advisory_financial_prefreeze" in ast.unparse(x)
               for x in handler.decorator_list)
