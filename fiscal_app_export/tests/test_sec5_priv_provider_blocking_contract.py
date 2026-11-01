"""SEC5-PRIV: evidencia y puertas negativas de bloqueo (solo documentación)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ROOT.parent / "docs" / "security" / "SEC5_PRIV_PROVEEDORES_BLOQUEO_EVIDENCIAS_20261101.md"
POLICY = ROOT.parent / "docs" / "security" / "SEC5_PRIV_POLITICA_PARA_APROBACION_20261101.md"


def test_provider_document_distinguishes_historical_restores_from_current_backups():
    note = PROVIDERS.read_text(encoding="utf-8")
    for required in (
        "us-east4-eqdc4a",
        "5.000 MB",
        "sin volumen persistente",
        "sin buckets",
        "dos copias manuales de la base de producción",
        "pg_dump",
        "age",
        "pre-u04-20261011T214522Z.dump.age",
        "RESTAURACION_LOCAL_U04_CORRECTA",
        "pre-u04-20261014T231820Z.dump.age",
        "S01 REHEARSAL: PASS",
        "No se accedió en esta revisión a los archivos actuales",
        "No hay backups periódicos automáticos comunicados",
        "última copia identificada es de 14/10/2026",
        "DPA efectivo del cliente",
        "cuenta Gmail de consumo",
        "Free, Pro y Scale",
        "Stripe Connect 70/30 es solo diseño futuro",
        "no se consultaron expedientes",
    ):
        assert required.lower() in note.lower(), required


def test_blocking_document_preserves_exceptions_and_avoids_misleading_flags():
    note = PROVIDERS.read_text(encoding="utf-8")
    for required in (
        "artículo 32 LOPDGDD",
        "Tres vías, no una purga global",
        "suprimir",
        "mantener_operativo",
        "bloquear_art32",
        "revisión_especial",
        "is_active=False",
        "cuenta de A desactivada",
        "restaura backup anterior",
        "idempotente",
        "No es necesario destruir todo el backup",
        "No migración ni nuevo rol todavía",
        "dos copias",
        "no declara cerrada la fase",
    ):
        assert required.lower() in note.lower(), required
    assert "NO aprobado para operar sobre datos" in note
    assert "no ejecuta supresiones" in note
    assert "no fusiona" in note
    assert "no despliega" in note


def test_both_documents_do_not_drop_the_17_table_scope():
    note = PROVIDERS.read_text(encoding="utf-8")
    policy = POLICY.read_text(encoding="utf-8")
    source = (ROOT / "models.py").read_text(encoding="utf-8")
    names = set(re.findall(r'^\s+__tablename__\s*=\s*"([a-z0-9_]+)"', source, flags=re.M))
    rows = re.findall(r'^\| `([a-z0-9_]+)` \|', policy, flags=re.M)
    assert len(names) == 17
    assert len(rows) == len(names)
    assert set(rows) == names
    assert "17 tablas ORM" in note
    assert "no implementa" in note.lower()
