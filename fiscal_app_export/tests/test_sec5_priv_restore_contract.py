"""Static guard: synthetic pg_dump restore rehearsal is NOT a production gate."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "fiscal_app_export/tests/qa_sec5_priv_restore_pg18.py"
DOC = ROOT / "docs/security/SEC5_PRIV_RESTORE_RECONCILIATION_PG18_20261102.md"
CI = ROOT / ".github/workflows/required-ci.yml"


def test_restore_replay_remains_ci_only_with_explicit_safety_gate():
    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    funcs = {item.name for item in tree.body if isinstance(item, ast.FunctionDef)}
    assert {"_guard", "_gate", "_reconcile", "_validate", "_client", "main"} <= funcs
    for literal in (
        'os.environ.get("GITHUB_ACTIONS") != "true"',
        'os.environ.get("CI") != "true"',
        'os.environ.get("FLASK_ENV") != "testing"',
        'os.environ.get("SEC5_PRIV_RESTORE_PG18_ONLY") != "1"',
        'os.environ.get("DATABASE_URL")',
        'k.startswith("RAILWAY_")',
        '"127.0.0.1"',
        '"postgres:18"',
        '"pg_dump"',
        '"pg_restore"',
        '"docker", "run", "--rm", "-i", "--network", "host"',
        'hmac.compare_digest',
        'backup_sha256',
        'to_jsonb(p)',
        '_canonical(row[5])',
        'col.name for col in ProcessingError.__table__.columns',
        'complete_through',
        'crash_after_first=True',
        'to_regclass',
        'traffic forbidden',
        'DROP DATABASE {} WITH (FORCE)',
        'grant_existing_runtime_acl(',
        'errors.InsufficientPrivilege',
    ):
        assert literal in source, literal
    assert "from app import" not in source
    assert "@app.route" not in source
    assert "RAILWAY_DATABASE_URL" not in source


def test_ci_runs_recovery_after_lifecycle_in_postgres_job_only():
    text = CI.read_text(encoding="utf-8")
    name = "SEC5-PRIV pg_dump restore and outside-backup reconciliation on disposable PostgreSQL 18"
    assert text.count(name) == 1
    position = text.index(name)
    snippet = text[position:position + 255]
    assert 'SEC5_PRIV_RESTORE_PG18_ONLY: "1"' in snippet
    assert "qa_sec5_priv_restore_pg18.py" in snippet
    assert text.index("postgres-bootstrap:") < position < text.index("browser-navigation:")
    assert text.index("qa_sec5_priv_record_lifecycle_pg18.py") < position


def test_doc_requires_closed_traffic_and_rejects_completeness_claims():
    contents = DOC.read_text(encoding="utf-8").lower()
    for item in (
        "pg_dump", "pg_restore", "datos ficticios", "fuera de la copia",
        "sin tráfico", "hmac", "idempotencia", "faltar cualquier",
        "no está conectado al arranque", "17 tablas", "no equivale",
        "producción", "stripe", "gmail", "resend",
    ):
        assert item in contents, item
