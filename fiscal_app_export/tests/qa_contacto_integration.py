"""Real Flask Contact integration, only within qa_flask_navigation's temp SQLite."""
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from qa_contacto_apple import TURNSTILE,fill
from qa_home_redesign import geometry
from urllib.parse import urlsplit

def check_contacto(app,origin):
    import app as module
    from models import Contacto
    assert app.testing and app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///')
    assert urlsplit(origin).hostname=='127.0.0.1'
    received=[];verifications=[];violations=[];cases=0
    def verify(token,ip):
        verifications.append(token)
        return token.startswith('synthetic-token')
    def restrict(route):
        request=route.request;u=urlsplit(request.url)
        if u.hostname!='127.0.0.1':violations.append(u.hostname);route.abort();return
        if request.method!='GET' and not(request.method=='POST' and u.path=='/api/contacto'):
            violations.append(request.method+' '+u.path);route.abort();return
        if request.method=='POST':received.append(request.post_data_json)
        route.continue_()
    # Real DB inserts occur only in disposable CI SQLite. Provider calls are mocked.
    with patch.object(module,'_verify_turnstile',side_effect=verify),patch.object(module.resend,'api_key','synthetic-only'),patch.object(module.resend.Emails,'send',return_value={'id':'synthetic-delivery'}) as email:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            try:
                for width in [390,768,1280]:
                    ctx=browser.new_context(viewport={'width':width,'height':900})
                    ctx.route('**/*',restrict)
                    page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.route('https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit',lambda r:r.fulfill(status=200,content_type='application/javascript',body=TURNSTILE%'ready'))
                    r=page.goto(origin+'/contacto',wait_until='networkidle')
                    assert r.status==200 and "form-action 'self'" in r.headers['content-security-policy']
                    assert page.locator('#contactForm').get_attribute('data-contact-mode')=='live'
                    assert not geometry(page,width),(width,geometry(page,width))
                    with app.app_context():before=Contacto.query.count()
                    fill(page)
                    with page.expect_response(lambda r:r.url==origin+'/api/contacto') as response:
                        page.locator('#contactSubmit').click()
                    assert response.value.status==200
                    page.get_by_text('Mensaje recibido.',exact=False).wait_for()
                    assert page.locator('#mensaje').input_value()==''
                    with app.app_context():
                        assert Contacto.query.count()==before+1
                        row=Contacto.query.order_by(Contacto.id.desc()).first()
                        assert row.email=='persona@example.invalid'
                        assert row.tipo_consulta=='soporte_tecnico'
                        assert row.mensaje.startswith('Consulta ficticia')
                    assert len(received)==email.call_count==len(verifications)==cases+1
                    assert page.evaluate('window.__resets')==1
                    assert not violations and not errors,(violations,errors)
                    ctx.close();cases+=1
            finally:browser.close()
        # Server rejection paths: bypass client only in this temp test instance.
        payload={'nombre':'Persona ficticia','email':'persona@example.invalid','tipo_consulta':'otro','mensaje':'Consulta ficticia suficientemente larga.','website':'','ts_token':'synthetic-token'}
        for update in [{'email':'incorrecto'},{'mensaje':'Hola'},{'tipo_consulta':'inexistente'},{'ts_token':'rejected-token'}]:
            with app.app_context():before=Contacto.query.count()
            sent=email.call_count
            with app.test_client() as client:r=client.post('/api/contacto',json={**payload,**update})
            assert r.status_code==400
            with app.app_context():assert Contacto.query.count()==before
            assert email.call_count==sent
            cases+=1
    print(f'CONTACTO_FLASK_QA: PASS ({cases} integration scenarios; temp SQLite; mocked email and Turnstile; no production I/O)')
    return cases
