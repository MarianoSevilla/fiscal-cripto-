"""Content/access contracts for the isolated Tools proposal."""
import json,re
from pathlib import Path
from html.parser import HTMLParser

STATIC=Path(__file__).resolve().parents[1]/'static'
PAGE=STATIC/'herramientas.html'

def test_production_is_indexable_and_keeps_canonical():
    text=PAGE.read_text()
    assert '<meta name="robots" content="index, follow">' in text
    assert '<link rel="canonical" href="https://marianosevilla.com/herramientas">' in text
    assert 'fonts.googleapis.com' not in text

def test_six_destinations_and_legal_links_remain():
    text=PAGE.read_text()
    for link in ['/signup/','/modelo-721-criptomonedas','/exchanges','/asesoramiento-fiscal-criptomonedas','/recursos','/metodo-fifo-criptomonedas','/about','/privacidad','/terminos','/cookies','/aviso-legal']:
        assert f'href="{link}"' in text,link
    assert 'Presupuestos y pagos de asesoramiento temporalmente suspendidos.' in text
    assert 'informe fiscal gratis' not in text.lower()
    assert 'informe fiscal sin coste' not in text.lower()
    assert 'No constituye asesoramiento fiscal ni legal.' in text

class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[]
    def handle_data(self,data):self.parts.append(data)

def plain(fragment):
    parser=Text();parser.feed(fragment)
    return ' '.join(' '.join(parser.parts).split())

def test_faq_schema_equals_visible_answers():
    text=PAGE.read_text()
    graph=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',text,re.S)[1])['@graph']
    faq=next(x for x in graph if x['@type']=='FAQPage')['mainEntity']
    visible=re.findall(r'<details class="apple-faq-item"><summary>(.*?)</summary><div class="apple-faq-answer"><p>(.*?)</p></div></details>',text,re.S)
    assert len(faq)==len(visible)==5
    for entry,(q,a) in zip(faq,visible):
        assert plain(q)==entry['name']
        assert plain(a)==entry['acceptedAnswer']['text']

def test_header_footer_match_home_except_current_page_semantics():
    home=(STATIC/'landing.html').read_text();text=PAGE.read_text()
    expected=home[home.index('<footer class="apple-footer">'):home.index('</footer>')+len('</footer>')]
    actual=text[text.index('<footer class="apple-footer">'):text.index('</footer>')+len('</footer>')]
    assert actual==expected
    assert '<script src="/static/nav.js"></script>' in text
    assert '<script src="/static/landing_apple.js" defer></script>' in text
    assert '<main id="contenido" tabindex="-1">' in text
    assert 'class="apple-skip"' in text


def test_only_the_requested_catalogue_changes_from_approved_v5():
    approved=(Path(__file__).parent/'fixtures/herramientas/approved_v5.html').read_text()
    actual=PAGE.read_text()
    catalogue=r'<ul class="tools-grid" role="list">[\s\S]*?</ul>'
    assert re.sub(catalogue,'CATALOGUE',actual).strip()==re.sub(catalogue,'CATALOGUE',approved).replace('<meta name="robots" content="noindex, nofollow">','<meta name="robots" content="index, follow">').strip()
    cards=re.findall(r'<li class="tools-card">\s*<h3>[^<]+</h3>\s*<p class="tools-card-description">[^<]+</p>\s*<a class="tools-card-link" href="[^"]+">[^<]+<span aria-hidden="true"> →</span></a>\s*</li>',actual)
    assert len(cards)==6
    assert 'tools-card-meta' not in actual and 'tools-card-top' not in actual

