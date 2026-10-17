"""Production templates with synthetic resources; no app/database/provider imports."""
import json,re
from pathlib import Path
from types import SimpleNamespace
from html.parser import HTMLParser
from jinja2 import Environment,FileSystemLoader,StrictUndefined,select_autoescape

ROOT=Path(__file__).resolve().parents[1]
ENV=Environment(loader=FileSystemLoader(ROOT/'templates'),autoescape=select_autoescape(['html']),undefined=StrictUndefined)
SAMPLE=json.loads((Path(__file__).parent/'resources_apple_fixture.json').read_text())

def render(kind='catalog',resources=None,**changes):
    sample=dict(SAMPLE,**changes)
    return ENV.get_template('recursos.html' if kind=='catalog' else 'recurso.html').render(resources=[SimpleNamespace(**sample)] if resources is None else resources,resource=SimpleNamespace(**sample))

class DOM(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.links=[];self.stack=[];self.success_in_form=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if a.get('id'):self.ids.append(a['id'])
        if tag=='a':self.links.append(a)
        if a.get('id')=='form-success':self.success_in_form='form' in self.stack
        if tag not in ['input','meta','link','br','img','hr']:self.stack.append(tag)
    def handle_endtag(self,tag):
        if tag in self.stack:self.stack=self.stack[:len(self.stack)-1-self.stack[::-1].index(tag)]

def test_templates_keep_production_scope_and_structure():
    for kind in ['catalog','detail']:
        text=render(kind);p=DOM();p.feed(text)
        assert len(p.ids)==len(set(p.ids))
        assert text.count('<main ')==1 and text.count('<h1 ')==1
        assert 'content="index, follow"' in text
        assert 'noindex' not in text
        assert 'rel="canonical"' in text and 'https://marianosevilla.com/recursos' in text
        assert 'fonts.googleapis.com' not in text and 'window.fetch' not in text
        assert 'class="apple-skip"' in text and 'class="apple-noscript-menu"' in text

def test_catalog_dynamic_empty_multiple_and_escaping():
    assert 'Ahora no hay dosieres del canal disponibles.' in render(resources=[])
    resources=[SimpleNamespace(**dict(SAMPLE,slug=f'ficticio-{i}',title='<script>example</script>')) for i in range(4)]
    text=render(resources=resources)
    assert text.count('class="apple-catalog-card"')==14
    assert '<script>example</script>' not in text and '&lt;script&gt;example&lt;/script&gt;' in text
    assert '/recursos/ficticio-3' in text

def test_only_current_partner_destinations_and_disclosure():
    new=DOM();new.feed(render())
    new_links={a['href'] for a in new.links if 'sponsored' in a.get('rel','')}
    assert new_links=={'https://bitvavo.com/es/affiliate/marianosevilla','https://www.gate.com/es-eu/campaigns/76?ref=VFKRXV1ACA&ref_type=132'}
    assert all(name not in render() for name in ['BingX','Bitget','Bitunix'])
    text=render();assert text.index('Estos son enlaces de afiliación.')<text.index('class="apple-catalog-grid resources-affiliates"')

def test_detail_keeps_fields_options_and_consent_requirements():
    text=render('detail');p=DOM();p.feed(text)
    for name in ['name','email','exchange','bitvavo_status','uid','uid_unknown','telegram_user','legal_accepted','marketing_consent','resource_id']:
        assert name in p.ids
    assert re.findall(r'<option value="(.*?)">',text)==['','bitvavo','binance','','registered_via_link','had_account','no_account','not_sure']
    assert '* Ambas opciones son obligatorias para enviar la solicitud.' in text
    assert 'Para enviar la solicitud necesitas activar JavaScript.' in text
    assert 'aria-describedby="uid-helper"' in text

def test_success_is_outside_form_and_live_feedback_exists():
    text=render('detail');p=DOM();p.feed(text)
    assert p.success_in_form is False
    assert 'id="form-success" class="resources-feedback" role="status" tabindex="-1" hidden' in text
    assert 'role="alert" hidden' in text
    js=(ROOT/'static/recursos_apple.js').read_text()
    assert "fetch('/api/recursos/solicitar'" in js
    assert 'marketing_consent:true' in js and 'legal_accepted:true' in js

def test_header_footer_and_legal_destinations_match_home():
    home=(ROOT/'static/landing.html').read_text();text=render()
    footer=home[home.index('<footer class="apple-footer">'):home.index('</footer>')+9]
    assert footer in text
    for href in ['/herramientas','/como-funciona','/recursos','/faq','/contacto','/privacidad','/terminos','/cookies','/aviso-legal']:
        assert f'href="{href}"' in text
    assert 'No constituye asesoramiento fiscal ni legal.' in text

def test_gumroad_resources_and_visible_copy():
    text=render();p=DOM();p.feed(text)
    product_links={a['href'] for a in p.links if a.get('href','').startswith('https://masetru.gumroad.com/l/')}
    assert product_links=={'https://masetru.gumroad.com/l/'+slug+'?layout=profile' for slug in ['algorand','velo','xdc','wevnv','shx','hbar','mapa-nuevo-dinero','checklist-exchange']}
    assert text.count('Comprar informe')==5
    assert 'Comprar guía' in text and 'Comprar el mapa' in text
    assert 'Descargar checklist' in text
    assert 'Registrarse en Bitvavo' in text and 'Registrarse en Gate' in text
    assert 'Gumroad' not in text
    assert text.index('id="informes-y-guias"') < text.index('id="exchanges-colaboradores"') < text.index('id="recursos-disponibles"')
    assert 'Recursos gratuitos.' in text and 'Informes de criptomonedas para analizar antes de invertir.' in text
    assert 'El dossier Bitcoin es gratuito y se solicita aquí.' in text
    assert 'Aportación libre desde 0 €' in text
    assert 'construye tu propio criterio antes de invertir' in text
    assert 'Elegir exchange' not in text
    assert 'Dos colaboradores. Una selección con criterio.' in text
    assert 'sujetas a sus condiciones vigentes' in text
    assert 'https://youtu.be/J5EKVx6gSn0' in text
    assert text.index('class="resources-audit"') < text.index('class="apple-catalog-grid resources-affiliates"')
    assert '<iframe' not in text
    for name in ['recursos.html','recurso.html','_resources_apple_head.html']:
        source=(ROOT/'templates'/name).read_text()
        assert 'window.fetch' not in source and 'recurso-ficticio' not in source
        assert 'resources-preview-note' not in source and 'noindex' not in source
