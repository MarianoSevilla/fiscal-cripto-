"""Isolated About browser QA: real local assets, synthetic sessions, GET only."""
import json
from pathlib import Path
from qa_home_redesign import WIDTHS,context,geometry

PATH='/about-apple-preview'

def open_page(ctx,origin):
    page=ctx.new_page();errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    response=page.goto(origin+PATH,wait_until='networkidle')
    assert response.status==200
    return page,errors

def structure(page,width,js=True):
    assert not geometry(page,width),(width,geometry(page,width))
    nav=page.locator('#site-nav').bounding_box()
    assert abs(nav['y'])<1 and 63<=nav['height']<=65,(width,nav)
    expected_top=nav['height']
    if not js and width>1200:
        access=page.locator('.apple-noscript-access')
        assert access.is_visible()
        expected_top+=access.bounding_box()['height']
    assert abs(page.locator('.about-intro').bounding_box()['y']-expected_top)<1
    assert page.locator('main').count()==page.locator('h1').count()==1
    for selector in ['h1','.about-lead']:
        box=page.locator(selector).bounding_box()
        inner=page.locator('.about-intro .apple-container').evaluate('e=>e.clientWidth-parseFloat(getComputedStyle(e).paddingLeft)-parseFloat(getComputedStyle(e).paddingRight)')
        assert abs(box['width']-inner)<1,(width,selector,box,inner)
    assert abs(page.locator('h1').bounding_box()['x']-page.locator('.about-profile').first.bounding_box()['x'])<1
    people=page.locator('.about-profile')
    assert people.count()==2
    assert people.locator('h2').all_text_contents()==['Mariano Sevilla','Rafael Ramos Martínez']
    columns=page.locator('.about-people-grid').evaluate('e=>getComputedStyle(e).gridTemplateColumns.split(" ").length')
    assert columns==(1 if width<=900 else 2)
    assert people.first.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(237, 245, 240)'
    assert people.first.evaluate('e=>getComputedStyle(e).borderRadius')=='16px'
    assert page.locator('meta[name="robots"]').get_attribute('content')=='noindex, nofollow'
    assert page.locator('link[rel="canonical"]').get_attribute('href')=='https://marianosevilla.com/about'
    assert page.locator('form,input[type="file"],table').count()==0
    assert page.locator('a:not([href]),a[href=""],a[href="#"]').count()==0
    assert page.locator('link[href*="fonts.googleapis"],link[href*="fonts.gstatic"]').count()==0
    body=page.locator('main').inner_text()
    assert 'Diplomado en Informática de Gestión' in body
    assert 'más de 25 años' in body and '4.579' in body
    assert 'no incluye una revisión profesional individual' in body
    assert 'comisión por la intermediación' in body
    assert page.locator('.about-help .apple-button').get_attribute('href')=='/pedir-asesoramiento'
    assert '→' not in page.locator('.about-help-actions').inner_text()
    data=json.loads(page.locator('script[type="application/ld+json"]').text_content())
    assert data['@type']=='AboutPage'
    assert [p['name'] for p in data['mainEntity']]==['Mariano Sevilla','Rafael Ramos Martínez']
    # Decode actual lazy images, including the second portrait below the fold.
    for image in page.locator('.about-portrait').all():
        assert image.get_attribute('width')==image.get_attribute('height')=='132'
        assert image.get_attribute('loading')=='lazy'
        assert image.get_attribute('srcset')
        image.scroll_into_view_if_needed()
        assert image.evaluate('e=>e.decode().then(()=>e.naturalWidth>0 && e.naturalHeight>0)')
    page.keyboard.press('Control+Home')

def run_about_apple(browser,origin):
    art=Path('qa-artifacts');art.mkdir(exist_ok=True);cases=0
    # Reuse approved Home files; the largest pair is under 27 KB combined.
    static=Path(__file__).resolve().parents[1]/'static'
    assert sum((static/f'home-apple-{person}-264.webp').stat().st_size for person in ['mariano','rafa'])<27000
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        page,errors=open_page(ctx,origin);structure(page,width)
        page.keyboard.press('Tab')
        assert page.locator('.apple-skip').evaluate('e=>e===document.activeElement')
        page.keyboard.press('Enter')
        assert page.locator('main').evaluate('e=>e===document.activeElement')
        if width<=1200:
            toggle=page.locator('#snavMenuToggle');toggle.click()
            assert page.locator('#snavMobileMenu a[href="/herramientas"]').is_visible()
            page.keyboard.press('Escape')
            assert toggle.get_attribute('aria-expanded')=='false'
            assert toggle.evaluate('e=>e===document.activeElement')
        assert not violations and not errors,(width,violations,errors)
        page.keyboard.press('Control+Home')
        page.screenshot(path=str(art/f'home_about_apple_{width}.png'),full_page=True)
        ctx.close();cases+=1
    for width in [320,390,768,1280]:
        ctx,violations=context(browser,width=width,js=False)
        page,errors=open_page(ctx,origin);structure(page,width,js=False)
        if width<=1200:
            page.locator('.apple-noscript-menu summary').click()
            assert page.locator('.apple-noscript-menu a[href="/herramientas"]').is_visible()
        assert not violations and not errors
        ctx.close();cases+=1
    for width in [320,390,768,1280]:
        ctx,violations=context(browser,width=width)
        page,errors=open_page(ctx,origin)
        page.add_style_tag(content='html{font-size:200%}')
        page.emulate_media(reduced_motion='reduce')
        assert not geometry(page,width),(width,geometry(page,width))
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
    print(f'ABOUT_APPLE_QA: PASS ({cases} scenarios; {len(WIDTHS)} widths; real portraits; no-JS; enlarged text; synthetic sessions)')
