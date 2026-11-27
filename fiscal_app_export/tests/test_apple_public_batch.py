"""Scope and essential content of the public Apple batch."""
from pathlib import Path
import re

STATIC=Path(__file__).resolve().parents[1]/"static"

def get(p):return (STATIC/p).read_text()
def css(s):return re.findall(r'<link rel="stylesheet" href="([^"]+)"',s)

def test_public_batch_reuses_reference_styles():
    groups={
        "exchanges/kraken.html":["exchanges/nexo.html","exchanges/cryptocom.html"],
        "terminos.html":["aviso-legal.html","cookies.html"],
        "asesoramiento-fiscal.html":["preferencias.html","asesoramiento-confirmado.html","pagar.html"],
    }
    for ref,pages in groups.items():
        for path in pages:
            html=get(path)
            assert css(html)==css(get(ref)),path
            assert "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html,path
            assert html.count("<h1")==html.count("<main ")==1,path
            assert 'class="apple-skip"' in html,path
            if not path.startswith("exchanges/"):
                assert html.count("<style>")==1,path  # approved noscript fallback
                assert 'class="apple-footer"' in html,path

def test_batch_preserves_public_contract():
    for name in ["nexo","cryptocom"]:
        html=get(f"exchanges/{name}.html")
        assert f'href="https://marianosevilla.com/exchanges/{name}"' in html
        assert f'href="/{name}" class="btn-asistencia"' in html
        assert 'class="files-table"' in html and 'class="faq-item"' in html
    assert get("aviso-legal.html").count('class="legal-section"')==8
    c=get("cookies.html")
    assert c.count('class="legal-section"')==5 and "<code>session</code>" in c
    assert "30 minutos" in c and "15 minutos" in c and 'href="/preferencias"' in c
    p=get("preferencias.html")
    assert "Siempre activas" in p and p.count("No se usan")==2
    assert "No hay cookies opcionales que gestionar" in p
    assert "<form" not in p
    assert "no acredita que se haya recibido ninguna solicitud ni ningún pago" in get("asesoramiento-confirmado.html")
    for path in ["pagar.html","asesoramiento-confirmado.html"]:
        s=get(path)
        assert '<meta name="robots" content="noindex">' in s
        main=s.split('<main ',1)[1].split('</main>',1)[0]
        assert "<form" not in main and "<button" not in main
        assert re.findall(r'href="([^"]+)"',main)==["/"]
    assert 'id="financialSuspension"' in get("pagar.html")
