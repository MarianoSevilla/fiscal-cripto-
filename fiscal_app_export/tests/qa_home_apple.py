"""Isolated browser QA for the additive Home variant; no production/provider I/O.

Uses the existing CI Playwright dependency and qa_responsive_nav local server.
All API calls return synthetic data; non-GET calls fail the test. No app import.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

WIDTHS=(320,375,390,480,640,768,900,1024,1200,1201,1280,1440)
ARTIFACTS=Path('qa-artifacts')
ROLES={
    'visitor':{'user':None},
    'user':{'user':{'email':'user@example.invalid','full_name':'Usuario ficticio'}},
    'advisor':{'user':{'email':'advisor@example.invalid','full_name':'Asesor ficticio','is_fiscal_advisor':True}},
    'admin':{'user':{'email':'admin@example.invalid','full_name':'Admin ficticio','is_admin':True}},
}

def geometry(page,width):
    return page.evaluate('''width => {
      const root=document.documentElement;
      const bad=[];
      if(root.scrollWidth>width+1)bad.push('document width '+root.scrollWidth);
      for(const el of document.querySelectorAll('.apple-home *')) {
        const s=getComputedStyle(el),r=el.getBoundingClientRect();
        if(!el.getClientRects().length||s.display==='none'||s.visibility==='hidden')continue;
        if(el.closest('.mock-table-wrap')&& !el.classList.contains('mock-table-wrap'))continue;
        if(r.left < -1 || r.right>width+1)bad.push(el.tagName+'.'+String(el.className)+' '+r.left+'..'+r.right);
      }
      return bad;
    }''',width)

def context(browser,role='visitor',width=390,height=812,js=True):
    ctx=browser.new_context(viewport={'width':width,'height':height},java_script_enabled=js)
    violations=[]
    def route(request_route):
        req=request_route.request;u=urlsplit(req.url)
        if req.method!='GET':
            violations.append(req.method+' '+u.path);request_route.abort();return
        if u.hostname!='127.0.0.1':
            violations.append('external request '+u.hostname);request_route.abort();return
        if u.path=='/api/me':
            request_route.fulfill(status=200,content_type='application/json',body=json.dumps(ROLES[role]));return
        if u.path.startswith('/api/'):
            violations.append('unexpected API '+u.path);request_route.abort();return
        request_route.continue_()
    ctx.route('**/*',route)
    return ctx,violations

def ready(page,origin,role='visitor'):
    errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
    response=page.goto(origin+'/static/landing_apple.html',wait_until='networkidle')
    assert response.status==200
    if role=='visitor':page.locator('#snavBtnSignup:not(.snav-hidden)').wait_for(state='attached')
    else:page.locator('#snavAvatarWrap:not(.snav-hidden)').wait_for(state='attached')
    return errors

def run_home_apple(browser,origin):
    ARTIFACTS.mkdir(exist_ok=True)
    cases=0
    for width in WIDTHS:
        ctx,violations=context(browser,width=width)
        page=ctx.new_page();errors=ready(page,origin)
        bad=geometry(page,width);assert not bad,(width,bad[:10])
        if width>1200:
            logo=page.locator('.snav-logo').bounding_box()
            links=page.locator('.snav-links').bounding_box()
            right=page.locator('.snav-right').bounding_box()
            assert logo['x']+logo['width']+8<=links['x'],('logo/links overlap',width)
            assert links['x']+links['width']+8<=right['x'],('links/access overlap',width)
        assert page.locator('main').count()==1
        assert page.locator('h1').count()==1
        assert page.locator('a.btn-primary').get_attribute('href')=='/signup/'
        assert page.locator('.mock-table-head > span').count()==5
        # Demonstration must appear before secondary advisory/team blocks on mobile.
        assert page.locator('.apple-demo').bounding_box()['y'] < page.locator('.apple-assistance').bounding_box()['y']
        # Full-page captures must include off-screen portraits as well. Changing
        # loading in this ephemeral test DOM keeps production lazy loading intact.
        page.locator('img[loading="lazy"]').evaluate_all("imgs=>imgs.forEach(img=>{img.loading='eager'})")
        page.evaluate("async()=>await Promise.all([...document.images].map(img=>img.decode()))")
        page.screenshot(path=str(ARTIFACTS/f'home_apple_{width}px.png'),full_page=True,animations='disabled')
        if width<=1200:
            toggle=page.locator('#snavMenuToggle');toggle.click()
            menu=page.locator('#snavMobileMenu')
            assert menu.is_visible()
            assert menu.locator('a[href="/herramientas"]').is_visible()
            assert menu.locator('a[href="/signup/"]').is_visible()
            assert not geometry(page,width)
            toggle.press('Escape');assert not menu.is_visible()
            assert page.evaluate('document.activeElement.id')=='snavMenuToggle'
        # Native details are usable with keyboard and preserve answer content.
        item=page.locator('.apple-faq-item').nth(1);summary=item.locator('summary')
        summary.focus();summary.press('Enter');assert item.get_attribute('open') is not None
        summary.press('Enter');assert item.get_attribute('open') is None
        # Existing dialog and Escape behavior, without submitting credentials.
        page.evaluate("abrirAuthModal('login')")
        assert page.locator('#authModal').is_visible()
        page.locator('#authModalClose').press('Escape')
        assert not page.locator('#authModal').is_visible()
        assert not errors,errors
        assert not violations,violations
        ctx.close();cases+=1
        print(f'Home Apple {width}px: PASS')

    for role in ['user','advisor','admin']:
        for width in [375,1280]:
            ctx,violations=context(browser,role,width);page=ctx.new_page();errors=ready(page,origin,role)
            page.locator('#snavAvatar').click()
            drop=page.locator('#snavDropdown')
            assert drop.is_visible()
            assert drop.get_attribute('role') is None
            assert drop.locator('a[href="/account"]').is_visible()
            assert drop.locator('#snavItemAdminAsesoria').is_visible()==(role in ['advisor','admin'])
            assert drop.locator('#snavItemStats').is_visible()==(role=='admin')
            page.locator('#snavAvatar').press('Escape')
            assert not drop.is_visible()
            assert page.evaluate('document.activeElement.id')=='snavAvatar'
            assert not geometry(page,width)
            assert not violations and not errors,(violations,errors)
            ctx.close();cases+=1

    # Text enlargement, reduced motion, low-height menu, and HTML fallback.
    ctx,violations=context(browser,width=390,height=568);page=ctx.new_page();ready(page,origin)
    page.locator('#snavMenuToggle').click()
    last=page.locator('#snavMobileMenu a[href="/signup/"]');last.scroll_into_view_if_needed()
    assert last.bounding_box()['y']+last.bounding_box()['height']<=569
    page.locator('#snavMenuToggle').press('Escape')
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('.snav-menu-icon').evaluate("el=>getComputedStyle(el).transitionDuration")=='0s'
    page.evaluate("document.documentElement.style.fontSize='200%'")
    assert not geometry(page,390)
    page.screenshot(path=str(ARTIFACTS/'home_apple_390px_text200.png'),full_page=True,animations='disabled')
    assert not violations;ctx.close();cases+=1
    ctx,violations=context(browser,width=375,js=False);page=ctx.new_page()
    page.goto(origin+'/static/landing_apple.html',wait_until='networkidle')
    assert page.locator('.snav-links a[href="/herramientas"]').is_visible()
    assert page.locator('.apple-noscript-access a[href="/login/"]').is_visible()
    assert not geometry(page,375)
    assert not violations;ctx.close();cases+=1
    print(f'Home Apple: {cases} synthetic browser scenarios PASS; no provider or external I/O')
