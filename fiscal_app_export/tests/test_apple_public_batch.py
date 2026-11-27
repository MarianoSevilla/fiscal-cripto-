"""Scope and essential content of the public Apple batch."""
from pathlib import Path
import re

STATIC=Path(__file__).resolve().parents[1]/"static"

def get(p):return (STATIC/p).read_text()
def css(s):return re.findall(r'<link rel="stylesheet" href="([^"]+)"',s)

def test_public_batch_reuses_reference_styles():
    groups={
        "exchanges/kraken.html":["exchanges/nexo.html","exchanges/cryptocom.html"],
        "terminos.html":["aviso-legal.html","cookies.html","seguridad.html"],
        "asesoramiento-fiscal.html":["preferencias.html","asesoramiento-confirmado.html","pagar.html","asesoramiento-cancelado.html"],
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


def test_security_and_cancellation_content():
    s=get("seguridad.html")
    assert 'href="https://marianosevilla.com/seguridad"' in s
    assert 'href="/privacidad#conservacion"' in s
    assert "archivos temporales" in s and "Algunos registros del análisis" in s
    assert "Nunca se guarda en disco" not in s
    assert "No guardamos en ninguna base de datos" not in s
    assert "Vulnerabilidad de seguridad" in s
    c=get("asesoramiento-cancelado.html")
    assert '<meta name="robots" content="noindex">' in c
    main=c.split('<main ',1)[1].split('</main>',1)[0]
    assert "PayPal" not in main and "No se ha realizado ningún cargo" not in main
    assert "temporalmente suspendidos" in main
    assert "<form" not in main and "<button" not in main
    assert re.findall(r'href="([^"]+)"',main)==["/pedir-asesoramiento-fiscal","/","/contacto"]


def test_exchange_ctas_follow_approved_fifo_structure():
    for name in ("binance","bitvavo","kraken","coinbase","nexo","cryptocom","bit2me"):
        html=get(f"exchanges/{name}.html")
        assert 'class="cta-micro-text"' not in html,name
        blocks=html.split('<div class="cta-mid asistencia-block">')
        assert len(blocks)==3,name
        badge = re.search(r'<h2 class="asistencia-badge">([^<]+)</h2>', blocks[0]).group(1)
        assert all(f'<h2 class="asistencia-badge">{badge}</h2>' in block for block in blocks[1:]),name
        assert "Crea tu cuenta gratis y sube" not in html,name
        mid=blocks[1].split('<div class="cta-buttons apple-hero-actions">',1)
        assert len(mid)==2,name
        assert mid[0].count("<li>")==3,name
        buttons,tail=mid[1].split("</div>",1)
        assert re.findall(r'href="([^"]+)"',buttons)==["/"+name,"/asesoramiento-fiscal-criptomonedas"],name
        assert tail.lstrip().startswith("</div>"),name
        assert 'class="cta-micro"' in blocks[2],name


def test_exchange_upload_button_labels():
    names = {"binance": "Binance", "bitvavo": "Bitvavo", "kraken": "Kraken", "coinbase": "Coinbase", "nexo": "Nexo", "cryptocom": "Crypto.com", "bit2me": "Bit2Me"}
    for slug, name in names.items():
        html = get(f"exchanges/{slug}.html")
        buttons = re.findall(r'<a href="/' + slug + r'" class="btn-cta btn-asistencia">([^<]+)</a>', html)
        assert buttons == [f"Subir CSV de {name}"] * 2, (slug, buttons)
