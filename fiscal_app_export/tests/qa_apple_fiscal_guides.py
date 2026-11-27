"""Apple public fiscal guides: compare with the independent approved reference.
Synthetic visitor only; no production, provider or write requests.
"""
from pathlib import Path
from qa_home_redesign import WIDTHS,context
from qa_advisory_apple import styles
from qa_apple_panel_standard import assert_home_panels

PAGES={"permuta-criptomonedas-irpf":{"tables":3,"faq":8,"sections":["que-es","cuando-tributa","como-calcular","valor-adquisicion","comisiones","como-declarar","perdidas","errores","faq"],"rows":12},"staking-criptomonedas-irpf":{"tables":3,"faq":8,"sections":["que-es","clasificacion","cuando-tributa","calculo","casillas","tipos","exchanges","venta","errores","faq"],"rows":16},"metodo-fifo-criptomonedas":{"tables":4,"rows":21,"faq":7,"sections":["que-es","por-que-obligatorio","como-calcular","pool-global","comisiones","fifo-vs-lifo","tsjpv-2025","errores","calculadora","faq"]},"bienes-homogeneos-criptomonedas":{"tables":3,"rows":17,"faq":6,"sections":["que-son","fifo","pool-global","vs-valores","norma-antiaplicacion","doctrina-foral","posiciones","ejemplos","faq"]},"perdidas-patrimoniales-criptomonedas":{"tables":4,"rows":20,"faq":6,"sections":["que-son","cuando-se-generan","casillas","como-declarar","calcular","obligacion","especiales","errores","faq"]},"compensar-perdidas-criptomonedas":{"tables":9,"rows":49,"faq":6,"sections":["mecanismo","compensacion-cruzada","capital-mobiliario","arrastre","precondicion","calculo-perdida","errores","casos","faq"]},"regla-dos-meses-criptomonedas":{"tables":4,"rows":21,"faq":6,"sections":["normativa","dgt","aeat","mecanismo","fifo","ejemplos","declarar","debate","faq","herramienta"]}}

def run_apple_fiscal_guides(browser,origin):
    out=Path("qa-artifacts");out.mkdir(exist_ok=True)
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        home=ctx.new_page()
        assert home.goto(origin+"/",wait_until="networkidle").status==200
        ref=ctx.new_page()
        assert ref.goto(origin+"/como-funciona",wait_until="networkidle").status==200
        for name,expected in PAGES.items():
            page=ctx.new_page();errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            assert page.goto(origin+"/static/"+name+".html",wait_until="networkidle").status==200
            for sel,props in [
                ("#site-nav",["background-color","min-height","position"]),
                (".how-intro",["background-color","color","padding-top","padding-bottom"]),
                (".how-intro .apple-container",["width","max-width","padding-left","padding-right"]),
                (".how-intro h1",["font-family","font-size","font-weight","line-height","letter-spacing","text-wrap","width","max-width","margin-bottom"]),
                (".how-lead",["font-size","line-height","color","width","max-width","margin-bottom"]),
                (".how-intro .apple-eyebrow",["font-size","font-weight","margin-bottom","color"]),
                (".apple-footer",["background-color","padding-top","padding-bottom"]),
                (".how-faq-list .apple-faq-item summary",["font-size","line-height","padding-top","padding-bottom"]),
            ]:
                assert styles(page,sel,props)==styles(ref,sel,props),(name,width,sel,styles(page,sel,props),styles(ref,sel,props))
            assert page.locator("#snavBtnSignup").text_content()=="Crear cuenta"
            for sel in (".how-intro h1",".how-lead"):
                a=page.locator(sel).bounding_box()
                c=page.locator(".how-intro .apple-container")
                b=c.bounding_box()
                pads=c.evaluate("e=>[parseFloat(getComputedStyle(e).paddingLeft),parseFloat(getComputedStyle(e).paddingRight)]")
                assert abs(a["x"]-b["x"]-pads[0])<1 and abs(a["width"]-b["width"]+sum(pads))<1,(name,width,sel,a,b,pads)
            counts={"metodo-fifo-criptomonedas":4,"bienes-homogeneos-criptomonedas":2,"permuta-criptomonedas-irpf":3,"staking-criptomonedas-irpf":2,"perdidas-patrimoniales-criptomonedas":2,"compensar-perdidas-criptomonedas":4,"regla-dos-meses-criptomonedas":3}
            assert_home_panels(page,home,width,name,counts[name])
            for button in page.locator(".apple-cta .apple-button").all():
                assert button.evaluate("e=>getComputedStyle(e).borderRadius") == "999px"
                assert button.evaluate("e=>getComputedStyle(e).backgroundColor") == "rgb(0, 107, 84)"
                assert button.evaluate("e=>getComputedStyle(e).color") == "rgb(255, 255, 255)"
            assert page.locator(".how-intro h1 br").count()==0
            assert page.locator(".how-intro .apple-cta").count()==0
            hero=page.locator(".how-intro").bounding_box()
            lead=page.locator(".how-lead").bounding_box()
            gap=hero["y"]+hero["height"]-lead["y"]-lead["height"]
            padding=float(styles(ref,".how-intro",["padding-bottom"])["padding-bottom"].removesuffix("px"))
            assert abs(gap-padding)<1,(name,width,gap,padding)
            assert page.locator(".files-table").count()==expected["tables"]
            assert page.locator(".files-table tr").count()==expected["rows"]
            assert page.locator(".apple-faq-item").count()==expected["faq"]
            for anchor in expected["sections"]:
                assert page.locator('[id="'+anchor+'"]').count()==1
                assert page.locator('.legal-index a[href="#'+anchor+'"]').count()==1
            faq=page.locator(".apple-faq-item").first
            initial=faq.get_attribute("open") is not None
            if initial: faq.locator("summary").click()
            faq.locator("summary").click()
            assert faq.get_attribute("open") is not None and faq.locator(".apple-faq-answer").is_visible()
            if not initial: faq.locator("summary").click()
            assert (faq.get_attribute("open") is not None)==initial
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),(name,width,"document overflow")
            assert page.evaluate("""() => [...document.querySelectorAll('.files-table-wrap')].every(e=>{const r=e.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1})"""),(name,width,"table wrapper overflow")
            if width in (390,768,1440):
                page.evaluate("window.scrollTo(0,0)")
                page.screenshot(path=str(out/f"home_apple_fiscal_{name}_{width}.png"),full_page=True,animations="disabled")
            assert not errors and not violations,(name,width,errors,violations)
            page.close()
        ctx.close()
    print(f"APPLE_FISCAL_GUIDES: PASS ({len(PAGES)} pages × {len(WIDTHS)} widths)")
