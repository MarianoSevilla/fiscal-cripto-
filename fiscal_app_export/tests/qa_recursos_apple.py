"""Render Jinja fixtures, intercept every request; no app/database/provider calls."""
import json
from pathlib import Path
from types import SimpleNamespace
from jinja2 import Environment,FileSystemLoader,StrictUndefined,select_autoescape
from qa_home_redesign import WIDTHS,context,geometry

ROOT=Path(__file__).resolve().parents[1]
ENV=Environment(loader=FileSystemLoader(ROOT/'templates'),autoescape=select_autoescape(['html']),undefined=StrictUndefined)
SAMPLE=json.loads((Path(__file__).parent/'resources_apple_fixture.json').read_text())
ART=Path('qa-artifacts')

def html(kind,resources=None,**changes):
    sample=SimpleNamespace(**dict(SAMPLE,**changes))
    return ENV.get_template('recursos_apple.html' if kind=='catalog' else 'recurso_apple.html').render(resources=[sample] if resources is None else resources,resource=sample)

def open_page(ctx,origin,kind='catalog',markup=None):
    page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.route('**/static/resources-apple-test.html',lambda r:r.fulfill(status=200,content_type='text/html',body=markup or html(kind)))
    page.goto(origin+'/static/resources-apple-test.html',wait_until='networkidle')
    return page,errors

def fill_form(page,uid='12345678'):
    page.locator('#name').fill('Persona ficticia');page.locator('#email').fill('synthetic@example.invalid')
    page.locator('#exchange').select_option('bitvavo');page.locator('#uid').fill(uid)
    page.locator('#legal_accepted').check();page.locator('#marketing_consent').check()

