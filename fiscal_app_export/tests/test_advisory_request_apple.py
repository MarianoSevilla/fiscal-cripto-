"""Advisory intake reuses Contact components; keep the existing request contract."""
from pathlib import Path
import re

STATIC=Path(__file__).resolve().parents[1]/"static"

def block(s,start,end):
    i=s.index(start)
    return s[i:s.index(end,i)+len(end)]

def test_request_uses_exact_approved_assets():
    s=(STATIC/"pedir-asesoramiento.html").read_text()
    c=(STATIC/"contacto.html").read_text()
    h=(STATIC/"landing.html").read_text()
    sheets=lambda x:re.findall(r'<link rel="stylesheet" href="([^"]+)"',x)
    assert sheets(s)==sheets(c)==["/static/nav.css","/static/landing_apple.css","/static/contacto_apple.css"]
    for start,end in [('<nav id="site-nav"',"</nav>"),("<noscript>","</noscript>")]:
        assert block(s,start,end)==block(c,start,end).replace(' aria-current="page"','')
    assert block(s,'<footer class="apple-footer">',"</footer>")==block(h,'<footer class="apple-footer">',"</footer>")
    assert s.count("<style>")==1 and "fonts.googleapis.com" not in s
    assert 'class="apple-home apple-contact"' in s
    assert 'class="apple-button contact-submit"' in s
    assert s.count("<h1 ")==s.count("<main ")==1

def test_request_preserves_fields_and_suspension():
    s=(STATIC/"pedir-asesoramiento.html").read_text()
    assert '<meta name="robots" content="noindex">' in s
    assert '<form id="advisoryForm" method="post" novalidate>' in s
    assert 'id="advisoryFields" class="contact-fields" disabled' in s
    assert 'id="submitBtn" disabled' in s
    assert "document.getElementById('advisoryFields').disabled = false" in s
    assert set(re.findall(r'name="(full_name|email|phone|case_description)"',s))=={"full_name","email","phone","case_description"}
    assert 'id="legalPrivacy" required' in s
    assert "Debes aceptar la política de privacidad" in s
    assert "fetch('/api/asesoramiento/solicitar'" in s
    assert "tax_residence_country: 'España'" in s
    assert "service_type:          'presupuesto_personalizado'" in s
    assert "tax_year:              new Date().getFullYear() - 1" in s
    assert "Presupuestos suspendidos" in s
    assert "No hemos generado ningún presupuesto, enlace de pago ni cargo." in s
    assert "/api/asesoramiento/precios" not in s
