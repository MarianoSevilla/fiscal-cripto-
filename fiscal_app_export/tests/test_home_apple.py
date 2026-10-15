"""Home preview contracts: preserve source copy, SEO, links and auth behavior."""
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

STATIC=Path(__file__).resolve().parents[1]/'static'

# Only these two copy corrections were approved in the v6 review. All other
# source paragraphs and words remain protected by the preservation contract.
APPROVED_COPY_REVISIONS={
    'Formato estructurado y claro, listo para adjuntar a tu declaración de la renta o entregar a tu asesor. Generado en segundos, descarga inmediata, sin registro previo.':
    'Formato estructurado y claro, listo para adjuntar a tu declaración de la renta o entregar a tu asesor. Generado en segundos, con descarga inmediata desde tu cuenta.',
    '¿Usas Nexo, Crypto.com, Uphold u otro exchange? Escríbenos — seguimos añadiendo soporte continuamente.':
    'Nexo, Crypto.com y Uphold también están en el listado completo de exchanges compatibles. ¿Necesitas ayuda? Escríbenos — seguimos añadiendo soporte continuamente.',
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

class HomeAppleContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=(STATIC/'landing.html').read_text()
        cls.new=(STATIC/'landing_apple.html').read_text()
        cls.a,cls.b=Document(cls.old),Document(cls.new)
    def test_original_copy_remains_except_approved_revisions(self):
        for old,new in APPROVED_COPY_REVISIONS.items():
            self.assertEqual(self.a.paragraphs.count(old),1)
            self.assertEqual(self.b.paragraphs.count(new),1)
            self.assertNotIn(old,self.b.paragraphs)
        expected=[APPROVED_COPY_REVISIONS.get(p,p) for p in self.a.paragraphs]
        missing=Counter(expected)-Counter(self.b.paragraphs)
        self.assertFalse(missing,dict(missing))
        # Also protect non-paragraph copy, including FAQ prompts and legal text.
        expected_text=normal(' '.join(self.a.text))
        for old,new in APPROVED_COPY_REVISIONS.items():
            self.assertEqual(expected_text.count(old),1)
            expected_text=expected_text.replace(old,new)
        old=Counter(expected_text.split())
        new=Counter(normal(' '.join(self.b.text)).split())
        self.assertFalse(old-new,dict(old-new))

    def test_example_table_preserves_data_and_header_relationships(self):
        fragment=re.search(r'<table class="mock-table">[\s\S]*?</table>',self.new)
        self.assertIsNotNone(fragment)
        table=ET.fromstring(fragment.group(0))
        self.assertIn('Datos ficticios',table.findtext('caption'))
        headers=table.findall('./thead/tr/th')
        self.assertEqual([h.text for h in headers],['Fecha','Activo','Tipo','Transmisión','G/P'])
        self.assertTrue(all(h.get('scope')=='col' for h in headers))
        rows=table.findall('./tbody/tr')
        self.assertEqual(len(rows),5)
        self.assertTrue(all(len(row.findall('td'))==5 for row in rows))
        original_rows=re.findall(r'<div class="mock-table-row">([\s\S]*?)</div>',self.old)
        original_text=[normal(' '.join(ET.fromstring('<div>'+r+'</div>').itertext())) for r in original_rows]
        self.assertEqual([normal(' '.join(row.itertext())) for row in rows],original_text)
    def test_links_and_structured_data_are_preserved(self):
        self.assertFalse(Counter(self.a.links)-Counter(self.b.links))
        self.assertEqual(self.a.schemas,self.b.schemas)
        self.assertEqual(self.a.canonical,self.b.canonical)
        self.assertEqual(self.b.canonical,'https://marianosevilla.com/')
    def test_variant_is_noindex_and_isolated(self):
        self.assertIn('noindex',self.b.robots)
        self.assertIn('nofollow',self.b.robots)
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
    def test_local_assets_and_source_anchors_exist(self):
        for href in self.b.links:
            if href.startswith('#'):self.assertIn(href[1:],self.b.ids)
        for name in ['landing_apple.css','landing_apple.js','nav.css','nav.js']:
            self.assertTrue((STATIC/name).is_file())
        self.assertNotIn('fonts.googleapis.com',self.new)
        self.assertIn('Datos ficticios',self.new)
        self.assertEqual(self.new.count('class="apple-faq-item"'),12)

if __name__=='__main__':unittest.main()
