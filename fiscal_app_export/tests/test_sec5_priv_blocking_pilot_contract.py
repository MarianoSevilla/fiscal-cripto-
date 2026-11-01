"""Static contract: prevent a test-only privacy blocker from becoming a live route."""
from pathlib import Path
import ast

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PILOT = HERE / "qa_sec5_priv_blocking_pg18.py"
CI = ROOT / ".github" / "workflows" / "required-ci.yml"
DOC = ROOT / "docs" / "security" / "SEC5_PRIV_PG18_BLOCKING_PILOT_20261101.md"


def test_pilot_remains_test_only_and_requires_an_explicit_ci_gate():
    source = PILOT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"_assert_synthetic_environment", "block_synthetic_contact",
            "assert_private_boundary", "main"} <= functions
    assert "GITHUB_ACTIONS" in source
    assert "SEC5_PRIV_PILOT_ONLY" in source
    assert 'or os.environ.get("FLASK_ENV") != "testing"' in source
    assert "127.0.0.1" in source
    assert '"ci-only-test-password"' in source
    assert 'os.environ.get("DATABASE_URL")' not in source
    assert "from app import" not in source
    assert "@app.route" not in source
    assert "SYNTHETIC_MANUALLY_REVIEWED" in source
    assert "FOR UPDATE" in source
    assert "SET LOCAL ROLE" in source
    assert "errors.InsufficientPrivilege" in source
    assert "inject_failure=True" in source
    assert "teardown_synthetic_store()" in source
    assert "SEC5_PRIV_PG18_PILOT: PASS" in source


def test_ci_runs_pilot_only_against_disposable_postgres_job():
    ci = CI.read_text(encoding="utf-8")
    check = "SEC5-PRIV isolated PostgreSQL 18 blocked-data privilege boundary"
    assert ci.count(check) == 1
    start = ci.index(check)
    snippet = ci[start:start + 250]
    assert 'SEC5_PRIV_PILOT_ONLY: "1"' in snippet
    assert "python fiscal_app_export/tests/qa_sec5_priv_blocking_pg18.py" in snippet
    assert ci.index(check) > ci.index("postgres-bootstrap:")
    assert ci.index(check) < ci.index("browser-navigation:")


def test_pilot_document_explicitly_excludes_real_deletion_and_production():
    text = DOC.read_text(encoding="utf-8")
    for phrase in (
        "No es solución de producción",
        "no crea roles de producción",
        "no activa purgas",
        "17 tablas",
        "no hay motor de borrado",
        "ni se han leído datos personales",
        "solo demostrará aislamiento",
        "No acredita cumplimiento jurídico integral",
        "Prohibido sin autorización independiente",
    ):
        assert phrase.lower() in text.lower(), phrase
