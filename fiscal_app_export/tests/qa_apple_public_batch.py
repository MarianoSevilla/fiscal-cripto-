"""Public Apple batch: same approved components and real responsive geometry.
All requests confined to localhost; no real payment links or personal records.
"""
from pathlib import Path
from qa_home_redesign import WIDTHS, context
from qa_advisory_apple import styles

PAGES={
    "exchanges/nexo.html":("guide","nexo"),
    "exchanges/cryptocom.html":("guide","cryptocom"),
    "aviso-legal.html":("legal","aviso"),
    "cookies.html":("legal","cookies"),
    "preferencias.html":("how","preferencias"),
    "asesoramiento-confirmado.html":("how","confirmado"),
    "pagar.html":("how","pagar"),
}
REF={"guide":"/static/exchanges/kraken.html","legal":"/terminos","how":"/static/asesoramiento-fiscal.html"}

def visible_overflow(page,width):
    return page.evaluate("""width=>{
        const bad=[];
        if(document.documentElement.scrollWidth>width+1)bad.push("document overflow");
        for(const e of document.querySelectorAll("body *")){
            const s=getComputedStyle(e),r=e.getBoundingClientRect();
            if(!e.getClientRects().length||s.display==="none"||s.visibility==="hidden")continue;
            if(e.closest(".files-table-wrap")&&!e.matches(".files-table-wrap"))continue;
            if(e.closest(".mock-table-wrap")&&!e.matches(".mock-table-wrap"))continue;
            if(r.left < -1 || r.right > width+1)bad.push(e.tagName+"."+String(e.className)+" "+r.left+".."+r.right);
        }
        return bad;
    }""",width)

def run_apple_public_batch(browser,origin):
    out=Path("qa-artifacts");out.mkdir(exist_ok=True)
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        refs={}
        for kind,path in REF.items():
            ref=ctx.new_page();assert ref.goto(origin+path,wait_until="networkidle").status==200
            refs[kind]=ref
        for path,(kind,name) in PAGES.items():
            page=ctx.new_page();errors=[];page.on("pageerror",lambda e:errors.append(str(e)))
            assert page.goto(origin+"/static/"+path,wait_until="networkidle").status==200
            page.locator("#snavBtnSignup:not(.snav-hidden)").wait_for(state="attached")
            assert page.locator("main").count()==page.locator("h1").count()==1
            assert page.locator(".apple-skip").count()==1
            assert not visible_overflow(page,width),(name,width,visible_overflow(page,width))
            ref=refs[kind]
            pairs=[("body","body",["font-family","font-size","background-color","color"]),
                   ("#site-nav","#site-nav",["background-color","position","min-height"])]
            if kind=="guide":
                pairs.extend([(".hero",".hero",["background-color","padding-top","padding-bottom"]),
                              (".wrap",".wrap",["max-width","padding-left","padding-right"]),
                              ("h1","h1",["font-family","font-size","line-height","font-weight"]),
                              (".content-grid",".content-grid",["grid-template-columns","gap"]),
                              (".btn-asistencia",".btn-asistencia",["min-height","border-radius","font-size","background-color","color"]),
                              (".files-table-wrap",".files-table-wrap",["overflow-x","border-radius"])])
                assert page.locator(".content-main > .asistencia-block").count()==1
                faq=page.locator("details.faq-item").first
                faq.locator("summary").click();assert faq.get_attribute("open") is not None
                faq.locator("summary").click()
                assert page.locator(".btn-asistencia").get_attribute("href")=="/"+name
            elif kind=="legal":
                pairs.extend([(".legal-intro",".legal-intro",["background-color","padding-top","padding-bottom"]),
                              (".legal-layout",".legal-layout",["max-width","grid-template-columns","gap","padding-top","padding-bottom"]),
                              (".legal-index",".legal-index",["background-color","border-radius","padding-top"]),
                              (".legal-section h2",".legal-section h2",["font-size","line-height","font-weight"])])
                links=page.locator(".legal-index a")
                assert links.count()==page.locator(".legal-section").count()
                for link in links.all():
                    assert page.locator(link.get_attribute("href")).count()==1
                links.last.click()
                assert page.url.endswith(links.last.get_attribute("href"))
            else:
                pairs.append((".apple-cta",".apple-cta",["background-color","border-radius","padding-top","padding-left","gap"]))
                pairs.append((".apple-cta .apple-button",".apple-cta .apple-button",["min-height","border-radius","font-size","background-color","color"]))
                if name=="preferencias":
                    cards=page.locator(".apple-catalog-card")
                    assert cards.count()==3
                    cols=3 if width>1200 else 2 if width>640 else 1
                    assert page.locator(".apple-catalog-grid").evaluate("e=>getComputedStyle(e).gridTemplateColumns.split(' ').length")==cols
                elif name=="pagar":
                    assert page.locator("#financialSuspension").is_visible()
                    assert "Pagos temporalmente suspendidos" in page.locator("h1").inner_text()
                else:
                    assert "no acredita que se haya recibido" in page.locator("main").inner_text()
            for sel,rsel,props in pairs:
                assert styles(page,sel,props)==styles(ref,rsel,props),(name,width,sel,styles(page,sel,props),styles(ref,rsel,props))
            if width<=1200:
                toggle=page.locator("#snavMenuToggle");toggle.click()
                assert page.locator("#snavMobileMenu a[href='/herramientas']").is_visible()
                toggle.press("Escape")
            assert not visible_overflow(page,width),(name,width,visible_overflow(page,width))
            assert not errors and not violations,(name,width,errors,violations)
            if width in (390,768,1440):
                page.evaluate("window.scrollTo(0,0)")
                page.screenshot(path=str(out/f"home_batch_{name}_{width}px.png"),full_page=True,animations="disabled")
            page.close()
        ctx.close()
    print(f"APPLE_PUBLIC_BATCH_QA: PASS ({len(PAGES)} pages × {len(WIDTHS)} widths)")
