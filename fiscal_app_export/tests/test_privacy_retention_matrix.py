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
