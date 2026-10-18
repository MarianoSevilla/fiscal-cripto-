"""Production Contact QA. Synthetic data; no app import, email, DB or provider I/O."""
import json
from pathlib import Path
from qa_home_redesign import WIDTHS,context,geometry

ROOT=Path(__file__).resolve().parents[1]
MARKUP=(ROOT/'static/contacto.html').read_text()
TURNSTILE='''window.__resets=0;window.__cfMode="%s";window.turnstile={
render:function(target,options){window.__cfOptions=options;const box=document.createElement('div');box.style.width=options.size==="compact"?"150px":"100%%";box.style.minWidth=options.size==="compact"?"150px":"300px";box.style.height=options.size==="compact"?"140px":"65px";document.querySelector(target).replaceChildren(box);if(window.__cfMode!=="pending")options.callback("synthetic-token");return "synthetic-widget";},
remove:function(){document.querySelector('#contactTurnstile').replaceChildren();},
reset:function(){window.__resets++;window.__cfOptions.callback("synthetic-token-"+window.__resets);}};'''

def open_page(ctx,origin,live=True,cf='ready',wait='networkidle'):
    page=ctx.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit',lambda r:r.fulfill(status=200,content_type='application/javascript',body=TURNSTILE%cf))
    page.route('**/api/contacto',lambda r:r.fulfill(status=200,content_type='application/json',body='{"ok":true}'))
    response=page.goto(origin+'/contacto',wait_until=wait)
    assert response.status==200
    if wait=='networkidle':page.locator('#contactSubmit:enabled').wait_for()
    return page,errors

def fill(page):
    page.locator('#nombre').fill('Persona ficticia')
    page.locator('#email').fill('persona@example.invalid')
    page.locator('#tipo').select_option('soporte_tecnico')
    page.locator('#mensaje').fill('Consulta ficticia sobre una incidencia de prueba, sin datos fiscales reales.')
    page.locator('#legal').check()

def structure(page,width):
    assert not geometry(page,width),(width,geometry(page,width))
    nav=page.locator('#site-nav').bounding_box()
    assert abs(nav['y'])<1 and 63<=nav['height']<=65,(width,nav)
    intro=page.locator('.contact-intro').bounding_box()
    assert abs(intro['y']-(nav['y']+nav['height']))<1,(width,intro,nav)
    assert page.locator('h1').count()==page.locator('main').count()==1
    assert page.locator('meta[name="robots"]').get_attribute('content')=='index, follow'
    assert page.locator('link[rel="canonical"]').get_attribute('href')=='https://marianosevilla.com/contacto'
    assert page.locator('#contactForm').get_attribute('method')=='post'
    assert page.locator('#contactForm').get_attribute('data-contact-mode')=='live'
    assert page.locator('#contactSubmit').evaluate('e=>getComputedStyle(e).borderRadius')=='999px'
    assert page.locator('#mensaje').get_attribute('minlength')=='20'
    assert page.locator('#mensaje').get_attribute('maxlength')=='3000'
    assert page.locator('#nombre').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')>=16
    assert page.locator('#nombre').bounding_box()['height']>=48
    assert page.locator('#contactStatus[role="status"][aria-live="polite"]').count()==1
    assert page.locator('#contactErrors[role="alert"]').count()==1
    assert page.locator('link[href*="fonts.googleapis"],link[href*="fonts.gstatic"]').count()==0
    assert page.locator('input[type="file"]').count()==0
    assert page.locator('h1').evaluate('e=>Math.abs(e.getBoundingClientRect().width-e.parentElement.clientWidth+parseFloat(getComputedStyle(e.parentElement).paddingLeft)+parseFloat(getComputedStyle(e.parentElement).paddingRight))<1')

