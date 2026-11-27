"""Unsubscribe: synthetic tokens only. POSTs are intercepted, never sent."""
import json
from pathlib import Path
from qa_home_redesign import WIDTHS,context
from qa_advisory_apple import styles
def run_unsubscribe_apple(browser,origin):
    out=Path("qa-artifacts");out.mkdir(exist_ok=True)
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900)
        page=ctx.new_page();ref=ctx.new_page();errors=[];calls=[]
        page.on("pageerror",lambda e:errors.append(str(e)))
        outcome={"ok":False}
        def mock(route):
            assert route.request.method=="POST"
            assert route.request.post_data_json=={"token":"synthetic-token"}
            calls.append(outcome["ok"])
            route.fulfill(status=200,content_type="application/json",body=json.dumps(outcome))
        page.route("**/api/unsubscribe",mock)
        assert ref.goto(origin+"/como-funciona",wait_until="networkidle").status==200
        url=origin+"/static/unsubscribe.html"
        assert page.goto(url,wait_until="networkidle").status==200
        assert page.locator("#state-invalid").is_visible()
        assert not page.locator("#state-confirm").is_visible()
        assert not calls
        for sel,props in [(".how-intro",["background-color","padding-top","padding-bottom"]),(".how-intro h1",["font-size","line-height","font-weight","letter-spacing","width","max-width","text-wrap"]),(".how-intro .apple-container",["width","padding-left","padding-right"]),("#site-nav",["background-color","position","min-height"]),(".apple-footer",["background-color","padding-top","padding-bottom"])]:
            assert styles(page,sel,props)==styles(ref,sel,props),(width,sel)
        assert page.goto(url+"?token=synthetic-token",wait_until="networkidle").status==200
        assert page.locator("#state-confirm").is_visible()
        assert page.locator("#unsub-email").inner_text()=="Tu dirección de email"
        assert not calls
        btn=page.locator("#btn-confirm")
        assert btn.evaluate("e=>getComputedStyle(e).borderRadius")=="999px"
        assert btn.evaluate("e=>getComputedStyle(e).minHeight")=="48px"
        assert btn.evaluate("e=>getComputedStyle(e).color")=="rgb(162, 39, 29)"
        if width in (390,768,1440):
            page.screenshot(path=str(out/f"home_unsubscribe_confirm_{width}.png"),full_page=True,animations="disabled")
        btn.click()
        page.locator("#error-msg").wait_for(state="visible")
        assert btn.is_enabled()
        outcome["ok"]=True
        btn.click()
        page.locator("#state-success").wait_for(state="visible")
        assert not page.locator("#state-confirm").is_visible()
        assert not page.locator("#state-invalid").is_visible()
        assert calls==[False,True]
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),width
        if width in (390,768,1440):
            page.screenshot(path=str(out/f"home_unsubscribe_success_{width}.png"),full_page=True,animations="disabled")
        assert not errors and not violations,(width,errors,violations)
        ctx.close()
    print(f"UNSUBSCRIBE_APPLE: PASS ({len(WIDTHS)} widths; invalid, confirm, simulated failure and success)")
