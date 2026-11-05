"""SEC5-PRIV: verify that the empty-account scenario stays a CI-only rehearsal."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAB = ROOT / "fiscal_app_export/tests/qa_sec5_priv_record_lifecycle_pg18.py"
POLICY = ROOT / "docs/security/SEC5_PRIV_EMPTY_ACCOUNT_REHEARSAL_20261105.md"
FLASK = ROOT / "fiscal_app_export/app.py"
WORKFLOW = ROOT / ".github/workflows/required-ci.yml"


def test_scenario_is_in_existing_ci_pg18_lab_not_in_flask():
    text = LAB.read_text(encoding="utf-8")
    tree = ast.parse(text)
    functions = {x.name for x in tree.body if isinstance(x, ast.FunctionDef)}
    assert {
        "_guard", "_rehearse_empty_account_row_only",
        "_assert_empty_account_rehearsal", "main",
    } <= functions
    assert "inventory_verified_user_synthetic(" in text
    assert "scope[\"tables_modeled\"] != 17" in text
    assert "if account.role != \"user\" or account.plan != \"free\"" in text
    assert "select(User).where(User.id == user_id).with_for_update()" in text
    assert "session.delete(account)" in text
    assert "session.flush()" in text
    assert "inject_after_flush" in text
    assert "manual_evidence != AUTHORIZED" in text
    assert "Barrier(2)" in text
    assert "ThreadPoolExecutor(max_workers=2)" in text
    assert "if any(count != 0 for count in scope[key].values()):" in text
    assert "SEC5_PRIV_EMPTY_ACCOUNT_PG18: PASS" in text
    assert text.count("        _assert_empty_account_rehearsal(engine, ids)") == 1
    assert "def _rehearse_empty_account_row_only" not in FLASK.read_text()
    assert "from qa_sec5_priv_record_lifecycle_pg18" not in FLASK.read_text()
    assert "@app.route" not in text
    assert "from app import" not in text


def test_existing_only_pg18_gate_is_unchanged():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count("qa_sec5_priv_record_lifecycle_pg18.py") == 1
    assert 'SEC5_PRIV_LIFECYCLE_PG18_ONLY: "1"' in workflow
    source = LAB.read_text(encoding="utf-8")
    for required in (
        'os.environ.get("GITHUB_ACTIONS") != "true"',
        'os.environ.get("CI") != "true"',
        'os.environ.get("FLASK_ENV") != "testing"',
        'os.environ.get("DATABASE_URL")',
        'k.startswith("RAILWAY_")',
        'if dbname not in ("postgres", DB):',
        'engine.url.database != DB or engine.url.host != "127.0.0.1"',
        "DROP DATABASE {} WITH (FORCE)",
    ):
        assert required in source, required


def test_report_cannot_be_interpreted_as_real_account_erasure():
    text = POLICY.read_text(encoding="utf-8").lower()
    for phrase in (
        "solo datos ficticios", "no implementa supresión", "no autoriza",
        "correo", "pagos", "proveedores", "backups",
        "bloqueo legal", "identidad", "no fusionar",
    ):
        assert phrase in text, phrase
