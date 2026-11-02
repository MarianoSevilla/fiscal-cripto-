"""SEC5-PRIV: isolated record lifecycle must remain a CI test, never a live service."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "fiscal_app_export/tests/qa_sec5_priv_record_lifecycle_pg18.py"
CI = ROOT / ".github/workflows/required-ci.yml"
DOC = ROOT / "docs/security/SEC5_PRIV_RECORD_LIFECYCLE_PG18_20261102.md"


def test_ci_only_record_rehearsal_cannot_be_an_application_endpoint():
    source = SCRIPT.read_text(encoding="utf-8")
    parsed = ast.parse(source)
    funcs = {node.name for node in parsed.body if isinstance(node, ast.FunctionDef)}
    assert {"_guard", "_rehearsal", "_assert_lifecycle", "main"} <= funcs
    for required in (
        'os.environ.get("GITHUB_ACTIONS") != "true"',
        'os.environ.get("CI") != "true"',
        'os.environ.get("SEC5_PRIV_LIFECYCLE_PG18_ONLY") != "1"',
        'os.environ.get("DATABASE_URL")',
        'k.startswith("RAILWAY_")',
        'host="127.0.0.1"',
        'CREATE DATABASE {}',
        'DROP DATABASE {} WITH (FORCE)',
        'len(model_tables) == 17',
        'grant_existing_runtime_acl(',
        'inject_failure=True',
        'casefold()',
        'FOR UPDATE',
        'to_jsonb(p)',
        'DELETE FROM public.processing_errors WHERE id=%s AND user_id=%s',
        'errors.InsufficientPrivilege',
    ):
        assert required in source, required
    assert "@app.route" not in source
    assert "from app import" not in source
    assert "ALTER DEFAULT PRIVILEGES" not in source
    assert "FROM public.processing_errors WHERE email=" not in source


def test_postgres_ci_executes_rehearsal_once_with_explicit_gate():
    workflow = CI.read_text(encoding="utf-8")
    anchor = "SEC5-PRIV synthetic record lifecycle against actual ORM tables on PostgreSQL 18"
    assert workflow.count(anchor) == 1
    ix = workflow.index(anchor)
    section = workflow[ix:ix + 290]
    assert 'SEC5_PRIV_LIFECYCLE_PG18_ONLY: "1"' in section
    assert "qa_sec5_priv_record_lifecycle_pg18.py" in section
    assert workflow.index("postgres-bootstrap:") < ix < workflow.index("browser-navigation:")


def test_document_explicitly_disclaims_real_erasure_and_legal_blocking():
    text = DOC.read_text(encoding="utf-8")
    for required in (
        "datos ficticios", "17 tablas", "processing_errors",
        "no constituye bloqueo legal", "no implementa supresión de cuentas",
        "Stripe", "copias de seguridad", "sin desplegar",
    ):
        assert required.lower() in text.lower(), required
