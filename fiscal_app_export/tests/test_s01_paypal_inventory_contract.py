"""S01-R01: offline aggregate-only contract checks, without a database."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location(
    "s01_paypal_inventory_local", TOOLS / "s01_paypal_inventory_local.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_only_aggregate_rows_leave_the_database():
    statement = module.build_aggregate_sql()
    assert statement.startswith("SELECT COUNT(*) FILTER")
    assert " FROM public.fiscal_advisory_requests" in statement
    assert statement.count("COUNT(*) FILTER") == len(module.COUNTS)
    assert "paypal_order_id" in statement
    assert "paypal_capture_id" in statement
    assert "email" not in statement
    assert "full_name" not in statement
    assert "billing_" not in statement
    assert "LIMIT" not in statement


def test_whitelist_and_no_raw_id_export():
    for good in ("paypal_order_id", "paypal_capture_id"):
        sql = module.duplicated_refs_sql(good)
        assert "SELECT COUNT(*) FROM (" in sql
        assert "HAVING COUNT(*) > 1" in sql
    for bad in ("email", "full_name", "paypal_order_id; DROP TABLE users"):
        with pytest.raises(ValueError):
            module.duplicated_refs_sql(bad)


def test_metric_identifiers_unique_and_all_conditions_fixed():
    names = [name for name, _ in module.COUNTS]
    assert len(names) == len(set(names))
    assert len(names) == 20
    assert names[0] == "expedientes_totales"
    assert names[1] == "expedientes_senal_paypal"
    assert all(condition and ";" not in condition for _, condition in module.COUNTS)


def test_guard_requires_read_only_before_any_counts():
    class FakeCursor:
        def __init__(self):
            self.count = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def execute(self, statement, *_):
            assert statement == "SHOW transaction_read_only"
            self.count += 1

        def fetchone(self):
            return ("off",)

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    # No real DB; intentionally bypass only schema lookups via monkeypatch,
    # keeping the READ ONLY proof mandatory.
    previous_columns = module.guard.columns
    previous_version = module.guard.version
    try:
        expected = {
            "paypal_order_id", "paypal_capture_id", "payment_provider",
            "amount_paid", "currency", "paid_at", "status", "is_test",
            "stripe_checkout_session_id", "stripe_payment_intent_id",
            "quote_accepted_at",
        }
        module.guard.columns = lambda *_: tuple(expected)
        module.guard.version = lambda *_: module.guard.PRE_REV
        with pytest.raises(module.guard.RehearsalError, match="READ ONLY"):
            module.aggregate_local_only(FakeConnection())
    finally:
        module.guard.columns = previous_columns
        module.guard.version = previous_version
