"""S01-G04 static invariants: no application import DDL or implicit web migration."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
BOOTSTRAP = ROOT / "bootstrap_db.py"
GATE = ROOT / "startup_schema_gate.py"
PROCFILE = ROOT / "Procfile"


def test_flask_application_import_has_no_create_all_or_emergency_ddl():
    source = APP.read_text(encoding="utf-8")
    parsed = ast.parse(source)
    for node in ast.walk(parsed):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr != "create_all", (
                "Implicit db.create_all is forbidden during Flask import"
            )
    assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS" not in source
    assert "ALTER TABLE fifo_reports ADD COLUMN IF NOT EXISTS" not in source
    assert "ALTER TABLE processing_errors ADD COLUMN IF NOT EXISTS" not in source


def test_procfile_only_verifies_schema_before_gunicorn():
    proc = PROCFILE.read_text(encoding="utf-8")
    assert "web: python startup_schema_gate.py && gunicorn " in proc
    assert "bootstrap_db.py" not in proc
    assert "flask db upgrade" not in proc
    assert "alembic upgrade" not in proc
    assert "db.create_all" not in proc


def test_startup_gate_remains_readonly_and_exact_revision():
    source = GATE.read_text(encoding="utf-8")
    assert "EXPECTED_HEAD = \"z9a0b1c2d3e4\"" in source
    assert "SET TRANSACTION READ ONLY" in source
    assert "transaction.rollback()" in source
    assert "REQUIRED_CONSTRAINTS" in source
    tree = ast.parse(source)
    methods = {"stamp", "upgrade", "create_all", "drop_all", "commit"}
    for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
        name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
        assert name not in methods, f"Startup gate must not invoke {name}"


def test_explicit_bootstrap_only_initializes_truly_empty_postgres():
    src = BOOTSTRAP.read_text(encoding="utf-8")
    assert "if not tables:" in src
    assert "db.create_all()" in src
    assert "_assert_pristine_current_schema(db.engine)" in src
    assert "stamp(revision=FRESH_SCHEMA_BASELINE)" in src


def test_offline_backup_rehearsal_proves_import_and_startup_gate():
    source = (ROOT / "tools" / "s01_rehearse_restored_backup.py").read_text(
        encoding="utf-8"
    )
    app_import = source.index('"Importación Flask sin DDL"')
    first_bootstrap = source.index('f"bootstrap_db.py pasada {repetition}"')
    startup = source.index('f"Gate de arranque READ ONLY pasada {repetition}"')
    assert app_import < first_bootstrap < startup
    assert "snapshot(conn) != before" in source
    assert "str(BASE / \"startup_schema_gate.py\")" in source
    assert "S01 G04 IMPORT: sin cambios en esquema ni historial OK" in source
    assert "S01 G04 STARTUP {repetition}: gate READ ONLY OK" in source
