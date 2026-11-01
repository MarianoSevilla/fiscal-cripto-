"""Guardrails for the disposable PostgreSQL 18 scope probe (test-only)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QA = Path(__file__).with_name("qa_sec5_priv_scope_pg18.py")
WORKFLOW = ROOT / ".github" / "workflows" / "required-ci.yml"


def test_sec5_priv_scope_pg18_remains_ci_only_without_runtime_entrypoint():
    source = QA.read_text(encoding="utf-8")
    for expected in (
        'os.environ.get("GITHUB_ACTIONS") != "true"',
        'os.environ.get("SEC5_PRIV_SCOPE_PG18_ONLY") != "1"',
        'os.environ.get("FLASK_ENV") != "testing"',
        'HOST = "127.0.0.1"',
        'DB = "sec5_priv_scope_ci"',
        "SET TRANSACTION READ ONLY",
        "CREATE DATABASE sec5_priv_scope_ci",
        "DROP DATABASE sec5_priv_scope_ci WITH (FORCE)",
        "inventory_verified_user_synthetic(",
        "SEC5_PRIV_SCOPE_PG18: PASS",
    ):
        assert expected in source
    assert "DATABASE_URL" not in source
    assert "from app import" not in source
    assert "@app.route" not in source
    assert "DELETE FROM" not in source
    assert "TRUNCATE" not in source


def test_scope_pg18_is_wired_only_to_disposable_postgres_ci_job():
    content = WORKFLOW.read_text(encoding="utf-8")
    step = "SEC5-PRIV count-only ORM scope on disposable PostgreSQL 18"
    assert content.count(step) == 1
    fragment = content[content.index(step):content.index(step) + 260]
    assert 'SEC5_PRIV_SCOPE_PG18_ONLY: "1"' in fragment
    assert "python fiscal_app_export/tests/qa_sec5_priv_scope_pg18.py" in fragment
    assert content.index("postgres-bootstrap:") < content.index(step)
    assert content.index(step) < content.index("browser-navigation:")
