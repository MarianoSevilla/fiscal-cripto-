"""SEC5-PRIV: advisory metadata probe must remain count-only and fail-closed."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sec5_priv_advisory_file_probe as probe


def _counts(**changes):
    defaults = {
        "metadata_rows": 2, "linked_requests": 1, "linked_users": 2,
        "missing_requests": 0, "missing_users": 0,
        "unlinked_request_owners": 0, "ownership_mismatches": 1,
    }
    return {**defaults, **changes}


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def one(self):
        return self.value


class FakeConnection:
    def __init__(self, counts, readonly="on", fails=False):
        self.counts = counts
        self.readonly = readonly
        self.fails = fails
        self.statements = []
        self.rolled_back = False

    def begin(self):
        self.statements.append("BEGIN")
        return SimpleNamespace(rollback=self.rollback)

    def rollback(self):
        self.rolled_back = True
        self.statements.append("ROLLBACK")

    def exec_driver_sql(self, statement):
        self.statements.append(statement)
        if statement == "SHOW transaction_read_only":
            return FakeResult(self.readonly)
        return FakeResult(None)

    def execute(self, query):
        self.statements.append(str(query))
        if self.fails:
            raise RuntimeError("simulated SQL failure containing a private name")
        return FakeResult(self.counts)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class FakeEngine:
    def __init__(self, counts=None, *, dialect="postgresql", readonly="on", fails=False):
        self.dialect = SimpleNamespace(name=dialect)
        self.connection = FakeConnection(counts or _counts(), readonly, fails)

    def connect(self):
        return self.connection


def test_readonly_counts_and_no_document_lookup(monkeypatch):
    monkeypatch.setattr(probe, "inspect_runtime_role", lambda engine: {
        "status": "CANDIDATE_ONLY", "risk_flags": []
    })
    engine = FakeEngine()
    result = probe.inspect_advisory_file_metadata(engine)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["metadata_rows"] == 2
    assert result["linked_users"] == 2
    assert result["ownership_mismatches"] == 1
    assert not result["physical_files_verified"]
    assert not result["complete_inventory_proven"]
    assert not result["data_erasure_authorized"]
    assert engine.connection.statements[:3] == [
        "BEGIN", "SET TRANSACTION READ ONLY", "SHOW transaction_read_only"
    ]
    assert engine.connection.rolled_back
    query = probe.METADATA_QUERY.lower()
    for forbidden in (
        "f.file_name", "f.file_path", "f.file_type", "file_size",
        "email", "select *", "insert into", "delete from",
        "update ", "create ", "drop ", "alter ", "pg_read_file"
    ):
        assert forbidden not in query


def test_empty_metadata_is_not_proof_of_no_physical_files(monkeypatch):
    monkeypatch.setattr(probe, "inspect_runtime_role", lambda engine: {
        "status": "CANDIDATE_ONLY", "risk_flags": []
    })
    result = probe.inspect_advisory_file_metadata(
        FakeEngine(_counts(**{k: 0 for k in probe.COUNT_FIELDS}))
    )
    assert result["status"] == "NO_METADATA_ROWS"
    assert not result["physical_files_verified"]
    assert not result["complete_inventory_proven"]


@pytest.mark.parametrize("role", [
    {"status": "NEEDS_SEPARATION", "risk_flags": ["superuser"]},
    {"status": "CANDIDATE_ONLY", "risk_flags": ["create_database"]},
])
def test_privileged_login_refused_before_data_query(monkeypatch, role):
    monkeypatch.setattr(probe, "inspect_runtime_role", lambda engine: role)
    engine = FakeEngine()
    with pytest.raises(RuntimeError, match="Limited runtime login"):
        probe.inspect_advisory_file_metadata(engine)
    assert engine.connection.statements == []


def test_sqlite_refused_before_data_query():
    engine = FakeEngine(dialect="sqlite")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        probe.inspect_advisory_file_metadata(engine)
    assert engine.connection.statements == []


@pytest.mark.parametrize("data", [
    _counts(metadata_rows=None),
    _counts(ownership_mismatches=3),
    _counts(metadata_rows=-1),
    _counts(metadata_rows=True),
])
def test_indeterminate_or_impossible_counts_fail_closed(monkeypatch, data):
    monkeypatch.setattr(probe, "inspect_runtime_role", lambda engine: {
        "status": "CANDIDATE_ONLY", "risk_flags": []
    })
    engine = FakeEngine(data)
    with pytest.raises(RuntimeError):
        probe.inspect_advisory_file_metadata(engine)
    assert engine.connection.rolled_back


def test_transaction_readonly_failure_prevents_select(monkeypatch):
    monkeypatch.setattr(probe, "inspect_runtime_role", lambda engine: {
        "status": "CANDIDATE_ONLY", "risk_flags": []
    })
    engine = FakeEngine(readonly="off")
    with pytest.raises(RuntimeError, match="Read-only"):
        probe.inspect_advisory_file_metadata(engine)
    assert engine.connection.rolled_back
    assert probe.METADATA_QUERY not in engine.connection.statements


def test_query_failure_rolls_back_without_logging_pii(monkeypatch):
    monkeypatch.setattr(probe, "inspect_runtime_role", lambda engine: {
        "status": "CANDIDATE_ONLY", "risk_flags": []
    })
    engine = FakeEngine(fails=True)
    with pytest.raises(RuntimeError):
        probe.inspect_advisory_file_metadata(engine)
    assert engine.connection.rolled_back


def test_cli_optin_and_isolated_from_server(monkeypatch, capsys):
    monkeypatch.delenv("SEC5_PRIV_ADVISORY_FILE_PROBE", raising=False)
    assert probe.main() == 2
    assert "OPT_IN_REQUIRED" in capsys.readouterr().err
    appdir = Path(__file__).resolve().parents[1]
    for name in ("app.py", "startup_schema_gate.py"):
        assert "from sec5_priv_advisory_file_probe" not in (appdir / name).read_text()
