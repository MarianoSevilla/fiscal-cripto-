"""Prueba opcional de navegación responsive usando Playwright y datos ficticios.

Ejecución (desde la raíz del repositorio):
    python fiscal_app_export/tests/qa_responsive_nav.py

Requiere Playwright/Chromium instalados como herramientas de desarrollo.
Sirve archivos locales por HTTP; no importa Flask, no lee datos de usuario
ni se conecta a Railway o producción. /api/me se simula con usuarios falsos.
"""
import json
import os
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

STATIC = Path(__file__).resolve().parents[1] / "static"
PAGES = {
    "/": "landing.html",
    "/como-funciona": "como-funciona.html",
    "/faq": "faq.html",
    "/privacidad": "privacidad.html",
    "/herramientas": "herramientas.html",
}
WIDTHS = (320, 375, 390, 480, 520, 768, 900, 901, 1024, 1200, 1201, 1280)
MOBILE_MAX = 1200


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/me":
            body = b'{"user":null}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in PAGES:
            self.path = "/" + PAGES[path]
        elif path.startswith("/static/"):
            self.path = path[len("/static"):]
        else:
            self.send_error(404)
            return
        super().do_GET()


@contextmanager
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        worker.join(timeout=3)
        httpd.server_close()


def check_header(page, width):
    positions = page.evaluate("""() => {
      return Object.fromEntries(['.snav-logo','.snav-right','#snavMenuToggle']
        .map(s => { const e=document.querySelector(s), r=e.getBoundingClientRect();
          return [s,{left:r.left,right:r.right,visible:getComputedStyle(e).display!=='none'}];
        }));
    }""")
    for selector, box in positions.items():
        if box["visible"]:
            assert box["left"] >= -1 and box["right"] <= width + 1, (
                f"{width}px: {selector} fuera de pantalla: {box}"
            )
    if width <= MOBILE_MAX:
        assert positions[".snav-logo"]["right"] < positions["#snavMenuToggle"]["left"]
    else:
        links = page.locator(".snav-links").bounding_box()
        right = page.locator(".snav-right").bounding_box()
        assert links and right
        assert links["x"] + links["width"] + 4 <= right["x"], (
            f"{width}px: enlaces solapan los controles de acceso"
        )


def main():
    from playwright.sync_api import sync_playwright

    anonymous = {"user": None}
    admin = {"user": {
        "email": "prueba@example.invalid",
        "full_name": "Usuario de prueba",
        "is_admin": True,
    }}
    launch = {"headless": True}
    if os.environ.get("CHROMIUM_EXECUTABLE"):
        launch["executable_path"] = os.environ["CHROMIUM_EXECUTABLE"]

    total = 0
    with server() as origin, sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        try:
            for route in PAGES:
                for width in WIDTHS:
                    page = browser.new_page(viewport={"width": width, "height": 812})
                    page.set_default_timeout(5000)
                    page.route("https://**/*", lambda r: r.abort())
                    page.route("**/api/me", lambda r: r.fulfill(
                        status=200, content_type="application/json",
                        body=json.dumps(anonymous),
                    ))
                    try:
                        page.goto(origin + route, wait_until="domcontentloaded")
                        page.locator("#snavBtnLogin:not(.snav-hidden)").wait_for(state="attached")
                        toggle = page.locator("#snavMenuToggle")
                        assert toggle.is_visible() == (width <= MOBILE_MAX)
                        check_header(page, width)
                        if width <= MOBILE_MAX:
                            toggle.click()
                            panel = page.locator("#snavMobileMenu")
                            assert toggle.get_attribute("aria-expanded") == "true"
                            assert panel.locator('a[href="/login/"]').is_visible()
                            assert panel.locator('a[href="/signup/"]').is_visible()
                            assert panel.locator('a[href="/faq"]').is_visible()
                            page.keyboard.press("Escape")
                            assert toggle.get_attribute("aria-expanded") == "false"
                            toggle.click()
                            page.mouse.click(width - 5, 800)
                            assert toggle.get_attribute("aria-expanded") == "false"
                        total += 1
                    finally:
                        page.close()

            for width in (320, 375, 768, 1024):
                page = browser.new_page(viewport={"width": width, "height": 812})
                page.set_default_timeout(5000)
                page.route("https://**/*", lambda r: r.abort())
                page.route("**/api/me", lambda r: r.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps(admin),
                ))
                try:
                    page.goto(origin, wait_until="domcontentloaded")
                    page.locator("#snavAvatarWrap:not(.snav-hidden)").wait_for(state="attached")
                    page.locator("#snavMenuToggle").click()
                    panel = page.locator("#snavMobileMenu")
                    assert panel.locator('a[href="/stats"]').is_visible()
                    assert panel.locator('a[href="/admin/asesoramiento"]').is_visible()
                    assert panel.get_by_role("button", name="Cerrar sesión").is_visible()
                    assert panel.locator('a[href="/login/"]').count() == 0
                    total += 1
                finally:
                    page.close()
            # Matriz independiente de permisos visibles en el menú móvil.
            profiles = (
                ("usuario", {"user":{"email":"user@example.invalid",
                    "full_name":"Usuario ficticio","is_admin":False,
                    "is_fiscal_advisor":False}},
                 False, False),
                ("asesor", {"user":{"email":"asesor@example.invalid",
                    "full_name":"Asesor ficticio","is_admin":False,
                    "is_fiscal_advisor":True}},
                 True, False),
                ("administrador", admin, True, True),
            )
            for role, payload, has_advisory, has_stats in profiles:
                for width in (320, 390, 768, 1200):
                    page = browser.new_page(viewport={"width":width,"height":812})
                    page.set_default_timeout(5000)
                    page.route("https://**/*", lambda r: r.abort())
                    def fake_auth(route):
                        route.fulfill(
                            status=200, content_type="application/json",
                            body=json.dumps(payload),
                        )
                    page.route("**/api/me", fake_auth)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    try:
                        page.goto(origin,wait_until="domcontentloaded")
                        page.locator("#snavAvatarWrap:not(.snav-hidden)").wait_for(state="attached")
                        toggle = page.locator("#snavMenuToggle")
                        toggle.click()
                        menu = page.locator("#snavMobileMenu")
                        assert menu.is_visible(), (role,width)
                        assert menu.locator('a[href="/account"]').is_visible()
                        assert menu.locator('a[href="/dashboard"]').is_visible()
                        assert menu.locator('a[href="/admin/asesoramiento"]').count() == int(has_advisory)
                        assert menu.locator('a[href="/stats"]').count() == int(has_stats)
                        assert menu.locator('a[href="/signup/"]').count() == 0
                        assert not errors, (role,width,errors)
                        page.keyboard.press("Tab")
                        assert page.evaluate("document.activeElement.closest('#snavMobileMenu') !== null"), (
                            role,width,"El foco no ha entrado en el menú abierto")
                        page.keyboard.press("Escape")
                        assert toggle.get_attribute("aria-expanded") == "false"
                        assert toggle.evaluate("(e) => document.activeElement === e"), (
                            role,width,"Escape no devuelve el foco al botón")
                        total += 1
                    finally:
                        page.close()
        finally:
            browser.close()
    print(f"QA responsive navegación: {total} casos PASS (datos simulados)")


if __name__ == "__main__":
    main()

