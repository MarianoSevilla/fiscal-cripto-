"""Static audit guard: inventory and explicit limits, no production data or providers."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
AUDIT = APP.parent / "docs" / "product" / "ANALITICA_PRIVACIDAD_AUDITORIA_20261101.md"


def test_analytics_audit_classifies_every_orm_table():
    source = (APP / "models.py").read_text(encoding="utf-8")
    audit = AUDIT.read_text(encoding="utf-8")
    actual = set(re.findall(r'^\s+__tablename__\s*=\s*"([a-z0-9_]+)"', source, re.M))
    documented = set(re.findall(r'^\| `([a-z0-9_]+)` \|', audit, re.M))
    assert len(actual) == 17  # Changes to ORM need renewed retention + analytics review.
    assert actual == documented, {
        "missing": sorted(actual - documented),
        "not_in_orm": sorted(documented - actual),
    }


def test_audit_distinguishes_operational_data_and_synthetic_demo():
    app = (APP / "app.py").read_text(encoding="utf-8")
    fixture = (APP / "stats_v2_fixture.py").read_text(encoding="utf-8")
    audit = AUDIT.read_text(encoding="utf-8")
    assert '@app.route("/api/stats")' in app
    assert '@app.route("/api/stats-v2/encuentro")' in app
    assert "ENCUENTRO_FIXTURE" in fixture and "ENCUENTRO_FIXTURE" in app
    assert "datos de escenario, no mediciones reales" in audit
    assert "no implementado" in audit
    assert "**sin consultas de datos reales**" in audit


def test_known_identification_and_financial_semantics_require_review():
    app = (APP / "app.py").read_text(encoding="utf-8")
    audit = AUDIT.read_text(encoding="utf-8")
    for field in (
        '"top_usuarios":', '"processing_errors":', '"detalle":',
        '"activos_30d":', '"conversion_pct":', '"ingresos_total_eur":',
    ):
        assert field in app, f"Stats contract changed; re-audit {field}"
    for requirement in (
        "Hallazgo PRIV-1", "Hallazgo PRIV-2",
        "Hallazgo MÉTRICA-1", "Hallazgo MÉTRICA-2",
        "No crear nuevas tablas por anticipación",
        "La identidad temporal para deduplicar cohortes sigue siendo dato personal",
    ):
        assert requirement in audit
