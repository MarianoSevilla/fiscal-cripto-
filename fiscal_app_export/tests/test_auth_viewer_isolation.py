"""The public design viewer must never link into a real Google login."""
from html.parser import HTMLParser
from pathlib import Path
import pytest

class Elements(HTMLParser):
    def __init__(self,text):
        super().__init__();self.nodes=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        self.nodes.append((tag,dict(attrs)))

@pytest.mark.parametrize('view',['login','signup','recuperar','restablecer','verificar'])
def test_auth_viewer_is_static_and_no_credentials_get(view):
    root=Path(__file__).resolve().parents[2]
    nodes=Elements((root/'auth-apple-preview'/view/'index.html').read_text()).nodes
    body=next(a for t,a in nodes if t=='body')
    assert body['data-auth-preview']=='true'
    for tag,a in nodes:
        if tag=='a' and 'auth-google' in a.get('class',''):
            assert a['href']=='#authHeading'
        if tag=='form':assert a.get('method')=='post'
        if tag=='input' and a.get('type')=='password':assert a.get('autocomplete')=='off'
        if tag=='script':assert not a.get('src')
