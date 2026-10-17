"""Isolated templates with synthetic resources; no app/database/provider imports."""
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
    return ENV.get_template('recursos_apple.html' if kind=='catalog' else 'recurso_apple.html').render(resources=[SimpleNamespace(**sample)] if resources is None else resources,resource=SimpleNamespace(**sample))

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

def test_templates_keep_preview_scope_and_structure():
    for kind in ['catalog','detail']:
        text=render(kind);p=DOM();p.feed(text)
        assert len(p.ids)==len(set(p.ids))
        assert text.count('<main ')==1 and text.count('<h1 ')==1
        assert 'content="noindex, nofollow"' in text
        assert 'rel="canonical"' in text and 'https://marianosevilla.com/recursos' in text
        assert 'fonts.googleapis.com' not in text and 'window.fetch' not in text
        assert 'class="apple-skip"' in text and 'class="apple-noscript-menu"' in text

def test_catalog_dynamic_empty_multiple_and_escaping():
    assert 'Todavía no hay recursos disponibles' in render(resources=[])
    resources=[SimpleNamespace(**dict(SAMPLE,slug=f'ficticio-{i}',title='<script>example</script>')) for i in range(4)]
    text=render(resources=resources)
    assert text.count('class="apple-catalog-card"')==8
    assert '<script>example</script>' not in text and '&lt;script&gt;example&lt;/script&gt;' in text
    assert '/recursos/ficticio-3' in text

def test_affiliate_destinations_and_disclosure_preserved():
    old=DOM();old.feed((ROOT/'templates/recursos.html').read_text());new=DOM();new.feed(render())
    old_links={a['href'] for a in old.links if 'sponsored' in a.get('rel','')}
    new_links={a['href'] for a in new.links if 'sponsored' in a.get('rel','')}
    assert len(old_links)==4 and old_links==new_links
    text=render();assert text.index('Estos son enlaces de afiliación.')<text.index('class="apple-catalog-grid resources-affiliates"')

def test_detail_keeps_fields_options_and_consent_requirements():
    text=render('detail');p=DOM();p.feed(text)
    for name in ['name','email','exchange','bitvavo_status','uid','uid_unknown','telegram_user','legal_accepted','marketing_consent','resource_id']:
        assert name in p.ids
    assert re.findall(r'<option value="(.*?)">',text)==re.findall(r'<option value="(.*?)">',(ROOT/'templates/recurso.html').read_text())
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
