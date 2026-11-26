"""Compare advisory components with approved pages at real Chromium widths."""
from pathlib import Path
from qa_home_redesign import WIDTHS,context,geometry

ADVISORY="/static/asesoramiento-fiscal.html"
REFERENCE="/static/como-funciona.html"

def styles(page,selector,properties):
    return page.locator(selector).first.evaluate(
        "(el,props)=>Object.fromEntries(props.map(p=>[p,getComputedStyle(el).getPropertyValue(p)]))",properties
    )

def run_advisory_apple(browser,origin):
    out=Path("qa-artifacts");out.mkdir(exist_ok=True)
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        errors=[]
        page=ctx.new_page();ref=ctx.new_page()
        for p,path in [(page,ADVISORY),(ref,REFERENCE)]:
            p.on("pageerror",lambda error:errors.append(str(error)))
            assert p.goto(origin+path,wait_until="networkidle").status==200
            p.locator("#snavBtnSignup:not(.snav-hidden)").wait_for(state="attached")
        assert not geometry(page,width),(width,geometry(page,width))
        for selector,props in [
            ("body",["font-family","font-size","line-height","color","background-color"]),
            ("#site-nav",["background-color","border-bottom-width","position"]),
            (".how-intro",["background-color","padding-top","padding-bottom"]),
            (".how-intro .apple-container",["max-width","padding-left","padding-right"]),
            ("h1",["font-size","line-height","font-weight","letter-spacing","max-width","width"]),
            (".how-actions",["margin-top"]),
            (".how-actions .apple-button",["background-color","color","border-radius","border-color","font-family","font-size","font-weight","min-height","padding-top","padding-left","display","justify-content"]),
            (".how-section",["padding-top","padding-bottom"]),
            (".apple-catalog-grid",["grid-template-columns","gap"]),
            (".apple-catalog-card",["background-color","border-radius","padding-top","padding-left","border-color"]),
            (".apple-cta",["background-color","border-radius","padding-top","padding-left","gap"]),
            (".apple-cta--compact",["grid-template-columns"]),
            (".apple-footer",["padding-top","padding-bottom","background-color"]),
        ]:
            # Compact CTA's intrinsic second track legitimately depends on label width.
            # Compare display/alignment rather than its text-dependent pixel width.
            if selector==".apple-cta--compact":
                props=["display","align-items","gap"]
            assert styles(page,selector,props)==styles(ref,selector,props),(width,selector,styles(page,selector,props),styles(ref,selector,props))
        cards=page.locator(".apple-catalog-card");assert cards.count()==3
        card_boxes=[c.bounding_box() for c in cards.all()]
        cols=3 if width>1200 else 2 if width>640 else 1
        grid=page.locator(".apple-catalog-grid").bounding_box()
        gap=page.locator(".apple-catalog-grid").evaluate("e=>parseFloat(getComputedStyle(e).columnGap)")
        expected=(grid["width"]-(cols-1)*gap)/cols
        assert all(abs(c["width"]-expected)<1 for c in card_boxes),(width,card_boxes,expected)
        assert page.locator(".apple-includes-grid").evaluate("e=>[...e.children].every(c=>c.getBoundingClientRect().width>150)"),width
        if width<=640:
            assert card_boxes[0]["y"]<card_boxes[1]["y"]<card_boxes[2]["y"]
        actions=page.get_by_role("link",name="Enviar solicitud sin pago",exact=True)
        assert actions.count()==3
        for a in actions.all():
            assert a.get_attribute("href")=="/pedir-asesoramiento-fiscal"
            assert a.bounding_box()["height"]>=48
        if width<=640:
            for sel in [".how-actions",".apple-cta--compact"]:
                container=page.locator(sel)
                action=container.locator(".apple-button").bounding_box()
                assert abs(action["width"]-container.evaluate("e=>e.clientWidth-parseFloat(getComputedStyle(e).paddingLeft)-parseFloat(getComputedStyle(e).paddingRight)"))<1
        photo=page.locator(".author-portrait img")
        photo.scroll_into_view_if_needed()
        page.wait_for_function("document.querySelector('.author-portrait img').naturalWidth>0")
        assert abs(photo.bounding_box()["width"]-(72 if width<=640 else 88))<1
        if width<=1200:
            toggle=page.locator("#snavMenuToggle")
            toggle.click()
            assert page.locator("#snavMobileMenu a[href='/herramientas']").is_visible()
            toggle.press("Escape")
            assert toggle.get_attribute("aria-expanded")=="false"
        if width in (390,1440):
            page.screenshot(path=str(out/f"home_advisory_{width}px.png"),full_page=True,animations="disabled")
        assert not errors and not violations,(width,errors,violations)
        ctx.close()
    for width in [390,1280]:
        ctx,violations=context(browser,width=width,js=False)
        page=ctx.new_page();assert page.goto(origin+ADVISORY).status==200
        assert not geometry(page,width)
        assert page.get_by_role("link",name="Enviar solicitud sin pago",exact=True).count()==3
        if width<=1200:
            page.locator(".apple-noscript-menu summary").click()
            assert page.locator(".apple-noscript-menu a[href='/herramientas']").is_visible()
        assert not violations
        ctx.close()
    print(f"ADVISORY_APPLE_QA: PASS ({len(WIDTHS)} widths + no-JS cases)")
