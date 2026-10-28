"""Regression: Home no longer shows the redundant trust strip.

The privacy policy and its retention section remain available in the standard
footer; do not resurrect the misleading old CSV non-storage claim.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_home_removes_posthero_trust_strip_without_losing_privacy_footer():
    home = (STATIC / "landing.html").read_text(encoding="utf-8")
    policy = (STATIC / "privacidad.html").read_text(encoding="utf-8")
    assert 'class="apple-trust"' not in home
    assert 'class="hero-checks"' not in home
    assert "tu CSV no se almacena" not in home
    assert 'href="/privacidad#conservacion"' not in home
    assert 'href="/privacidad"' in home
    assert 'id="conservacion"' in policy
    assert "archivos temporales" in policy.lower()


def test_home_follows_green_hero_with_how_it_works():
    home = (STATIC / "landing.html").read_text(encoding="utf-8")
    assert '</div></div>\n<section class="apple-section apple-how"' in home
    assert home.count('class="apple-section apple-how"') == 1
    assert "Método FIFO</li>" not in home
    assert "100% online, sin instalación</li>" not in home
    assert "Consultar exchanges compatibles →" in home  # Available elsewhere.
