"""SEC5-PRIV: changing the ORM must trigger a retention-matrix review.

Pure source regression: no DB, no remote services and no user data.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT.parent / "docs" / "security" / "SEC5_PRIV_011_013_RETENTION_MATRIX.md"


def test_retention_matrix_covers_all_orm_tables():
    source = (ROOT / "models.py").read_text(encoding="utf-8")
    matrix = MATRIX.read_text(encoding="utf-8")
    actual = set(re.findall(r'^\s+__tablename__\s*=\s*"([a-z0-9_]+)"', source, flags=re.M))
    documented = set(re.findall(r'^\| `([a-z0-9_]+)` \|', matrix, flags=re.M))
    assert actual, "No ORM tables found: validate the inventory parser"
    assert actual == documented, (
        f"Tables missing in retention inventory: {sorted(actual - documented)}; "
        f"undocumented entries: {sorted(documented - actual)}"
    )


def test_retention_matrix_explicitly_rejects_global_erasure_claim():
    matrix = MATRIX.read_text(encoding="utf-8")
    assert "desidentifica parcialmente" in matrix
    assert "No se modifica" in matrix
    assert "no representa una supresión exhaustiva" in matrix
    assert "Bloqueo y acceso" in matrix
    assert "no política de retención aprobada" in matrix


def test_decision_proposal_covers_existing_tables_and_remains_non_executable():
    """Document every ORM table and preserve the explicit approval gate."""
    source = (ROOT / "models.py").read_text(encoding="utf-8")
    policy = (
        ROOT.parent / "docs" / "security" / "SEC5_PRIV_011_013_DECISION_PROPOSAL.md"
    ).read_text(encoding="utf-8")
    tables = {
        line.split('"')[1] for line in source.splitlines()
        if "__tablename__" in line and '"' in line
    }
    rows = {
        line.split("|")[1].strip().strip(chr(96))
        for line in policy.splitlines()
        if line.startswith("| " + chr(96))
    }
    assert tables == rows, (sorted(tables - rows), sorted(rows - tables))
    assert "BORRADOR PARA DECISIÓN" in policy
    assert "No aprobado, no aplicado en producción" in policy
    assert "Ninguna nueva purga se autoriza" in policy
    assert "Criterios técnicos aceptados para DISEÑO (no ejecución)" in policy
    assert "calendario de **evaluación y propuesta de supresión**" in policy
    assert "nunca borrado ciego de incidencias abiertas" in policy
    assert "derechos de acceso a informes comprados" in policy
    assert "retención de expedientes económicos" in policy
    assert "NO mínimos ni máximos legales" in policy


def test_acceptance_contract_covers_orm_and_keeps_execution_blocked():
    """The acceptance contract cannot silently omit new models or authorize deletion.

    Pure textual check; no database connection, provider access or deletion.
    """
    contract_path = ROOT.parent / "docs" / "security" / "SEC5_PRIV_011_013_ACCEPTANCE_CONTRACT.md"
    contract = contract_path.read_text(encoding="utf-8")
    source = (ROOT / "models.py").read_text(encoding="utf-8")
    tables = set(re.findall(r'^\s+__tablename__\s*=\s*"([a-z0-9_]+)"', source, flags=re.M))
    contract_rows = set(re.findall(r'^\| ' + chr(96) + r'([a-z0-9_]+)' + chr(96) + r' \|', contract, flags=re.M))
    assert tables, "ORM table inventory unexpectedly empty"
    assert tables == contract_rows, (
        f"Missing contract decisions: {sorted(tables - contract_rows)}; "
        f"unrecognized contract tables: {sorted(contract_rows - tables)}"
    )
    assert "no aprobada para ejecutar" in contract
    assert "no fechas de borrado ni plazos impuestos por ley" in contract
    assert "ningún umbral activa por sí solo borrado" in contract
    assert "No significa que SEC5-PRIV-011/012/013 esté jurídicamente cerrado" in contract


def test_acceptance_contract_separates_historical_resource_marketing_consent():
    """Historical forced checkboxes must not become marketing authorization."""
    contract = (
        ROOT.parent / "docs" / "security" / "SEC5_PRIV_011_013_ACCEPTANCE_CONTRACT.md"
    ).read_text(encoding="utf-8")
    assert "PR #161" in contract
    assert "marketing_consent=True" in contract
    assert "No inferir que las solicitudes históricas" in contract
    assert "no incluir esos registros en futuras campañas únicamente por ese booleano" in contract
