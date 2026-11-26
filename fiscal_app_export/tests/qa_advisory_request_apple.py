"""Compare the actual advisory intake with approved Contact in Chromium.
Only synthetic session and request responses; never send real requests.
The existing real Flask C2-R02 E2E suite independently exercises persistence.
"""
import json
from pathlib import Path
from qa_home_redesign import WIDTHS,context,geometry
from qa_advisory_apple import styles
from qa_contacto_apple import open_page

PAGE="/static/pedir-asesoramiento.html"

def run_advisory_request_apple(browser,origin):
    out=Path("qa-artifacts");out.mkdir(exist_ok=True)
    for width in WIDTHS:
        ctx,violations=context(browser,width=width,height=900,role="user")
        page=ctx.new_page();errors=[]
        page.on("pageerror",lambda e:errors.append(str(e)))
        requests=[]
        def submit(route):
            req=route.request
            assert req.method=="POST" and req.url==origin+"/api/asesoramiento/solicitar"
            requests.append(req.post_data_json)
            route.fulfill(status=400 if len(requests)==1 else 200,content_type="application/json",
                          body=json.dumps({"error":"Error ficticio de prueba"} if len(requests)==1 else {"ok":True}))
        page.route("**/api/asesoramiento/solicitar",submit)
        assert page.goto(origin+PAGE,wait_until="networkidle").status==200
        page.locator("#submitBtn:enabled").wait_for()
        assert page.locator("#emailField").input_value()=="user@example.invalid"
        assert page.locator("#emailField").get_attribute("readonly") is not None
        ref,ref_errors=open_page(ctx,origin)
        for sel,ref_sel,props in [
            ("body","body",["font-family","font-size","line-height","background-color","color"]),
            ("#site-nav","#site-nav",["background-color","position","min-height"]),
            (".contact-intro",".contact-intro",["background-color"]),
            (".apple-intro-inner",".apple-intro-inner",["padding-top","padding-bottom","padding-left","padding-right","max-width"]),
            ("h1","h1",["font-size","line-height","letter-spacing","font-weight"]),
            (".contact-section",".contact-section",["padding-top","padding-bottom"]),
            (".contact-layout",".contact-layout",["grid-template-columns","gap","max-width","padding-left","padding-right"]),
            (".contact-form-card",".contact-form-card",["padding-top","padding-left","border-radius","border-color","background-color"]),
            ("#fullName","#nombre",["font-family","font-size","min-height","border-radius","border-color","padding-top","padding-left","background-color"]),
            ("#caseDesc","#mensaje",["font-family","font-size","min-height","border-radius","border-color","padding-top","padding-left"]),
            ("#legalPrivacy","#legal",["width","height","accent-color"]),
            ("#submitBtn","#contactSubmit",["font-family","font-size","font-weight","min-height","padding-top","padding-left","border-radius","background-color","color","width"]),
            (".contact-aside",".contact-aside",["grid-template-columns","gap"]),
            (".contact-advice",".contact-advice",["padding-top","border-radius","background-color","border-color"]),
            (".apple-footer",".apple-footer",["background-color","padding-top","padding-bottom"]),
        ]:
            assert styles(page,sel,props)==styles(ref,ref_sel,props),(width,sel,styles(page,sel,props),styles(ref,ref_sel,props))
        assert not geometry(page,width),(width,geometry(page,width))
        if width in (390,1440):
            page.screenshot(path=str(out/f"home_advisory_request_{width}px.png"),full_page=True,animations="disabled")
        page.locator("#fullName").fill("Persona ficticia")
        page.locator("#caseDesc").fill("Caso ficticio sin datos personales ni operaciones reales.")
        page.locator("#submitBtn").click()
        assert page.locator("#errorMsg").is_visible()
        assert "Debes aceptar" in page.locator("#errorMsg").inner_text()
        assert requests==[]
        page.locator("#legalPrivacy").check()
        page.locator("#submitBtn").click()
        page.get_by_text("Error ficticio de prueba",exact=True).wait_for()
        assert page.locator("#submitBtn").is_enabled()
        assert page.locator("#caseDesc").input_value()=="Caso ficticio sin datos personales ni operaciones reales."
        page.locator("#submitBtn").click()
        page.locator("#successMsg").wait_for()
        assert not page.locator("#advisoryForm").is_visible()
        assert "No hemos generado ningún presupuesto" in page.locator("#successMsg").inner_text()
        assert len(requests)==2 and requests[0]==requests[1]
        assert requests[0]["email"]=="user@example.invalid"
        assert requests[0]["phone"] is None
        assert requests[0]["service_type"]=="presupuesto_personalizado"
        assert requests[0]["tax_residence_country"]=="España"
        assert requests[0]["operation_types"]==requests[0]["current_situation"]==[]
        assert not geometry(page,width),(width,geometry(page,width))
        assert not errors and not ref_errors and not violations,(width,errors,ref_errors,violations)
        ctx.close()
    for width in (390,1280):
        ctx,violations=context(browser,width=width,js=False)
        page=ctx.new_page();assert page.goto(origin+PAGE).status==200
        assert page.locator("#submitBtn").is_disabled()
        assert page.locator("#fullName").is_disabled()
        assert page.locator("#requestBootNotice").is_visible()
        assert not geometry(page,width) and not violations
        ctx.close()
    print(f"ADVISORY_REQUEST_APPLE_QA: PASS ({len(WIDTHS)} widths + no-JS cases)")
