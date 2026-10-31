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


def test_session_cookie_policy_matches_server_side_expiry():
    """Privacy copy must not promise persistent login after AUTH-SESSION-TTL-001."""
    policy = (STATIC / "privacidad.html").read_text(encoding="utf-8")
    cookies = (STATIC / "cookies.html").read_text(encoding="utf-8")
    server = (STATIC.parent / "app.py").read_text(encoding="utf-8")

    assert "_USER_IDLE_TTL_S = 30 * 60" in server
    assert "_STAFF_IDLE_TTL_S = 15 * 60" in server
    assert "_STAFF_ABSOLUTE_TTL_S = 8 * 60 * 60" in server
    assert "session.permanent = False" in server

    for text in (policy, cookies):
        assert "30 minutos de inactividad" in text
        assert "15 minutos" in text
        assert "8 horas" in text
        assert "«Recordarme»" in text

    assert "cookie persistente configurada para treinta días" not in policy
    assert "se elimina al cerrar el navegador" not in cookies
    assert "esto no amplía la validez de la sesión" in policy
    assert "no prolonga la sesión caducada" in cookies
