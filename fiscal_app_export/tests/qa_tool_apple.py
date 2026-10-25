"""02-A. Chromium/Flask UI regression for all 11 shared FIFO pages.

All content is fictitious. Analysis, year-detection and PDF download requests
are fulfilled in the browser; no parser, tax engine, provider or real record is
called or written. The server is the temporary SQLite Flask fixture.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import expect, sync_playwright

TOOLS = ("fiscal", "bitvavo", "bit2me", "kraken", "coinbase", "nexo",
         "cryptocom", "uphold", "mexc", "bitget", "kucoin")
WIDTHS = (375, 768, 1440)
MULTI = {"bitget", "kucoin"}
RESULT = {
    "ok": True,
    "token": "synthetic-ui-token",
    "operaciones": [
        {"fecha": "2025-03-04", "tipo": "venta", "activo": "BTC",
         "cantidad": 0.5, "transmision": 1500.0, "coste_fifo": 1000.0,
         "ganancia_perdida": 500.0, "periodo_dias": 63},
        {"fecha": "2024-04-11", "tipo": "venta", "activo": "ETH",
         "cantidad": 1.0, "transmision": 500.0, "coste_fifo": 600.0,
         "ganancia_perdida": -100.0, "periodo_dias": 12}
    ],
    "posicion": [
        {"activo": "BTC", "cantidad": 0.25, "precio_medio": 1000.0,
         "coste_total": 250.0}
    ],
    "rendimientos": [
        {"subtipo": "staking", "activo": "ETH", "operaciones": 1,
         "cantidad": 0.04, "valor_eur": 85.0}
    ],
    "advertencias": ["Ejemplo sintético: revisar documentación de origen"]
}


def run_tool_apple(origin, cookie_name, cookie_value):
    output = Path("qa-artifacts")
    output.mkdir(exist_ok=True)
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for name in TOOLS:
                for width in WIDTHS:
                    ctx = browser.new_context(
                        viewport={"width": width, "height": 900}, accept_downloads=True
                    )
                    ctx.add_cookies([{"name": cookie_name, "value": cookie_value,
                                     "url": origin, "httpOnly": True, "sameSite": "Lax"}])
                    writes = []
                    violations = []
                    errors = []
                    analysis_attempt = [0]
                    first_error = width == 375

                    def guard(route):
                        req = route.request
                        uri = urlsplit(req.url)
                        if uri.hostname != "127.0.0.1":
                            violations.append("external " + uri.hostname)
                            route.abort()
                            return
                        if uri.path == "/api/me":
                            route.fulfill(status=200, content_type="application/json",
                                          body=json.dumps({"user": {
                                              "full_name": "Persona ficticia",
                                              "email": "persona@example.invalid",
                                              "is_admin": False,
                                              "is_fiscal_advisor": False,
                                              "plan": "free"
                                          }}))
                            return
                        if uri.path.startswith("/api/descargar/"):
                            violations.append("unexpected download GET " + uri.path)
                            route.abort()
                            return
                        if req.method != "GET":
                            writes.append((req.method, uri.path,
                                           req.post_data or ""))
                            if uri.path.endswith("/anos"):
                                route.fulfill(status=200, content_type="application/json",
                                              body=json.dumps({"ok": True, "anos": [2024, 2025],
                                                               "resumen": {}, "advertencias": []}))
                                return
                            if uri.path == "/api/analizar" or (
                                name in MULTI and uri.path == "/api/" + name + "/analizar"
                            ):
                                analysis_attempt[0] += 1
                                if first_error and analysis_attempt[0] == 1:
                                    route.fulfill(status=422, content_type="application/json",
                                                  body='{"ok":false,"error":"Datos fiscales no seguros: historial incompleto"}')
                                else:
                                    route.fulfill(status=200, content_type="application/json",
                                                  body=json.dumps(RESULT))
                                return
                            violations.append("unexpected POST " + uri.path)
                            route.abort()
                            return
                        if uri.path.startswith("/api/"):
                            violations.append("unexpected API GET " + uri.path)
                            route.abort()
                            return
                        route.continue_()

                    ctx.route("**/*", guard)
                    page = ctx.new_page()
                    page.on("pageerror", lambda exc: errors.append(str(exc)))
                    # Expected 422 on a mocked import is a browser HTTP console
                    # warning, not a JS exception. All other errors are retained.
                    page.on("console", lambda msg: errors.append(msg.text)
                            if msg.type == "error" and not (
                                first_error and "422" in msg.text
                                and "Failed to load resource" in msg.text
                            ) else None)
                    try:
                        response = page.goto(origin + "/" + name, wait_until="networkidle")
                        assert response and response.status == 200, (name, width, response.status if response else None)
                        assert page.locator("body").get_attribute("class") == "apple-home apple-tool"
                        assert page.locator("#site-nav").is_visible()
                        assert page.locator("main#contenido").count() == 1
                        assert page.locator("h1").count() == 1
                        assert page.locator("#emptyState").is_visible()
                        assert not page.locator("#resultsContent").is_visible()
                        assert page.locator("#btnAnalizar").is_disabled()
                        assert page.locator('link[href="/static/tool_apple.css"]').count() == 1
                        assert page.locator('link[href="/static/landing_apple.css"]').count() == 1
                        assert page.locator('link[href*="fonts.googleapis.com"]').count() == 0
                        assert page.locator('a[href="/dashboard"]').count() >= (0 if name == "fiscal" else 1)
                        assert page.locator('footer a[href="/privacidad"]').count() == 1
                        assert page.locator('footer a[href="/terminos"]').count() == 1
                        assert page.locator('meta[name="robots"]').count() == 1
                        assert page.locator("#nombre").input_value() == "Persona ficticia"
                        # No sustituir las instrucciones de estos exchanges por
                        # la cadena por defecto de Binance al cargar el DOM.
                        if name in ("nexo", "uphold", "kucoin"):
                            hint = page.locator("#dropHint").inner_text().lower()
                            assert name in hint, (name, width, hint)
                            assert "binance" not in hint, (name, width, hint)
                        assert page.locator("#csvInput").evaluate(
                            "e => parseFloat(getComputedStyle(e).fontSize)"
                        ) >= 16 or page.locator("#csvInput").evaluate(
                            "e => getComputedStyle(e).opacity"
                        ) == "0"

                        picker = page.locator("#csvInput")
                        accept = picker.get_attribute("accept")
                        assert (".xlsx" in accept) == (name == "mexc" or (
                            name == "bit2me" and "true" in page.evaluate("String(BIT2ME_EXCEL_ENABLED)")
                        )), (name, accept)
                        assert (picker.get_attribute("multiple") is not None) == (name in MULTI)

                        if width == 375:
                            bad_filename = "incorrect.csv" if name == "mexc" else "incorrect.txt"
                            picker.set_input_files({"name": bad_filename, "mimeType": "text/plain",
                                                    "buffer": b"invalid format"})
                            assert "fichero" in page.locator("#dropHint").inner_text().lower() or (
                                "aceptan" in page.locator("#dropHint").inner_text().lower()
                            )
                            assert page.locator("#btnAnalizar").is_disabled()

                        def attach_valid():
                            if name == "mexc":
                                inputs = [{"name": "sample.xlsx", "mimeType": "application/octet-stream",
                                           "buffer": b"synthetic excel bytes"}]
                            else:
                                count = 2 if name in MULTI else 1
                                inputs = [
                                    {"name": f"sample_{i}.csv", "mimeType": "text/csv",
                                     "buffer": b"fecha,activo,valor\n2024-03-01,BTC,1\n2025-03-04,BTC,2"}
                                    for i in range(count)
                                ]
                            count = len(inputs)
                            picker.set_input_files(inputs)
                            page.locator("#btnAnalizar").wait_for(state="visible")
                            expect(page.locator("#btnAnalizar")).to_be_enabled(timeout=12000)
                            assert page.locator("#year-chips-wrap").is_visible()
                            assert page.locator('.year-chip[data-year="2025"]').count() == 1
                            return count

                        count = attach_valid()
                        if width == 375:
                            assert page.locator("#fileSelected").is_visible()
                        page.locator("#btnAnalizar").click()
                        if first_error:
                            page.locator("#errorState").wait_for(state="visible")
                            assert page.locator("#btnRetry").is_visible()
                            page.locator("#btnRetry").click()
                            assert page.locator("#emptyState").is_visible()
                            count = attach_valid()
                            page.locator("#btnAnalizar").click()
                        page.locator("#resultsContent").wait_for(state="visible")
                        assert page.locator("#kpiOps").inner_text() == "2"
                        assert page.locator("#tbodyOps tr").count() == 2
                        assert page.locator("#btnDownload").is_visible()
                        assert page.locator("#btnDownload").get_attribute("href") == (
                            "/api/descargar/synthetic-ui-token?exchange=" +
                            ("binance" if name == "fiscal" else name)
                        )
                        path_expected = ("/api/" + name + "/analizar"
                                         if name in MULTI else "/api/analizar")
                        analysis = [x for x in writes if x[1] == path_expected]
                        assert len(analysis) == (2 if first_error else 1), (name, width, writes)
                        assert analysis[-1][2].count('name="csv"') == count
                        if name not in MULTI:
                            assert 'name="exchange"' in analysis[-1][2]
                        assert 'name="ejercicio"' in analysis[-1][2]
                        for tab in ("activos", "posicion", "rendimientos", "advertencias"):
                            button = page.locator(f'[data-tab="{tab}"]')
                            button.click()
                            assert button.get_attribute("aria-selected") == "true"
                            assert page.locator("#tab-" + tab).is_visible()
                        assert "Ejemplo sintético" in page.locator("#warnContainer").inner_text()
                        page.locator('[data-tab="operaciones"]').focus()
                        page.keyboard.press("ArrowRight")
                        assert page.locator('[data-tab="activos"]').get_attribute("aria-selected") == "true"
                        if width == 375:
                            # Verificar la acción sin cursar siquiera un GET a la
                            # ruta de descarga: Playwright/Chromium puede iniciar
                            # downloads sin notificar las rutas interceptadas.
                            page.evaluate("""() => {
                                const link = document.getElementById('btnDownload');
                                link.addEventListener('click', e => {
                                    e.preventDefault();
                                    window.__syntheticDownloadClicked = link.getAttribute('href');
                                }, {once:true});
                            }""")
                            page.locator("#btnDownload").click()
                            assert page.evaluate("window.__syntheticDownloadClicked") == (
                                "/api/descargar/synthetic-ui-token?exchange=" +
                                ("binance" if name == "fiscal" else name)
                            )
                            assert page.locator("#btnDownload").get_attribute(
                                "download"
                            ).endswith(".pdf")
                        page.screenshot(path=str(output / f"home_fifo_{name}_{width}.png"), full_page=True)
                        assert page.evaluate("""() => document.documentElement.scrollWidth <= innerWidth + 1"""), (name,width,"page overflow")
                        assert page.locator(".upload-bar").evaluate(
                            "(e) => e.getBoundingClientRect().right <= innerWidth + 1"
                        ), (name,width,"upload overflow")
                        assert not violations and not errors,(name,width,violations,errors)
                        results.append((name,width,"PASS",len(analysis),count))
                    finally:
                        ctx.close()
        finally:
            browser.close()
    assert len(results) == 33, results
    for name in TOOLS:
        each = [x for x in results if x[0] == name]
        assert len(each) == 3
        print("FIFO_TOOL_02A:", name, "PASS", [x[1] for x in each], "mocked API", flush=True)
    print("FIFO_TOOL_02A: PASS (33 route/viewport scenarios, 11 routes, synthetic uploads,"
          " synthetic PDF tokens, no actual fiscal calculation or write)")
