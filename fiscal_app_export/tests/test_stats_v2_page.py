"""
Tests de /stats-v2 — Fase 2 del Hito 1 (esqueleto + contrato de datos).

Cubre:
  1. Acceso: admin-only en página y endpoint de datos (supuesto aprobado:
     @require_admin_page / @require_admin).
  2. Esqueleto: noindex, orden fijo de las cinco regiones (I4), ausencia de
     navegación del sitio (I1), presencia de las dos bandas del marco (I3),
     tokens del Design System enlazados.
  3. Contrato de datos: campos obligatorios del encuentro y de cada línea,
     niveles de solidez categóricos sin números ni porcentajes (I9/E1),
     tripartita completa (I17), historia desde el origen (I18), coherencia
     Ancla → línea impostergable (I14) con el orden de urgencia (I13).
  4. /stats-v2 fuera del sitemap (supuesto aprobado).
"""

import sys
import os
import shutil
import subprocess
import tempfile
from datetime import datetime

import pytest

# ── Entorno antes de importar app ────────────────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-stats-v2")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User
from stats_v2_fixture import ENCUENTRO_FIXTURE

NIVELES_SOLIDEZ = {"fragil", "en-construccion", "consistente", "solida"}
ESTADOS_09 = {
    "pendiente-de-posicion", "en-reevaluacion", "aplazada", "escalada",
    "en-intervencion", "reportada", "senalada", "cerrada",
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _app():
    flask_app.config["TESTING"] = True
    flask_app.config["RATELIMIT_ENABLED"] = False
    flask_app.config["WTF_CSRF_ENABLED"] = False
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    with flask_app.app_context():
        db.create_all()
    yield flask_app
    with flask_app.app_context():
        db.session.remove()


def _create_user(app, email, role, password="Test-1234-safe"):
    with app.app_context():
        u = User(
            email=email,
            full_name=f"Test {role}",
            role=role,
            email_verified_at=datetime.utcnow(),
        )
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return u.id


@pytest.fixture(scope="module")
def user_id(_app):
    uid = _create_user(_app, "statsv2_user@example.com", "user")
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture(scope="module")
def admin_id(_app):
    uid = _create_user(_app, "statsv2_admin@example.com", "admin")
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture
def anon_client(_app):
    return _app.test_client()


@pytest.fixture
def user_client(_app, user_id):
    c = _app.test_client()
    r = c.post("/api/login", json={"email": "statsv2_user@example.com", "password": "Test-1234-safe"})
    assert r.status_code == 200, f"Login user falló: {r.get_json()}"
    return c


@pytest.fixture
def admin_client(_app, admin_id):
    c = _app.test_client()
    r = c.post("/api/login", json={"email": "statsv2_admin@example.com", "password": "Test-1234-safe"})
    assert r.status_code == 200, f"Login admin falló: {r.get_json()}"
    return c


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ACCESO
# ═══════════════════════════════════════════════════════════════════════════════

class TestAcceso:
    def test_pagina_anon_redirige(self, anon_client):
        r = anon_client.get("/stats-v2")
        assert r.status_code == 302

    def test_pagina_user_redirige_a_dashboard(self, user_client):
        r = user_client.get("/stats-v2")
        assert r.status_code == 302
        assert "/dashboard" in r.headers.get("Location", "")

    def test_pagina_admin_200(self, admin_client):
        r = admin_client.get("/stats-v2")
        assert r.status_code == 200

    def test_api_user_403(self, user_client):
        r = user_client.get("/api/stats-v2/encuentro")
        assert r.status_code == 403

    def test_api_admin_200_json(self, admin_client):
        r = admin_client.get("/api/stats-v2/encuentro")
        assert r.status_code == 200
        data = r.get_json()
        assert data is not None
        assert "lineas" in data


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ESQUELETO (I1, I3, I4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEsqueleto:
    @pytest.fixture
    def html(self, admin_client):
        return admin_client.get("/stats-v2").get_data(as_text=True)

    def test_noindex(self, html):
        assert 'name="robots"' in html and "noindex" in html

    def test_sin_navegacion_del_sitio(self, html):
        # I1: la página es el encuentro — sin nav del sitio, sin menú.
        assert "nav.css" not in html
        assert "nav.js" not in html

    def test_bandas_del_marco(self, html):
        # I3: Ancla arriba y Consulta abajo, elementos del marco.
        assert 'id="ancla"' in html
        assert 'id="consulta"' in html

    def test_regiones_en_orden_fijo(self, html):
        # I4: cabecera → apertura → llegadas → periferia → pausa.
        ids = ["cabecera-encuentro", "bloque-apertura", "region-llegadas",
               "periferia", "region-pausa"]
        posiciones = [html.index(f'id="{i}"') for i in ids]
        assert posiciones == sorted(posiciones), "Las regiones no están en el orden de I4"

    def test_tokens_del_design_system(self, html):
        assert "/static/stats-v2/tokens.css" in html
        assert "/static/stats-v2/pagina.css" in html


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CONTRATO DE DATOS
# ═══════════════════════════════════════════════════════════════════════════════

class TestContrato:
    def test_campos_del_encuentro(self):
        for campo in ("origen", "cabecera", "declaracion_conjunta", "ancla",
                      "pausa", "periferia", "llegadas", "lineas"):
            assert campo in ENCUENTRO_FIXTURE, f"Falta el campo '{campo}' del encuentro"
        assert ENCUENTRO_FIXTURE["origen"] in ("sistema", "responsable")
        assert ENCUENTRO_FIXTURE["cabecera"]["convocatoria"]
        assert ENCUENTRO_FIXTURE["cabecera"]["continuidad"]

    def test_campos_de_cada_linea(self):
        assert len(ENCUENTRO_FIXTURE["lineas"]) >= 1
        for linea in ENCUENTRO_FIXTURE["lineas"]:
            for campo in ("id", "implicacion", "solidez", "novedad",
                          "estado_como_acto", "pertenencia", "estado",
                          "actos", "posicion", "bandas", "historia"):
                assert campo in linea, f"Falta '{campo}' en la línea {linea.get('id')}"
            assert linea["estado"] in ESTADOS_09

    def test_solidez_categorica_sin_numeros(self):
        # I9/E1: solo los cuatro niveles; ningún dígito ni '%' en la convicción.
        for linea in ENCUENTRO_FIXTURE["lineas"]:
            solidez = linea["solidez"]
            assert set(solidez.keys()) == {"lectura", "implicacion"}
            for dimension, nivel in solidez.items():
                assert nivel in NIVELES_SOLIDEZ, (
                    f"Nivel de solidez no categórico en {linea['id']}.{dimension}: {nivel!r}"
                )
                assert not any(c.isdigit() for c in nivel)
                assert "%" not in nivel

    def test_tripartita_completa(self):
        # I17: Observo / Interpreto / Esto implica — siempre las tres.
        for linea in ENCUENTRO_FIXTURE["lineas"]:
            for segmento in ("observo", "interpreto", "implica"):
                assert linea["posicion"].get(segmento), (
                    f"Tripartita incompleta en {linea['id']}: falta '{segmento}'"
                )

    def test_historia_desde_el_origen(self):
        # I18: la primera entrada es el nacimiento de la línea.
        for linea in ENCUENTRO_FIXTURE["lineas"]:
            assert len(linea["historia"]) >= 1
            for entrada in linea["historia"]:
                assert entrada["cuando"] and entrada["entrada"]
            assert linea["historia"][0]["entrada"].startswith("Nace la línea"), (
                f"La historia de {linea['id']} no comienza en el origen"
            )

    def test_ancla_conduce_a_linea_urgente(self):
        # I14 + I13: el Ancla apunta a una línea existente; la impostergable
        # encabeza el orden de urgencia.
        ancla = ENCUENTRO_FIXTURE["ancla"]
        ids = [l["id"] for l in ENCUENTRO_FIXTURE["lineas"]]
        assert ancla["linea_id"] in ids
        if ancla["estado"] == "impostergable":
            assert ancla["linea_id"] == ids[0]

    def test_bandas_estructura(self):
        for linea in ENCUENTRO_FIXTURE["lineas"]:
            assert set(linea["bandas"].keys()) == {"razon", "procedencia", "coste"}


# ═══════════════════════════════════════════════════════════════════════════════
# 4. SOLIDEZDUAL (E1 v0.4 — fase 3)
# ═══════════════════════════════════════════════════════════════════════════════

_APP_DIR = os.path.dirname(os.path.dirname(__file__))


class TestSolidezDual:
    def test_assets_enlazados(self, admin_client):
        html = admin_client.get("/stats-v2").get_data(as_text=True)
        assert "/static/stats-v2/solidez-dual.css" in html
        assert "/static/stats-v2/solidez-dual.js" in html

    def test_css_construye_los_cuatro_niveles(self):
        ruta = os.path.join(_APP_DIR, "static", "stats-v2", "solidez-dual.css")
        with open(ruta, encoding="utf-8") as f:
            css = f.read()
        for clase in ("sd-nivel-fragil", "sd-nivel-en-construccion",
                      "sd-nivel-consistente", "sd-nivel-solida"):
            assert clase in css, f"Falta la construcción del nivel {clase}"
        # T3: la reserva E3 (ámbar/ocre) y las prohibiciones de paleta —
        # el componente solo usa tinta.
        for prohibido in ("--acento-novedad", "--aplazar", "--descartar"):
            assert prohibido not in css, (
                f"SolidezDual usa color semántico ({prohibido}): el color no participa en la solidez"
            )

    @pytest.mark.skipif(shutil.which("node") is None, reason="node no disponible")
    def test_nucleo_en_node_16_combinaciones_sin_digitos_ni_porcentajes(self):
        """Ejecuta tests/js/test_solidez_dual.js: 16 combinaciones, palabras
        de nivel exactas, aria, y ausencia de dígitos/% en la convicción."""
        ruta = os.path.join(_APP_DIR, "tests", "js", "test_solidez_dual.js")
        r = subprocess.run(["node", ruta], capture_output=True, text=True)
        assert r.returncode == 0, f"Test JS falló:\n{r.stdout}\n{r.stderr}"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ENTRADALINEA (E2/I15 — fase 4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEntradaLinea:
    def test_assets_enlazados(self, admin_client):
        html = admin_client.get("/stats-v2").get_data(as_text=True)
        assert "/static/stats-v2/entrada-linea.css" in html
        assert "/static/stats-v2/entrada-linea.js" in html

    def test_la_entrada_no_es_tarjeta(self):
        # I2/E2: sin borde, sin fondo, sin sombra — prosa estructurada.
        ruta = os.path.join(_APP_DIR, "static", "stats-v2", "entrada-linea.css")
        with open(ruta, encoding="utf-8") as f:
            lineas_css = [
                l for l in f.read().splitlines()
                if not l.strip().startswith(("/*", "*", "*/"))
            ]
        css = "\n".join(lineas_css)
        for prohibido in ("border:", "border-", "background", "box-shadow"):
            assert prohibido not in css, (
                f"entrada-linea.css contiene '{prohibido}': la entrada no es tarjeta (I2)"
            )

    def test_la_marca_usa_el_acento_de_novedad(self):
        # I7: la marca es textual Y con el único acento del producto.
        ruta = os.path.join(_APP_DIR, "static", "stats-v2", "entrada-linea.css")
        with open(ruta, encoding="utf-8") as f:
            css = f.read()
        assert "--acento-novedad" in css

    @pytest.mark.skipif(shutil.which("node") is None, reason="node no disponible")
    def test_nucleo_en_node_anatomia_y_par_de_juicio(self):
        """Ejecuta tests/js/test_entrada_linea.js: anatomía de 5 elementos,
        marca condicional con origen legible, obligatoriedad del par
        implicación+solidez, metadatos «estado · pertenencia»."""
        ruta = os.path.join(_APP_DIR, "tests", "js", "test_entrada_linea.js")
        r = subprocess.run(["node", ruta], capture_output=True, text=True)
        assert r.returncode == 0, f"Test JS falló:\n{r.stdout}\n{r.stderr}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. LINEAEXPANDIDA (D11, I16–I18 — fase 5)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLineaExpandida:
    def test_assets_enlazados(self, admin_client):
        html = admin_client.get("/stats-v2").get_data(as_text=True)
        assert "/static/stats-v2/linea-expandida.css" in html
        assert "/static/stats-v2/linea-expandida.js" in html

    def test_nunca_una_ficha_sin_primitivas_de_navegacion(self):
        # I16: expansión en el sitio — ningún JS del silo navega, cambia la
        # URL, abre ventanas ni desplaza el scroll programáticamente.
        js_dir = os.path.join(_APP_DIR, "static", "stats-v2")
        prohibidas = ("pushState", "replaceState", "location.href",
                      "location.hash", "location.assign", "window.open",
                      "scrollIntoView", "scrollTo(")
        for nombre in sorted(os.listdir(js_dir)):
            if not nombre.endswith(".js"):
                continue
            with open(os.path.join(js_dir, nombre), encoding="utf-8") as f:
                js = f.read()
            for primitiva in prohibidas:
                assert primitiva not in js, (
                    f"{nombre} contiene {primitiva}: la expansión sería una página (I16)"
                )

    def test_expansion_no_es_tarjeta(self):
        # La expansión es prosa en la columna: sin borde, fondo ni sombra.
        ruta = os.path.join(_APP_DIR, "static", "stats-v2", "linea-expandida.css")
        with open(ruta, encoding="utf-8") as f:
            lineas_css = [
                l for l in f.read().splitlines()
                if not l.strip().startswith(("/*", "*", "*/"))
            ]
        css = "\n".join(lineas_css)
        for prohibido in ("border:", "border-", "background", "box-shadow"):
            assert prohibido not in css, (
                f"linea-expandida.css contiene '{prohibido}': la expansión no es una ficha"
            )

    def test_especimen_retirado(self):
        # Fase 5: la revisión se hace sobre el componente real.
        for nombre in ("encuentro.js", "pagina.css"):
            ruta = os.path.join(_APP_DIR, "static", "stats-v2", nombre)
            with open(ruta, encoding="utf-8") as f:
                assert "especimen" not in f.read().lower(), (
                    f"El espécimen temporal sigue en {nombre}"
                )

    @pytest.mark.skipif(shutil.which("node") is None, reason="node no disponible")
    def test_nucleo_en_node_tripartita_y_bandas(self):
        """Ejecuta tests/js/test_linea_expandida.js: tripartita obligatoria,
        rótulos exactos, bandas presentes en orden estable."""
        ruta = os.path.join(_APP_DIR, "tests", "js", "test_linea_expandida.js")
        r = subprocess.run(["node", ruta], capture_output=True, text=True)
        assert r.returncode == 0, f"Test JS falló:\n{r.stdout}\n{r.stderr}"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. HISTORIALINEA (I18 — fase 6) + NO-REPLIEGUE (corrección fase 5)
# ═══════════════════════════════════════════════════════════════════════════════

class TestHistoriaLinea:
    def test_assets_enlazados(self, admin_client):
        html = admin_client.get("/stats-v2").get_data(as_text=True)
        assert "/static/stats-v2/historia-linea.css" in html
        assert "/static/stats-v2/historia-linea.js" in html

    def test_evidencia_grafica_solo_en_la_historia(self):
        # I2/I18: el único lugar del producto donde pueden vivir gráficos.
        js_dir = os.path.join(_APP_DIR, "static", "stats-v2")
        for nombre in sorted(os.listdir(js_dir)):
            if not nombre.endswith(".js") or nombre == "historia-linea.js":
                continue
            with open(os.path.join(js_dir, nombre), encoding="utf-8") as f:
                js = f.read()
            assert "createElementNS" not in js, (
                f"{nombre} crea gráficos: la evidencia solo vive en la Historia (I18)"
            )

    def test_la_historia_no_es_tarjeta(self):
        ruta = os.path.join(_APP_DIR, "static", "stats-v2", "historia-linea.css")
        with open(ruta, encoding="utf-8") as f:
            lineas_css = [
                l for l in f.read().splitlines()
                if not l.strip().startswith(("/*", "*", "*/"))
            ]
        css = "\n".join(lineas_css)
        for prohibido in ("border:", "border-", "background", "box-shadow"):
            assert prohibido not in css, (
                f"historia-linea.css contiene '{prohibido}': la historia es prosa dentro de la línea"
            )

    def test_sin_repliegue_en_linea_ni_en_historia(self):
        # Corrección de fase 5: lo abordado y lo revelado permanecen — el
        # gesto solo abre; ningún código vuelve a ocultar.
        for nombre in ("entrada-linea.js", "historia-linea.js"):
            ruta = os.path.join(_APP_DIR, "static", "stats-v2", nombre)
            with open(ruta, encoding="utf-8") as f:
                js = f.read()
            assert "hidden = true" not in js.replace(".hidden = true;", "MONTAJE", 1), (
                f"{nombre} repliega después del gesto"
            )
            assert 'setAttribute("aria-expanded", "true")' in js
            assert "String(" not in js, f"{nombre} alterna aria-expanded: hay toggle"

    @pytest.mark.skipif(shutil.which("node") is None, reason="node no disponible")
    def test_nucleo_en_node_registro_desde_el_origen(self):
        """Ejecuta tests/js/test_historia_linea.js: orden desde el origen,
        rótulo exacto, evidencias normalizadas y rechazos."""
        ruta = os.path.join(_APP_DIR, "tests", "js", "test_historia_linea.js")
        r = subprocess.run(["node", ruta], capture_output=True, text=True)
        assert r.returncode == 0, f"Test JS falló:\n{r.stdout}\n{r.stderr}"


# ═══════════════════════════════════════════════════════════════════════════════
# 8. FILA DE ACTOS + PANEL-EN-GESTO (I19/I20 v1.1, T6/T7, D13 — fase 7)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFilaYPanel:
    def test_assets_enlazados(self, admin_client):
        html = admin_client.get("/stats-v2").get_data(as_text=True)
        for asset in ("fila-actos.css", "fila-actos.js", "panel-acto.css",
                      "panel-acto.js", "actos.js"):
            assert f"/static/stats-v2/{asset}" in html

    def test_contrato_trae_el_repertorio(self):
        # D12/T6: el repertorio lo trae el dato; pendiente-de-posicion es íntegro.
        for linea in ENCUENTRO_FIXTURE["lineas"]:
            assert "actos" in linea
            if linea["estado"] == "pendiente-de-posicion":
                assert set(linea["actos"]) == {
                    "activar", "cuestionar", "enriquecer", "aplazar", "descartar"
                }

    def test_relleno_reservado_a_activar(self):
        # T6: el relleno a tinta plena en un control interactivo es solo de
        # Activar. En el código, la clase acto-relleno solo se asigna cuando
        # el acto es 'activar'.
        for nombre in ("fila-actos.js", "panel-acto.js"):
            ruta = os.path.join(_APP_DIR, "static", "stats-v2", nombre)
            with open(ruta, encoding="utf-8") as f:
                js = f.read()
            for linea_js in js.splitlines():
                if "acto-relleno" in linea_js and "*" not in linea_js:
                    assert '"activar"' in linea_js, (
                        f"{nombre} asigna el relleno fuera de Activar: {linea_js.strip()}"
                    )

    def test_sin_estados_deshabilitados_en_la_fila(self):
        # T6: no existen actos deshabilitados. El atenuado del panel es otra
        # cosa (gesto incompleto, aria-disabled — T7).
        ruta = os.path.join(_APP_DIR, "static", "stats-v2", "fila-actos.css")
        with open(ruta, encoding="utf-8") as f:
            css = f.read()
        assert ":disabled" not in css and "disabled" not in css.replace(
            "aria-disabled", ""
        ), "fila-actos.css construye estados deshabilitados (T6 los prohíbe)"

    def test_panel_sobre_superficie_leve_sin_sombra_ni_radio(self):
        # T7: --papel-2, sin sombra; sin radio en fila ni panel.
        for nombre in ("panel-acto.css", "fila-actos.css"):
            ruta = os.path.join(_APP_DIR, "static", "stats-v2", nombre)
            with open(ruta, encoding="utf-8") as f:
                lineas_css = [
                    l for l in f.read().splitlines()
                    if not l.strip().startswith(("/*", "*", "*/"))
                ]
            css = "\n".join(lineas_css)
            assert "box-shadow" not in css
            for regla in css.split(";"):
                if "border-radius" in regla:
                    assert "border-radius: 0" in regla.strip(), (
                        f"{nombre} usa radio: {regla.strip()}"
                    )
        with open(os.path.join(_APP_DIR, "static", "stats-v2", "panel-acto.css"),
                  encoding="utf-8") as f:
            assert "--papel-2" in f.read()

    @pytest.mark.skipif(shutil.which("node") is None, reason="node no disponible")
    def test_nucleo_en_node_actos_y_panel(self):
        """Ejecuta tests/js/test_actos_panel.js: zonas T6, nombres literales,
        niveles/razones con consecuencia, condición literal de I20c, precarga
        única de D13.5, genéricos de confirmación rechazados."""
        ruta = os.path.join(_APP_DIR, "tests", "js", "test_actos_panel.js")
        r = subprocess.run(["node", ruta], capture_output=True, text=True)
        assert r.returncode == 0, f"Test JS falló:\n{r.stdout}\n{r.stderr}"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. CONSUMACIÓN + BANDAS + DESCARTAR (D13.1/D14/I21/T12/T6 — fase 8)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConsumacion:
    def test_assets_enlazados(self, admin_client):
        html = admin_client.get("/stats-v2").get_data(as_text=True)
        for asset in ("consumar.js", "gesto-linea.js", "banda-linea.js",
                      "banda-linea.css", "control-descartar.js",
                      "control-descartar.css"):
            assert f"/static/stats-v2/{asset}" in html

    def test_banda_construccion_t12(self):
        # T12: superficie leve, familias de T3, sin borde/radio/icono/sombra;
        # el ámbar de E3 sigue prohibido.
        ruta = os.path.join(_APP_DIR, "static", "stats-v2", "banda-linea.css")
        with open(ruta, encoding="utf-8") as f:
            lineas_css = [
                l for l in f.read().splitlines()
                if not l.strip().startswith(("/*", "*", "*/"))
            ]
        css = "\n".join(lineas_css)
        for familia in ("--aplazar-fondo", "--descartar-fondo", "--papel-2"):
            assert familia in css, f"banda-linea.css no construye la familia {familia}"
        for prohibido in ("border:", "border-", "box-shadow", "url("):
            assert prohibido not in css, f"banda-linea.css contiene '{prohibido}' (T12)"

    def test_descartar_es_control_de_archivo(self):
        # T6/[06·C6]: texto sepia, sin contorno ni relleno — jamás par
        # visual de un botón de la fila.
        ruta = os.path.join(_APP_DIR, "static", "stats-v2", "control-descartar.css")
        with open(ruta, encoding="utf-8") as f:
            lineas_css = [
                l for l in f.read().splitlines()
                if not l.strip().startswith(("/*", "*", "*/"))
            ]
        css = "\n".join(lineas_css)
        assert "--descartar" in css
        for prohibido in ("background", "border:", "border-", "box-shadow"):
            assert prohibido not in css, (
                f"control-descartar.css contiene '{prohibido}': forma de botón, no de archivo"
            )

    def test_gestor_compartido_entre_fila_y_descartar(self):
        # D13.2: la línea es UN contexto de juicio — linea-expandida crea un
        # gestor y lo pasa a ambos componentes.
        ruta = os.path.join(_APP_DIR, "static", "stats-v2", "linea-expandida.js")
        with open(ruta, encoding="utf-8") as f:
            js = f.read()
        assert js.count("GestorGestoLinea.crear()") == 1
        assert "FilaDeActos.crear(linea, gestor)" in js
        assert "ControlDescartar.crear(linea, gestor)" in js

    @pytest.mark.skipif(shutil.which("node") is None, reason="node no disponible")
    def test_nucleo_en_node_consumacion(self):
        """Ejecuta tests/js/test_consumar.js: transiciones del protocolo,
        repertorios (05·IV incluido), constancias con familia T12 sin
        dígitos, condición vigente de I20c, posicionalidad y rechazos."""
        ruta = os.path.join(_APP_DIR, "tests", "js", "test_consumar.js")
        r = subprocess.run(["node", ruta], capture_output=True, text=True)
        assert r.returncode == 0, f"Test JS falló:\n{r.stdout}\n{r.stderr}"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. FUERA DEL SITEMAP
# ═══════════════════════════════════════════════════════════════════════════════

class TestSitemap:
    def test_stats_v2_no_esta_en_sitemap(self):
        ruta = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "static", "sitemap.xml")
        with open(ruta, encoding="utf-8") as f:
            assert "stats-v2" not in f.read()
