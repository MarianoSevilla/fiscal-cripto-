"""
Tests para el campo NIF de usuario y su integración con el Modelo 721.

 1.  _validar_nif_usuario acepta DNI válido (12345678Z).
 2.  _validar_nif_usuario acepta NIE válido (X1234567L).
 3.  _validar_nif_usuario acepta CIF válido (B12345678).
 4.  _validar_nif_usuario acepta vacío (campo opcional).
 5.  _normalizar_nif quita espacios y convierte a mayúsculas.
 6.  _validar_nif_usuario rechaza formatos inválidos.
 7.  Usuario existente sin NIF no rompe nada (nif=None por defecto).
 8.  /api/update-nif guarda NIF válido → 200.
 9.  /api/update-nif rechaza NIF inválido → 400.
10.  /api/update-nif acepta vaciado del NIF → 200.
11.  /api/me incluye campo nif.
12.  /account devuelve 200.
13.  /api/721 devuelve nif_faltante=True cuando el usuario no tiene NIF guardado.
14.  /api/721 devuelve nif_faltante=False cuando el usuario tiene NIF guardado.
"""

import io
import sys
import os
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

# ── Configurar entorno antes de importar app ────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-key-nif-tests-only")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db, _validar_nif_usuario, _normalizar_nif
from models import User


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _app():
    flask_app.config["TESTING"]              = True
    flask_app.config["RATELIMIT_ENABLED"]    = False
    flask_app.config["WTF_CSRF_ENABLED"]     = False
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    # SQLite no acepta connect_timeout — limpiar opciones de engine para tests
    flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(_app):
    return _app.test_client()


