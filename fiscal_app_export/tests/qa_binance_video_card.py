"""Binance tutorial presentation at three viewports; no external navigation or writes."""
import json
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

WIDTHS = (375, 768, 1440)
VIDEO_URL = "https://www.youtube.com/watch?v=VabS6OsZ-1E"


def run_binance_video_card(origin, cookie_name, cookie_value):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in WIDTHS:
                context = browser.new_context(viewport={"width": width, "height": 900})
                context.add_cookies([{
                    "name": cookie_name, "value": cookie_value, "url": origin,
                    "httpOnly": True, "sameSite": "Lax",
                }])
                errors, forbidden = [], []

                def guard(route):
                    uri = urlsplit(route.request.url)
                    if uri.hostname != "127.0.0.1":
                        forbidden.append(("external", uri.hostname))
                        route.abort()
                    elif uri.path == "/api/me":
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps({"user": {
                                          "full_name": "Usuario sintético",
                                          "email": "test-video@example.invalid",
                                          "is_admin": False, "is_fiscal_advisor": False,
                                          "plan": "free",
                                      }}))
                    elif route.request.method != "GET":
                        forbidden.append((route.request.method, uri.path))
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", guard)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                try:
                    res = page.goto(origin + "/binance", wait_until="networkidle")
                    assert res and res.status == 200, ("binance", width)
                    assert page.locator(".how-to-card").count() == 3
                    card = page.locator(".tool-video")
                    assert card.count() == 1 and card.is_visible()
                    assert card.locator(".tool-video-mark svg").count() == 1
                    assert card.locator(".tool-video-eyebrow").is_visible()
                    assert "Binance" in card.locator("h3").inner_text()
                    link = card.locator(".tool-video-link")
                    assert link.is_visible()
                    assert link.get_attribute("href") == VIDEO_URL
                    assert link.get_attribute("target") == "_blank"
                    assert "noopener" in link.get_attribute("rel")
                    assert link.evaluate("(el) => el.getBoundingClientRect().height >= 44")
                    assert card.evaluate("""el => {
                        const r = el.getBoundingClientRect();
                        return r.left >= -1 && r.right <= innerWidth + 1;
                    }"""), ("binance", width, "card overflowing viewport")
                    assert page.evaluate(
                        "() => document.documentElement.scrollWidth <= innerWidth + 1"
                    ), ("binance", width, "horizontal overflow")
                    assert card.evaluate("""el => {
                        const s = getComputedStyle(el);
                        return s.borderTopColor === 'rgb(185, 216, 203)' &&
                               s.borderTopLeftRadius === '16px';
                    }"""), (width, "resources card styling")
                    if width == 375:
                        assert card.evaluate(
                            "el => getComputedStyle(el).flexDirection === 'column'"
                        )
                    if width == 1440:
                        assert card.evaluate(
                            "el => getComputedStyle(el).flexDirection === 'row'"
                        )
                    alias = page.goto(origin + "/binance-v2", wait_until="networkidle")
                    assert alias and alias.status == 200
                    assert page.locator(".tool-video-link").get_attribute("href") == VIDEO_URL
                    other = page.goto(origin + "/bitvavo", wait_until="networkidle")
                    assert other and other.status == 200
                    assert page.locator(".tool-video").count() == 0
                    assert not errors and not forbidden, (width, errors, forbidden)
                finally:
                    context.close()
        finally:
            browser.close()
    print("BINANCE_VIDEO_CARD: PASS (375, 768, 1440; live Flask/Chromium; no writes)")
