"""Smoke test read-only against the isolated public Railway staging URL.

Only HTTP GET and browser navigation. No accounts, secrets, mail, payments,
uploads, writes, or production requests. Run from GitHub Actions runner.
"""
import os
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

OUT = Path("staging-smoke-artifacts")


def main():
    target = os.environ.get("STAGING_URL", "").rstrip("/")
    parsed = urlparse(target)
    assert parsed.scheme == "https"
    assert parsed.hostname == "fiscal-cripto-staging-staging.up.railway.app", (
        "Refusing to target any other host"
    )

    session = requests.Session()
    for route in ("/", "/como-funciona", "/faq"):
        response = session.get(target + route, timeout=18, allow_redirects=False)
        assert response.status_code == 200, (route, response.status_code)
        assert "text/html" in response.headers.get("Content-Type", "")
        print(f"HTTP GET {route}: 200 PASS")

    who = session.get(target + "/api/me", timeout=18)
    assert who.status_code == 200, who.status_code
    assert who.json().get("user") is None
    print("HTTP /api/me: unauthenticated PASS")

    # Redirect should not expose an authenticated admin page.
    protected = session.get(target + "/stats", timeout=18, allow_redirects=False)
    assert protected.status_code in (302, 303), protected.status_code
    assert "/login" in protected.headers.get("Location", "")
    print("HTTP /stats: login required PASS")

    OUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in (320, 375, 1280):
                page = browser.new_page(
                    viewport={"width": width, "height": 812},
                    device_scale_factor=1,
                )
                # Do not load third-party assets or decorative images.
                def route_request(route):
                    request = route.request
                    if (
                        urlparse(request.url).hostname != parsed.hostname
                        or request.resource_type in ("image", "font", "media")
                    ):
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/*", route_request)
                page.set_default_timeout(12000)
                try:
                    response = page.goto(target + "/", wait_until="domcontentloaded")
                    assert response and response.status == 200
                    # La sesión se hidrata con /api/me después del DOMContentLoaded.
                    page.locator("#snavSkeleton.snav-hidden").wait_for(state="attached")
                    toggle = page.locator("#snavMenuToggle")
                    assert toggle.is_visible() == (width <= 1200), width
                    if width <= 1200:
                        toggle.click()
                        panel = page.locator("#snavMobileMenu")
                        assert panel.is_visible()
                        assert panel.locator('a[href="/faq"]').is_visible()
                        assert panel.locator('a[href="/signup/"]').is_visible()
                        page.keyboard.press("Escape")
                        assert not panel.is_visible()
                    else:
                        assert page.locator(".snav-links").is_visible()

                    width_metrics = page.evaluate("""() => ({
                      viewport:document.documentElement.clientWidth,
                      content:document.documentElement.scrollWidth,
                      body:document.body.scrollWidth
                    })""")
                    assert width_metrics["content"] <= width + 1, (
                        width, width_metrics
                    )
                    page.screenshot(
                        path=str(OUT / f"staging_home_{width}px.png"),
                        full_page=True, animations="disabled"
                    )
                    print(f"Browser staging {width}px PASS")
                finally:
                    page.close()
        finally:
            browser.close()

    print("Staging HTTPS, anonymous API, auth redirect and responsive PASS")


if __name__ == "__main__":
    main()
