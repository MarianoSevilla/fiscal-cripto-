"""Home integration: preserve approved design, source copy, SEO and auth behavior."""
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

STATIC=Path(__file__).resolve().parents[1]/'static'
BASELINES=Path(__file__).with_name('fixtures')/'home_apple'
V20_COPY=json.loads((Path(__file__).with_name('home_apple_v20_copy.json')).read_text())

def revise_v20(text, include_labels=False):
    for change in V20_COPY['paragraphs']+(V20_COPY['labels'] if include_labels else []):
        text=text.replace(change['before'],change['after'])
    return text

# Explicitly approved paragraph revisions and labels (V6–V11).
# All remaining source paragraphs and words stay protected.
APPROVED_COPY_REVISIONS={
    'Formato estructurado y claro, listo para adjuntar a tu declaración de la renta o entregar a tu asesor. Generado en segundos, descarga inmediata, sin registro previo.':
    'Formato estructurado y claro, listo para adjuntar a tu declaración de la renta o entregar a tu asesor. Generado en segundos, con descarga inmediata desde tu cuenta.',
    'Sin tarjeta · Importa tus CSVs · Generación automática FIFO':
    'Sin tarjeta · Importa tus CSVs · Generación automática FIFO · Datos para tu declaración',
}

# V17: bounded audit correction, supported by AEAT Renta 2025 scales.
APPROVED_FISCAL_COPY=(
    'A esa ganancia se aplica el tipo del ahorro: entre el 19% y el 28% según el importe total del ejercicio. El mismo cálculo aplica',
    'En el ejercicio 2025, en territorio común, la base liquidable del ahorro se grava por tramos entre el 19 % y el 30 %. El tipo aplicable depende del importe total de esa base. El mismo cálculo de la ganancia aplica',
)
APPROVED_FISCAL_SCHEMA=(
    'A esa ganancia se aplica el tipo del ahorro, entre el 19% y el 28% según el importe total del ejercicio.',
    'En el ejercicio 2025, en territorio común, la base liquidable del ahorro se grava por tramos entre el 19 % y el 30 %. El tipo aplicable depende del importe total de esa base.',
)

# V15: owner-approved removal of this complete redundant support block.
REMOVED_SOURCE_PARAGRAPH='¿Usas Nexo, Crypto.com, Uphold u otro exchange? Escríbenos — seguimos añadiendo soporte continuamente.'
REMOVED_PREVIEW_PARAGRAPH='Nexo, Crypto.com y Uphold también están en el listado completo de exchanges compatibles. ¿Necesitas ayuda? Escríbenos — seguimos añadiendo soporte continuamente.'

# V8: explicitly approved navigation label; destination and content are retained.
APPROVED_LINK_LABEL=('Ver todos los exchanges compatibles →',
                     'Consultar exchanges compatibles →')
APPROVED_REPORT_CTA=('Genera tu informe gratis','Preparar mi informe')
APPROVED_PRESENTATION_LABELS={
    'Crea tu cuenta gratis':'Crear cuenta',
    'fiscal.marianosevilla.com':'Informe FIFO de criptomonedas',
}
APPROVED_EXAMPLE_DATES={
    f'{day}/{month}/2024':f'{day}/{month}/2025'
    for day,month in [('15','03'),('02','05'),('18','06'),('29','09'),('11','11')]
}

def normal(text):
    return ' '.join(text.split())

class Document(HTMLParser):
    def __init__(self,text):
        super().__init__();self.stack=[];self.excluded=0;self.text=[];self.paragraphs=[]
        self.current_p=None;self.ids=[];self.links=[];self.schemas=[];self.schema=None
        self.robots='';self.canonical='';self.main=0;self.h1=0;self.body=False
        self.feed(text)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='body':self.body=True
        if tag in ('script','style'):
            self.excluded+=1
            if a.get('type')=='application/ld+json':self.schema=[]
        if a.get('id'):self.ids.append(a['id'])
        if tag=='meta' and a.get('name')=='robots':self.robots=a.get('content','')
        if tag=='link' and a.get('rel')=='canonical':self.canonical=a.get('href','')
        if tag=='main':self.main+=1
        if tag=='h1':self.h1+=1
        if self.body and tag=='a':self.links.append(a.get('href',''))
        if self.body and tag=='p':self.current_p=[]
    def handle_endtag(self,tag):
        if tag in ('script','style'):
            if self.schema is not None:
                self.schemas.append(json.loads(''.join(self.schema)));self.schema=None
            self.excluded=max(0,self.excluded-1)
        if tag=='p' and self.current_p is not None:
            self.paragraphs.append(normal(' '.join(self.current_p)));self.current_p=None
        if tag=='body':self.body=False
    def handle_data(self,data):
        if self.schema is not None:self.schema.append(data)
        if self.body and not self.excluded:
            self.text.append(data)
            if self.current_p is not None:self.current_p.append(data)

class HomeRedesignContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=(BASELINES/'original_main.html').read_text()
        cls.new=(STATIC/'landing.html').read_text()
        cls.a,cls.b=Document(cls.old),Document(cls.new)
    def test_original_copy_remains_except_approved_revisions(self):
        for old,new in APPROVED_COPY_REVISIONS.items():
            self.assertEqual(self.a.paragraphs.count(old),1)
            self.assertEqual(self.b.paragraphs.count(revise_v20(new)),1)
            self.assertNotIn(old,self.b.paragraphs)
        self.assertEqual(self.a.paragraphs.count(REMOVED_SOURCE_PARAGRAPH),1)
        expected=[revise_v20(APPROVED_COPY_REVISIONS.get(p,p).replace(*APPROVED_FISCAL_COPY)) for p in self.a.paragraphs
                  if p!=REMOVED_SOURCE_PARAGRAPH]
        missing=Counter(expected)-Counter(self.b.paragraphs)
        self.assertFalse(missing,dict(missing))
        # Also protect non-paragraph copy, including FAQ prompts and legal text.
        expected_text=normal(' '.join(self.a.text))
        self.assertEqual(expected_text.count(REMOVED_SOURCE_PARAGRAPH),1)
        expected_text=expected_text.replace(REMOVED_SOURCE_PARAGRAPH,'')
        for old,new in APPROVED_COPY_REVISIONS.items():
            self.assertEqual(expected_text.count(old),1)
            expected_text=expected_text.replace(old,new)
        old,new=APPROVED_FISCAL_COPY
        self.assertEqual(expected_text.count(old),1)
        expected_text=expected_text.replace(old,new)
        expected_text=revise_v20(expected_text,include_labels=True)
        old_label,new_label=APPROVED_LINK_LABEL
        self.assertEqual(expected_text.count(old_label),1)
        expected_text=expected_text.replace(old_label,new_label)
        self.assertEqual(normal(' '.join(self.b.text)).count(new_label),1)
        old_cta,new_cta=APPROVED_REPORT_CTA
        self.assertEqual(expected_text.count(old_cta),1)
        expected_text=expected_text.replace(old_cta,new_cta)
        self.assertEqual(normal(' '.join(self.b.text)).count(new_cta),1)
        self.assertNotIn(old_cta,normal(' '.join(self.b.text)))
        for old_value,new_value in {**APPROVED_PRESENTATION_LABELS,**APPROVED_EXAMPLE_DATES}.items():
            self.assertEqual(expected_text.count(old_value),1)
            expected_text=expected_text.replace(old_value,new_value)
        # Owner-approved October 28 restoration: remove only the old four-item
        # trust list. Its unsafe privacy claim is not reintroduced elsewhere.
        removed_copy=('Método FIFO Compatible con los principales exchanges '
                      'Privacidad y seguridad — tu CSV no se almacena '
                      '100% online, sin instalación')
        self.assertEqual(expected_text.count(removed_copy),1)
        expected_text=expected_text.replace(removed_copy,'')
        self.assertNotIn('Consulta cómo tratamos tus archivos en nuestra',self.new)
        old=Counter(expected_text.split())
        new=Counter(normal(' '.join(self.b.text)).split())
        self.assertFalse(old-new,dict(old-new))

    def test_example_table_preserves_data_and_header_relationships(self):
        fragment=re.search(r'<table class="mock-table">[\s\S]*?</table>',self.new)
        self.assertIsNotNone(fragment)
        table=ET.fromstring(fragment.group(0))
        self.assertIn('Datos ficticios',table.findtext('caption'))
        headers=table.findall('./thead/tr/th')
        self.assertEqual([h.text for h in headers[:4]],['Fecha','Activo','Tipo','Transmisión'])
        self.assertEqual(headers[-1].find("span[@aria-hidden='true']").text,'G/P')
        self.assertEqual(headers[-1].find("span[@class='apple-sr-only']").text,'Ganancia o pérdida')
        self.assertIn('Importes en euros',table.findtext('caption'))
        self.assertTrue(all(h.get('scope')=='col' for h in headers))
        rows=table.findall('./tbody/tr')
        self.assertEqual(len(rows),5)
        self.assertTrue(all(len(row.findall('td'))==5 for row in rows))
        original_rows=re.findall(r'<div class="mock-table-row">([\s\S]*?)</div>',self.old)
        original_text=[normal(' '.join(ET.fromstring('<div>'+r+'</div>').itertext())) for r in original_rows]
        for old_date,new_date in APPROVED_EXAMPLE_DATES.items():
            original_text=[row.replace(old_date,new_date) for row in original_text]
        self.assertEqual([normal(' '.join(row.itertext())) for row in rows],original_text)
        dates=table.findall('./tbody/tr/td/time')
        self.assertEqual(len(dates),5)
        self.assertEqual([date.text for date in dates],list(APPROVED_EXAMPLE_DATES.values()))
        for date in dates:
            day,month,year=date.text.split('/')
            self.assertEqual(date.get('datetime'),f'{year}-{month}-{day}')
    def test_links_and_structured_data_are_preserved(self):
        expected_links=Counter(self.a.links)
        expected_links['/contacto']-=1  # Link inside the explicitly removed block.
        self.assertFalse(expected_links-Counter(self.b.links))
        self.assertGreaterEqual(self.b.links.count('/contacto'),1)
        # Footer redesign keeps each original destination and its full disclaimer.
        original_footer=re.search(r'<div class="legal-bar">[\s\S]*?</div>\s*</div>',self.old).group(0)
        footer=ET.fromstring(re.search(r'<footer\b[\s\S]*?</footer>',self.new).group(0))
        original_notice=normal(re.search(r'<span>([\s\S]*?)</span>',original_footer).group(1))
        self.assertEqual(footer.find('.//p[@class="apple-footer-disclaimer"]').text,original_notice)
        footer_links=Counter(link.get('href') for link in footer.findall('.//a'))
        self.assertFalse(Counter(re.findall(r'href="([^"]+)"',original_footer))-footer_links)
        self.assertEqual(footer_links['/contacto'],1)
        expected_schemas=json.loads(json.dumps(self.a.schemas))
        app=next(item for item in expected_schemas[0]['@graph'] if item['@id'].endswith('#app'))
        self.assertEqual(app.pop('offers'),{'@type':'Offer','price':'0','priceCurrency':'EUR'})
        faq=next(item for item in expected_schemas[1]['mainEntity'] if item['name']=='¿Cómo se calculan las ganancias de Bitcoin?')
        self.assertIn(APPROVED_FISCAL_SCHEMA[0],faq['acceptedAnswer']['text'])
        faq['acceptedAnswer']['text']=faq['acceptedAnswer']['text'].replace(*APPROVED_FISCAL_SCHEMA)
        for change in V20_COPY['schemas']:
            parent=expected_schemas
            for key in change['path'][:-1]:parent=parent[key]
            key=change['path'][-1]
            self.assertEqual(parent[key],change['before'])
            parent[key]=change['after']
        self.assertEqual(expected_schemas,self.b.schemas)
        self.assertEqual(self.a.canonical,self.b.canonical)
        self.assertEqual(self.b.canonical,'https://marianosevilla.com/')
    def test_removed_support_block_does_not_return(self):
        text=normal(' '.join(self.b.text))
        self.assertNotIn('apple-exchange-support',self.new)
        self.assertNotIn('apple-support-context',self.new)
        self.assertNotIn(REMOVED_SOURCE_PARAGRAPH,text)
        self.assertNotIn(REMOVED_PREVIEW_PARAGRAPH,text)
        self.assertNotIn('¿Necesitas ayuda?',text)
        self.assertNotIn('seguimos añadiendo soporte continuamente.',text)
        self.assertEqual(self.b.ids.count('asistenciaBlock'),1)
        self.assertIn('Asistencia especializada',text)
        self.assertIn('¿Necesitas ayuda con tu declaración?',text)
        self.assertIn('/pedir-asesoramiento',self.b.links)
    def test_home_remains_indexable_and_preserves_document_structure(self):
        self.assertEqual(self.b.robots,'index, follow')
        self.assertNotIn('noindex',self.b.robots)
        self.assertNotIn('landing_apple.',self.old)
        self.assertIn('class="apple-home"',self.new)
        self.assertEqual(self.b.main,1)
        self.assertEqual(self.b.h1,1)
        self.assertEqual(len(self.b.ids),len(set(self.b.ids)))
    def test_authentication_script_is_unchanged(self):
        def script(s):
            return next(x for x in re.findall(r'<script[^>]*>([\s\S]*?)</script>',s)
                        if 'const _authModal' in x)
        self.assertEqual(script(self.old),script(self.new))
        for ident in ['authModal','authFormLogin','authFormReg','authLoginEmail','authLoginPass']:
            self.assertIn(ident,self.b.ids)

    def test_home_is_exactly_approved_v24_with_original_indexing_policy(self):
        approved=(BASELINES/'approved_v24.html').read_text()
        self.assertEqual(approved.count('<meta name="robots" content="noindex, nofollow">'),1)
        expected=approved.replace(
            '<meta name="robots" content="noindex, nofollow">',
            '<meta name="robots" content="index, follow">')
        # Only the redundant trust strip below the green hero is removed.
        trust=r'<section class="apple-trust"[\s\S]*?</section>\n'
        self.assertEqual(len(re.findall(trust,expected)),1)
        expected=re.sub(trust,'',expected,count=1)
        self.assertEqual(self.new,expected)
    def test_local_assets_and_source_anchors_exist(self):
        for href in self.b.links:
            if href.startswith('#'):self.assertIn(href[1:],self.b.ids)
        for name in ['landing_apple.css','landing_apple.js','nav.css','nav.js']:
            self.assertTrue((STATIC/name).is_file())
        self.assertNotIn('fonts.googleapis.com',self.new)
        self.assertIn('Datos ficticios',self.new)
        self.assertEqual(self.new.count('class="apple-faq-item"'),12)
        self.assertNotIn('class="apple-faq-item" open',self.new)
        self.assertIn('id="apple-exchange-more" open',self.new)

    def test_metadata_does_not_promise_an_undefined_free_report(self):
        descriptions=re.findall(r'<meta (?:name="description"|property="og:description"|name="twitter:description") content="([^"]+)"',self.new)
        self.assertEqual(len(descriptions),3)
        self.assertEqual(len(set(descriptions)),1)
        self.assertNotIn('gratis',descriptions[0].lower())
        app=next(item for item in self.b.schemas[0]['@graph'] if item['@id'].endswith('#app'))
        self.assertNotIn('offers',app)

    def test_v20_is_bounded_editorial_revision_and_faq_schema_matches(self):
        previous=Document((BASELINES/'v19.html').read_text())
        actual_changes=[{'before':old,'after':new} for old,new in zip(previous.paragraphs,self.b.paragraphs) if old!=new]
        self.assertEqual(len(previous.paragraphs),len(self.b.paragraphs))
        self.assertEqual(actual_changes,V20_COPY['paragraphs'])
        for change in V20_COPY['paragraphs']:
            self.assertEqual(previous.paragraphs.count(change['before']),1)
            self.assertEqual(self.b.paragraphs.count(change['after']),1)
        # PR114: only the duplicate pending-session fallback is retired.
        # Keep every other byte of the approved Home enhancements protected.
        approved_js=(BASELINES/'v19.js').read_text()
        start=approved_js.index('  // A delayed session lookup must not block public navigation.')
        end=approved_js.index('  // Demonstration dates follow the previous tax year in Spain.',start)
        expected_js=approved_js[:start]+'  // Shared nav.js owns pending/error/anonymous access states on every page.\n\n'+approved_js[end:]
        self.assertEqual((STATIC/'landing_apple.js').read_text(),expected_js)
        css=(STATIC/'landing_apple.css').read_text()
        original,layout=css.split('/* V24: approved V23 geometry, with the application\'s session-aware header. */')
        self.assertEqual(original.rstrip(),(BASELINES/'v19.css').read_text().rstrip())
        self.assertIn('.apple-home #site-nav { position:relative;',layout)
        self.assertIn('.apple-home .apple-intro-inner { padding-top:36px; }',layout)
        self.assertNotIn('position:fixed',layout)
        self.assertEqual(previous.ids,self.b.ids)
        without_noscript=lambda text: re.sub(r'<noscript>[\s\S]*?</noscript>','',text)
        previous_html=(BASELINES/'v19.html').read_text()
        trust=r'<section class="apple-trust"[\s\S]*?</section>\n'
        self.assertEqual(len(re.findall(trust,previous_html)),1)
        previous_html=re.sub(trust,'',previous_html,count=1)
        expected_links=Document(without_noscript(previous_html)).links
        actual_links=Document(without_noscript(self.new)).links
        self.assertNotIn('/privacidad#conservacion',actual_links)
        self.assertIn('/exchanges',actual_links)  # Still linked from the exchange section.
        self.assertIn('/privacidad',actual_links)  # Privacy remains in the footer.
        self.assertEqual(expected_links,actual_links)
        items=re.findall(r'<details class="apple-faq-item"><summary>(.*?)</summary><div class="apple-faq-answer"><p>([\s\S]*?)</p>',self.new)
        from html import unescape
        faq=self.b.schemas[1]['mainEntity']
        self.assertEqual(len(items),12)
        for (question,answer),entry in zip(items,faq):
            self.assertEqual(unescape(question),entry['name'])
            self.assertEqual(normal(unescape(re.sub('<[^>]+>','',answer))),entry['acceptedAnswer']['text'])
        for stale in ('casilla 0033','casilla 1626','desde 2019','art. 37.2','Art. 37.2','única forma válida','PDF listo para Hacienda','combina los datos automáticamente'):
            self.assertNotIn(stale,self.new)

    def test_v21_changes_only_noscript_header_and_preserves_native_navigation(self):
        baseline=(BASELINES/'v20.html').read_text().replace(
            '<meta name="robots" content="noindex, nofollow">',
            '<meta name="robots" content="index, follow">')
        # The entire V21 trust band is removed, not reverted to its unsafe copy.
        trust=r'<section class="apple-trust"[\s\S]*?</section>\n'
        self.assertEqual(len(re.findall(trust,baseline)),1)
        baseline=re.sub(trust,'',baseline,count=1)
        pattern=r'<noscript>[\s\S]*?</noscript>'
        self.assertEqual(re.sub(pattern,'',baseline),re.sub(pattern,'',self.new))
        fallback=re.search(pattern,self.new).group(0)
        menu=re.search(r'<details class="apple-noscript-menu">([\s\S]*?)</details>',fallback).group(1)
        self.assertIn('<summary>',menu)
        self.assertIn('Menú principal',menu)
        self.assertNotIn(' open',menu)
        self.assertNotIn('<script',fallback)
        self.assertNotIn('onclick',fallback)
        self.assertEqual(Document('<body>'+menu+'</body>').links,
                         ['/herramientas','/como-funciona','/recursos','/faq','/contacto','/login/','/signup/'])
        self.assertIn('@media (max-width:1200px)',fallback)
        self.assertIn('@media (min-width:1201px)',fallback)
        mobile=fallback.split('@media (max-width:1200px)',1)[1]
        self.assertNotIn('position:static',mobile)
        self.assertNotIn('flex-wrap:wrap',mobile)
        self.assertIn('width:44px;height:44px',mobile)
        self.assertIn('max-height:calc(100dvh - 64px)',mobile)

    def test_portraits_have_local_responsive_assets_and_png_fallbacks(self):
        pictures=re.findall(r'<picture class="author-portrait">([\s\S]*?)</picture>',self.new)
        self.assertEqual(len(pictures),2)
        for picture in pictures:
            self.assertIn('type="image/webp"',picture)
            self.assertIn('loading="lazy"',picture)
            self.assertIn('decoding="async"',picture)
            self.assertIn('sizes="(max-width:640px) 72px, 88px"',picture)
            for asset in re.findall(r'/static/(home-apple-[\w.-]+)',picture):
                self.assertTrue((STATIC/asset).is_file(),asset)
            self.assertRegex(picture,r'<img[^>]+src="/static/home-apple-[^"]+\.png"')
        # At 2x and 3x, both WebP images stay below the agreed 100 kB budget.
        for width in (176,264):
            self.assertLess(sum((STATIC/f'home-apple-{person}-{width}.webp').stat().st_size for person in ('mariano','rafa')),100_000)

if __name__=='__main__':unittest.main()
