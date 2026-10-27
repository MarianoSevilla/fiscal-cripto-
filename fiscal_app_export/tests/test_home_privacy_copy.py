"""Regression: homepage file privacy claim matches published retention disclosure."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_home_file_privacy_claim_is_qualified_and_links_to_retention():
    home = (STATIC / "landing.html").read_text(encoding="utf-8")
    policy = (STATIC / "privacidad.html").read_text(encoding="utf-8")
    assert "tu CSV no se almacena" not in home
    assert 'href="/privacidad#conservacion"' in home
    assert "cómo tratamos tus archivos" in home
    assert 'id="conservacion"' in policy
    assert "archivos temporales" in policy.lower()
