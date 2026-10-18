"""Exchanges preview QA using the existing isolated browser test infrastructure.

No Flask imports, uploads, database, providers or external requests. Exercises
geometry and real native controls rather than stubbing their implementation.
"""
import json
from pathlib import Path
from qa_home_redesign import WIDTHS,context,geometry

PATH='/exchanges-apple-preview'

def open_page(ctx,origin):
    page=ctx.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    response=page.goto(origin+PATH,wait_until='networkidle')
    assert response.status==200
    return page,errors

def structure(page,width):
    assert not geometry(page,width),(width,geometry(page,width))
    header=page.locator('#site-nav').bounding_box()
    assert abs(header['y'])<1 and 63<=header['height']<=65,(width,header)
    intro=page.locator('.exchanges-intro').bounding_box()
    assert abs(intro['y']-header['height'])<1,(width,intro,header)
    assert page.locator('main').count()==page.locator('h1').count()==1
    for selector in ['h1','.exchanges-lead']:
        box=page.locator(selector).bounding_box()
        inner=page.locator('.exchanges-intro .apple-container').evaluate('e=>e.clientWidth-parseFloat(getComputedStyle(e).paddingLeft)-parseFloat(getComputedStyle(e).paddingRight)')
        assert abs(box['width']-inner)<1,(width,selector,box,inner)
    cards=page.locator('.exchanges-catalogue .apple-exchange-card')
    assert cards.count()==11
    assert all(cards.nth(i).is_visible() for i in range(11))
    names=cards.locator('h3').all_text_contents()
    assert len(set(names))==11 and 'KuCoin' in names and 'Gate' not in names
    assert 'XLS o XLSX' in cards.filter(has_text='MEXC').inner_text()
    assert cards.filter(has_text='MEXC').get_attribute('href')=='/mexc'
    assert cards.filter(has_text='KuCoin').get_attribute('href')=='/kucoin'
    columns=page.locator('.apple-catalog-grid').evaluate('e=>getComputedStyle(e).gridTemplateColumns.split(" ").length')
    assert columns==(1 if width<=640 else 2 if width<=1200 else 3),(width,columns)
    assert cards.first.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(237, 245, 240)'
    assert cards.first.evaluate('e=>getComputedStyle(e).borderRadius')=='16px'
    assert page.locator('.exchanges-intro .apple-button').evaluate('e=>getComputedStyle(e).borderRadius')=='999px'
    assert page.locator('meta[name="robots"]').get_attribute('content')=='noindex, nofollow'
    assert page.locator('link[rel="canonical"]').get_attribute('href')=='https://marianosevilla.com/exchanges'
    assert page.locator('input[type="file"],form,table').count()==0
    assert page.locator('a:not([href]),a[href=""],a[href="#"]').count()==0
    assert page.locator('link[href*="fonts.googleapis"],link[href*="fonts.gstatic"]').count()==0
    data=json.loads(page.locator('script[type="application/ld+json"]').text_content())
    items=data['mainEntity']['itemListElement']
    assert data['mainEntity']['numberOfItems']==len(items)==11
    assert [x['name'] for x in items]==names
    assert [x['position'] for x in items]==list(range(1,12))
    assert not any(x.get('url','').endswith('/exchanges/kucoin') for x in items)

def run_exchanges_apple(browser,origin):
    art=Path('qa-artifacts');art.mkdir(exist_ok=True);cases=0
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        page,errors=open_page(ctx,origin);structure(page,width)
        page.keyboard.press('Tab')
        assert page.locator('.apple-skip').evaluate('e=>e===document.activeElement')
        page.keyboard.press('Enter')
        assert page.locator('main').evaluate('e=>e===document.activeElement')
        summary=page.locator('.apple-faq-item summary').first
        summary.focus();page.keyboard.press('Enter')
        assert page.locator('.apple-faq-item').first.get_attribute('open') is not None
        assert page.locator('.apple-faq-answer').first.is_visible()
        page.keyboard.press('Enter')
        assert page.locator('.apple-faq-item').first.get_attribute('open') is None
        # Every question remains reachable; native controls reveal all answers.
        for entry in page.locator('.apple-faq-item').all():
            entry.locator('summary').click()
            assert entry.locator('.apple-faq-answer').is_visible()
        assert not geometry(page,width),(width,geometry(page,width))
        if width<=1200:
            page.locator('#snavMenuToggle').click()
            assert page.locator('#snavMobileMenu a[href="/herramientas"]').is_visible()
            page.keyboard.press('Escape')
            assert page.locator('#snavMenuToggle').get_attribute('aria-expanded')=='false'
            assert page.locator('#snavMenuToggle').evaluate('e=>e===document.activeElement')
        assert not violations and not errors,(width,violations,errors)
        page.keyboard.press('Control+Home')
        page.screenshot(path=str(art/f'home_exchanges_apple_{width}.png'),full_page=True)
        ctx.close();cases+=1
    for width in [320,390,768,1280]:
        ctx,violations=context(browser,width=width,js=False)
        page,errors=open_page(ctx,origin);structure(page,width)
        page.locator('.apple-faq-item summary').first.click()
        assert page.locator('.apple-faq-answer').first.is_visible()
        if width<=1200:
            page.locator('.apple-noscript-menu summary').click()
            assert page.locator('.apple-noscript-menu a[href="/herramientas"]').is_visible()
        assert not violations and not errors
        ctx.close();cases+=1
    for width in [390,768,1280]:
        ctx,violations=context(browser,width=width)
        page,errors=open_page(ctx,origin)
        page.add_style_tag(content='html{font-size:200%}')
        assert not geometry(page,width),(width,geometry(page,width))
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.apple-exchange-card').first.evaluate('e=>getComputedStyle(e).transitionDuration')=='0s'
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
    print(f'EXCHANGES_APPLE_QA: PASS ({cases} scenarios; {len(WIDTHS)} widths; native disclosures; enlarged text; synthetic sessions)')
