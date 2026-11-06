"""SEC5-PRIV — Synthetic, offline review of declared case gates.

TEST SUPPORT ONLY. Untrusted declarations are not evidence: even a complete
packet can only be proposed for human review, NEVER authorize erasure, blocking,
SQL writes, deployment, or a GDPR compliance claim.

No DB, Flask, network, filesystem, command line, provider, or secrets access.
"""
from __future__ import annotations

from collections.abc import Mapping

REQUIRED_GATES = frozenset({
    "IDENTITY_AND_SCOPE",
    "PURPOSE_AND_LEGAL_BASIS",
    "FINANCIAL_AND_EXTERNAL_DEPENDENCIES",
    "SQL_AND_HTTP_ISOLATION",
    "ATOMICITY_AND_BACKUP_RECONCILIATION",
    "EXPLICIT_PRODUCTION_AUTHORIZATION",
})
OUTCOMES = frozenset({
    "SUPRIMIR", "MANTENER_OPERATIVO", "BLOQUEAR_ART32", "REVISION_ESPECIAL",
})
DECLARATIONS = frozenset({"PENDING", "DECLARED_REVIEWED", "CONFLICT"})


def _validate_contract(contract: Mapping) -> None:
    if not isinstance(contract, dict) or set(contract) != {
        "schema_version", "status", "execution_enabled",
        "automated_account_closure", "automatic_erasure",
        "review_outcomes", "required_gates", "scenarios",
    }:
        raise ValueError("Unexpected contract shape")
    if type(contract["schema_version"]) is not int or contract["schema_version"] != 1:
        raise ValueError("Unknown contract version")
    if contract["status"] != "DESIGN_ONLY":
        raise ValueError("Only design-only contracts allowed")
    if any(contract[x] is not False for x in (
        "execution_enabled", "automated_account_closure", "automatic_erasure"
    )):
        raise ValueError("Execution must remain disabled")
    if (not isinstance(contract["required_gates"], list)
            or len(contract["required_gates"]) != len(REQUIRED_GATES)
            or set(contract["required_gates"]) != REQUIRED_GATES
            or not isinstance(contract["review_outcomes"], list)
            or len(contract["review_outcomes"]) != len(OUTCOMES)
            or set(contract["review_outcomes"]) != OUTCOMES):
        raise ValueError("Required gates or outcomes changed")
    if not isinstance(contract["scenarios"], list) or len(contract["scenarios"]) < 8:
        raise ValueError("Adversarial scenarios not present")


def review_declared_case(packet: Mapping, contract: Mapping) -> dict:
    """Classify only synthetic declarations. Never return permission to act.

    Do not feed PII, identities, receipts, real case numbers or credentials.
    All `DECLARED_REVIEWED` statuses are unverified claims, not audit evidence.
    """
    _validate_contract(contract)
    if not isinstance(packet, dict) or set(packet) != {"outcome", "gates"}:
        raise ValueError("Packet must contain only outcome and gates")
    outcome = packet["outcome"]
    if not isinstance(outcome, str) or outcome not in OUTCOMES:
        raise ValueError("Unknown decision")
    gates = packet["gates"]
    if (not isinstance(gates, dict) or set(gates) != REQUIRED_GATES
            or any(type(gates[name]) is not str
                   or gates[name] not in DECLARATIONS
                   for name in REQUIRED_GATES)):
        raise ValueError("Every required gate needs a valid declaration")

    missing = tuple(sorted(name for name in REQUIRED_GATES
                           if gates[name] == "PENDING"))
    conflicting = tuple(sorted(name for name in REQUIRED_GATES
                               if gates[name] == "CONFLICT"))
    if conflicting:
        status = "NO_GO_CONFLICT"
        next_step = "PRESERVE_AND_RESOLVE_CONFLICT"
    elif missing:
        status = "NO_GO_INCOMPLETE"
        next_step = "COLLECT_AND_VERIFY_EVIDENCE"
    elif outcome in {"REVISION_ESPECIAL", "MANTENER_OPERATIVO"}:
        status = "NO_GO_DESTRUCTIVE_ACTION"
        next_step = "HUMAN_PURPOSE_REVIEW"
    else:
        status = "HUMAN_REVIEW_REQUIRED"
        next_step = "INDEPENDENTLY_VERIFY_EVIDENCE_AND_REQUEST_AUTHORIZATION"

    return {
        "status": status,
        "proposed_outcome": outcome,
        "pending_gates": missing,
        "conflicting_gates": conflicting,
        "next_step": next_step,
        "allow_erasure": False,
        "allow_legal_blocking": False,
        "allow_sql_writes": False,
        "allow_deployment": False,
        "evidence_independently_verified": False,
        "real_case_handling_supported": False,
    }
