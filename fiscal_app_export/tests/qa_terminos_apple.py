"""Isolated terms preview: synthetic sessions, no app/provider I/O."""
import re
from pathlib import Path
from qa_home_redesign import WIDTHS, context, geometry

ROOT=Path(__file__).resolve().parents[1]
MARKUP=(ROOT/'static/terminos_apple.html').read_text()
VIEWER=(ROOT.parent/'terminos-apple-preview/index.html').read_text()
IDS=('ambito', 'herramientas', 'cuenta', 'archivos', 'informes', 'asesoramiento', 'condiciones-economicas', 'uso-y-seguridad', 'disponibilidad', 'propiedad-intelectual', 'baja-y-privacidad', 'cambios', 'reclamaciones')

def open_page(ctx,origin,viewer=False,wait='networkidle'):
    page=ctx.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    markup=VIEWER if viewer else MARKUP
    page.route('**/static/terminos-apple-test.html',lambda r:r.fulfill(status=200,content_type='text/html',body=markup))
    if viewer:
        page.route('**/terminos-apple-preview/session.json',lambda r:r.fulfill(status=200,content_type='application/json',body='{"user":null}'))
    response=page.goto(origin+'/static/terminos-apple-test.html',wait_until=wait)
    assert response.status==200
    return page,errors

def structure(page,width,strict_header=True):
    assert not geometry(page,width),(width,geometry(page,width))
    nav=page.locator('#site-nav').bounding_box()
    intro=page.locator('.legal-intro').bounding_box()
    assert abs(nav['y'])<1,(width,nav)
    if strict_header:
        assert 63<=nav['height']<=65,(width,nav)
        assert abs(intro['y']-nav['height'])<1,(width,intro)
    else:
        # Desktop no-JS fallback adds visible account links above the article.
        assert intro['y']>=nav['y']+nav['height']-1,(width,intro)
    assert page.locator('h1').count()==page.locator('main').count()==1
    assert page.locator('.legal-section').count()==len(IDS)
    assert page.locator('meta[name="robots"]').get_attribute('content')=='noindex, nofollow'
    assert page.locator('link[rel="canonical"]').get_attribute('href')=='https://marianosevilla.com/terminos'
    assert page.locator('.legal-index a').count()==len(IDS)
    assert all(page.locator('#'+i).count()==1 for i in IDS)
    assert page.locator('.legal-section[hidden]').count()==0
    assert page.locator('form').count()==page.locator('input').count()==0
    assert not re.search(r'\b\d{8}[A-Z]\b',page.locator('body').inner_text())
    assert page.locator('.legal-help .apple-button').get_attribute('href')=='mailto:colab.marianosevilla@gmail.com'
    assert page.locator('.legal-help .apple-button').evaluate('e=>getComputedStyle(e).borderRadius')=='999px'
    assert page.locator('h1').evaluate('e=>Math.abs(e.getBoundingClientRect().width-e.parentElement.clientWidth+parseFloat(getComputedStyle(e.parentElement).paddingLeft)+parseFloat(getComputedStyle(e.parentElement).paddingRight))<1')
    assert page.locator('link[href*="fonts.googleapis"],link[href*="fonts.gstatic"]').count()==0

def run_terminos_apple(browser,origin):
    cases=0;art=Path('qa-artifacts');art.mkdir(exist_ok=True)
    assert 'window.fetch' not in MARKUP
    assert 'Consultar mis derechos' not in MARKUP
    assert 'legal-hero-link' not in MARKUP
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        page,errors=open_page(ctx,origin)
        page.locator('#snavBtnSignup:not(.snav-hidden)').wait_for(state='attached')
        structure(page,width)
        page.keyboard.press('Tab')
        assert page.locator('.apple-skip').evaluate('e=>e===document.activeElement')
        page.keyboard.press('Enter')
        assert page.locator('main').evaluate('e=>e===document.activeElement')
        page.locator('.legal-index a[href="#reclamaciones"]').click()
        assert page.url.endswith('#reclamaciones')
        title=page.locator('#reclamaciones-title').bounding_box()
        assert 0<=title['y']<page.viewport_size['height']-30,(width,title)
        page.locator('.legal-index a[href="#ambito"]').click()
        page.keyboard.press('Control+Home')
        if width<=1200:
            page.locator('#snavMenuToggle').click()
            assert page.locator('#snavMobileMenu a[href="/herramientas"]').is_visible()
            assert page.locator('#snavMobileMenu a[href="/recursos"]').is_visible()
            page.keyboard.press('Escape')
            assert page.locator('#snavMenuToggle').get_attribute('aria-expanded')=='false'
        assert not violations and not errors,(width,violations,errors)
        page.screenshot(path=str(art/f'home_terminos_apple_{width}.png'),full_page=True)
        ctx.close();cases+=1
    for width in [320,390,768,1280]:
        ctx,violations=context(browser,width=width,js=False)
        page,errors=open_page(ctx,origin);structure(page,width,strict_header=False)
        page.locator('.legal-index a[href="#reclamaciones"]').click()
        assert page.url.endswith('#reclamaciones')
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
    for width in [390,1280]:
        ctx,violations=context(browser,width=width)
        page,errors=open_page(ctx,origin,viewer=True)
        page.locator('#snavBtnSignup:not(.snav-hidden)').wait_for(state='attached')
        structure(page,width)
        assert page.locator('script[src],link[rel="stylesheet"]').count()==0
        page.locator('.legal-index a[href="#reclamaciones"]').click()
        assert page.url.endswith('#reclamaciones')
        assert not violations and not errors,(violations,errors)
        ctx.close();cases+=1
    for width in [390,1280]:
        ctx,violations=context(browser,width=width)
        page,errors=open_page(ctx,origin)
        page.emulate_media(media='print')
        assert not page.locator('#site-nav').is_visible()
        assert not page.locator('.legal-index').is_visible()
        assert page.locator('#reclamaciones').is_visible()
        assert page.locator('#asesoramiento').is_visible()
        assert not violations and not errors
        ctx.close();cases+=1
    print(f'TERMINOS_APPLE_QA: PASS ({cases} scenarios; {len(WIDTHS)} widths; two renderings; synthetic sessions; no external requests)')

