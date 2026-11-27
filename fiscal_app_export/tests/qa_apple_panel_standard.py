"""Compare actual promotional panels against the unmodified approved Home.
No synthetic style tokens and no external requests.
"""
from pathlib import Path

def css(el,props):
    return el.evaluate("(e,p)=>Object.fromEntries(p.map(k=>[k,getComputedStyle(e).getPropertyValue(k)]))",props)

def assert_home_panels(page,home,width,name,expected):
    canonical=home.locator("#asistenciaBlock")
    assert canonical.count()==1
    cards=page.locator("main .apple-assistance .asistencia-block")
    assert cards.count()==expected,(name,width,cards.count(),expected)
    out=Path("qa-artifacts")
    for i,card in enumerate(cards.all()):
        pairs=[
            ("",["background-color","border-top-color","border-top-width","border-radius","padding-top","padding-bottom","padding-left","padding-right"]),
            (":scope > .asistencia-badge",["font-family","font-size","font-weight","line-height","letter-spacing","color","margin-top","margin-bottom"]),
            (":scope > p",["font-family","font-size","line-height","color","max-width"]),
            (":scope > p > strong",["font-family","font-size","font-weight","line-height","letter-spacing","color","margin-bottom"]),
            (":scope > .asistencia-bullets",["display","flex-direction","flex-wrap","gap","font-size","color","margin-top","margin-bottom","padding-left","list-style-type"]),
            (":scope > .asistencia-bullets > li",["font-family","font-size","line-height","color"]),
        ]
        for selector,props in pairs:
            a=card if not selector else card.locator(selector).first
            b=canonical if not selector else canonical.locator(selector).first
            assert a.count()==1 and a.is_visible(),(name,width,i,selector)
            assert css(a,props)==css(b,props),(name,width,i,selector,css(a,props),css(b,props))
        assert card.locator(":scope > .asistencia-bullets > li").count()==3
        buttons=card.locator(".btn-asistencia")
        assert buttons.count()>=1
        props=["font-family","font-size","font-weight","line-height","min-height","border-radius","border-top-color","padding-top","padding-bottom","padding-left","padding-right","background-color","color","text-decoration-line"]
        for button in buttons.all():
            assert css(button,props)==css(canonical.locator(".btn-asistencia"),props),(name,width,i,"button",css(button,props),css(canonical.locator(".btn-asistencia"),props))
        gaps=card.evaluate("""e=>{
            const r=e.getBoundingClientRect(), a=e.firstElementChild.getBoundingClientRect(), b=e.lastElementChild.getBoundingClientRect(), s=getComputedStyle(e);
            return {top:a.top-r.top,bottom:r.bottom-b.bottom,expectedTop:parseFloat(s.paddingTop)+parseFloat(s.borderTopWidth),expectedBottom:parseFloat(s.paddingBottom)+parseFloat(s.borderBottomWidth),overflow:e.scrollWidth>e.clientWidth+1};
        }""")
        assert not gaps["overflow"] and abs(gaps["top"]-gaps["expectedTop"])<1 and abs(gaps["bottom"]-gaps["expectedBottom"])<1,(name,width,i,gaps)
        assert not card.locator(".cta-micro,.cta-micro-text").count()
        if width in (390,768,1440):
            card.screenshot(path=str(out/f"home_approved_panel_{name}_{i+1}_{width}.png"),animations="disabled")
