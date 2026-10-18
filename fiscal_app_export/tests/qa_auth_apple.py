"""Responsive auth UI with synthetic API replies; no provider/network writes."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from qa_home_redesign import WIDTHS,geometry

def context(browser,width=390,js=True,reply=None):
    ctx=browser.new_context(viewport={'width':width,'height':900},java_script_enabled=js)
    calls=[];violations=[]
    def route(r):
        u=urlsplit(r.request.url)
        if u.hostname!='127.0.0.1':
            violations.append('external '+u.hostname);r.abort();return
        if u.path=='/api/me':r.fulfill(status=200,content_type='application/json',body='{"user":null}');return
        if r.request.method=='POST':
            calls.append(u.path)
            if reply is None:violations.append('unexpected write');r.abort();return
            status,data=reply(u.path,r.request.post_data_json)
            r.fulfill(status=status,content_type='application/json',body=json.dumps(data));return
        if u.path=='/dashboard':r.fulfill(status=200,content_type='text/html',body='<main>Destino ficticio</main>');return
        if u.path.startswith('/api/'):
            violations.append('unexpected API '+u.path);r.abort();return
        r.continue_()
    ctx.route('**/*',route)
    return ctx,calls,violations

def open_page(ctx,origin,view,query=''):
    p=ctx.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
    paths={'login':'/login','signup':'/signup','forgot':'/recuperar-contrasena',
           'reset':'/reset-password/synthetic-token','verify':'/verify-email-result'}
    assert p.goto(origin+paths[view]+query,wait_until='networkidle').status==200
    return p,errors

def credentials(page):
    page.locator('#authEmail').fill('person@example.invalid')
    page.locator('#authPassword').fill('A fictional password 2026!')

def run_auth_apple(browser,origin):
    cases=0;art=Path('qa-artifacts');art.mkdir(exist_ok=True)
    for width in WIDTHS:
        for view in ['login','signup','forgot','reset','verify']:
            ctx,calls,violations=context(browser,width)
            p,errors=open_page(ctx,origin,view)
            assert not geometry(p,width),(width,view,geometry(p,width))
            assert p.locator('main').count()==p.locator('h1').count()==1
            assert p.locator('meta[name=robots]').get_attribute('content')=='noindex, nofollow'
            assert p.locator('link[href*="fonts.googleapis"]').count()==0
            assert p.locator('a[href*="/legal/"]').count()==0
            assert p.locator('#authForm').get_attribute('method')=='post'
            for input in p.locator('input').all():
                assert input.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')>=16
                assert input.get_attribute('aria-describedby')
            if width<=900:assert not p.locator('.auth-story').is_visible()
            else:
                assert p.locator('.auth-story').is_visible()
                for image in p.locator('.auth-story img').all():
                    assert image.evaluate('e=>e.complete&&e.naturalWidth>0')
            assert not calls and not violations and not errors,(view,width,violations,errors)
            if width in [390,768,1280]:p.screenshot(path=str(art/f'home_auth_{view}_{width}.png'),full_page=True)
            ctx.close();cases+=1
    # Empty/invalid inputs stay local and move focus to the field.
    ctx,calls,violations=context(browser);p,errors=open_page(ctx,origin,'login')
    p.locator('#authSubmit').click();assert p.locator('#authEmail').get_attribute('aria-invalid')=='true'
    assert p.locator('#authEmail').evaluate('e=>e===document.activeElement')
    credentials(p);p.locator('.auth-reveal').click();assert p.locator('#authPassword').get_attribute('type')=='text'
    p.locator('.auth-reveal').click();assert p.locator('#authPassword').get_attribute('type')=='password'
    assert not calls and not violations;ctx.close();cases+=1
    # Failures must not masquerade as successful email delivery.
    for view in ['login','forgot','verify']:
        ctx,calls,violations=context(browser,reply=lambda path,data:(429,{'error':'Synthetic limit'}))
        p,errors=open_page(ctx,origin,view)
        p.locator('#authEmail').fill('person@example.invalid')
        if view=='login':p.locator('#authPassword').fill('A fictional password 2026!')
        p.locator('#authSubmit').click();p.locator('#authError').wait_for(state='visible')
        assert 'demasiados intentos' in p.locator('#authError').inner_text()
        assert not p.locator('#authStatus').is_visible()
        assert p.locator('#authSubmit').is_enabled()
        assert len(calls)==1 and not violations and not errors;ctx.close();cases+=1
    ctx,calls,violations=context(browser,reply=lambda path,data:(201,{'pending_verification':True,'message':'Si puedes utilizar este correo, recibirás instrucciones para continuar.'}))
    p,errors=open_page(ctx,origin,'signup')
    p.locator('#authName').fill('Persona ficticia');credentials(p);p.locator('#authSubmit').click()
    p.locator('#authStatus').wait_for(state='visible')
    assert not p.locator('#authForm').is_visible() and not p.locator('.auth-google').is_visible()
    assert p.locator('#authResend').is_visible() and len(calls)==1 and not violations and not errors
    assert p.locator('#authContinue').is_visible() and p.locator('#authRecovery').is_visible()
    assert p.locator('#authPassword').input_value()==''
    ctx.close();cases+=1
    # A server reply containing an external redirect is rejected by the browser too.
    ctx,calls,violations=context(browser,reply=lambda path,data:(200,{'redirect_to':'//example.invalid'}))
    p,errors=open_page(ctx,origin,'login','?next=%2F%2Fexample.invalid')
    credentials(p);p.locator('#authSubmit').click();p.wait_for_url(origin+'/dashboard')
    assert not violations and not errors;ctx.close();cases+=1
    # Normal next survives links to signup, Google and recovery.
    ctx,calls,violations=context(browser);p,errors=open_page(ctx,origin,'login','?next=%2Fpedir-asesoramiento')
    for selector in ['.auth-google','a[href*="signup"]','a[href*="recuperar"]']:
        assert 'next=%2Fpedir-asesoramiento' in p.locator(selector).get_attribute('href')
    assert not violations and not errors;ctx.close();cases+=1
    for width in [320,768,1280]:
        ctx,calls,violations=context(browser,width);p,errors=open_page(ctx,origin,'signup')
        p.add_style_tag(content='html{font-size:200%}');p.emulate_media(reduced_motion='reduce')
        assert not geometry(p,width)
        assert p.locator('.auth-orbit img').first.evaluate('e=>getComputedStyle(e).animationName')=='none'
        assert not violations and not errors;ctx.close();cases+=1
    ctx,calls,violations=context(browser,320,js=False);p,errors=open_page(ctx,origin,'login')
    assert p.locator('.auth-noscript').is_visible() and not p.locator('#authForm').is_visible()
    assert not calls and not violations and not errors;ctx.close();cases+=1
    print(f'AUTH_APPLE_QA: PASS ({cases} scenarios; 5 views; {len(WIDTHS)} widths; synthetic requests only)')
