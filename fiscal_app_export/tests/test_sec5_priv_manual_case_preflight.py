"""SEC5-PRIV: adversarial offline case preflight — no connection to real data."""
import ast
import copy
import json
from pathlib import Path

import pytest

from privacy_case_preflight import REQUIRED_GATES, review_declared_case

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "docs/security/SEC5_PRIV_CASE_REVIEW_CONTRACT_20261102.json"
SOURCE = ROOT / "fiscal_app_export/tests/privacy_case_preflight.py"
RUNBOOK = ROOT / "docs/security/SEC5_PRIV_MANUAL_CASE_PREFLIGHT_20261106.md"


@pytest.fixture
def contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def packet(outcome="SUPRIMIR", **overrides):
    gates = {name: "DECLARED_REVIEWED" for name in REQUIRED_GATES}
    gates.update(overrides)
    return {"outcome": outcome, "gates": gates}


@pytest.mark.parametrize("outcome", ["SUPRIMIR", "BLOQUEAR_ART32"])
def test_even_complete_declarations_never_authorize_action(contract, outcome):
    p = packet(outcome)
    snapshot = copy.deepcopy((p, contract))
    result = review_declared_case(p, contract)
    assert result["status"] == "HUMAN_REVIEW_REQUIRED"
    assert result["next_step"] == "INDEPENDENTLY_VERIFY_EVIDENCE_AND_REQUEST_AUTHORIZATION"
    for field in (
        "allow_erasure", "allow_legal_blocking", "allow_sql_writes",
        "allow_deployment", "evidence_independently_verified",
        "real_case_handling_supported",
    ):
        assert result[field] is False
    assert (p, contract) == snapshot


@pytest.mark.parametrize("outcome", ["REVISION_ESPECIAL", "MANTENER_OPERATIVO"])
def test_review_or_operational_retention_cannot_be_destructive(contract, outcome):
    result = review_declared_case(packet(outcome), contract)
    assert result["status"] == "NO_GO_DESTRUCTIVE_ACTION"
    assert result["allow_erasure"] is False


@pytest.mark.parametrize("gate", sorted(REQUIRED_GATES))
def test_every_missing_gate_blocks_candidate(contract, gate):
    result = review_declared_case(packet(**{gate: "PENDING"}), contract)
    assert result["status"] == "NO_GO_INCOMPLETE"
    assert result["pending_gates"] == (gate,)
    assert result["allow_sql_writes"] is False


@pytest.mark.parametrize("gate", sorted(REQUIRED_GATES))
def test_every_conflicting_gate_blocks_candidate(contract, gate):
    result = review_declared_case(packet(**{gate: "CONFLICT"}), contract)
    assert result["status"] == "NO_GO_CONFLICT"
    assert result["conflicting_gates"] == (gate,)


def test_conflict_takes_priority_over_pending(contract):
    result = review_declared_case(packet(
        FINANCIAL_AND_EXTERNAL_DEPENDENCIES="CONFLICT",
        ATOMICITY_AND_BACKUP_RECONCILIATION="PENDING",
    ), contract)
    assert result["status"] == "NO_GO_CONFLICT"
    assert len(result["pending_gates"]) == len(result["conflicting_gates"]) == 1


@pytest.mark.parametrize("tamper", [
    {"execution_enabled": True},
    {"automated_account_closure": True},
    {"automatic_erasure": True},
    {"schema_version": 2},
    {"status": "ACTIVE"},
    {"required_gates": ["IDENTITY_AND_SCOPE"]},
    {"review_outcomes": ["SUPRIMIR"]},
    {"scenarios": []},
    {"unexpected": 1},
])
def test_tampered_design_contract_fails_closed(contract, tamper):
    contract.update(tamper)
    with pytest.raises(ValueError):
        review_declared_case(packet(), contract)


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(email="example@example.invalid"),
    lambda p: p.update(user_id=1),
    lambda p: p["gates"].pop("IDENTITY_AND_SCOPE"),
    lambda p: p["gates"].update(unknown="DECLARED_REVIEWED"),
    lambda p: p["gates"].update(IDENTITY_AND_SCOPE=True),
    lambda p: p["gates"].update(IDENTITY_AND_SCOPE="VERIFIED"),
    lambda p: p.update(outcome="AUTOMATIC_PURGE"),
    lambda p: p.update(gates=[]),
])
def test_unexpected_or_pii_shaped_payload_fails_closed(contract, mutation):
    p = packet()
    mutation(p)
    with pytest.raises(ValueError):
        review_declared_case(p, contract)


def test_existing_eight_adversarial_scenarios_each_force_no_go(contract):
    scenarios = {x["id"] for x in contract["scenarios"]}
    adversity = {
        "SHARED_HISTORICAL_EMAIL": ("IDENTITY_AND_SCOPE", "CONFLICT"),
        "DEACTIVATED_ACCOUNT": ("IDENTITY_AND_SCOPE", "PENDING"),
        "S01_FINANCIAL_HOLD": ("FINANCIAL_AND_EXTERNAL_DEPENDENCIES", "CONFLICT"),
        "SQL_ROLE_BOUNDARY": ("SQL_AND_HTTP_ISOLATION", "PENDING"),
        "MID_TRANSACTION_FAILURE": ("ATOMICITY_AND_BACKUP_RECONCILIATION", "CONFLICT"),
        "BACKUP_BEFORE_REQUEST": ("ATOMICITY_AND_BACKUP_RECONCILIATION", "PENDING"),
        "EXTERNAL_PROVIDER_FAILURE": ("FINANCIAL_AND_EXTERNAL_DEPENDENCIES", "PENDING"),
        "INACTIVITY_24_MONTHS": ("PURPOSE_AND_LEGAL_BASIS", "PENDING"),
    }
    assert scenarios == set(adversity)
    for name, (gate, state) in adversity.items():
        outcome = "MANTENER_OPERATIVO" if name == "INACTIVITY_24_MONTHS" else "SUPRIMIR"
        result = review_declared_case(packet(outcome, **{gate: state}), contract)
        assert result["status"].startswith("NO_GO")
        assert result["allow_erasure"] is False


def test_code_and_runbook_keep_preflight_offline_and_non_authoritative():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imports = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ] + [alias.name for node in ast.walk(tree)
         if isinstance(node, ast.Import) for alias in node.names]
    assert set(imports).issubset({"__future__", "collections.abc"})
    source = SOURCE.read_text(encoding="utf-8")
    assert "def review_declared_case(" in source
    assert "execute(" not in source
    assert "commit(" not in source
    assert "app.route" not in source
    for path in (
        ROOT / "fiscal_app_export/app.py",
        ROOT / "fiscal_app_export/startup_schema_gate.py",
    ):
        assert "privacy_case_preflight" not in path.read_text(encoding="utf-8")

    doc = RUNBOOK.read_text(encoding="utf-8").lower()
    for phrase in (
        "17 tablas", "seis puertas", "sin datos personales",
        "revisión humana", "no autoriza", "pagos", "backups",
        "stripe", "gmail", "resend", "rafael", "bloqueo",
        "sin despliegue", "sin fusión",
    ):
        assert phrase in doc, phrase
