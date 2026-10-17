"""Browser QA for the integrated Home at /; no production/provider I/O.

Uses the existing CI Playwright dependency and qa_responsive_nav local server.
All API calls return synthetic data; non-GET calls fail the test. No app import.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

WIDTHS=(320,375,390,480,640,641,768,900,1024,1200,1201,1280,1440)
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

def context(browser,role='visitor',width=390,height=812,js=True,pending_session=None):
    ctx=browser.new_context(viewport={'width':width,'height':height},java_script_enabled=js)
    violations=[]
    def route(request_route):
        req=request_route.request;u=urlsplit(req.url)
        if req.method!='GET':
            violations.append(req.method+' '+u.path);request_route.abort();return
        if u.hostname!='127.0.0.1':
            violations.append('external request '+u.hostname);request_route.abort();return
        if u.path=='/api/me':
            if pending_session is not None:
                pending_session.append(request_route);return
            request_route.fulfill(status=200,content_type='application/json',body=json.dumps(ROLES[role]));return
        if u.path.startswith('/api/'):
            violations.append('unexpected API '+u.path);request_route.abort();return
        request_route.continue_()
    ctx.route('**/*',route)
    return ctx,violations

def ready(page,origin,role='visitor'):
    errors=[];page.on('pageerror',lambda err:errors.append(str(err)))
    response=page.goto(origin+'/',wait_until='networkidle')
    assert response.status==200
    if role=='visitor':page.locator('#snavBtnSignup:not(.snav-hidden)').wait_for(state='attached')
    else:page.locator('#snavAvatarWrap:not(.snav-hidden)').wait_for(state='attached')
    return errors

def run_home_redesign(browser,origin):
    ARTIFACTS.mkdir(exist_ok=True)
    cases=0
    for width in WIDTHS:
        ctx,violations=context(browser,width=width)
        page=ctx.new_page();errors=ready(page,origin)
        bad=geometry(page,width)
        if bad:
            page.screenshot(path=str(ARTIFACTS/f'home_apple_failure_{width}px.png'),full_page=True)
            print('Overflow diagnostics:',page.locator('.apple-sr-only').evaluate_all('els=>els.map(el=>({text:el.textContent,rect:el.getBoundingClientRect().toJSON(),offsetParent:el.offsetParent&&el.offsetParent.className}))'))
        assert not bad,(width,bad[:10])
        # Same in-flow, compact header geometry as the approved public V23.
        header=page.locator('#site-nav').bounding_box()
        assert abs(header['y'])<1,('header starts below document top',width,header)
        assert 63<=header['height']<=65,('unexpected header height',width,header)
        intro_top=page.locator('.apple-intro').bounding_box()['y']
        assert abs(intro_top-(header['y']+header['height']))<1,('header/intro gap',width)
        if width>1200:
            logo=page.locator('.snav-logo').bounding_box()
            links=page.locator('.snav-links').bounding_box()
            right=page.locator('.snav-right').bounding_box()
            assert logo['x']+logo['width']+8<=links['x'],('logo/links overlap',width)
            assert links['x']+links['width']+8<=right['x'],('links/access overlap',width)
        assert page.locator('main').count()==1
        assert page.locator('h1').count()==1
        assert page.locator('a.btn-primary').get_attribute('href')=='/signup/'
        assert page.locator('a.btn-primary').get_attribute('aria-label') is None
        assert page.locator('.apple-hero-actions').get_by_role('link',name='Crear cuenta',exact=True).count()==1
        assert page.locator('.device-url').inner_text()=='Informe FIFO de criptomonedas'
        table=page.get_by_role('table',name='Operaciones del informe de ejemplo. Datos ficticios. Importes en euros.')
        assert table.get_by_role('columnheader',name='Ganancia o pérdida',exact=True).count()==1
        assert table.get_by_role('columnheader').count()==5
        assert table.get_by_role('row').count()==6
        assert table.get_by_role('cell').count()==25
        if width>1200:
            wrap=page.locator('.mock-table-wrap')
            assert wrap.evaluate('el=>el.scrollWidth<=el.clientWidth+1'),('desktop example scrolls',width)
            edge=wrap.bounding_box()
            last=table.get_by_role('row').nth(1).get_by_role('cell').nth(4).bounding_box()
            assert last['x']+last['width']<=edge['x']+edge['width']+1,('last column clipped',width)
            assert not page.locator('.apple-table-hint').is_visible()
        expected_year=page.evaluate("Number(new Intl.DateTimeFormat('en',{year:'numeric',timeZone:'Europe/Madrid'}).format(new Date()))-1")
        dates=page.locator('.apple-example-date')
        assert dates.count()==5
        assert all(dates.nth(i).text_content().endswith('/'+str(expected_year)) for i in range(5))
        how=page.locator('.apple-hero-actions a[href="#como-funciona"]')
        assert how.is_visible()==(width>1200)
        if width>1200:
            assert page.locator('.apple-hero-actions').get_by_role('link',name='Cómo funciona',exact=True).count()==1
        assert how.locator('[aria-hidden="true"]').text_content()=='↓'
        assert page.locator('.apple-includes').get_by_role('link',name='Preparar mi informe',exact=True).get_attribute('href')=='/signup/'
        assert page.locator('.apple-tablet-only').is_visible()==(640<width<=1200)
        assert page.locator('.apple-exchange-support').count()==0
        assert page.locator('#asistenciaBlock').is_visible()
        if 640<width<=1200:
            desc=page.locator('.hero-desc').bounding_box()
            container=page.locator('.apple-hero .apple-container').bounding_box()
            assert abs(desc['width']-container['width'])<1,('tablet description width',width)
            micro=page.locator('.cta-micro')
            line_height=micro.evaluate('el=>parseFloat(getComputedStyle(el).lineHeight)')
            assert micro.bounding_box()['height']<=line_height+1,('tablet microcopy wraps',width)
        if width==390:
            assert page.locator('.device-frame').bounding_box()['y']<750
        # V7 pairs copy and report only on wide screens, preserving DOM order.
        hero=page.locator('.apple-hero').bounding_box()
        demo=page.locator('.apple-demo').bounding_box()
        if width>1200:
            assert hero['x']+hero['width']+24<=demo['x'],('intro columns',width)
        else:
            assert hero['y']+hero['height']<=demo['y']+1,('intro reading order',width)
        # Earlier owner-approved section widths must survive this polish pass.
        reference=page.locator('.apple-exchanges .apple-container').bounding_box()
        for section in ['#fiscalidad','#metodo-fifo','.apple-faq']:
            box=page.locator(section+' .apple-container').bounding_box()
            assert abs(box['x']-reference['x'])<1
            assert abs(box['width']-reference['width'])<1
        footer=page.get_by_role('contentinfo')
        assert footer.count()==1
        assert footer.locator('a').count()==11
        footer_box=footer.locator('.apple-container').bounding_box()
        assert abs(footer_box['x']-reference['x'])<1
        assert abs(footer_box['width']-reference['width'])<1
        explore=footer.get_by_role('navigation',name='Explorar',exact=True)
        help_nav=footer.get_by_role('navigation',name='Ayuda',exact=True)
        assert explore.is_visible() and help_nav.is_visible()
        assert footer.get_by_role('navigation',name='Información legal',exact=True).get_by_role('link').count()==4
        assert footer.locator('.apple-footer-year').inner_text()==str(expected_year+1)
        brand_box=footer.locator('.apple-footer-brand').bounding_box()
        explore_box=explore.bounding_box()
        help_box=help_nav.bounding_box()
        assert abs(explore_box['y']-help_box['y'])<1
        if width<=1200:
            assert brand_box['y']+brand_box['height']<=explore_box['y']
        else:
            assert abs(brand_box['y']-explore_box['y'])<1
        if width<=640:
            assert all(link.bounding_box()['height']>=44 for link in footer.get_by_role('link').all())
        # Six cards remain available; mobile initially shows the two most used.
        cards=page.locator('.apple-exchange-card')
        assert cards.count()==6
        more=page.locator('#apple-exchange-more')
        if width<=640:
            assert more.get_attribute('open') is None
            assert [cards.nth(i).is_visible() for i in range(6)]==[True,True,False,False,False,False]
            for selector in ['a.btn-primary','.apple-includes .apple-button']:
                box=page.locator(selector).bounding_box()
                # The hero action group itself fills the content column.
                content=page.locator(selector).evaluate('el=>el.closest(".apple-container").getBoundingClientRect().width')
                if selector!='a.btn-primary':
                    pad=page.locator(selector).evaluate('el=>parseFloat(getComputedStyle(el.closest(".apple-container")).paddingLeft)')
                    content-=2*pad
                assert abs(box['width']-content)<1,('primary width',selector,width)
            more.locator('summary').focus();more.locator('summary').press('Enter')
            assert more.get_attribute('open') is not None
            assert all(cards.nth(i).is_visible() for i in range(6))
            assert not geometry(page,width)
            more.locator('summary').press('Enter')
            assert more.get_attribute('open') is None
        else:
            assert all(cards.nth(i).is_visible() for i in range(6))
            boxes=[cards.nth(i).bounding_box() for i in range(6)]
            expected_columns=2 if width<=1200 else 3
            row_tops={round(box['y']) for box in boxes}
            assert len(row_tops)==6//expected_columns,('exchange rows',width,boxes)
        assert page.locator('.apple-exchange-secondary a').get_attribute('href')=='/exchanges/bit2me'
        # Demonstration must appear before secondary advisory/team blocks on mobile.
        assert page.locator('.apple-demo').bounding_box()['y'] < page.locator('.apple-assistance').bounding_box()['y']
        assert page.locator('.apple-faq-item[open]').count()==0
        # Full-page captures must include off-screen portraits as well. Changing
        # loading in this ephemeral test DOM keeps production lazy loading intact.
        page.locator('img[loading="lazy"]').evaluate_all("imgs=>imgs.forEach(img=>{img.loading='eager'})")
        page.evaluate("async()=>await Promise.all([...document.images].map(img=>img.decode()))")
        page.screenshot(path=str(ARTIFACTS/f'home_apple_{width}px.png'),full_page=True,animations='disabled')
        if width==390:
            wrap=page.locator('.mock-table-wrap')
            wrap.focus();wrap.press('ArrowRight')
            page.wait_for_function("document.querySelector('.mock-table-wrap').scrollLeft>0")
            wrap.evaluate('el=>{el.scrollLeft=0;el.blur()}')
        if width in [390,1280]:
            primary=page.locator('a.btn-primary');primary.hover()
            initial=primary.evaluate('el=>getComputedStyle(el).backgroundColor')
            page.mouse.down()
            pressed=primary.evaluate('el=>getComputedStyle(el).backgroundColor')
            assert pressed!=initial,('missing press feedback',width)
            page.mouse.move(1,300);page.mouse.up()
            assert page.url==origin+'/'
        if width<=1200:
            assert not page.locator('#snavBtnSignup').is_visible()
            toggle=page.locator('#snavMenuToggle');toggle.click()
            menu=page.locator('#snavMobileMenu')
            assert menu.is_visible()
            assert menu.locator('a[href="/herramientas"]').is_visible()
            assert menu.locator('a[href="/signup/"]').is_visible()
            signup=menu.get_by_role('link',name='Crear cuenta',exact=True)
            assert signup.is_visible()
            # At 390px the preceding press test leaves a short color transition.
            # Compare resting button states, with the pointer outside both CTAs.
            page.mouse.move(1,1)
            page.wait_for_function('''() => {
              const a=getComputedStyle(document.querySelector('a.btn-primary'));
              const b=getComputedStyle(document.querySelector('#snavMobileMenu a[href="/signup/"]'));
              return a.backgroundColor===b.backgroundColor && a.color===b.color && a.borderRadius===b.borderRadius;
            }''',timeout=3000)
            primary_style=page.locator('a.btn-primary').evaluate('el=>{const s=getComputedStyle(el);return [s.backgroundColor,s.color,s.borderRadius]}')
            assert signup.evaluate('el=>{const s=getComputedStyle(el);return [s.backgroundColor,s.color,s.borderRadius]}')==primary_style
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
        print(f'Home integrada {width}px: PASS')

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
            assert drop.locator('#snavBtnLogout').evaluate('el=>getComputedStyle(el).color')=='rgb(180, 35, 24)'
            page.locator('#snavAvatar').press('Escape')
            assert not drop.is_visible()
            assert page.evaluate('document.activeElement.id')=='snavAvatar'
            assert not geometry(page,width)
            assert not violations and not errors,(violations,errors)
            ctx.close();cases+=1

    # An unresolved session still offers public links. Release the same fake
    # request later; no extra request, account mutation, or logout is needed.
    for role in ['visitor','user']:
        for width in [375,1280]:
            pending=[]
            ctx,violations=context(browser,role,width,pending_session=pending)
            page=ctx.new_page();errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(origin+'/',wait_until='domcontentloaded')
            page.locator('.apple-access-desktop').wait_for(state='attached',timeout=7000)
            assert len(pending)==1
            if width<=1200:
                page.locator('#snavMenuToggle').click()
                fallback=page.locator('.apple-access-mobile')
            else:
                fallback=page.locator('.apple-access-desktop')
            link=fallback.get_by_role('link',name='Iniciar sesión',exact=True)
            assert link.is_visible()
            assert fallback.get_by_role('link',name='Crear cuenta',exact=True).get_attribute('href')=='/signup/'
            link.focus()
            pending[0].fulfill(status=200,content_type='application/json',body=json.dumps(ROLES[role]))
            page.wait_for_function("document.querySelectorAll('.apple-access-fallback').length===0")
            if role=='user':
                assert not page.locator('#snavAvatarWrap').evaluate("el=>el.classList.contains('snav-hidden')")
                assert page.evaluate('document.activeElement.id')==('snavMenuToggle' if width<=1200 else 'snavAvatar')
            elif width<=1200:
                assert page.locator('#snavMobileMenu a[href="/login/"]').evaluate('el=>el===document.activeElement')
            else:
                assert page.evaluate('document.activeElement.id')=='snavBtnLogin'
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
    for width in (375,768):
        ctx,violations=context(browser,width=width,js=False);page=ctx.new_page()
        page.goto(origin+'/',wait_until='networkidle')
        assert not page.locator('.snav-links a[href="/herramientas"]').is_visible()
        native_menu=page.locator('.apple-noscript-menu')
        assert native_menu.get_attribute('open') is None
        native_menu.locator('summary').click()
        assert native_menu.get_attribute('open') is not None
        assert native_menu.locator('a[href="/herramientas"]').is_visible()
        assert native_menu.locator('a[href="/login/"]').is_visible()
        assert native_menu.locator('a[href="/signup/"]').is_visible()
        assert not geometry(page,width)
        native_menu.locator('summary').click()
        assert native_menu.get_attribute('open') is None
        assert page.locator('#apple-exchange-more').get_attribute('open') is not None
        assert all(page.locator('.apple-exchange-card').nth(i).is_visible() for i in range(6))
        assert not geometry(page,width)
        assert not violations;ctx.close();cases+=1
    print(f'Home integrada: {cases} synthetic browser scenarios PASS; no provider or external I/O')