def run_contacto_apple(browser,origin):
    cases=0;art=Path('qa-artifacts');art.mkdir(exist_ok=True)
    assert 'window.fetch' not in MARKUP and 'data-contact-mode="live"' in MARKUP
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        page,errors=open_page(ctx,origin);structure(page,width)
        page.keyboard.press('Tab');assert page.locator('.apple-skip').evaluate('e=>e===document.activeElement')
        page.keyboard.press('Enter');assert page.locator('main').evaluate('e=>e===document.activeElement')
        if width<=1200:
            page.locator('#snavMenuToggle').click()
            assert page.locator('#snavMobileMenu a[href="/herramientas"]').is_visible()
            page.keyboard.press('Escape')
            assert page.locator('#snavMenuToggle').get_attribute('aria-expanded')=='false'
        fill(page);before_selection=page.url
        page.locator('#tipo').select_option('asistencia_fiscal')
        assert page.url==before_selection
        assert page.locator('#nombre').input_value()=='Persona ficticia'
        assert page.locator('#contactAdviceHint').is_visible()
        page.locator('#tipo').select_option('otro')
        assert not page.locator('#contactAdviceHint').is_visible()
        page.locator('#contactSubmit').click()
        page.get_by_text('Mensaje recibido.',exact=False).wait_for()
        assert page.locator('#mensaje').input_value()==''
        assert not violations and not errors,(width,violations,errors)
        page.keyboard.press('Control+Home')
        page.screenshot(path=str(art/f'home_contacto_apple_{width}.png'),full_page=True)
        ctx.close();cases+=1
    for width in [320,390,768,1280]:
        ctx,violations=context(browser,width=width,js=False)
        page=ctx.new_page()
        page.goto(origin+'/contacto',wait_until='networkidle')
        assert page.locator('#contactSubmit').is_disabled()
        assert page.locator('#nombre').is_disabled()
        assert page.locator('#contactForm').get_attribute('method')=='post'
        assert page.locator('#contactBootNotice').is_visible()
        assert page.locator('.contact-fallback a[href^="mailto:"]').is_visible()
        if width<=1200:
            page.locator('.apple-noscript-menu summary').click()
            assert page.locator('.apple-noscript-menu a[href="/herramientas"]').is_visible()
        assert not geometry(page,width),(width,geometry(page,width))
        assert not violations
        ctx.close();cases+=1
    for width in [390,768,1280]:
        ctx,violations=context(browser,width=width)
        page,errors=open_page(ctx,origin)
        page.add_style_tag(content='html{font-size:200%}')
        assert not geometry(page,width),(width,geometry(page,width))
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.apple-button').evaluate('e=>getComputedStyle(e).transitionDuration')=='0s'
        assert not violations and not errors
        ctx.close();cases+=1
    for role in ['user','admin']:
        ctx,violations=context(browser,width=390,role=role)
        page,errors=open_page(ctx,origin)
        page.locator('#snavAvatarWrap:not(.snav-hidden)').wait_for(state='attached')
        page.locator('#snavMenuToggle').click()
        assert page.locator('#snavMobileMenu a[href="/dashboard"]').is_visible()
        assert not violations and not errors
        ctx.close();cases+=1
    held=[];ctx,violations=context(browser,width=390,pending_session=held)
    page,errors=open_page(ctx,origin,wait='domcontentloaded')
    page.locator('#snavMenuToggle').click()
    assert page.locator('#snavMobileMenu a[href="/herramientas"]').is_visible()
    assert held
    for route in held:route.fulfill(status=200,content_type='application/json',body='{"user":null}')
    page.locator('#snavBtnSignup:not(.snav-hidden)').wait_for(state='attached')
    assert not violations and not errors
    ctx.close();cases+=1
    # Client validation, each one begins with a fully valid synthetic draft.
    for name,value,focus in [('nombre','','nombre'),('email','no-es-email','email'),('mensaje','Hola','mensaje'),('mensaje',' '*25,'mensaje'),('legal',False,'legal')]:
        ctx,violations=context(browser,width=390);page,errors=open_page(ctx,origin);fill(page)
        if name=='legal':page.locator('#legal').uncheck()
        else:page.locator('#'+name).fill(value)
        page.locator('#contactSubmit').click()
        assert page.locator('#contactErrors').is_visible()
        assert page.locator('#'+focus).get_attribute('aria-invalid')=='true'
        assert page.locator('#'+focus).evaluate('e=>e===document.activeElement')
        assert not violations and not errors
        ctx.close();cases+=1
    # Live controller tested only with mocked local responses and synthetic Turnstile.
    for width in [390,1280]:
        for scenario in ['success','bad-request','rate-limit','server-error','not-json','network','pending-token','expired-token','double-click']:
            ctx,violations=context(browser,width=width)
            page,errors=open_page(ctx,origin,live=True,cf='pending' if scenario=='pending-token' else 'ready')
            requests=[];held_posts=[]
            def api(route):
                requests.append(route.request.post_data_json)
                if scenario=='network':route.abort();return
                if scenario=='double-click':held_posts.append(route);return
                status={'bad-request':400,'rate-limit':429,'server-error':500}.get(scenario,200)
                if scenario=='not-json':route.fulfill(status=status,content_type='text/html',body='<h1>Error ficticio</h1>');return
                route.fulfill(status=status,content_type='application/json',body=json.dumps({'ok':True} if scenario=='success' else {'error':'Datos inválidos de prueba.'}))
            page.route('**/api/contacto',api)
            fill(page)
            if scenario=='expired-token':page.evaluate('window.__cfOptions["expired-callback"]()')
            page.locator('#contactSubmit').click()
            if scenario in ['pending-token','expired-token']:
                assert not requests
                assert page.locator('#contactErrors').is_visible()
                if scenario=='expired-token':
                    page.locator('#contactSecurityRetry').click()
                    assert page.evaluate('window.__resets')==1
            elif scenario=='double-click':
                page.wait_for_function('document.getElementById("contactSubmit").disabled')
                page.locator('#contactForm').dispatch_event('submit')
                assert len(requests)==1 and len(held_posts)==1
                held_posts[0].fulfill(status=200,content_type='application/json',body='{"ok":true}')
                page.get_by_text('Mensaje recibido.',exact=False).wait_for()
            elif scenario=='success':
                page.get_by_text('Mensaje recibido.',exact=False).wait_for()
                assert page.locator('#mensaje').input_value()==''
                assert len(requests)==1
            else:
                page.locator('#contactErrors:not([hidden])').wait_for()
                assert page.locator('#mensaje').input_value().startswith('Consulta ficticia')
                assert len(requests)==1
            if requests:
                page.locator('#contactSubmit:enabled').wait_for()
                assert page.evaluate('window.__resets')==1
                assert set(requests[0])=={'nombre','email','tipo_consulta','mensaje','website','ts_token'}
            assert not violations and not errors,(scenario,violations,errors)
            ctx.close();cases+=1
    ctx,violations=context(browser,width=1280)
    page,errors=open_page(ctx,origin)
    assert page.evaluate('window.__cfOptions.size')=='flexible'
    page.set_viewport_size({'width':320,'height':900})
    page.wait_for_function('window.__cfOptions.size==="compact"')
    assert not geometry(page,320),geometry(page,320)
    page.set_viewport_size({'width':768,'height':900})
    page.wait_for_function('window.__cfOptions.size==="flexible"')
    assert not geometry(page,768),geometry(page,768)
    assert not violations and not errors
    ctx.close();cases+=1
    print(f'CONTACTO_APPLE_QA: PASS ({cases} scenarios; {len(WIDTHS)} widths; synthetic form and security; no external requests)')
