"""Advisory landing: use exactly the approved shared Apple components."""
from pathlib import Path
import re

STATIC=Path(__file__).resolve().parents[1]/"static"

def fragment(s, opening, closing):
    start=s.index(opening)
    return s[start:s.index(closing,start)+len(closing)]

def test_advisory_reuses_approved_assets_and_shell():
    html=(STATIC/"asesoramiento-fiscal.html").read_text()
    how=(STATIC/"como-funciona.html").read_text()
    home=(STATIC/"landing.html").read_text()
    styles=lambda s:re.findall(r'<link rel="stylesheet" href="([^"]+)"',s)
    assert styles(html)==styles(how)==[
        "/static/nav.css","/static/landing_apple.css",
        "/static/como_funciona_apple.css","/static/apple_cta.css",
    ]
    assert html.count("<style>")==1  # approved no-JS menu only
    assert fragment(html,"<noscript>","</noscript>")==fragment(how,"<noscript>","</noscript>").replace(' aria-current="page"','')
    assert fragment(html,'<nav id="site-nav"',"</nav>")==fragment(how,'<nav id="site-nav"',"</nav>").replace(' aria-current="page"','')
    assert fragment(html,'<footer class="apple-footer">',"</footer>")==fragment(home,'<footer class="apple-footer">',"</footer>")
    portraits=re.findall(r'<picture class="author-portrait">[\s\S]*?</picture>',home)
    assert len([p for p in portraits if "home-apple-rafa" in p and p in html])==1
    assert 'src="/static/nav.js"' in html and 'src="/static/landing_apple.js"' in html
    assert 'class="apple-home apple-how-page"' in html

def test_advisory_preserves_safe_request_contract_and_seo():
    html=(STATIC/"asesoramiento-fiscal.html").read_text()
    assert 'href="https://marianosevilla.com/asesoramiento-fiscal-criptomonedas"' in html
    assert '<meta name="robots" content="index, follow">' in html
    assert html.count("<h1 ")==html.count("<main ")==1
    assert html.count('class="apple-catalog-card"')==3
    actions=re.findall(r'<a class="apple-button"[^>]*href="([^"]+)">([^<]+)</a>',html)
    assert actions==[("/pedir-asesoramiento-fiscal","Enviar solicitud sin pago")]*3
    assert "Presupuestos, enlaces de pago y cobros temporalmente suspendidos." in html
    assert "no hay un plazo de respuesta confirmado" in html
    assert "El servicio profesional se contrata directamente con Rafael Ramos." in html
    assert "Qué no incluye" in html and "Declaración de patrimonio o modelos 720/721" in html
    assert "/api/asesoramiento/precios" not in html
    assert '<form' not in html and 'fonts.googleapis.com' not in html
