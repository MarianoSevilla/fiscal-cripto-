"""The editorial Modelo 721 guide adopts existing Cómo funciona components.
No fiscal assertions beyond preservation of the previously published content.
"""
from pathlib import Path
from qa_home_redesign import WIDTHS,context,geometry
from qa_advisory_apple import styles
from qa_apple_panel_standard import assert_home_panels

PAGE="/static/modelo-721-criptomonedas.html"
REFERENCE="/como-funciona"

def run_modelo721_guide_apple(browser,origin):
    out=Path("qa-artifacts");out.mkdir(exist_ok=True)
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        page=ctx.new_page();ref=ctx.new_page();errors=[]
        home=ctx.new_page()
        assert home.goto(origin+"/",wait_until="networkidle").status==200
        for p,path in ((page,PAGE),(ref,REFERENCE)):
            p.on("pageerror",lambda e:errors.append(str(e)))
            assert p.goto(origin+path,wait_until="networkidle").status==200
        for selector,reference,props in [
            ("#site-nav","#site-nav",["background-color","min-height","position"]),
            (".how-intro",".how-intro",["background-color","color","padding-top","padding-bottom"]),
            (".how-intro .apple-container",".how-intro .apple-container",["width","max-width","padding-left","padding-right"]),
            (".how-intro h1",".how-intro h1",["font-family","font-size","line-height","font-weight","letter-spacing","text-wrap","max-width","width","margin-bottom"]),
            (".how-intro .how-lead",".how-intro .how-lead",["font-size","line-height","color","width","max-width","margin-bottom"]),
            (".how-intro .apple-eyebrow",".how-intro .apple-eyebrow",["font-size","font-weight","color","margin-bottom"]),
            (".how-actions",".how-actions",["margin-top"]),
            (".how-actions .apple-button",".how-actions .apple-button",["font-family","font-size","font-weight","background-color","color","min-height","border-radius","padding-left","padding-right","width"]),
            (".how-micro",".how-micro",["margin-top","font-size","color"]),
            (".how-section",".how-section",["padding-top","padding-bottom"]),
            (".apple-catalog-grid",".apple-catalog-grid",["grid-template-columns","gap"]),
            (".apple-catalog-card",".apple-catalog-card",["background-color","border-color","border-radius","padding-top","padding-left"]),
            (".apple-faq-item summary",".apple-faq-item summary",["font-size","line-height","padding-top","padding-bottom"]),
            (".apple-footer",".apple-footer",["background-color","padding-top","padding-bottom"]),
        ]:
            assert styles(page,selector,props)==styles(ref,reference,props),(width,selector,styles(page,selector,props),styles(ref,reference,props))
        assert page.locator("#snavBtnSignup").text_content()=="Crear cuenta"
        assert page.locator(".how-intro h1 br").count()==0
        for sel in (".how-intro h1",".how-intro p.how-lead"):
            a=page.locator(sel).bounding_box()
            c=page.locator(".how-intro .apple-container")
            b=c.bounding_box()
            pads=c.evaluate("e=>[parseFloat(getComputedStyle(e).paddingLeft),parseFloat(getComputedStyle(e).paddingRight)]")
            assert abs(a["x"]-b["x"]-pads[0])<1 and abs(a["width"]-b["width"]+sum(pads))<1,(width,sel,a,b,pads)
        assert_home_panels(page,home,width,"modelo-721-criptomonedas",1)
        assert not geometry(page,width),(width,geometry(page,width))
        assert page.locator("#quien-debe-presentar-modelo-721 .apple-catalog-card").count()==6
        assert page.locator("#como-funciona-herramienta-721 .apple-catalog-card").count()==4
        assert page.locator("#exchanges-extranjeros-modelo-721 img").count()==7
        assert page.locator(".apple-faq-item").count()==6
        faq=page.locator(".apple-faq-item").first
        faq.locator("summary").click();assert faq.get_attribute("open") is not None
        faq.locator("summary").click()
        if width<=1200:
            toggle=page.locator("#snavMenuToggle");toggle.click()
            assert page.locator("#snavMobileMenu a[href='/herramientas']").is_visible()
            toggle.press("Escape")
        assert not errors and not violations,(width,errors,violations)
        if width in (390,768,1440):
            page.evaluate("window.scrollTo(0,0)")
            page.screenshot(path=str(out/f"home_modelo721_guide_{width}.png"),full_page=True,animations="disabled")
        ctx.close()
    print(f"MODELO721_GUIDE_APPLE: PASS ({len(WIDTHS)} widths)")
