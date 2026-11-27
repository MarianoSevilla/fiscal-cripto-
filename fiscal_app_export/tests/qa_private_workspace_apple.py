"""Isolated private workspace UI: actual data contracts, synthetic records only."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from qa_home_redesign import WIDTHS,context
from qa_advisory_apple import styles
DATE="2026-06-01T10:00:00Z"
ADVISORY={"id":1,"full_name":"Persona ficticia","email":"persona@example.invalid","status":"submitted","status_label":"Solicitud recibida","service_label":"Asesoramiento fiscal","service_type":"fiscal","tax_year":2025,"created_at":DATE,"updated_at":DATE,"amount_paid":0,"notes":[],"history":[],"operation_types":[],"current_situation":[],"is_test":True}
CONTACT={"id":1,"nombre":"Contacto ficticio","email":"contacto@example.invalid","email_mask":"c***@example.invalid","estado":"nuevo","tipo_consulta":"general","created_at":DATE,"mensaje_corto":"Consulta de prueba","archived_at":None}
RESOURCE={"id":1,"name":"Recurso ficticio","email":"recurso@example.invalid","status":"pending","status_label":"Pendiente","resource_title":"Guía de prueba","created_at":DATE,"marketing_consent":False}
STATS={"usuarios":{"total":0,"ratio_activacion":0,"por_mes":[],"verificados":0,"sin_verificar":0,"activos_30d":0,"con_informes":0,"sin_informes":0,"free":0,"pro":0},
       "informes":{"generados":0,"fallidos":0,"total":0,"descargados":0,"tasa_descarga":0,"por_mes":[],"por_exchange":[],"por_ejercicio":[],"por_volumen":[],"por_exchange_volumen":[],"power_1k":0,"power_10k":0,"avg_per_user":0,"avg_csv_rows":0,"top_usuarios":[],"avg_processing_ms":0,"por_error_type":[]},
       "contactos":{"total":0,"nuevos":0,"respondidos":0,"por_tipo":[]},
       "asesoramiento":{"total":0,"pagadas":0,"pendientes_pago":0,"sin_asignar":0,"ingresos_total_eur":0,"ingresos_por_mes":[],"por_estado":[],"ingresos_por_servicio":[]},
       "errores":{"por_mes":[],"processing_errors":[]},"meta":{"usuarios_hoy":0,"informes_hoy":0,"errores_24h":0}}
FIXTURES={
 "/api/asesoramiento/mis-solicitudes":[ADVISORY],
 "/api/admin/asesoramiento/solicitudes":[ADVISORY],
 "/api/admin/asesoramiento/solicitudes/1":ADVISORY,
 "/api/admin/contactos":[CONTACT],
 "/api/admin/recursos/solicitudes":[RESOURCE],
 "/api/admin/recursos/solicitudes/1":RESOURCE,
 "/api/admin/comunicaciones/campaigns":[],
 "/api/admin/comunicaciones/recipients/counts":{"all":0,"verified":0,"unverified":0,"individual":0},
 "/api/stats":STATS,
}
PAGES=("mis-solicitudes-fiscales","admin-asesoramiento","admin-contactos","admin-recursos","admin-comunicaciones","stats")
def run_private_workspace_apple(browser,origin):
    out=Path("qa-artifacts");out.mkdir(exist_ok=True)
    for width in WIDTHS:
        ctx,violations=context(browser,role="admin",width=width,height=900)
        ref=ctx.new_page()
        assert ref.goto(origin+"/como-funciona",wait_until="networkidle").status==200
        for name in PAGES:
            page=ctx.new_page();errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            def mock(route):
                u=urlsplit(route.request.url)
                if u.hostname!="127.0.0.1" or route.request.method!="GET" or u.path not in FIXTURES:
                    violations.append(route.request.method+" "+u.path);route.abort();return
                route.fulfill(status=200,content_type="application/json",body=json.dumps(FIXTURES[u.path]))
            for path in FIXTURES: page.route("**"+path+"*",mock)
            assert page.goto(origin+"/static/"+name+".html",wait_until="networkidle").status==200
            for sel,props in [(".how-intro",["background-color","padding-top","padding-bottom"]),(".how-intro h1",["font-size","line-height","font-weight","letter-spacing","width","max-width","text-wrap"]),(".how-intro .apple-container",["width","padding-left","padding-right"]),("#site-nav",["background-color","position","min-height"]),(".apple-footer",["background-color","padding-top","padding-bottom"])]:
                assert styles(page,sel,props)==styles(ref,sel,props),(name,width,sel)
            assert page.locator("h1").count()==1
            if name=="mis-solicitudes-fiscales":
                page.locator(".request-card").wait_for()
                assert page.locator(".preview-banner").is_visible()
            elif name in ("admin-asesoramiento","admin-contactos","admin-recursos"):
                page.locator(".request-item").first.click()
                page.locator(".detail-name").wait_for()
                assert "fictici" in page.locator(".detail-name").inner_text().lower()
            elif name=="admin-comunicaciones":
                page.locator(".btn-new").click()
                assert page.locator(".composer-panel").is_visible()
            else:
                page.locator("#content").wait_for(state="visible")
                assert page.locator("#kpiUsuariosHoy").inner_text()=="0"
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1"),(name,width,"overflow")
            for b in page.locator(".action-btn,.btn-new,.card-cta").all():
                if b.is_visible():
                    assert b.evaluate("e=>getComputedStyle(e).borderRadius")=="999px",(name,width)
                    assert b.evaluate("e=>parseFloat(getComputedStyle(e).minHeight)")>=48,(name,width)
            assert not errors and not violations,(name,width,errors,violations)
            if width in (390,768,1440):
                page.evaluate("window.scrollTo(0,0)")
                page.screenshot(path=str(out/f"home_private_{name}_{width}.png"),full_page=True,animations="disabled")
            page.close()
        ctx.close()
    print(f"PRIVATE_WORKSPACE_APPLE: PASS ({len(PAGES)} pages × {len(WIDTHS)} widths; synthetic records and no writes)")
