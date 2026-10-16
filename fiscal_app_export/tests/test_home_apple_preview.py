"""Offline review contracts; these are not browser rendering tests."""
import importlib.util
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('export_preview',ROOT/'review-helpers/export_preview.py')
helper=importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class OfflineHeaderContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/'fiscal_app_export/static/landing_apple.html').read_text()
        cls.preview=helper.preview_header(cls.source)

    def test_native_menu_is_present_without_script_or_noscript(self):
        header=re.search(r'<nav id="site-nav">[\s\S]*?</nav>',self.source).group(0)
        source_links=re.findall(r'href="([^"]+)"',re.search(r'<ul class="snav-links">[\s\S]*?</ul>',header).group(0))
        menu=re.search(r'<details class="apple-preview-menu">([\s\S]*?)</details>',self.preview).group(1)
        self.assertEqual(re.findall(r'href="([^"]+)"',menu),source_links+['/login/','/signup/'])
        self.assertIn('<summary aria-label="Menú principal">',menu)
        self.assertNotIn(' open',menu)
        self.assertNotIn('onclick',menu)
        self.assertNotIn('<script',menu)
        self.assertNotIn('<noscript',self.preview)
        # Drawn in markup, not an empty element relying on pseudo-elements.
        icon=ET.fromstring(re.search(r'<svg\b[\s\S]*?</svg>',menu).group(0))
        self.assertEqual(icon.get('width'),'20')
        self.assertEqual(icon.find('path').get('stroke'),'currentColor')
        styles=re.search(r'<style id="apple-preview-header-styles">([\s\S]*?)</style>',self.preview).group(1)
        self.assertNotIn('position:fixed',styles)
        self.assertIn('#site-nav{position:relative',styles)
        self.assertIn('width:44px;height:44px',styles)
        self.assertIn('.apple-skip{position:absolute',styles)
        self.assertIn('body.apple-home{margin:0!important;padding:0!important}',styles)
        body=self.preview.split('<body class="apple-home">',1)[1].lstrip()
        self.assertTrue(body.startswith('<nav id="site-nav"'))

    def test_header_adapter_preserves_all_main_content_and_scripts(self):
        main=lambda text: re.search(r'<main\b[\s\S]*?</main>',text).group(0)
        self.assertEqual(main(self.source),main(self.preview))
        schemas=lambda text: re.findall(r'<script type="application/ld\+json">[\s\S]*?</script>',text)
        self.assertEqual(schemas(self.source),schemas(self.preview))
        # Remove the one isolated adaptation and require full source identity.
        normalized=re.sub(r'<style id="apple-preview-header-styles">[\s\S]*?</style>\n','',self.preview)
        new_header=re.search(r'<nav id="site-nav"[\s\S]*?</details>\s*</div>\s*</nav>',normalized).group(0)
        original_header=re.search(r'<nav id="site-nav">[\s\S]*?</nav>',self.source).group(0)
        normalized=normalized.replace(new_header,original_header,1)
        skip='<a class="apple-skip" href="#contenido">Saltar al contenido</a>'
        normalized=normalized.replace(original_header+'\n'+skip,skip+'\n'+original_header,1)
        self.assertEqual(normalized,re.sub(r'<noscript>[\s\S]*?</noscript>','',self.source))


if __name__=='__main__':
    unittest.main()
