"""01-B: account Apple Chromium QA; synthetic identities and intercepted writes only.

Invoked from qa_flask_navigation on temporary SQLite users. All account
mutations are fulfilled in-browser and cannot touch even the fixture DB.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def run_account_apple(origin, cookie_name, cookie_value):
    scenarios = 0
    art = Path("qa-artifacts")
    art.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in (375, 768, 1440):
                for google in (False, True):
                    calls = []
                    unexpected = []
                    user = {
                        "email": "persona@example.invalid",
                        "full_name": "Persona ficticia",
                        "nif": "12345678Z",
                        "email_verified": True,
                        "created_at": "2026-01-15T12:00:00Z",
                        "plan": "free",
                        "is_google": google,
                        "is_admin": False,
                        "is_fiscal_advisor": False,
                    }
                    ctx = browser.new_context(viewport={"width": width, "height": 900})
                    ctx.add_cookies([{
                        "name": cookie_name, "value": cookie_value,
                        "url": origin, "httpOnly": True, "sameSite": "Lax"
                    }])

                    def route_handler(route):
                        request = route.request
                        url = urlsplit(request.url)
                        if url.hostname != "127.0.0.1":
                            unexpected.append(f"external request {url.hostname}")
                            route.abort()
                            return
                        if url.path == "/api/me":
                            route.fulfill(status=200, content_type="application/json",
                                          body=json.dumps({"user": user}))
                            return
                        if request.method != "GET":
                            calls.append((url.path, request.post_data_json if request.post_data else None))
                            if url.path == "/api/update-profile":
                                data = request.post_data_json
                                route.fulfill(status=200, content_type="application/json",
                                              body=json.dumps({"full_name": data["full_name"],
                                                               "nif": data["nif"]}))
                            elif url.path == "/api/change-password":
                                route.fulfill(status=200, content_type="application/json",
                                              body='{"message":"Synthetic password changed"}')
                            elif url.path == "/api/delete-account/request":
                                route.fulfill(status=200, content_type="application/json",
                                              body='{"message":"Synthetic code sent"}')
                            elif url.path == "/api/delete-account":
                                route.fulfill(status=400, content_type="application/json",
                                              body='{"error":"Confirmación ficticia rechazada"}')
                            else:
                                unexpected.append(f"unexpected write {request.method} {url.path}")
                                route.abort()
                            return
                        if url.path.startswith("/api/"):
                            unexpected.append(f"unexpected API GET {url.path}")
                            route.abort()
                            return
                        route.continue_()

                    ctx.route("**/*", route_handler)
                    page = ctx.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("console", lambda message: errors.append(message.text)
                            if message.type == "error" and not (
                                "Failed to load resource" in message.text
                                and "400" in message.text
                            ) else None)
                    try:
                        response = page.goto(origin + "/account", wait_until="networkidle")
                        assert response and response.status == 200
                        page.locator("#accountContent").wait_for(state="visible")
                        assert page.locator("h1").inner_text() == "Mi cuenta"
                        assert page.locator("#infoEmail").inner_text() == "persona@example.invalid"
                        assert page.locator("#infoCreated").inner_text() != "—"
                        assert page.locator("#infoVerified").is_visible()
                        assert page.locator("#infoPlan").inner_text() == "Free"
                        assert page.locator("#nameInput").input_value() == "Persona ficticia"
                        assert page.locator("#nifInput").input_value() == "12345678Z"
                        assert page.locator("#sectionPassword").is_visible() == (not google)
                        assert page.locator("#site-nav").is_visible()
                        assert page.locator('a[href="/herramientas"]').count() > 0
                        assert page.locator('a[href="/privacidad"]').count() > 0
                        assert page.locator('a[href="/terminos"]').count() > 0
                        assert page.evaluate(
                            "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
                        ), ("horizontal overflow", width, google)
                        assert page.locator("#nameInput").evaluate(
                            "el => parseFloat(getComputedStyle(el).fontSize)"
                        ) >= 16
                        assert page.evaluate(
                            "() => getComputedStyle(document.body).backgroundColor"
                        ) != "rgb(11, 18, 32)"
                        if not google:
                            page.locator("#pwBtn").click()
                            assert "Completa todos" in page.locator("#pwMsg").inner_text()
                            page.locator("#pwCurrent").fill("old-synthetic")
                            page.locator("#pwNew").fill("new-synthetic-123")
                            page.locator("#pwConfirm").fill("bad-synthetic")
                            page.locator("#pwBtn").click()
                            assert "no coinciden" in page.locator("#pwMsg").inner_text()
                            page.locator("#pwConfirm").fill("new-synthetic-123")
                            page.locator("#pwBtn").click()
                            page.get_by_text("¡Contraseña actualizada correctamente!").wait_for(state="visible")
                            assert "actualizada" in page.locator("#pwMsg").inner_text()
                            assert any(p == "/api/change-password" for p, _ in calls)

                        # Error de validación local y edición del nombre/NIF.
                        page.locator("#nameInput").fill(" ")
                        page.locator("#profileBtn").click()
                        assert "no pueden estar vacíos" in page.locator("#profileMsg").inner_text()
                        assert not any(p == "/api/update-profile" for p, _ in calls)
                        page.locator("#nameInput").fill("Persona Editada")
                        page.locator("#nifInput").fill("x1234567l")
                        page.locator("#profileBtn").click()
                        page.get_by_text("¡Cambios guardados correctamente!").wait_for(state="visible")
                        assert page.locator("#nameInput").input_value() == "Persona Editada"
                        assert page.locator("#nifInput").input_value() == "X1234567L"
                        assert "guardados" in page.locator("#profileMsg").inner_text()
                        assert any(p == "/api/update-profile" and data == {
                            "full_name": "Persona Editada", "nif": "X1234567L"
                        } for p, data in calls)

                        # Diálogo accesible, Escape, cancelación y restauración del foco.
                        opener = page.locator("#btnDeleteAccount")
                        opener.click()
                        modal = page.locator("#deleteModal")
                        assert modal.is_visible()
                        assert modal.get_attribute("aria-modal") == "true"
                        assert page.evaluate("document.activeElement.id") == (
                            "delBtnConfirm" if google else "delPasswordInput"
                        )
                        assert page.locator("#delPanelOAuthStep1").is_visible() == google
                        assert page.locator("#delPanelPassword").is_visible() == (not google)
                        page.keyboard.press("Escape")
                        assert not modal.is_visible()
                        assert page.evaluate("document.activeElement.id") == "btnDeleteAccount"
                        opener.click()
                        if google:
                            page.locator("#delBtnConfirm").click()
                            page.locator("#delPanelOAuthStep2").wait_for(state="visible")
                            assert page.locator("#delPanelOAuthStep2").is_visible()
                            assert any(p == "/api/delete-account/request" for p, _ in calls)
                            page.locator("#delTokenInput").fill("FAKE-CODE")
                            page.locator("#delBtnConfirm").click()
                            page.locator("#delError").wait_for(state="visible")
                            assert page.locator("#delError").is_visible()
                            assert any(p == "/api/delete-account" and data == {
                                "token": "FAKE-CODE"
                            } for p, data in calls)
                        else:
                            page.locator("#delPasswordInput").focus()
                            page.keyboard.press("Shift+Tab")
                            assert page.evaluate("document.activeElement.id") == "delBtnConfirm"
                            page.locator("#delPasswordInput").fill("fake-pass")
                            page.locator("#delBtnConfirm").click()
                            page.locator("#delError").wait_for(state="visible")
                            assert page.locator("#delError").is_visible()
                            assert any(p == "/api/delete-account" and data == {
                                "password": "fake-pass"
                            } for p, data in calls)
                        if width in (375, 768, 1440):
                            page.screenshot(path=str(art / f"home_account_dialog_{'google' if google else 'email'}_{width}.png"),
                                            full_page=True)
                        page.locator("#delBtnCancel").click()
                        assert not modal.is_visible()
                        assert page.evaluate("document.activeElement.id") == "btnDeleteAccount"
                        page.screenshot(path=str(art / f"home_account_{'google' if google else 'email'}_{width}.png"),
                                        full_page=True)
                        assert not unexpected and not errors, (width, google, unexpected, errors)
                        scenarios += 1
                    finally:
                        ctx.close()

            # Fail-closed when /api/me cannot be checked; retry is visible.
            for mode in ("error", "expired"):
                ctx = browser.new_context(viewport={"width": 375, "height": 900})
                ctx.add_cookies([{
                    "name": cookie_name, "value": cookie_value, "url": origin,
                    "httpOnly": True, "sameSite": "Lax"
                }])
                def fail_me(route):
                    route.fulfill(status=503 if mode == "error" else 200,
                                  content_type="application/json",
                                  body='{"error":"Synthetic unavailable"}' if mode == "error"
                                       else '{"user":null}')
                ctx.route("**/api/me", fail_me)
                # Una sesión simulada como caducada no debe reautenticarse por
                # la cookie del usuario de prueba al abrir /login/.
                if mode == "expired":
                    ctx.route("**/login/", lambda route: route.fulfill(
                        status=200, content_type="text/html",
                        body="<main>Login sintético</main>"))
                page = ctx.new_page()
                try:
                    page.goto(origin + "/account", wait_until="domcontentloaded")
                    if mode == "error":
                        page.locator("#accountRetry").wait_for(state="visible")
                        assert not page.locator("#accountContent").is_visible()
                        assert "No podemos comprobar" in page.locator("#accountStatusText").inner_text()
                    else:
                        page.wait_for_url("**/login/", timeout=10000)
                    scenarios += 1
                finally:
                    ctx.close()
        finally:
            browser.close()
    print(f"ACCOUNT_APPLE_QA: PASS ({scenarios} scenarios, widths 375/768/1440, "
          "email/Google, synthetic API writes, accessible modal, session errors)")
