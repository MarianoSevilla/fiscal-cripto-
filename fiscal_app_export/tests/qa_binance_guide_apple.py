"""04-B1: public Binance editorial guide — Apple style, SEO, navigation and layout."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

WIDTHS = (375, 768, 1440)
URL = "/exchanges/binance"


def run_binance_guide_apple(origin, cookie_name, cookie_value):
    output = Path("qa-artifacts")
    output.mkdir(exist_ok=True)
    passed = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in WIDTHS:
                ctx = browser.new_context(viewport={"width": width, "height": 900})
                ctx.add_cookies([{
                    "name": cookie_name, "value": cookie_value, "url": origin,
                    "httpOnly": True, "sameSite": "Lax",
                }])
                blocked_external, unexpected_writes, errors = [], [], []

                def guard(route):
                    uri = urlsplit(route.request.url)
                    if uri.hostname != "127.0.0.1":
                        blocked_external.append(uri.hostname)
                        route.abort()
                    elif uri.path == "/api/me":
                        route.fulfill(
                            status=200,
                            content_type="application/json",
                            body=json.dumps({"user": {
                                "full_name": "Persona simulada",
                                "email": "simulada@example.invalid",
                                "is_admin": False, "is_fiscal_advisor": False,
                            }})
                        )
                    elif route.request.method != "GET" or uri.path.startswith("/api/"):
                        unexpected_writes.append((route.request.method, uri.path))
                        route.abort()
                    else:
                        route.continue_()

                ctx.route("**/*", guard)
                page = ctx.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                try:
                    resp = page.goto(origin + URL, wait_until="networkidle")
                    assert resp and resp.status == 200, (width, "HTTP")
                    assert page.locator("body").get_attribute("class") == (
                        "apple-home apple-exchange-guide apple-guide-binance"
                    )
                    assert page.locator("main#contenido").count() == 1
                    assert page.locator(".apple-skip[href='#contenido']").count() == 1
                    assert page.locator("#site-nav").is_visible()
                    assert page.locator('#site-nav a[href="/herramientas"]').count() >= 1
                    assert page.locator("#site-nav .snav-logo").is_visible()
                    assert page.locator('link[href="/static/nav.css"]').count() == 1
                    assert page.locator('link[href="/static/landing_apple.css"]').count() == 1
                    assert page.locator('link[href="/static/exchange_guide_apple.css"]').count() == 1
                    assert page.locator('link[href*="fonts.googleapis.com"]').count() == 0

                    # Metadata editorial SEO: noindex/canonical/OG/LD+JSON untouched.
                    assert page.title() == (
                        "Declarar Binance en Hacienda: CSV, FIFO e informe fiscal"
                    )
                    assert page.locator('meta[name="robots"]').get_attribute("content") == (
                        "index, follow"
                    )
                    assert page.locator('link[rel="canonical"]').get_attribute("href") == (
                        "https://marianosevilla.com/exchanges/binance"
                    )
                    assert page.locator('meta[property="og:url"]').get_attribute("content") == (
                        "https://marianosevilla.com/exchanges/binance"
                    )
                    graph = json.loads(
                        page.locator('script[type="application/ld+json"]').text_content()
                    )["@graph"]
                    kinds = {node["@type"]: node for node in graph}
                    assert set(kinds) == {"BreadcrumbList", "Article", "HowTo", "FAQPage"}
                    assert len(kinds["HowTo"]["step"]) == 6
                    assert len(kinds["FAQPage"]["mainEntity"]) == 6
                    assert kinds["Article"]["datePublished"] == "2026-06-05"
                    assert "Rafael Ramos Martínez" == kinds["Article"]["author"]["name"]

                    h1 = page.locator(".hero h1")
                    assert h1.count() == 1
                    assert "Binance" in h1.inner_text()
                    assert "FIFO" in h1.inner_text()
                    assert page.locator(".hero").evaluate(
                        "el => getComputedStyle(el).backgroundColor"
                    ) == "rgb(7, 60, 50)"
                    assert page.locator("body").evaluate(
                        "el => getComputedStyle(el).backgroundColor"
                    ) == "rgb(255, 255, 255)"
                    badge_left = page.locator(".hero-badge").evaluate(
                        "el => el.getBoundingClientRect().left"
                    )
                    title_left = h1.evaluate(
                        "el => el.getBoundingClientRect().left"
                    )
                    assert abs(badge_left - title_left) <= 1, (
                        width, "heading alignment", badge_left, title_left
                    )

                    # Preserve editorial components and four CTAs to the same FIFO tool.
                    assert page.locator(".steps-list > li").count() == 6
                    assert page.locator(".files-table tbody tr").count() == 4
                    assert page.locator(".error-card").count() == 3
                    assert page.locator(".faq-item").count() == 6
                    assert page.locator('a[href="/binance"]').count() == 4
                    assert page.locator(
                        '.cta-final a[href="/asesoramiento-fiscal-criptomonedas"]'
                    ).count() == 1
                    assert page.locator('.content-main a[href="/exchanges/bitvavo"]').count() >= 1
                    assert page.locator('a[href="/modelo-721-criptomonedas"]').count() >= 1
                    assert page.locator('a[href="/privacidad"]').count() == 1
                    # 04-A1: el hero verde contiene solo textos editoriales;
                    # el bloque CTA está en el área blanca anterior al artículo.
                    assert page.locator(".hero .asistencia-block").count() == 0
                    assert page.locator(".content-main > .asistencia-block").count() == 1
                    assert page.locator(".content-main > .asistencia-block").is_visible()
                    assert page.locator(".hero .hero-desc").count() == 1
                    assert page.locator(".content-main > .asistencia-block").evaluate(
                        "el => el.getBoundingClientRect().top >= "
                        "document.querySelector('.hero').getBoundingClientRect().bottom"
                    ), (width, "CTA dentro de franja verde")
                    assert page.locator(".content-main > .asistencia-block").evaluate(
                        "el => getComputedStyle(el).backgroundColor"
                    ) == "rgb(245, 248, 246)"
                    assert page.locator('.content-main > .asistencia-block .btn-asistencia').evaluate(
                        "el => getComputedStyle(el).color"
                    ) == "rgb(255, 255, 255)"

                    page.locator(".faq-item summary").first.click()
                    assert page.locator(".faq-item").first.get_attribute("open") is not None
                    assert page.locator(".faq-item .faq-a").first.is_visible()
                    if width <= 768:
                        assert page.locator("#snavMenuToggle").is_visible()
                        page.locator("#snavMenuToggle").click()
                        assert page.locator("#snavMobileMenu").is_visible()
                        page.locator("#snavMenuToggle").click()

                    # Diagnóstico de desbordamiento: registrar los elementos exactos
                    # sin enmascarar un posible error de diseño con overflow-x:hidden.
                    overflow = page.evaluate("""() => {
                        const root = document.documentElement;
                        const vw = innerWidth;
                        const elems = [...document.querySelectorAll('body *')];
                        const offenders = elems.map(el => {
                            const r = el.getBoundingClientRect();
                            const cs = getComputedStyle(el);
                            return {tag: el.tagName, cls: String(el.className).slice(0,90),
                                right: Math.round(r.right), left: Math.round(r.left),
                                width: Math.round(r.width), scroll: el.scrollWidth,
                                client: el.clientWidth, overflowX: cs.overflowX};
                        }).filter(x => x.right > vw + 1 && x.width > 0)
                          .sort((a,b) => b.right - a.right).slice(0,22);
                        return {viewport: vw, document: root.scrollWidth,
                                body: document.body.scrollWidth, offenders};
                    }""")
                    if overflow["document"] > width + 1:
                        print("BITVAVO_GUIDE_OVERFLOW_DIAGNOSTIC:",
                              json.dumps(overflow, ensure_ascii=False), flush=True)
                    assert overflow["document"] <= width + 1, (
                        width, "document horizontal overflow", overflow
                    )
                    legal_links = page.locator(".legal-bar-links")
                    assert legal_links.evaluate(
                        "el => el.getBoundingClientRect().right <= innerWidth + 1"
                    ), (width, "footer legal links overflow")
                    if width == 375:
                        assert page.locator(".files-table-wrap").evaluate(
                            "el => el.scrollWidth > el.clientWidth"
                        ), "Table should scroll inside its wrapper, not expand the page"
                    assert not blocked_external and not unexpected_writes and not errors, (
                        width, blocked_external, unexpected_writes, errors
                    )
                    page.screenshot(
                        path=str(output / f"guide_binance_apple_{width}.png"),
                        full_page=True
                    )
                    passed += 1
                    print("BINANCE_GUIDE_04B1:", width, "PASS", flush=True)
                finally:
                    ctx.close()
        finally:
            browser.close()

    assert passed == len(WIDTHS)
    print("BINANCE_GUIDE_04B1: PASS (3 responsive viewports, SEO, 6 steps, "
          "4 CSV rows, 6 FAQ, navigation, 4 conversion links; no fiscal API calls)")
