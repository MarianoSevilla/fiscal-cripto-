"""Isolated Tools browser checks; synthetic sessions, no provider or user I/O."""
from pathlib import Path
from qa_home_redesign import WIDTHS, context, geometry

PAGE='/herramientas'
ARTIFACTS=Path('qa-artifacts')

def ready(page,origin,role='visitor'):
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    response=page.goto(origin+PAGE,wait_until='networkidle')
    assert response.status==200
    target='#snavBtnSignup:not(.snav-hidden)' if role=='visitor' else '#snavAvatarWrap:not(.snav-hidden)'
    page.locator(target).wait_for(state='attached')
    return errors

def run_herramientas_apple(browser,origin):
    ARTIFACTS.mkdir(exist_ok=True)
    cases=0
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        page=ctx.new_page();errors=ready(page,origin)
        assert not geometry(page,width),(width,geometry(page,width))
        header=page.locator('#site-nav').bounding_box()
        assert abs(header['y'])<1 and 63<=header['height']<=65,(width,header)
        intro=page.locator('.tools-intro').bounding_box()
        assert abs(intro['y']-header['height'])<1,(width,intro)
        assert page.locator('.tools-intro').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(7, 60, 50)'
        assert page.locator('#tools-title').evaluate('e=>getComputedStyle(e).color')=='rgb(255, 255, 255)'
        for selector in ['.tools-intro .apple-eyebrow','#tools-title em']:
            assert page.locator(selector).evaluate('e=>getComputedStyle(e).color')=='rgb(166, 237, 207)'
        assert page.locator('.tools-lead').evaluate('e=>getComputedStyle(e).color')=='rgb(195, 219, 209)'
        assert page.locator('h1').count()==1 and page.locator('main').count()==1
        assert page.locator('h1').inner_text()=='Herramientas fiscales para criptomonedas.'
        assert page.locator('.tools-breadcrumb').count()==0
        assert page.locator('nav[aria-label="Ruta de navegación"]').count()==0
        for selector in ['h1','.tools-lead']:
            assert page.locator(selector).evaluate('e=>{const s=getComputedStyle(e.parentElement);return Math.abs(e.getBoundingClientRect().width-(e.parentElement.clientWidth-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight)))<1}'),(width,selector)
        assert page.locator('.tools-card').count()==6
        cards=page.locator('.tools-card')
        assert all(cards.nth(i).is_visible() for i in range(6))
        if width>1200:
            assert page.locator('.tools-grid').bounding_box()['y']<640
            assert cards.nth(1).bounding_box()['y']==cards.nth(0).bounding_box()['y']
            assert cards.nth(2).bounding_box()['y']==cards.nth(0).bounding_box()['y']
            assert cards.nth(3).bounding_box()['y']>cards.nth(0).bounding_box()['y']
        elif width>640:
            assert cards.nth(1).bounding_box()['y']==cards.nth(0).bounding_box()['y']
            assert cards.nth(2).bounding_box()['y']>cards.nth(0).bounding_box()['y']
        else:
            for i in range(1,6):
                prev=cards.nth(i-1).bounding_box();curr=cards.nth(i).bounding_box()
                assert curr['y']>=prev['y']+prev['height']
        for button in page.locator('.tools-card a,.tools-help a').all():
            assert button.bounding_box()['height']>=44
        assert page.get_by_role('contentinfo').get_by_role('navigation',name='Información legal').get_by_role('link').count()==4
        assert page.locator('.apple-faq-item[open]').count()==0
        question=page.locator('.apple-faq-item summary').first
        question.focus();question.press('Enter')
        assert page.locator('.apple-faq-item').first.get_attribute('open') is not None
        question.press('Enter')
        if width<=1200:
            toggle=page.locator('#snavMenuToggle')
            assert toggle.get_attribute('aria-label')=='Abrir menú'
            assert toggle.is_visible()
            toggle.click()
            current=page.locator('#snavMobileMenu a[aria-current="page"]')
            assert current.count()==1 and current.inner_text()=='Herramientas'
            assert page.locator('#snavMobileMenu').get_by_role('link',name='Crear cuenta',exact=True).is_visible()
            toggle.press('Escape')
            assert toggle.get_attribute('aria-expanded')=='false'
            assert toggle.evaluate('e=>e===document.activeElement')
        assert not geometry(page,width),(width,geometry(page,width))
        page.screenshot(path=str(ARTIFACTS/f'home_herramientas_{width}px.png'),full_page=True)
        assert not errors,(width,errors)
        assert not violations,(width,violations)
        ctx.close();cases+=1
    for role in ['user','advisor','admin']:
        ctx,violations=context(browser,role=role,width=390)
        page=ctx.new_page();errors=ready(page,origin,role)
        page.get_by_role('button',name='Abrir menú',exact=True).click()
        assert page.locator('#snavMobileMenu a[aria-current="page"]').count()==1
        assert not page.locator('#snavMobileMenu').get_by_role('link',name='Crear cuenta',exact=True).count()
        assert page.locator('#snavMobileMenu a[href="/dashboard"]').is_visible()
        if role=='user':assert not page.locator('#snavMobileMenu a[href="/admin/comunicaciones"]').count()
        if role=='admin':assert page.locator('#snavMobileMenu a[href="/admin/comunicaciones"]').is_visible()
        assert not geometry(page,390)
        assert not errors and not violations
        ctx.close();cases+=1
    for width in [390,768,1280]:
        ctx,violations=context(browser,width=width,js=False)
        page=ctx.new_page();page.goto(origin+PAGE)
        assert not geometry(page,width),(width,geometry(page,width))
        assert page.locator('.tools-card a').count()==6
        if width<=1200:
            disclosure=page.locator('.apple-noscript-menu')
            disclosure.locator('summary').click()
            assert disclosure.locator('a[aria-current="page"]').is_visible()
        assert not geometry(page,width),(width,geometry(page,width))
        assert not violations
        ctx.close();cases+=1
    for width in [390,768,1280]:
        ctx,violations=context(browser,width=width)
        page=ctx.new_page();errors=ready(page,origin)
        page.add_style_tag(content='html{font-size:200%}')
        assert not geometry(page,width),(width,geometry(page,width))
        page.screenshot(path=str(ARTIFACTS/f'home_herramientas_text200_{width}px.png'),full_page=True)
        assert not errors and not violations
        ctx.close();cases+=1
    ctx,violations=context(browser,width=390)
    page=ctx.new_page();page.emulate_media(reduced_motion='reduce');ready(page,origin)
    assert page.locator('.tools-card').first.evaluate("e=>getComputedStyle(e).animationName")=='none'
    assert not violations
    ctx.close();cases+=1
    print(f'HERRAMIENTAS_APPLE_QA: PASS ({cases} synthetic browser scenarios; {len(WIDTHS)} widths)')
