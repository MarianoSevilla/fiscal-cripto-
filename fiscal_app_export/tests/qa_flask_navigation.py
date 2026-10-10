"""End-to-end de navegación/roles contra Flask real, sólo en CI aislado.

- No se modifica app.py ni la autenticación de producción.
- La base de datos SQLite se crea en TemporaryDirectory, con cuentas .invalid.
- Flask escucha únicamente en 127.0.0.1 sobre un puerto efímero.
- Las cookies se obtienen del test_client oficial, no de rutas auxiliares.
- No se leen secretos, Railway, Postgres, Resend ni archivos de usuarios.
"""
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

APP_DIR = Path(__file__).resolve().parents[1]

ROUTES = (
    "/", "/como-funciona", "/faq", "/contacto",
    "/dashboard", "/account", "/admin/asesoramiento",
    "/stats", "/mis-solicitudes-fiscales",
)
PRIVATE_PAGES = (
    "/dashboard", "/account", "/admin/asesoramiento", "/stats",
)
ROLES = ("visitante", "usuario", "asesor", "administrador")
WIDTHS = (320, 375, 768, 1024, 1280)


def expected_http(role, path):
    if path in ("/", "/como-funciona", "/faq", "/contacto"):
        return 200
    if role == "visitante":
        return 302
    if path in ("/dashboard", "/account"):
        return 200
    if path == "/admin/asesoramiento":
        return 200 if role in ("asesor", "administrador") else 302
    if path == "/stats":
        return 200 if role == "administrador" else 302
    if path == "/mis-solicitudes-fiscales":
        return 200 if role == "administrador" else 404
    raise AssertionError(path)