def run_recursos_apple(browser,origin):
    ART.mkdir(exist_ok=True);cases=0
    for kind in ['catalog','detail']:
        for width in WIDTHS:
            ctx,violations=context(browser,width=width,height=900)
            page,errors=open_page(ctx,origin,kind)
            page.locator('#snavBtnSignup:not(.snav-hidden)').wait_for(state='attached')
            assert not geometry(page,width),(kind,width,geometry(page,width))
            header=page.locator('#site-nav').bounding_box();intro=page.locator('.resources-intro').bounding_box()
            assert abs(header['y'])<1 and 63<=header['height']<=65
            assert abs(intro['y']-header['height'])<1
            assert page.locator('h1').count()==page.locator('main').count()==1
            assert page.locator('h1').evaluate('e=>{const s=getComputedStyle(e.parentElement);return Math.abs(e.getBoundingClientRect().width-e.parentElement.clientWidth+parseFloat(s.paddingLeft)+parseFloat(s.paddingRight))<1}')
            if kind=='catalog':
                cards=page.locator('.apple-catalog-card');assert cards.count()==5
                assert page.locator('.resources-catalog .apple-catalog-card').get_attribute('href')=='/recursos/recurso-ficticio'
                for card in cards.all():
                    assert card.evaluate("e=>getComputedStyle(e).backgroundColor")=='rgb(237, 245, 240)'
                    assert card.evaluate("e=>getComputedStyle(e).borderRadius")=='16px'
                    assert card.locator('h3').evaluate("e=>getComputedStyle(e).fontSize")=='24px'
                notice=page.locator('.resources-affiliate-notice');assert notice.bounding_box()['y']<page.locator('.resources-affiliates').bounding_box()['y']
            else:
                assert page.locator('#submit-btn').is_disabled()
                assert page.locator('#exchange option').all_text_contents()==['Selecciona un exchange','Bitvavo','Binance']
                assert page.locator('#form-success').is_hidden()
                if width<=640:assert page.locator('#name').bounding_box()['y']<page.locator('#email').bounding_box()['y']
                else:assert page.locator('#name').bounding_box()['y']==page.locator('#email').bounding_box()['y']
            if width<=1200:
                toggle=page.locator('#snavMenuToggle');toggle.click()
                assert page.locator('#snavMobileMenu a[aria-current="page"]').inner_text()=='Recursos'
                page.keyboard.press('Escape');assert toggle.get_attribute('aria-expanded')=='false'
            page.screenshot(path=str(ART/f'home_resources_{kind}_{width}px.png'),full_page=True)
            assert not errors and not violations,(kind,width,errors,violations)
            ctx.close();cases+=1
    for kind in ['catalog','detail']:
        for width in [390,768,1280]:
            ctx,violations=context(browser,width=width,js=False);page,_=open_page(ctx,origin,kind)
            assert not geometry(page,width)
            if width<=1200:
                page.locator('.apple-noscript-menu summary').click();assert page.locator('.apple-noscript-menu a[aria-current="page"]').is_visible()
            if kind=='detail':assert page.locator('#resource-form').is_hidden() and page.get_by_text('Para enviar la solicitud necesitas activar JavaScript.',exact=False).is_visible()
            assert not violations;ctx.close();cases+=1
        for width in [390,768,1280]:
            ctx,violations=context(browser,width=width);page,errors=open_page(ctx,origin,kind)
            page.add_style_tag(content='html{font-size:200%}')
            assert not geometry(page,width),(kind,width,geometry(page,width))
            page.screenshot(path=str(ART/f'home_resources_{kind}_text200_{width}px.png'),full_page=True)
            assert not errors and not violations;ctx.close();cases+=1
        ctx,violations=context(browser,width=390);page,errors=open_page(ctx,origin,kind)
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.apple-button').first.evaluate('e=>getComputedStyle(e).transitionDuration')=='0s'
        assert not errors and not violations;ctx.close();cases+=1
    for role in ['user','admin']:
        ctx,violations=context(browser,width=390,role=role);page,errors=open_page(ctx,origin)
        page.locator('#snavAvatarWrap:not(.snav-hidden)').wait_for(state='attached')
        page.locator('#snavMenuToggle').click();assert page.locator('#snavMobileMenu a[aria-current="page"]').inner_text()=='Recursos'
        assert page.locator('#snavMobileMenu a[href="/dashboard"]').is_visible()
        assert not errors and not violations;ctx.close();cases+=1
    for resources in [[],[SimpleNamespace(**dict(SAMPLE,slug=f'ficticio-{i}',title='Recurso '+('largo'*30))) for i in range(4)]]:
        ctx,violations=context(browser,width=320);page,errors=open_page(ctx,origin,markup=html('catalog',resources=resources))
        assert not geometry(page,320);assert page.locator('.resources-catalog .apple-catalog-card').count()==len(resources)
        if not resources:assert page.locator('.resources-empty').is_visible()
        assert not errors and not violations;ctx.close();cases+=1
    for scenario in ['success','retry','offline','uid']:
        ctx,violations=context(browser,width=390);page,errors=open_page(ctx,origin,'detail');sent=[]
        def submit(route):
            payload=route.request.post_data_json;sent.append(payload)
            assert payload['email']=='synthetic@example.invalid' and payload['resource_id']==999999
            if scenario=='offline':route.abort();return
            status=400 if scenario=='retry' and len(sent)==1 else 201
            route.fulfill(status=status,content_type='application/json',body=json.dumps({'error':'Error sintético. Revisa los datos.'} if status==400 else {'ok':True}))
        page.route('**/api/recursos/solicitar',submit)
        fill_form(page,uid='' if scenario=='uid' else '12345678');page.locator('#submit-btn').click()
        if scenario=='uid':
            assert not sent;assert page.locator('#uid').get_attribute('aria-invalid')=='true'
            page.locator('#uid_unknown').check();page.locator('#submit-btn').click()
        if scenario=='retry':
            page.locator('#form-error').wait_for(state='visible');assert page.locator('#name').input_value()=='Persona ficticia'
            page.locator('#submit-btn').click()
        if scenario=='offline':
            page.locator('#form-error').wait_for(state='visible');assert page.locator('#resource-form').is_visible() and page.locator('#submit-btn').is_enabled()
        else:
            page.locator('#form-success').wait_for(state='visible');assert page.locator('#resource-form').is_hidden()
            assert page.locator('#form-success').evaluate('e=>document.activeElement===e')
            assert sent[-1]['legal_accepted'] is True and sent[-1]['marketing_consent'] is True
        assert not errors and not violations,(scenario,errors,violations)
        ctx.close();cases+=1
    print(f'RECURSOS_APPLE_QA: PASS ({cases} synthetic browser scenarios; {len(WIDTHS)} widths; two templates; mocked requests only)')
