"""Editorial page only: retain existing content, routes and approved assets."""
from pathlib import Path
import json,re
STATIC=Path(__file__).resolve().parents[1]/"static"

def test_modelo721_editorial_apple():
    s=(STATIC/"modelo-721-criptomonedas.html").read_text()
    ref=(STATIC/"como-funciona.html").read_text()
    assert "fonts.googleapis.com" not in s
    assert s.count("<style>")==1
    assert 'class="apple-home apple-exchanges-page apple-how-page"' in s
    for name in ("nav.css","landing_apple.css","exchanges_apple.css","como_funciona_apple.css","apple_cta.css"):
        assert s.count(f'href="/static/{name}"')==1
    assert s.count("<main ")==s.count("<h1 ")==1
    assert 'href="https://marianosevilla.com/modelo-721-criptomonedas"' in s
    assert '<meta name="robots" content="index, follow">' in s
    for anchor in ("que-es-modelo-721","quien-debe-presentar-modelo-721","como-funciona-herramienta-721","exchanges-extranjeros-modelo-721","faq-modelo-721-criptomonedas"):
        assert s.count(f'id="{anchor}"')==1
    assert s.count('class="apple-faq-item"')==6
    assert s.count('class="exchanges-logo"')==7
    assert s.count('class="apple-catalog-card"')==16
    assert "50.000 €" in s and "20.000 €" in s
    assert 'no presenta el Modelo 721 ante la AEAT' in s
    assert 'class="apple-button" href="/signup/">Crear cuenta' in s
    assert 'href="/como-funciona">Cómo funciona' in s
    assert 'href="/exchanges"' in s
    assert 'src="/static/landing_apple.js"' in s
    schema=json.loads(re.search(r'<script type="application/ld\+json">([\s\S]*?)</script>',s).group(1))
    assert any(x.get("@type")=="FAQPage" for x in schema["@graph"])
