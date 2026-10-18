"""Workspace UI, role discovery and inert viewer; synthetic responses only."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from qa_home_redesign import WIDTHS,geometry

def context(browser,role='user',width=390,js=True,pending=None,plan='free'):
    ctx=browser.new_context(viewport={'width':width,'height':900},java_script_enabled=js)
    calls=[];bad=[]
    user={'full_name':'Persona ficticia','email':'fixture@example.invalid','nif':'12345678Z',
          'plan':plan,'is_admin':role=='admin','is_fiscal_advisor':role in ['admin','advisor']}
    def route(r):
        req=r.request;u=urlsplit(req.url)
        if u.hostname!='127.0.0.1':bad.append('external '+u.hostname);r.abort();return
        if u.path=='/api/me':
            calls.append(u.path)
            if pending is not None:pending.append(r);return
            r.fulfill(status=503 if role=='error' else 200,content_type='application/json',
                      body=json.dumps({'user':None if role in ['expired','error'] else user}));return
        if u.path.startswith('/api/') or req.method!='GET':
            bad.append(req.method+' '+u.path);r.abort();return
        r.continue_()
    ctx.route('**/*',route)
    return ctx,calls,bad

def open_page(ctx,origin,path='/dashboard',wait='networkidle'):
    p=ctx.new_page();errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
    assert p.goto(origin+path,wait_until=wait).status==200
    return p,errors

def run_shared_access_regression(browser,origin):
    """Shared header state and naming on approved and legacy page shells."""
    from qa_responsive_nav import check_header
    cases=0
    for path in ['/','/herramientas','/exchanges','/modelo721','/dashboard']:
        for role in ['user','advisor','admin']:
            for width in [390,1280]:
                ctx,calls,bad=context(browser,role,width)
                if path=='/modelo721':
                    # Existing tool typography is outside this UI renewal.
                    ctx.route('https://fonts.googleapis.com/**',lambda r:r.fulfill(status=200,body=''))
                    ctx.route('https://fonts.gstatic.com/**',lambda r:r.abort())
                p,errors=open_page(ctx,origin,path)
                p.locator('#site-nav[data-auth-state=authenticated]').wait_for()
                assert p.locator('#snavItemDash').inner_text()=='Mi espacio fiscal'
                assert p.locator('#snavItemPlanes,a[href="/pricing"]').count()==0
                if path=='/modelo721':
                    assert p.locator('.result-actions a[href="/dashboard"]').inner_text()=='Mi espacio fiscal'
                if width<=1200:
                    p.locator('#snavMenuToggle').click()
                    assert p.locator('#snavMobileMenu').get_by_role('link',name='Mi espacio fiscal',exact=True).is_visible()
                    assert p.locator('#snavMobileMenu a[href="/pricing"]').count()==0
                assert not bad and not errors,(path,role,width,bad,errors)
                ctx.close();cases+=1
    # HTTP failure, network failure, invalid JSON and invalid response schema
    # must remain unknown, both in the header and inside the workspace.
    for path in ['/','/exchanges','/dashboard']:
        for mode in ['http','network','json','schema']:
            for width in [320,768,1280]:
                ctx,calls,bad=context(browser,width=width)
                def fail(r):
                    if mode=='network':r.abort();return
                    r.fulfill(status=503 if mode=='http' else 200,content_type='application/json',
                              body='not-json' if mode=='json' else '{}' if mode=='schema' else '{"error":"Synthetic unavailable"}')
                ctx.route('**/api/me',fail)
                p,errors=open_page(ctx,origin,path)
                p.locator('#site-nav[data-auth-state=error]').wait_for()
                assert p.locator('#snavAuthRetry').is_visible()
                assert p.locator('#snavAuthStatus').inner_text()=='No podemos comprobar tu sesión. Vuelve a intentarlo.'
                assert p.locator('#snavBtnLogin:not(.snav-hidden),#snavBtnSignup:not(.snav-hidden),#snavAvatarWrap:not(.snav-hidden)').count()==0
                if width<=1200:
                    p.locator('#snavMenuToggle').click()
                    menu=p.locator('#snavMobileMenu')
                    assert menu.locator('#snavMobileRetry').is_visible()
                    assert menu.locator('a[href="/login/"],a[href="/signup/"],a[href="/dashboard"],a[href^="/admin/"]').count()==0
                check_header(p,width)
                assert not geometry(p,width),(path,mode,width,geometry(p,width))
                if path=='/dashboard':
                    assert not p.locator('#dashWorkspace').is_visible()
                    assert p.locator('#dashAccessTitle').inner_text()=='No podemos comprobar tu sesión'
                    assert not p.locator('#dashResume').is_visible()
                assert not bad and not errors,(path,mode,width,bad,errors)
                ctx.close();cases+=1
    # Retrying reloads the page and recovers the existing session, without logout.
    for path in ['/','/exchanges','/dashboard']:
        for width in [320,1280]:
            ctx,calls,bad=context(browser,width=width);attempts=[]
            def recover(r):
                attempts.append(1)
                r.fulfill(status=503 if len(attempts)==1 else 200,content_type='application/json',
                          body='{}' if len(attempts)==1 else '{"user":{"full_name":"Persona ficticia","is_admin":false,"is_fiscal_advisor":false}}')
            ctx.route('**/api/me',recover);p,errors=open_page(ctx,origin,path)
            p.locator('#snavAuthRetry').click();p.wait_for_load_state('networkidle')
            p.locator('#site-nav[data-auth-state=authenticated]').wait_for()
            assert len(attempts)==2 and p.url==origin+path
            assert p.locator('#snavAvatarWrap').is_visible()
            assert p.locator('#snavAuthRetry').is_hidden()
            assert not bad and not errors,(path,width,bad,errors)
            ctx.close();cases+=1
    print(f'SHARED_ACCESS_QA: PASS ({cases} scenarios; shared name; no pricing; HTTP/network/JSON/schema failures; retry recovery)')

def run_dashboard_apple(browser,origin):
    art=Path('qa-artifacts');art.mkdir(exist_ok=True);cases=0
    for width in WIDTHS:
        for role in ['user','advisor','admin']:
            ctx,calls,bad=context(browser,role,width);p,errors=open_page(ctx,origin)
            p.locator('body[data-dashboard-state=ready]').wait_for()
            assert not geometry(p,width),(role,width,geometry(p,width))
            assert p.locator('h1').inner_text()=='Mi espacio fiscal'
            assert p.locator('main').count()==1
            assert p.locator('[data-exchange-name]').count()==11
            assert p.locator('#site-nav').bounding_box()['y']==0
            assert p.locator('#dashSearch').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)')>=16
            assert p.locator('link[href*="fonts.googleapis"]').count()==0
            assert p.locator('#dashManagement').is_visible()==(role!='user')
            assert p.locator('#dashRoleLinks li').count()=={'user':0,'advisor':1,'admin':6}[role]
            for img in p.locator('#dashExchanges img').all():assert img.evaluate('e=>e.complete&&e.naturalWidth>0')
            assert p.locator('#snavItemPlanes,a[href="/pricing"]').count()==0
            assert p.locator('#snavItemDash').inner_text()=='Mi espacio fiscal'
            assert p.evaluate('async()=>Object.keys(await window.SiteNav.ready).sort()')==['is_admin','is_fiscal_advisor','state']
            assert calls==['/api/me'] and not bad and not errors,(role,width,calls,bad,errors)
            if role=='user' and width in [390,768,1280]:
                p.screenshot(path=str(art/f'home_dashboard_{width}.png'),full_page=True)
            ctx.close();cases+=1
    # Search is local, Unicode/case-insensitive, labelled, and reversible.
    ctx,calls,bad=context(browser);p,errors=open_page(ctx,origin)
    p.get_by_role('link',name='Informe FIFO',exact=False).first.click()
    p.wait_for_function("document.activeElement.id==='fifo'")
    p.locator('#dashSearch').fill('bíTvavo')
    assert p.locator('[data-exchange-name]:visible').count()==1
    assert p.locator('#dashCount').inner_text()=='1 exchange disponible'
    p.locator('#dashSearch').fill('<img src=x onerror=alert(1)>')
    assert p.locator('#dashEmpty').is_visible() and p.locator('[data-exchange-name]:visible').count()==0
    p.locator('#dashSearchClear').click()
    assert p.locator('[data-exchange-name]:visible').count()==11
    assert p.locator('#dashSearch').evaluate('e=>e===document.activeElement')
    assert calls==['/api/me'] and not bad and not errors;ctx.close();cases+=1
    # A paid plan is not a role. An admin retains access even on a free plan.
    for role,plan,count in [('user','pro',0),('admin','free',6)]:
        ctx,calls,bad=context(browser,role,plan=plan);p,errors=open_page(ctx,origin)
        assert p.locator('#dashRoleLinks li').count()==count
        assert not bad and not errors;ctx.close();cases+=1
    # Native disclosure keyboard behavior and the existing mobile role menu.
    for role in ['user','advisor','admin']:
        for width in [390,1280]:
            ctx,calls,bad=context(browser,role,width);p,errors=open_page(ctx,origin)
            if width>1200:
                p.locator('#snavAvatar').focus();p.keyboard.press('Enter')
                assert p.locator('#snavAvatar').get_attribute('aria-expanded')=='true'
                assert p.locator('#snavDropdown').get_attribute('role') is None
                p.screenshot(path=str(art/f'home_dashboard_menu_{role}_{width}.png'),full_page=True)
                p.keyboard.press('Escape')
                p.wait_for_function("document.activeElement.id==='snavAvatar'")
            else:
                p.locator('#snavMenuToggle').click()
                menu=p.locator('#snavMobileMenu')
                assert menu.get_by_role('link',name='Mi espacio fiscal',exact=True).count()==1
                assert menu.get_by_role('link',name='Planes',exact=True).count()==0
                assert menu.get_by_role('link',name='Panel asesoramiento',exact=True).count()==(0 if role=='user' else 1)
                assert menu.get_by_role('link',name='Stats',exact=True).count()==(1 if role=='admin' else 0)
                p.keyboard.press('Escape')
                assert not menu.is_visible()
            assert not bad and not errors;ctx.close();cases+=1
    for role in ['expired','error']:
        ctx,calls,bad=context(browser,role);p,errors=open_page(ctx,origin)
        assert not p.locator('#dashWorkspace').is_visible()
        assert not p.locator('#dashManagement').is_visible()
        assert p.locator('#dashResume').is_visible()==(role=='expired')
        assert p.locator('#dashRetry').is_visible()==(role=='error')
        p.screenshot(path=str(art/f'home_dashboard_{role}.png'),full_page=True)
        assert calls==['/api/me'] and not bad and not errors;ctx.close();cases+=1
    # Delayed auth never reveals privileged content and reuses the same request.
    pending=[];ctx,calls,bad=context(browser,pending=pending);p=ctx.new_page();p.clock.install()
    p.goto(origin+'/dashboard',wait_until='load')
    p.locator('#snavMenuToggle').click();p.clock.fast_forward(9000)
    assert not p.locator('#dashWorkspace').is_visible() and p.locator('#dashRetry').is_visible()
    assert len(pending)==1
    pending[0].fulfill(status=200,content_type='application/json',body='{"user":{"is_admin":true,"is_fiscal_advisor":true}}')
    p.locator('body[data-dashboard-state=ready]').wait_for()
    assert p.locator('#snavMobileMenu').get_by_role('link',name='Planes',exact=True).count()==0
    assert p.locator('#dashRoleLinks li').count()==6
    assert calls==['/api/me'] and not bad;ctx.close();cases+=1
    for width in [320,768,1280]:
        ctx,calls,bad=context(browser,width=width);p,errors=open_page(ctx,origin)
        p.add_style_tag(content='html{font-size:200%}')
        p.emulate_media(reduced_motion='reduce')
        assert not geometry(p,width),(width,geometry(p,width))
        assert p.locator('[data-exchange-name]').first.evaluate('e=>getComputedStyle(e).transitionDuration')=='0s'
        assert not bad and not errors;ctx.close();cases+=1
    ctx,calls,bad=context(browser,js=False,width=320);p,errors=open_page(ctx,origin)
    assert p.locator('#dashWorkspace').is_visible() and p.locator('.dash-nojs').is_visible()
    assert not p.locator('#dashManagement').is_visible() and not geometry(p,320)
    assert not calls and not bad and not errors;ctx.close();cases+=1
    # Public viewer has synthetic identities and never sends even /api/me.
    for profile in ['usuario','asesor','administrador','caducada','error']:
        ctx,calls,bad=context(browser);p,errors=open_page(ctx,origin,'/dashboard-apple-viewer?perfil='+profile)
        assert p.locator('body').get_attribute('data-dashboard-preview')=='true'
        if profile in ['usuario','asesor','administrador']:
            p.locator('a[href="#vista-modelo721"]').click()
            assert p.locator('#dashViewerNotice').is_visible()
            assert p.locator('a[href="/account"],a[href="/admin/contactos"]').count()==0
        else:assert not p.locator('#dashWorkspace').is_visible()
        assert not calls and not bad and not errors,(profile,calls,bad,errors)
        ctx.close();cases+=1
    # Baseline screenshot: old HTML unmodified; external fonts intercepted.
    ctx=browser.new_context(viewport={'width':1280,'height':900})
    ctx.route('https://fonts.googleapis.com/**',lambda r:r.fulfill(status=200,body=''))
    ctx.route('https://fonts.gstatic.com/**',lambda r:r.abort())
    ctx.route('**/api/me',lambda r:r.fulfill(status=200,content_type='application/json',body='{"user":{"full_name":"Persona ficticia"}}'))
    p=ctx.new_page();p.goto(origin+'/dashboard-baseline',wait_until='networkidle')
    p.screenshot(path=str(art/'home_dashboard_baseline_1280.png'),full_page=True);ctx.close()
    print(f'DASHBOARD_APPLE_QA: PASS ({cases} scenarios; 3 roles; 13 widths; synthetic data; final /dashboard route; inert viewer)')
    run_shared_access_regression(browser,origin)
