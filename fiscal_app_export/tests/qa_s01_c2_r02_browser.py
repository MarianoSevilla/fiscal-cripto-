"""C2-R02 browser E2E using real Flask, synthetic accounts, local SQLite/Chromium.

ONLY loopback requests; never Railway, PayPal, Stripe, Resend, real clients or
production DB. The browser exercises actual app routes and real JS/CSRF, rather
than mocks of management endpoints. Intentionally CI-only and ephemeral.
"""
import os
from pathlib import Path
import sys
from unittest.mock import patch
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("CI") != "true":
    raise RuntimeError("C2-R02 real-browser test is permitted only in GitHub CI")
if os.environ.get("FLASK_ENV") != "testing":
    raise RuntimeError("C2-R02 cannot test a non-testing environment")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_flask_navigation import flask_cookie, real_flask  # noqa: E402

WIDTHS = (375, 1280)


def restrict_network(route):
    parsed = urlsplit(route.request.url)
    if parsed.hostname == "127.0.0.1":
        route.continue_()
    else:
        # No outbound traffic. Even fonts/icons are intentionally unavailable.
        route.abort()


def new_context(browser, app, origin, identity=None, width=375):
    context = browser.new_context(viewport={"width": width, "height": 900})
    context.route("**/*", restrict_network)
    if identity is not None:
        cookie = flask_cookie(app, identity)
        context.add_cookies([{
            "name": app.config.get("SESSION_COOKIE_NAME", "session"),
            "value": cookie,
            "url": origin,
            "sameSite": "Lax",
            "httpOnly": True,
        }])
    return context


def checks(page, label):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    return errors


def check_ui_width(page, width, label):
    body_width = page.evaluate("document.documentElement.scrollWidth")
    assert body_width <= width + 2, (label, width, body_width)


def wait_list_item(page, request_id):
    item = page.locator('.request-item[data-id="' + str(request_id) + '"]')
    item.wait_for(state="visible", timeout=15000)
    return item


def confirm_state(app, request_id, status, has_quote=False):
    from models import FiscalAdvisoryRequest
    with app.app_context():
        obj = app.extensions["sqlalchemy"].session.get(FiscalAdvisoryRequest, request_id)
        assert obj is not None
        assert obj.status == status, (request_id, obj.status, status)
        if not has_quote:
            assert obj.quoted_amount is None
            assert obj.payment_link_token is None
            assert obj.paypal_capture_id is None
            assert obj.amount_paid is None
            assert obj.paid_at is None


def guarded_fetch(page, uri, *, method="POST", payload=None, headers=None):
    return page.evaluate("""async ({uri, method, payload, headers}) => {
        const response = await fetch(uri, {
            method, credentials:'include', headers: Object.assign({
                'Content-Type':'application/json'
            }, headers || {}), body: method === 'POST' ? JSON.stringify(payload || {}) : undefined
        });
        return {status:response.status, text:await response.text()};
    }""", {"uri": uri, "method": method, "payload": payload, "headers": headers})


