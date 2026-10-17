"""Isolated FAQ presentation; intercept sessions, never import app/database."""
from pathlib import Path
from qa_home_redesign import WIDTHS, context, geometry

ROOT=Path(__file__).resolve().parents[1]
MARKUP=(ROOT/'static/faq_apple.html').read_text()

def open_page(ctx,origin,suffix=''):
    page=ctx.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/static/faq-apple-test.html',lambda r:r.fulfill(status=200,content_type='text/html',body=MARKUP))
    page.goto(origin+'/static/faq-apple-test.html'+suffix,wait_until='networkidle')
    return page,errors

def run_faq_apple(browser,origin):
    art=Path('qa-artifacts');art.mkdir(exist_ok=True);cases=0
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        page,errors=open_page(ctx,origin)
        page.locator('#snavBtnSignup:not(.snav-hidden)').wait_for(state='attached')
        assert not geometry(page,width),(width,geometry(page,width))
        nav=page.locator('#site-nav').bounding_box();hero=page.locator('.faq-intro').bounding_box()
        assert abs(nav['y'])<1 and 63<=nav['height']<=65,(width,nav)
        assert abs(hero['y']-nav['height'])<1,(width,hero)
        assert page.locator('main').count()==page.locator('h1').count()==1
        assert page.locator('.apple-faq-item').count()==20
        assert page.locator('.faq-section').count()==4
        assert page.locator('meta[name="robots"]').get_attribute('content')=='noindex, nofollow'
        assert page.locator('h1').evaluate('e=>Math.abs(e.getBoundingClientRect().width-e.parentElement.clientWidth+parseFloat(getComputedStyle(e.parentElement).paddingLeft)+parseFloat(getComputedStyle(e.parentElement).paddingRight))<1')
        page.locator('#staking summary').click();assert page.locator('#staking').get_attribute('open') is not None
        page.locator('#airdrops summary').click();assert page.locator('#staking[open]').count()==1
        page.locator('#airdrops summary').focus();page.keyboard.press('Space');assert page.locator('#airdrops[open]').count()==0
        if width<=1200:
            toggle=page.locator('#snavMenuToggle');toggle.click()
            assert page.locator('#snavMobileMenu a[aria-current="page"]').inner_text()=='FAQ'
            page.keyboard.press('Escape');assert toggle.get_attribute('aria-expanded')=='false'
        page.screenshot(path=str(art/f'faq_apple_{width}.png'),full_page=True)
        assert not errors and not violations,(width,errors,violations)
        ctx.close();cases+=1
    for width in [320,390,768,1280]:
        ctx,violations=context(browser,width=width,js=False);page,errors=open_page(ctx,origin)
        page.locator('#staking summary').click();assert page.locator('#staking .apple-faq-answer').is_visible()
        if width<=1200:
            page.locator('.apple-noscript-menu summary').click()
            assert page.locator('.apple-noscript-menu a[aria-current="page"]').is_visible()
        assert not geometry(page,width) and not violations and not errors
        ctx.close();cases+=1
    for width in [390,768,1280]:
        ctx,violations=context(browser,width=width);page,errors=open_page(ctx,origin,'#extracto-informe-fifo')
        assert page.locator('#extracto-informe-fifo[open]').count()==1
        page.add_style_tag(content='html{font-size:200%}')
        assert not geometry(page,width),(width,geometry(page,width))
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.apple-button').evaluate('e=>getComputedStyle(e).transitionDuration')=='0s'
        assert not violations and not errors;ctx.close();cases+=1
    for role in ['user','admin']:
        ctx,violations=context(browser,width=390,role=role);page,errors=open_page(ctx,origin)
        page.locator('#snavAvatarWrap:not(.snav-hidden)').wait_for(state='attached')
        page.locator('#snavMenuToggle').click()
        assert page.locator('#snavMobileMenu a[href="/dashboard"]').is_visible()
        assert not violations and not errors;ctx.close();cases+=1
    print(f'FAQ_APPLE_QA: PASS ({cases} scenarios; {len(WIDTHS)} widths; no production requests)')