@contextmanager
def real_flask():
    # Hacer imposible utilizar por error el almacén de datos externo.
    with TemporaryDirectory(prefix="ms-responsive-flask-") as tmp:
        os.environ["FLASK_ENV"] = "testing"
        os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(tmp) / "only_fixture.sqlite")
        os.environ["SECRET_KEY"] = "ci-fixture-only-session-key-not-a-real-secret"
        os.environ["ADMIN_EMAILS"] = ""
        os.environ["FISCAL_ADVISOR_EMAILS"] = ""
        os.environ["RESEND_API_KEY"] = ""
        os.environ["ENABLE_ADVISORY_UPLOADS"] = "false"
        os.environ["ENABLE_ADVISORY_STATUS_EMAILS"] = "false"
        sys.path.insert(0, str(APP_DIR))
        from app import app as flask_app, db
        from models import User

        assert flask_app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
        assert not flask_app.config["SESSION_COOKIE_SECURE"]
        flask_app.config.update(TESTING=True, RATELIMIT_ENABLED=False)

        identities = {}
        with flask_app.app_context():
            db.create_all()
            for name, role in (
                ("usuario", "user"),
                ("asesor", "fiscal_advisor"),
                ("administrador", "admin"),
            ):
                u = User(
                    email=name + "@example.invalid",
                    full_name="Usuario ficticio " + name,
                    role=role,
                    is_active=True,
                )
                db.session.add(u)
                db.session.flush()
                identities[name] = u.id
            db.session.commit()

        server = make_server("127.0.0.1", 0, flask_app, threaded=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield flask_app, identities, f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()
            with flask_app.app_context():
                db.session.remove()
                db.drop_all()


def flask_cookie(app, user_id):
    if user_id is None:
        return None
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True
        cookie = client.get_cookie(app.config.get("SESSION_COOKIE_NAME", "session"))
        assert cookie, "Cookie de sesión no creada en test_client"
        return cookie.value


def check_back_end(app, identities):
    total = 0
    for role in ROLES:
        with app.test_client() as client:
            if role != "visitante":
                with client.session_transaction() as session:
                    session["_user_id"] = str(identities[role])
                    session["_fresh"] = True
            resp = client.get("/api/me")
            assert resp.status_code == 200
            user = resp.json.get("user")
            if role == "visitante":
                assert user is None
            else:
                assert user["email"].endswith("@example.invalid")
                assert user["is_admin"] == (role == "administrador")
                assert user["is_fiscal_advisor"] == (role in ("asesor", "administrador"))
            total += 1
            for path in ROUTES:
                response = client.get(path, follow_redirects=False)
                want = expected_http(role, path)
                assert response.status_code == want, (
                    role, path, response.status_code, want
                )
                if want == 302:
                    location = response.headers.get("Location", "")
                    assert location.startswith(("/login/", "/dashboard")), (
                        role, path, location
                    )
                total += 1
    return total


def restrict_network(route):
    parsed = urlsplit(route.request.url)
    if parsed.hostname == "127.0.0.1":
        route.continue_()
    else:
        route.abort()


def check_browsers(app, identities, origin):
    total = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for role in ROLES:
                for width in WIDTHS:
                    context = browser.new_context(
                        viewport={"width": width, "height": 812}
                    )
                    context.route("**/*", restrict_network)
                    cookie = flask_cookie(app, identities.get(role))
                    if cookie is not None:
                        context.add_cookies([{
                            "name": app.config.get("SESSION_COOKIE_NAME", "session"),
                            "value": cookie,
                            "url": origin,
                            "httpOnly": True,
                            "sameSite": "Lax",
                        }])
                    page = context.new_page()
                    page.set_default_timeout(12000)
                    try:
                        r = page.goto(origin + "/dashboard" if role != "visitante" else origin,
                                      wait_until="domcontentloaded")
                        assert r and r.status == 200, (role,width,r.status if r else None)
                        page.locator("#snavSkeleton.snav-hidden").wait_for(state="attached")
                        payload = page.evaluate("""async () => {
                          const r=await fetch('/api/me',{credentials:'include'});
                          return r.json();
                        }""")
                        actual = payload["user"]
                        assert (actual is not None) == (role != "visitante"), (
                            role, width, payload
                        )

                        toggle = page.locator("#snavMenuToggle")
                        assert toggle.is_visible() == (width <= 1200), (role,width)
                        if width <= 1200:
                            toggle.click()
                            menu = page.locator("#snavMobileMenu")
                        else:
                            if role == "visitante":
                                menu = page.locator(".snav-right")
                            else:
                                page.locator("#snavAvatar").click()
                                menu = page.locator("#snavDropdown")
                        assert menu.is_visible(), (role,width)
                        assert (menu.locator('a[href="/dashboard"]:visible').count() > 0) == (
                            role != "visitante"
                        ), (role,width,"dashboard")
                        assert (menu.locator('a[href="/admin/asesoramiento"]:visible').count() > 0) == (
                            role in ("asesor","administrador")
                        ), (role,width,"advisor")
                        assert (menu.locator('a[href="/stats"]:visible').count() > 0) == (
                            role == "administrador"
                        ), (role,width,"stats")
                        assert (menu.locator('a[href="/mis-solicitudes-fiscales"]:visible').count() > 0) == (
                            role == "administrador"
                        ), (role,width,"requests")
                        if role == "visitante":
                            assert menu.locator('a[href="/signup/"]:visible').count() == 1
                        total += 1
                    finally:
                        context.close()

            # Páginas privadas servidas por Flask real, no por servidor estático.
            for role in ("usuario","asesor","administrador"):
                context = browser.new_context(viewport={"width":375,"height":812})
                context.route("**/*", restrict_network)
                context.add_cookies([{
                    "name": app.config.get("SESSION_COOKIE_NAME", "session"),
                    "value": flask_cookie(app, identities[role]),
                    "url": origin,
                    "httpOnly": True,
                    "sameSite":"Lax",
                }])
                try:
                    for path in PRIVATE_PAGES:
                        if expected_http(role,path) != 200:
                            continue
                        page = context.new_page()
                        page.set_default_timeout(12000)
                        try:
                            resp = page.goto(origin + path,wait_until="domcontentloaded")
                            assert resp and resp.status == 200, (role,path)
                            page.locator("#snavSkeleton.snav-hidden").wait_for(state="attached")
                            assert page.locator("#snavMenuToggle").is_visible(), (
                                role,path,"falta menú"
                            )
                            page.locator("#snavMenuToggle").click()
                            assert page.locator("#snavMobileMenu").is_visible(), (
                                role,path,"menú no abre"
                            )
                            total += 1
                        finally:
                            page.close()
                finally:
                    context.close()
        finally:
            browser.close()
    return total


def main():
    with real_flask() as (app, identities, origin):
        backend = check_back_end(app,identities)
        browser = check_browsers(app,identities,origin)
    print(f"Flask real: {backend} HTTP/API checks PASS; {browser} browser checks PASS")


if __name__ == "__main__":
    main()