@pytest.fixture
def test_user(_app):
    """Usuario de prueba sin NIF, email verificado."""
    with _app.app_context():
        u = User(
            email="test_nif@example.com",
            full_name="Test Usuario",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("test-pass-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


def _login(client, email="test_nif@example.com", password="test-pass-1234"):
    """Ayudante: inicia sesión y devuelve el cliente con cookies."""
    client.post("/api/login", json={"email": email, "password": password})
    return client


# ── 1-6: Tests de la función de validación (sin Flask) ──────────────────────

@pytest.mark.parametrize("nif", ["12345678Z", "12345678A", "00000000T"])
def test_nif_dni_valido(nif):
    """DNI: 8 dígitos + letra."""
    ok, err = _validar_nif_usuario(nif)
    assert ok, f"Se esperaba válido para {nif!r}: {err}"


@pytest.mark.parametrize("nif", ["X1234567L", "Y0000000Z", "Z9999999R"])
def test_nif_nie_valido(nif):
    """NIE: X/Y/Z + 7 dígitos + letra."""
    ok, err = _validar_nif_usuario(nif)
    assert ok, f"Se esperaba válido para {nif!r}: {err}"


@pytest.mark.parametrize("nif", ["B12345678", "A00000001", "G99999990"])
def test_nif_cif_valido(nif):
    """CIF: letra + 7 dígitos + letra/dígito."""
    ok, err = _validar_nif_usuario(nif)
    assert ok, f"Se esperaba válido para {nif!r}: {err}"


def test_nif_vacio_valido():
    """Campo vacío → válido (opcional)."""
    ok, err = _validar_nif_usuario("")
    assert ok
    assert err == ""


def test_normalizar_nif_espacios_y_minusculas():
    """Espacios y minúsculas se normalizan."""
    assert _normalizar_nif("  12345678z  ") == "12345678Z"
    assert _normalizar_nif("x1234567l")      == "X1234567L"


@pytest.mark.parametrize("nif", [
    "12345678",        # sin letra final
    "ABCDEFGHI",       # todo letras
    "123 456 78Z",     # espacios internos (no normalizados antes de pasar)
    "mario@test.com",  # email
    "A" * 25,          # demasiado largo
    "1234567",         # demasiado corto
])
def test_nif_invalido_rechazado(nif):
    """Formatos claramente inválidos deben rechazarse."""
    ok, _ = _validar_nif_usuario(nif)
    assert not ok, f"Se esperaba inválido para {nif!r}"


# ── 7: Usuario sin NIF no rompe nada ────────────────────────────────────────

def test_usuario_sin_nif_no_rompe(_app):
    """User.nif puede ser None sin errores."""
    with _app.app_context():
        u = User(email="nonif@example.com")
        db.session.add(u)
        db.session.commit()
        assert u.nif is None
        db.session.delete(u)
        db.session.commit()


# ── 8-10: /api/update-nif ────────────────────────────────────────────────────

def test_update_nif_valido(client, test_user):
    """NIF válido se guarda correctamente."""
    _login(client)
    res  = client.post("/api/update-nif",
                       json={"nif": "12345678Z"},
                       content_type="application/json")
    data = res.get_json()
    assert res.status_code == 200, data
    assert data.get("nif_saved") is True


def test_update_nif_invalido_devuelve_400(client, test_user):
    """NIF inválido devuelve 400."""
    _login(client)
    res = client.post("/api/update-nif",
                      json={"nif": "INVALIDO"},
                      content_type="application/json")
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_update_nif_vacio_borra_nif(client, test_user, _app):
    """NIF vacío borra el NIF guardado."""
    _login(client)
    # Guardar primero
    client.post("/api/update-nif", json={"nif": "12345678Z"},
                content_type="application/json")
    # Borrar
    res  = client.post("/api/update-nif", json={"nif": ""},
                       content_type="application/json")
    data = res.get_json()
    assert res.status_code == 200, data
    assert data.get("nif_saved") is False
    with _app.app_context():
        u = User.query.get(test_user)
        assert u.nif is None


# ── 11: /api/me incluye nif ──────────────────────────────────────────────────

def test_api_me_incluye_nif(client, test_user, _app):
    """La respuesta de /api/me contiene el campo nif."""
    _login(client)
    # Guardar un NIF primero
    client.post("/api/update-nif", json={"nif": "B12345678"},
                content_type="application/json")
    res  = client.get("/api/me")
    data = res.get_json()
    assert res.status_code == 200
    assert "nif" in data["user"]
    assert data["user"]["nif"] == "B12345678"


# ── 12: /account devuelve 200 ────────────────────────────────────────────────

def test_account_page_devuelve_200(client):
    """La página /account sigue devolviendo 200."""
    res = client.get("/account")
    assert res.status_code == 200


# ── 13-14: /api/721 con y sin NIF guardado ──────────────────────────────────

_DATOS_721_MOCK = {
    "modelo": "721",
    "ejercicio": 2024,
    "potencialmente_obligado": True,
    "informe_orientativo": True,
    "exchanges": [],
    "advertencias": [],
}

_VALIDACION_MOCK_SIN_NIF = MagicMock(
    xml_generable=False,
    es_borrador=False,
    bloqueantes=["NIF del declarante no proporcionado."],
    advertencias=[],
    por_debajo_umbral=False,
)

_VALIDACION_MOCK_CON_NIF = MagicMock(
    xml_generable=True,
    es_borrador=True,
    bloqueantes=[],
    advertencias=["Identificador fiscal del custodio pendiente de verificación."],
    por_debajo_umbral=False,
)

_NEXO_CSV = (
    "Transaction,Type,Input Currency,Input Amount,Output Currency,"
    "Output Amount,USD Equivalent,Fee,Fee Currency,Details,Date / Time (UTC)\n"
    'NXT001,Interest,NEXO,1.0,NEXO,1.0,$1.00,-,-,"approved",2024-06-01 00:00:00\n'
)


def _post_721(client, csv_content=_NEXO_CSV):
    data = {
        "exchange":  (io.BytesIO(b"exchange_placeholder"), "e"),
        "ejercicio": (None, "2024"),
        "csv":       (io.BytesIO(csv_content.encode()), "nexo.csv"),
    }
    # Override exchange field as plain string
    return client.post(
        "/api/721",
        data={"exchange": "nexo", "ejercicio": "2024",
              "csv": (io.BytesIO(csv_content.encode()), "nexo.csv")},
        content_type="multipart/form-data",
    )


@patch("app.generar_datos_modelo_721", return_value=_DATOS_721_MOCK)
@patch("app.obtener_precios_historicos", return_value={})
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
@patch("app.validar_para_xml",          return_value=_VALIDACION_MOCK_SIN_NIF)
@patch("app._motor_desde_csv_721",      return_value=MagicMock())
def test_api_721_nif_faltante(mock_motor, mock_val, mock_enr, mock_prec,
                               mock_datos, client, test_user, _app):
    """Sin NIF en el perfil, la respuesta incluye nif_faltante=True."""
    _login(client)
    # Asegurarse de que el usuario no tiene NIF
    with _app.app_context():
        u = User.query.get(test_user)
        u.nif = None
        db.session.commit()

    res  = client.post(
        "/api/721",
        data={"exchange": "nexo", "ejercicio": "2024",
              "csv": (io.BytesIO(_NEXO_CSV.encode()), "nexo.csv")},
        content_type="multipart/form-data",
    )
    data = res.get_json()
    assert res.status_code == 200, data
    assert data.get("nif_faltante") is True


@patch("app.generar_datos_modelo_721", return_value=_DATOS_721_MOCK)
@patch("app.obtener_precios_historicos", return_value={})
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
@patch("app.validar_para_xml",          return_value=_VALIDACION_MOCK_CON_NIF)
@patch("app._motor_desde_csv_721",      return_value=MagicMock())
def test_api_721_nif_guardado(mock_motor, mock_val, mock_enr, mock_prec,
                               mock_datos, client, test_user, _app):
    """Con NIF guardado en el perfil, nif_faltante=False."""
    _login(client)
    # Guardar el NIF a través del endpoint para que quede en la sesión actual
    r = client.post("/api/update-nif", json={"nif": "12345678Z"},
                    content_type="application/json")
    assert r.status_code == 200, r.get_json()

    res  = client.post(
        "/api/721",
        data={"exchange": "nexo", "ejercicio": "2024",
              "csv": (io.BytesIO(_NEXO_CSV.encode()), "nexo.csv")},
        content_type="multipart/form-data",
    )
    data = res.get_json()
    assert res.status_code == 200, data
    assert data.get("nif_faltante") is False
