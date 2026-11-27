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


def mid_cta(page):
    card=page.locator(".content-main.prose > .cta-mid")
    assert card.count()==1
    return card

def cta_bottom_gap(page):
    card=mid_cta(page)
    a=card.bounding_box()
    b=card.locator(".cta-buttons").bounding_box()
    return a["y"]+a["height"]-b["y"]-b["height"]

def compare_mid_cta(page,reference,width,name):
    card=mid_cta(page)
    selector=".content-main.prose > .cta-mid"
    assert card.evaluate("e=>Array.from(e.children,c=>c.tagName+':'+c.className).join('|')")==mid_cta(reference).evaluate("e=>Array.from(e.children,c=>c.tagName+':'+c.className).join('|')"),(name,width,"CTA structure")
    assert card.locator(".cta-micro-text").count()==0
    assert card.locator(".cta-benefits > li").count()==3
    assert card.locator(".cta-buttons > a").count()==2
    assert card.locator(".btn-cta").get_attribute("href")=="/"+name
    assert card.locator(".btn-outline").get_attribute("href")=="/asesoramiento-fiscal-criptomonedas"
    pairs=[
        ("",["background-color","border-radius","border-top-width","border-top-color","padding-top","padding-right","padding-bottom","padding-left","margin-top","margin-bottom","text-align"]),
        (" .cta-mid-title",["font-family","font-size","font-weight","line-height","letter-spacing","color","margin-bottom"]),
        (" > p",["font-family","font-size","line-height","color","margin-bottom"]),
        (" .cta-benefits",["display","flex-direction","gap","margin-top","margin-bottom","padding-left"]),
        (" .cta-benefits > li:first-child",["font-family","font-size","line-height","color","gap"]),
        (" .cta-buttons",["display","flex-direction","flex-wrap","gap","justify-content"]),
        (" .btn-cta",["font-family","font-size","font-weight","line-height","border-radius","min-height","padding-top","padding-bottom","padding-left","padding-right","background-color","color"]),
        (" .btn-outline",["font-family","font-size","font-weight","line-height","border-radius","min-height","padding-top","padding-bottom","padding-left","padding-right","background-color","color"]),
    ]
    for suffix,props in pairs:
        compare(page,selector+suffix,reference,selector+suffix,props,width,name)
    gap=cta_bottom_gap(page)
    expected=cta_bottom_gap(reference)
    assert abs(gap-expected)<1,(name,width,"space below buttons",gap,expected)
    assert abs(card.bounding_box()["width"]-mid_cta(reference).bounding_box()["width"])<1,(name,width,"card width")
    assert card.evaluate("e=>e.scrollWidth<=e.clientWidth+1"),(name,width,"CTA overflow")
    # Content-specific button labels and wrapping may change the card height.
    # The shared layout, bottom spacing and control styles must not change.
    if width in (390,768,1440):
        card.screenshot(path=str(ART/f"home_apple_mid_cta_{name}_{width}.png"),animations="disabled")


def run_apple_hero_standard(browser,origin):
    ART.mkdir(exist_ok=True)
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        ref=ctx.new_page()
        assert ref.goto(origin+REF,wait_until="networkidle").status==200
        cta_reference=ctx.new_page()
        assert cta_reference.goto(origin+"/static/exchanges/bitvavo.html",wait_until="networkidle").status==200
        for name in GUIDES:
            page=ctx.new_page()
            errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            assert page.goto(origin+"/static/exchanges/"+name+".html",wait_until="networkidle").status==200
            assert page.locator("#snavBtnSignup").text_content()==ref.locator("#snavBtnSignup").text_content()=="Crear cuenta",(name,width,"signup label")
            compare(page,"#site-nav",ref,"#site-nav",["background-color","min-height","position"],width,name)
            if width>1200:
                compare(page,"#snavBtnSignup",ref,"#snavBtnSignup",["background-color","color","font-family","font-size","font-weight","padding-left","padding-right","border-radius","width","height"],width,name)
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
            assert page.locator(".hero .hero-snippet").count()==0,(name,width,"editorial card inside intro")
            if name=="coinbase":
                snippet=page.locator(".content-main #definicion")
                assert snippet.count()==1 and snippet.is_visible(),(name,width,"editorial definition missing")
                assert snippet.bounding_box()["y"]>=hero["y"]+hero["height"]-1,(name,width,"definition overlaps intro")
            assert page.locator(".hero").evaluate("e=>e.scrollWidth<=e.clientWidth+1"),(name,width,"hero overflow")
            compare_mid_cta(page,cta_reference,width,name)
            assert not errors and not violations,(name,width,errors,violations)
            if width in (390,768,1440):
                page.locator(".hero").screenshot(path=str(ART/f"home_apple_hero_{name}_{width}.png"),animations="disabled")
            page.close()
        ctx.close()
    print(f"APPLE_HERO_STANDARD: PASS ({len(GUIDES)} guides × {len(WIDTHS)} widths; canonical cross-family equality)")
