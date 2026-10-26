"""03-A: Modelo 721 Apple UI, against isolated real Flask + synthetic browser inputs."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

WIDTHS = (375, 768, 1440)


def run_modelo721_apple(origin, cookie_name, cookie_value):
    output = Path("qa-artifacts")
    output.mkdir(exist_ok=True)
    scenarios = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in WIDTHS:
                ctx = browser.new_context(viewport={"width": width, "height": 900})
                ctx.add_cookies([{
                    "name": cookie_name, "value": cookie_value, "url": origin,
                    "httpOnly": True, "sameSite": "Lax",
                }])
                external = []
                unexpected = []
                errors = []
                mocked_posts = []

                def guard(route):
                    uri = urlsplit(route.request.url)
                    if uri.hostname != "127.0.0.1":
                        external.append(uri.hostname or "")
                        route.abort()
                        return
                    if uri.path == "/api/me":
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps({"user": {
                                          "full_name": "Persona simulada",
                                          "email": "ejemplo@example.invalid",
                                          "is_admin": False, "is_fiscal_advisor": False,
                                      }}))
                        return
                    if uri.path == "/api/721" and route.request.method == "POST":
                        mocked_posts.append(uri.path)
                        route.fulfill(status=422, content_type="application/json",
                                      body='{"error":"Historial ficticio incompleto"}')
                        return
                    if route.request.method != "GET" or uri.path.startswith("/api/"):
                        unexpected.append((route.request.method, uri.path))
                        route.abort()
                        return
                    route.continue_()

                ctx.route("**/*", guard)
                page = ctx.new_page()
                page.on("pageerror", lambda err: errors.append(str(err)))
                try:
                    response = page.goto(origin + "/modelo721", wait_until="networkidle")
                    assert response and response.status == 200
                    assert page.locator("body").get_attribute("class") == (
                        "apple-home apple-modelo721"
                    )
                    assert page.locator("main#contenido").count() == 1
                    assert page.locator("h1").inner_text() == "Criptomonedas en el extranjero"
                    assert page.locator('meta[name="robots"]').get_attribute("content") == "noindex"
                    assert page.locator('link[href="/static/landing_apple.css"]').count() == 1
                    assert page.locator('link[href="/static/modelo721_apple.css"]').count() == 1
                    assert page.locator('link[href*="fonts.googleapis.com"]').count() == 0
                    assert page.locator("#site-nav").is_visible()
                    assert page.locator("#panel-form").is_visible()
                    assert not page.locator("#panel-result").is_visible()
                    assert page.locator("#btn-submit").is_disabled()
                    assert page.locator(".m721-hero").evaluate(
                        "el => getComputedStyle(el).backgroundColor"
                    ) == "rgb(7, 60, 50)"
                    assert page.locator("body").evaluate(
                        "el => getComputedStyle(el).backgroundColor"
                    ) == "rgb(247, 249, 248)"
                    badge_left = page.locator(".page-badge").evaluate(
                        "el => el.getBoundingClientRect().left"
                    )
                    title_left = page.locator("h1").evaluate(
                        "el => el.getBoundingClientRect().left"
                    )
                    assert abs(badge_left - title_left) <= 1, (width, badge_left, title_left)
                    assert page.locator("#sel-ejercicio option").count() >= 1
                    assert page.locator("#csv-hint a").get_attribute("href") == (
                        "/privacidad#conservacion"
                    )
                    assert "nunca se almacena" not in page.locator("#csv-hint").inner_text().lower()
                    page.locator("#toggle-declarante").click()
                    assert page.locator("#declarante-fields").is_visible()
                    assert "borrador" in page.locator("#declarante-fields").inner_text().lower()
                    page.locator("#toggle-declarante").click()
                    assert not page.locator("#declarante-fields").is_visible()
                    # Cambio de formato al seleccionar MEXC; no realiza envíos.
                    page.locator("#sel-exchange").select_option("mexc")
                    assert page.locator("#file-input").get_attribute("accept") == ".xlsx,.xls"
                    assert page.locator("#csv-hint a").get_attribute("href") == (
                        "/privacidad#conservacion"
                    )
                    assert "nunca se almacena" not in page.locator("#csv-hint").inner_text().lower()
                    # La opción Bit2Me mantiene la explicación sin consultar el API.
                    page.locator("#sel-exchange").select_option("bit2me")
                    assert page.locator("#bit2me-info").is_visible()
                    assert not page.locator("#card-csv").is_visible()
                    assert page.locator("#btn-submit").inner_text() == "Ver explicación"
                    page.locator("#btn-submit").click()
                    assert page.locator("#panel-result").is_visible()
                    assert page.locator("#estado-texto").text_content().strip() == "No aplica"
                    assert page.locator("#bit2me-result").is_visible()
                    assert not mocked_posts
                    page.locator("#btn-nuevo").click()
                    assert page.locator("#panel-form").is_visible()
                    page.locator("#sel-exchange").select_option("bitvavo")
                    assert page.locator("#file-input").get_attribute("accept") == ".csv,.txt"
                    page.locator("#file-input").set_input_files({
                        "name": "operaciones-ficticias.csv",
                        "mimeType": "text/csv",
                        "buffer": b"fecha,tipo\n2025-01-01,simulada\n",
                    })
                    assert page.locator("#drop-filename").inner_text() == (
                        "operaciones-ficticias.csv"
                    )
                    assert page.locator("#btn-submit").is_enabled()
                    page.locator("#btn-submit").click()
                    page.get_by_role("button", name="Historial ficticio incompleto").wait_for()
                    assert mocked_posts == ["/api/721"]
                    assert page.locator("#panel-form").is_visible()
                    page.screenshot(path=str(output / f"modelo721_apple_{width}.png"),
                                    full_page=True)
                    assert page.evaluate(
                        "() => document.documentElement.scrollWidth <= innerWidth + 1"
                    ), (width, "horizontal overflow")
                    assert not external and not unexpected and not errors, (
                        width, external, unexpected, errors
                    )
                    scenarios += 1
                    print("MODELO721_APPLE_QA:", width, "PASS", flush=True)
                finally:
                    ctx.close()
        finally:
            browser.close()
    assert scenarios == 3
    print("MODELO721_APPLE_QA: PASS (3 viewports, synthetic CSV / 422, "
          "Bit2Me without API, MEXC XLSX, privacy wording, no external I/O)")
