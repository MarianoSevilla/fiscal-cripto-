"""Content, access and SEO contracts for the isolated How proposal."""
import json,re
from html.parser import HTMLParser
from pathlib import Path

STATIC=Path(__file__).resolve().parents[1]/'static'
PAGE=STATIC/'como_funciona_apple.html'

class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[]
    def handle_data(self,data):self.parts.append(data)

def plain(fragment):
    p=Text();p.feed(fragment);return ' '.join(' '.join(p.parts).split())

def test_preview_scope_and_metadata():
    text=PAGE.read_text()
    assert '<meta name="robots" content="noindex, nofollow">' in text
    assert '<link rel="canonical" href="https://marianosevilla.com/como-funciona">' in text
    assert 'fonts.googleapis.com' not in text and '<form' not in text
    assert 'window.fetch' not in text
    for script in ['nav.js','landing_apple.js','como_funciona_apple.js']:
        assert f'src="/static/{script}"' in text
    assert text.count('<main ')==1 and text.count('<h1 ')==1

def test_preserve_destinations_and_original_anchors():
    text=PAGE.read_text()
    for path in ['/signup/','/login/','/exchanges','/exchanges/binance','/exchanges/bitvavo','/exchanges/kraken','/contacto','/metodo-fifo-criptomonedas','/modelo-721-criptomonedas','/pedir-asesoramiento','/faq','/privacidad','/terminos','/cookies','/aviso-legal']:
        assert f'href="{path}"' in text,path
    for anchor in ['sube-tu-csv','clasificacion','calculo-fifo','informe-pdf','privacidad-seguridad','faq']:
        assert f'id="{anchor}"' in text,anchor
    assert text.count('class="apple-catalog-card"')==3
    for name in ['Binance','Bit2Me','Bitget','Bitvavo','Coinbase','Crypto.com','Kraken','KuCoin','MEXC','Nexo','Uphold','Bybit']:
        assert name in text

def test_report_is_semantic_and_copy_is_bounded():
    text=PAGE.read_text()
    assert text.count('<table ')==1 and text.count('scope="col"')==5
    assert 'Datos ficticios' in text and 'tabindex="0" role="region"' in text
    assert '2024' not in text and '37.2' not in text and 'casilla 0033' not in text
    assert 'Presupuestos y pagos de asesoramiento temporalmente suspendidos.' in text
    assert 'No constituye asesoramiento fiscal ni legal.' in text
    assert 'No des por consolidado automáticamente el historial de distintos exchanges.' in text
    assert 'El registro no implica que todos los informes o servicios estén incluidos.' in text
    assert 'no se comparten con terceros' not in text

def test_faq_schema_matches_visible_answers():
    text=PAGE.read_text()
    graph=json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>',text,re.S)[1])['@graph']
    faq=next(x for x in graph if x['@type']=='FAQPage')['mainEntity']
    visible=re.findall(r'<details class="apple-faq-item"><summary>(.*?)</summary><div class="apple-faq-answer"><p>(.*?)</p></div></details>',text,re.S)
    assert len(visible)==len(faq)==7
    for item,(q,a) in zip(faq,visible):
        assert plain(q)==item['name']
        assert plain(a)==item['acceptedAnswer']['text']

def test_footer_reuses_approved_home_and_nojs_access_exists():
    home=(STATIC/'landing.html').read_text();text=PAGE.read_text()
    def footer(s):return s[s.index('<footer class="apple-footer">'):s.index('</footer>')+9]
    assert footer(text)==footer(home)
    assert 'class="apple-noscript-menu"' in text
    assert 'class="apple-skip"' in text

def test_cta_positions_and_final_hierarchy():
    text=PAGE.read_text()
    assert 'href="/static/apple_cta.css"' in text
    assert text.index('id="informe-pdf"')<text.index('id="how-mid-cta"')<text.index('id="privacidad-seguridad"')
    assert text.index('id="faq"')<text.index('id="how-final-cta"')<text.index('<footer')
    final=text.split('id="how-final-cta">',1)[1].split('</div></div></section>',1)[0]
    assert final.index('apple-cta-eyebrow')<final.index('<h2')<final.index('apple-cta-description')<final.index('apple-cta-notice')<final.index('apple-cta-benefits')<final.index('class="apple-button"')
    assert final.rstrip().endswith('>Crear cuenta</a>')
