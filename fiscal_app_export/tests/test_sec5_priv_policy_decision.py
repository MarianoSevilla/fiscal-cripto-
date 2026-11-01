"""Control documental SEC5-PRIV: contrato de decisión, sin acceso a usuarios ni DB."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT.parent / "docs" / "security" / "SEC5_PRIV_POLITICA_PARA_APROBACION_20261101.md"


def _policy():
    return POLICY.read_text(encoding="utf-8")


def test_policy_covers_exactly_every_orm_table():
    orm = (ROOT / "models.py").read_text(encoding="utf-8")
    actual = set(re.findall(r'^\s+__tablename__\s*=\s*"([a-z0-9_]+)"', orm, flags=re.M))
    rows = re.findall(r'^\| `([a-z0-9_]+)` \|', _policy(), flags=re.M)
    assert len(rows) == len(set(rows)) == len(actual) == 17
    assert set(rows) == actual


def test_policy_is_not_authorization_for_retention_or_erasure():
    policy = _policy()
    for exact in (
        "PROPUESTA PARA APROBACIÓN, NO APROBADA NI IMPLEMENTADA",
        "no es un plazo legal ni autoriza retención automática",
        "No hay purga automática por una cifra",
        "Baja de cuenta ≠ supresión integral",
        "Bloqueo efectivo:",
        "Aún no validable sin hechos externos o producto",
        "no aprobar plazos finales",
        "afectar a producción",
    ):
        assert exact in policy
    assert "la auditoría del panel queda aplazada" in policy.lower()


def test_policy_keeps_key_service_and_legal_exceptions():
    policy = _policy()
    for exact in (
        "Rafael Ramos",
        "fiscal_advisory_files",
        "marketing_consent=True",
        "Código de Comercio art. 30",
        "Ley 10/2010 art. 2.1(m) y 25",
        "LOPDGDD art. 32",
        "Stripe",
        "Railway",
        "Gmail",
        "Resend",
        "compras/derechos de descarga",
    ):
        assert exact in policy
