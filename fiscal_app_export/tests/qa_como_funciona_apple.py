"""How prototype QA; local server, synthetic sessions, no provider/user I/O."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from qa_home_redesign import WIDTHS,context,geometry

PAGE='/static/como_funciona_apple.html'
ARTIFACTS=Path('qa-artifacts')

def ready(page,origin,role='visitor'):
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    r=page.goto(origin+PAGE,wait_until='networkidle');assert r.status==200
    target='#snavBtnSignup:not(.snav-hidden)' if role=='visitor' else '#snavAvatarWrap:not(.snav-hidden)'
    page.locator(target).wait_for(state='attached')
    return errors

def run_como_funciona_apple(browser,origin):
    ARTIFACTS.mkdir(exist_ok=True);cases=0
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        page=ctx.new_page();errors=ready(page,origin)
        assert not geometry(page,width),(width,geometry(page,width))
        header=page.locator('#site-nav').bounding_box();intro=page.locator('.how-intro').bounding_box()
        assert abs(header['y'])<1 and 63<=header['height']<=65,(width,header)
        assert abs(intro['y']-header['height'])<1,(width,intro)
        assert page.locator('h1').count()==page.locator('main').count()==1
        for selector in ['h1','.how-lead']:
            assert page.locator(selector).evaluate('e=>{const s=getComputedStyle(e.parentElement);return Math.abs(e.getBoundingClientRect().width-e.parentElement.clientWidth+parseFloat(s.paddingLeft)+parseFloat(s.paddingRight))<1}'),(width,selector)
        assert page.locator('.how-intro').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(7, 60, 50)'
        cards=page.locator('.apple-catalog-card');assert cards.count()==3
        for card in cards.all():
            assert card.is_visible() and card.bounding_box()['height']>=44
            assert card.evaluate("e=>getComputedStyle(e).backgroundColor")=='rgb(237, 245, 240)'
            assert card.evaluate("e=>getComputedStyle(e).borderRadius")=='16px'
            assert card.locator('h3').evaluate("e=>getComputedStyle(e).fontSize")=='24px'
        if width>1200:assert cards.nth(0).bounding_box()['y']==cards.nth(2).bounding_box()['y']
        elif width>640:assert cards.nth(0).bounding_box()['y']==cards.nth(1).bounding_box()['y']<cards.nth(2).bounding_box()['y']
        else:assert cards.nth(0).bounding_box()['y']<cards.nth(1).bounding_box()['y']<cards.nth(2).bounding_box()['y']
        table=page.get_by_role('table',name='Operaciones del informe de ejemplo. Datos ficticios. Importes en euros.')
        assert table.get_by_role('columnheader').count()==5 and table.get_by_role('row').count()==6
        assert table.get_by_role('columnheader',name='Ganancia o pérdida').count()==1
        assert table.locator('th,td').evaluate_all("els=>els.every(e=>getComputedStyle(e).display!=='none')")
        wrap=page.locator('.mock-table-wrap');assert wrap.get_attribute('tabindex')=='0'
        if width>1200:assert wrap.evaluate('e=>e.scrollWidth<=e.clientWidth+1')
        year=datetime.now(ZoneInfo('Europe/Madrid')).year-1
        assert page.locator('.apple-example-date').first.get_attribute('datetime')==f'{year}-03-15'
        guides=page.locator('#how-exchanges');assert guides.get_attribute('open') is None
        guides.locator('summary').focus();guides.locator('summary').press('Enter')
        assert guides.locator('a').count()==12
        assert guides.locator('.how-exchanges a').count()==11
        assert all(link.is_visible() and link.bounding_box()['height']>=44 for link in guides.locator('.how-exchanges a').all())
        guides.locator('summary').press('Enter')
        assert page.locator('.apple-faq-item').count()==7
        faq=page.locator('.apple-faq-item').first;faq.locator('summary').focus();faq.locator('summary').press('Enter')
        assert faq.get_attribute('open') is not None
        faq.locator('summary').press('Enter')
        if width<=1200:
            toggle=page.locator('#snavMenuToggle');assert toggle.is_visible();assert toggle.get_attribute('aria-label')=='Abrir menú';toggle.click()
            current=page.locator('#snavMobileMenu a[aria-current="page"]')
            assert current.count()==1 and current.inner_text()=='Cómo funciona'
            toggle.press('Escape');assert toggle.get_attribute('aria-expanded')=='false'
            assert toggle.evaluate('e=>e===document.activeElement')
        assert not geometry(page,width),(width,geometry(page,width))
        page.screenshot(path=str(ARTIFACTS/f'home_how_{width}px.png'),full_page=True)
        assert not errors and not violations,(width,errors,violations)
        ctx.close();cases+=1
    for role in ['user','advisor','admin']:
        ctx,violations=context(browser,width=390,role=role)
        page=ctx.new_page();errors=ready(page,origin,role)
        page.get_by_role('button',name='Abrir menú',exact=True).click()
        assert page.locator('#snavMobileMenu a[aria-current="page"]').count()==1
        assert page.locator('#snavMobileMenu a[href="/dashboard"]').is_visible()
        assert not page.locator('#snavMobileMenu').get_by_role('link',name='Crear cuenta',exact=True).count()
        if role=='user':assert not page.locator('#snavMobileMenu a[href="/admin/comunicaciones"]').count()
        if role=='admin':assert page.locator('#snavMobileMenu a[href="/admin/comunicaciones"]').is_visible()
        assert not geometry(page,390) and not errors and not violations
        ctx.close();cases+=1
    for width in [390,768,1280]:
        ctx,violations=context(browser,width=width,js=False)
        page=ctx.new_page();page.goto(origin+PAGE)
        assert not geometry(page,width),(width,geometry(page,width))
        assert page.locator('.apple-catalog-card').count()==3
        assert page.locator('table th').count()==5
        if width<=1200:
            disclosure=page.locator('.apple-noscript-menu');disclosure.locator('summary').click()
            assert disclosure.locator('a[aria-current="page"]').is_visible()
        assert not geometry(page,width) and not violations
        ctx.close();cases+=1
    for width in [390,768,1280]:
        ctx,violations=context(browser,width=width)
        page=ctx.new_page();errors=ready(page,origin)
        page.add_style_tag(content='html{font-size:200%}')
        assert not geometry(page,width),(width,geometry(page,width))
        assert page.locator('.mock-table th').count()==5
        page.screenshot(path=str(ARTIFACTS/f'home_how_text200_{width}px.png'),full_page=True)
        assert not errors and not violations
        ctx.close();cases+=1
    ctx,violations=context(browser,width=390)
    page=ctx.new_page();page.emulate_media(reduced_motion='reduce');errors=ready(page,origin)
    assert page.locator('.apple-catalog-card').first.evaluate('e=>getComputedStyle(e).transitionDuration')=='0s'
    assert not errors and not violations
    ctx.close();cases+=1
    ctx,violations=context(browser,width=1280)
    page=ctx.new_page();errors=ready(page,origin)
    page.locator('.apple-catalog-card').first.hover()
    page.wait_for_function("getComputedStyle(document.querySelector('.apple-catalog-card')).borderColor==='rgb(0, 107, 84)'")
    page.locator('.apple-catalog-card').first.click()
    assert page.url.endswith('#sube-tu-csv')
    assert not errors and not violations
    ctx.close();cases+=1
    print(f'COMO_FUNCIONA_APPLE_QA: PASS ({cases} synthetic browser scenarios; {len(WIDTHS)} widths)')
