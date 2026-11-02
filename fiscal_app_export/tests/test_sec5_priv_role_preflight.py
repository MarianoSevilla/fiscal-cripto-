"""SEC5-PRIV: ensure the explicit role-audit command is read-only and fail-closed."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sec5_priv_role_preflight import inspect_runtime_role, main, ROLE_QUERY

BOOL_FIELDS = {
    "same_session_role": True,
    "rolcanlogin": True,
    "rolsuper": False,
    "rolbypassrls": False,
    "rolcreaterole": False,
    "rolcreatedb": False,
    "rolreplication": False,
    "database_owner_membership": False,
    "public_schema_owner_membership": False,
    "public_object_owner_membership": False,
    "public_schema_create": False,
    "database_schema_create": False,
    "privileged_set_role": False,
}


class SyntheticResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def one(self):
        return self.value


class SyntheticConnection:
    def __init__(self, row, readonly="on"):
        self.row = row
        self.readonly = readonly
        self.calls = []
        self.rolled_back = False

    def begin(self):
        self.calls.append("BEGIN")
        return SimpleNamespace(rollback=self._rollback)

    def _rollback(self):
        self.calls.append("ROLLBACK")
        self.rolled_back = True

    def exec_driver_sql(self, sql):
        self.calls.append(sql)
        if sql == "SHOW transaction_read_only":
            return SyntheticResult(self.readonly)
        return SyntheticResult(None)

    def execute(self, statement):
        self.calls.append(str(statement))
        return SyntheticResult(self.row)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class SyntheticEngine:
    def __init__(self, row, name="postgresql", readonly="on"):
        self.dialect = SimpleNamespace(name=name)
        self.connection = SyntheticConnection(row, readonly)

    def connect(self):
        return self.connection


def test_clean_login_is_only_candidate_not_vault_proof():
    engine = SyntheticEngine({"pg_major": 18, **BOOL_FIELDS})
    result = inspect_runtime_role(engine)
    assert result["status"] == "CANDIDATE_ONLY"
    assert not result["vault_isolation_proven"]
    assert not result["production_authorized"]
    assert result["risk_flags"] == []
    assert engine.connection.calls[0:3] == [
        "BEGIN", "SET TRANSACTION READ ONLY", "SHOW transaction_read_only"
    ]
    assert engine.connection.calls[-1] == "ROLLBACK"


@pytest.mark.parametrize("flag", [
    "rolsuper", "rolbypassrls", "rolcreaterole", "rolcreatedb",
    "database_owner_membership", "public_schema_owner_membership",
    "public_object_owner_membership", "public_schema_create",
    "database_schema_create", "privileged_set_role",
])
def test_privileged_connection_is_not_safe(flag):
    engine = SyntheticEngine({"pg_major": 18, **BOOL_FIELDS, flag: True})
    result = inspect_runtime_role(engine)
    assert result["status"] == "NEEDS_SEPARATION"
    assert result["risk_flags"]


@pytest.mark.parametrize("flag", ["same_session_role", "rolcanlogin"])
def test_missing_session_or_login_status_fails(flag):
    engine = SyntheticEngine({"pg_major": 18, **BOOL_FIELDS, flag: False})
    assert inspect_runtime_role(engine)["status"] == "NEEDS_SEPARATION"


def test_readonly_failure_stops_before_catalog_query():
    engine = SyntheticEngine({"pg_major": 18, **BOOL_FIELDS}, readonly="off")
    with pytest.raises(RuntimeError, match="Read-only"):
        inspect_runtime_role(engine)
    assert engine.connection.rolled_back
    assert not any("FROM pg_roles" in sql for sql in engine.connection.calls)


def test_null_attribute_and_wrong_engine_fail_closed():
    for changed in ({"rolsuper": None}, {"rolsuper": "false"}):
        engine = SyntheticEngine({"pg_major": 18, **BOOL_FIELDS, **changed})
        with pytest.raises(RuntimeError, match="Indeterminate"):
            inspect_runtime_role(engine)
        assert engine.connection.rolled_back
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        inspect_runtime_role(SyntheticEngine({}, name="sqlite"))
    with pytest.raises(RuntimeError, match="18"):
        inspect_runtime_role(SyntheticEngine({"pg_major": 17, **BOOL_FIELDS}))


def test_cli_refuses_inadvertent_execution(monkeypatch, capsys):
    monkeypatch.delenv("SEC5_PRIV_ROLE_PREFLIGHT", raising=False)
    assert main() == 2
    assert "OPT_IN_REQUIRED" in capsys.readouterr().err


def test_catalog_only_and_no_live_runtime_side_effects():
    assert "FROM pg_roles" in ROLE_QUERY
    assert "FROM pg_database" in ROLE_QUERY
    assert "FROM pg_namespace" in ROLE_QUERY
    assert "FROM pg_class" in ROLE_QUERY
    for forbidden in (
        "pg_authid", "FROM users", "FROM fiscal_advisory_requests",
        "DELETE FROM", "UPDATE ", "INSERT INTO", "CREATE ROLE",
        "ALTER ROLE", "DROP ROLE", "PASSWORD", "pg_shadow"
    ):
        assert forbidden not in ROLE_QUERY.upper() if forbidden.isupper() else forbidden not in ROLE_QUERY
    app = (Path(__file__).resolve().parents[1] / "app.py").read_text()
    startup = (Path(__file__).resolve().parents[1] / "startup_schema_gate.py").read_text()
    assert "from sec5_priv_role_preflight" not in app
    assert "from sec5_priv_role_preflight" not in startup
