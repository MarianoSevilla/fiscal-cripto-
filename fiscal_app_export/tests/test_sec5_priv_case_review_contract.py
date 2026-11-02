"""SEC5-PRIV design contract only: no database connections or mutations."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/security/SEC5_PRIV_CASE_REVIEW_20261102.md"
CONTRACT = ROOT / "docs/security/SEC5_PRIV_CASE_REVIEW_CONTRACT_20261102.json"
PROBE = ROOT / "fiscal_app_export/tests/privacy_scope_probe.py"
CASES = {
    "SHARED_HISTORICAL_EMAIL": "NO_CROSS_ACCOUNT_ATTRIBUTION",
    "DEACTIVATED_ACCOUNT": "EXTERNAL_IDENTITY_PROOF_REQUIRED",
    "S01_FINANCIAL_HOLD": "PRESERVE_FINANCIAL_CHAIN",
    "SQL_ROLE_BOUNDARY": "DATABASE_PERMISSION_DENIED",
    "MID_TRANSACTION_FAILURE": "ROLLBACK_AND_IDEMPOTENCE",
    "BACKUP_BEFORE_REQUEST": "RECONCILE_BEFORE_TRAFFIC",
    "EXTERNAL_PROVIDER_FAILURE": "EXTERNAL_STATUS_PARTIAL",
    "INACTIVITY_24_MONTHS": "REVIEW_ONLY_NO_CLOSURE",
}
GATES = {
    "IDENTITY_AND_SCOPE", "PURPOSE_AND_LEGAL_BASIS",
    "FINANCIAL_AND_EXTERNAL_DEPENDENCIES", "SQL_AND_HTTP_ISOLATION",
    "ATOMICITY_AND_BACKUP_RECONCILIATION", "EXPLICIT_PRODUCTION_AUTHORIZATION",
}

def test_design_only_requires_human_review():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["status"] == "DESIGN_ONLY"
    for flag in ("execution_enabled", "automated_account_closure", "automatic_erasure"):
        assert data[flag] is False
    assert set(data["required_gates"]) == GATES
    assert len(data["required_gates"]) == len(GATES)
    assert set(data["review_outcomes"]) == {
        "SUPRIMIR", "MANTENER_OPERATIVO", "BLOQUEAR_ART32", "REVISION_ESPECIAL"
    }

def test_synthetic_scenarios_cover_critical_failure_modes():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    scenarios = data["scenarios"]
    assert len(scenarios) == len(CASES)
    assert {s["id"]: s["expected"] for s in scenarios} == CASES
    for case in scenarios:
        assert len(case["given"]) >= 20
        assert len(case["must_prove"]) >= 2
        assert len(case["must_prove"]) == len(set(case["must_prove"]))
        assert set(case) == {"id", "given", "expected", "must_prove"}

def test_document_and_existing_scope_probe_remain_fail_closed():
    doc = DOC.read_text(encoding="utf-8")
    for term in ("17 tablas ORM", "24 meses", "S01", "PostgreSQL 18",
                 "rollback", "reconciliación", "autorización específica",
                 "Ningún cambio productivo"):
        assert term.lower() in doc.lower()
    src = PROBE.read_text(encoding="utf-8")
    ast.parse(src)
    for flag in ('"delete_permitted": False', '"blocking_proven": False',
                 '"external_systems_checked": False', '"scope_complete": False',
                 '"requires_external_identity_proof": True'):
        assert flag in src