def main():
    cases = 0
    with real_flask() as (flask_app, identities, origin):
        # Import model classes only AFTER the isolated Flask harness has
        # installed its SQLite-only config and app module search path.
        from models import FiscalAdvisoryRequest, AdvisoryInternalNote, AdvisoryAuditLog
        # The harness refuses inherited DATABASE_URL and creates a private SQLite
        # temp file. Assert it independently before any browser or DB operation.
        assert flask_app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
        with flask_app.app_context():
            historic = FiscalAdvisoryRequest(
                user_id=identities["usuario"],
                full_name="Expediente histórico ficticio C2-R02",
                email="usuario@example.invalid",
                tax_residence_country="España",
                tax_year=2025, service_type="presupuesto_personalizado",
                case_description="Expediente inventado para comprobar solo lectura.",
                status="submitted",
                paypal_order_id="synthetic-c2-r02-nonpayment-legacy-order",
            )
            from app import db
            db.session.add(historic)
            db.session.commit()
            historic_id = historic.id

        # Calls are patched at the boundary even though the public financial
        # endpoints are PREFREEZE and the providers have inert tombstones.
        with patch("app._send_advisory_confirmation_email") as confirmation, \
             patch("app._send_advisory_internal_notification") as internal, \
             patch("app._send_advisory_quote_email") as quote, \
             patch("app._send_advisory_message_email") as msg, \
             patch("app._paypal_create_order") as paypal:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    for width in WIDTHS:
                        # Landing: no fixed price, payment link or false 2-3-day promise.
                        anonymous = new_context(browser, flask_app, origin, width=width)
                        landing = anonymous.new_page()
                        errors = checks(landing, "landing")
                        response = landing.goto(origin + "/asesoramiento-fiscal-criptomonedas")
                        assert response.status == 200
                        assert landing.get_by_text("Presupuestos suspendidos").count() == 3
                        assert landing.get_by_text("No hay un plazo de respuesta confirmado", exact=False).count() >= 1
                        assert "2–3 días hábiles" not in landing.locator("body").inner_text()
                        assert not errors, (width, errors)
                        check_ui_width(landing, width, "landing")
                        # The old confirmation URL MUST NOT certify a payment.
                        paid_url = landing.goto(origin + "/asesoramiento-fiscal-confirmado")
                        assert paid_url.status == 503
                        assert paid_url.headers.get("cache-control") == "no-store"
                        assert landing.get_by_text("no acredita que se haya recibido", exact=False).is_visible()
                        assert "Hemos recibido tu solicitud y tu pago" not in landing.locator("body").inner_text()
                        assert "2–3 días hábiles" not in landing.locator("body").inner_text()
                        check_ui_width(landing, width, "legacy confirmation")
                        landing.close()
                        anonymous.close()
                        cases += 2

                        # Real user session and actual public submission JS.
                        user = new_context(
                            browser, flask_app, origin, identities["usuario"], width,
                        )
                        page = user.new_page()
                        errors = checks(page, "intake")
                        response = page.goto(origin + "/pedir-asesoramiento-fiscal")
                        assert response.status == 200
                        page.locator("#emailField").wait_for(state="visible")
                        assert page.locator("#emailField").input_value() == "usuario@example.invalid"
                        page.locator("#fullName").fill("Caso ficticio navegador " + str(width))
                        page.locator("#caseDesc").fill(
                            "Situación completamente inventada para verificar C2-R02 sin datos reales."
                        )
                        page.locator("#submitBtn").click()
                        page.locator("#errorMsg").wait_for(state="visible")
                        assert "Debes aceptar la política de privacidad" in page.locator("#errorMsg").inner_text()
                        page.locator("#legalPrivacy").check()
                        page.locator("#submitBtn").click()
                        page.locator("#successMsg").wait_for(state="visible", timeout=15000)
                        assert "No hemos generado ningún presupuesto" in page.locator("#successMsg").inner_text()
                        assert not errors, (width, errors)
                        check_ui_width(page, width, "intake")

                        # A customer cannot read or modify the admin management API.
                        blocked = guarded_fetch(page, "/api/admin/asesoramiento/solicitudes",
                                                method="GET")
                        assert blocked["status"] in (401, 403), blocked
                        blocked = guarded_fetch(
                            page, "/api/admin/asesoramiento/solicitudes/" + str(historic_id) +
                            "/gestion/nota", payload={"nota": "Unauthorized attempt"},
                        )
                        assert blocked["status"] in (401, 403), blocked
                        page.close()
                        user.close()
                        cases += 2

                        with flask_app.app_context():
                            made = FiscalAdvisoryRequest.query.filter_by(
                                full_name="Caso ficticio navegador " + str(width),
                            ).one()
                            request_id = made.id
                            assert made.status == "submitted"
                            assert made.payment_link_token is None
                            assert made.amount_paid is None

                        # Advisor loads actual panel JS, token CSRF, and DB writes.
                        advisor = new_context(
                            browser, flask_app, origin, identities["asesor"], width,
                        )
                        panel = advisor.new_page()
                        errors = checks(panel, "advisor")
                        response = panel.goto(origin + "/admin/asesoramiento")
                        assert response.status == 200
                        wait_list_item(panel, request_id).click()
                        panel.locator("#noteInput").wait_for(state="visible")
                        assert panel.get_by_text("Operativa S01 temporalmente suspendida").is_visible()
                        assert panel.get_by_role("button", name="Enviar presupuesto").count() == 0
                        assert panel.get_by_role("button", name="Reenviar link de pago").count() == 0
                        check_ui_width(panel, width, "advisor panel")
                        assert panel.locator("#btnStatus").is_enabled()
                        assert panel.locator("#newStatus option").all_text_contents() == [
                            "Solicitud recibida", "En revisión",
                        ]

                        # CSRF is essential even for an authorized advisor.
                        no_csrf = guarded_fetch(
                            panel, "/api/admin/asesoramiento/solicitudes/" +
                            str(request_id) + "/gestion/estado",
                            payload={"status": "under_review"},
                        )
                        assert no_csrf["status"] == 403, no_csrf
                        panel.locator("#noteInput").fill("Nota sintética del asesor " + str(width))
                        panel.locator("#btnNote").click()
                        panel.get_by_text("✓ Nota guardada").wait_for(state="visible")
                        panel.get_by_text("Nota sintética del asesor " + str(width)).wait_for(state="visible")
                        panel.locator("#newStatus").select_option("under_review")
                        panel.locator("#btnStatus").click()
                        panel.get_by_text("Estado actualizado correctamente.").wait_for(
                            state="visible", timeout=15000,
                        )
                        confirm_state(flask_app, request_id, "under_review")
                        with flask_app.app_context():
                            assert AdvisoryInternalNote.query.filter_by(
                                request_id=request_id
                            ).count() == 1
                            assert AdvisoryAuditLog.query.filter_by(
                                request_id=request_id,
                                action=AdvisoryAuditLog.ACTION_STATUS_CHANGED,
                            ).count() == 1

                        # Frozen financial legacy endpoints are inaccessible.
                        for path in (
                            "/api/admin/asesoramiento/solicitudes/" +
                            str(request_id) + "/enviar-presupuesto",
                            "/api/admin/asesoramiento/solicitudes/" +
                            str(request_id) + "/mensaje",
                            "/api/pago/iniciar/synthetic-token",
                        ):
                            frozen = guarded_fetch(panel, path)
                            assert frozen["status"] == 503, (path, frozen)
                        cases += 5

                        # Read-only historic order is present but can't change status.
                        wait_list_item(panel, historic_id).click()
                        panel.locator("#noteInput").wait_for(state="visible")
                        assert not panel.locator("#btnStatus").is_enabled()
                        assert "Expediente protegido" in panel.locator("#newStatus").inner_text()
                        assert panel.locator("#btnNote").is_enabled()
                        forged = guarded_fetch(
                            panel, "/api/admin/asesoramiento/solicitudes/" +
                            str(historic_id) + "/gestion/estado",
                            payload={"status": "under_review"},
                        )
                        assert forged["status"] == 403 or forged["status"] == 409, forged
                        # The browser acquired a CSRF token from the note action; an
                        # explicit CSRF-backed state request must be rejected for evidence.
                        token_response = panel.evaluate("""async () => {
                            const r=await fetch('/api/admin/asesoramiento/gestion-token',{
                                credentials:'include',cache:'no-store'
                            }); return r.json();
                        }""")
                        denied = guarded_fetch(
                            panel, "/api/admin/asesoramiento/solicitudes/" +
                            str(historic_id) + "/gestion/estado",
                            payload={"status": "under_review"},
                            headers={"X-S01-C1-CSRF": token_response["csrf_token"]},
                        )
                        assert denied["status"] == 409, denied
                        confirm_state(flask_app, historic_id, "submitted", has_quote=True)
                        assert not errors, (width, errors)
                        panel.close()
                        advisor.close()
                        cases += 3

                        # Administrators have view permission but no destructive UI.
                        admin = new_context(
                            browser, flask_app, origin, identities["administrador"], width,
                        )
                        pg = admin.new_page()
                        response = pg.goto(origin + "/admin/asesoramiento")
                        assert response.status == 200
                        wait_list_item(pg, historic_id).click()
                        pg.locator("#isTestCheck").wait_for(state="attached")
                        assert pg.locator("#isTestCheck").is_disabled()
                        assert pg.locator(".btn-danger").is_disabled()
                        pg.close()
                        admin.close()
                        cases += 1
                finally:
                    browser.close()
            quote.assert_not_called()
            msg.assert_not_called()
            paypal.assert_not_called()
            assert confirmation.call_count == len(WIDTHS)
            assert internal.call_count == len(WIDTHS)

    print("S01 C2-R02 browser E2E: " + str(cases) +
          " synthetic mobile/desktop checks PASS; roles, CSRF, notes, states, "
          "historic evidence, suspended prices/payment routes PASS; "
          "no external/provider I/O")


if __name__ == "__main__":
    main()
