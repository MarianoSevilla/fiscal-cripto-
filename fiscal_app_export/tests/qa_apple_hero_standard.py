"""Cross-family Apple hero contract: use the owner's canonical Cómo funciona.
Unlike comparing one exchange guide with another, this detects shared drift.
All traffic stays on the isolated local server; no real accounts or payments.
"""
from pathlib import Path
from qa_home_redesign import WIDTHS, context
from qa_advisory_apple import styles

GUIDES=("binance","bit2me","bitvavo","coinbase","kraken","nexo","cryptocom")
REF="/como-funciona"
ART=Path("qa-artifacts")

def compare(page,sel,ref,ref_sel,props,width,name):
    actual=styles(page,sel,props)
    expected=styles(ref,ref_sel,props)
    assert actual==expected,(name,width,sel,actual,expected)

def full_width(page,selector,container):
    a=page.locator(selector).bounding_box()
    b=page.locator(container).bounding_box()
    pads=page.locator(container).evaluate("e=>[parseFloat(getComputedStyle(e).paddingLeft),parseFloat(getComputedStyle(e).paddingRight)]")
    assert abs(a["x"]-b["x"]-pads[0])<1,(selector,a,b,pads)
    assert abs(a["width"]-(b["width"]-sum(pads)))<1,(selector,a,b,pads)

def run_apple_hero_standard(browser,origin):
    ART.mkdir(exist_ok=True)
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        ref=ctx.new_page()
        assert ref.goto(origin+REF,wait_until="networkidle").status==200
        for name in GUIDES:
            page=ctx.new_page()
            errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            assert page.goto(origin+"/static/exchanges/"+name+".html",wait_until="networkidle").status==200
            compare(page,".hero",ref,".how-intro",["padding-top","padding-bottom","background-color","color"],width,name)
            compare(page,".hero .wrap",ref,".how-intro .apple-container",["width","max-width","padding-left","padding-right"],width,name)
            compare(page,".hero h1",ref,".how-intro h1",["font-family","font-size","font-weight","line-height","letter-spacing","max-width","width","margin-bottom","text-wrap"],width,name)
            compare(page,".hero-desc",ref,".how-lead",["font-family","font-size","line-height","color","max-width","width","margin-bottom"],width,name)
            compare(page,".hero-badge",ref,".how-intro .apple-eyebrow",["font-size","font-weight","color","letter-spacing","margin-bottom"],width,name)
            for selector in (".hero h1",".hero-desc"):
                full_width(page,selector,".hero .wrap")
            hero=page.locator(".hero").bounding_box()
            desc=page.locator(".hero-desc").bounding_box()
            nav=page.locator("#site-nav").bounding_box()
            gap=hero["y"]+hero["height"]-desc["y"]-desc["height"]
            expected=float(styles(ref,".how-intro",["padding-bottom"])["padding-bottom"].removesuffix("px"))
            assert abs(gap-expected)<1,(name,width,gap,expected)
            assert abs(hero["y"]-nav["y"]-nav["height"])<1,(name,width,hero,nav)
            assert page.locator(".hero h1 br").count()==0,(name,width,"forced break")
            assert page.locator(".hero").evaluate("e=>e.scrollWidth<=e.clientWidth+1"),(name,width,"hero overflow")
            assert not errors and not violations,(name,width,errors,violations)
            if width in (390,768,1440):
                page.locator(".hero").screenshot(path=str(ART/f"apple_hero_{name}_{width}.png"),animations="disabled")
            page.close()
        ctx.close()
    print(f"APPLE_HERO_STANDARD: PASS ({len(GUIDES)} guides × {len(WIDTHS)} widths; canonical cross-family equality)")
