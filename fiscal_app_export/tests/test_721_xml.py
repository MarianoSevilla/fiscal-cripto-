"""
Tests para el endpoint /api/721/xml (generación guiada de XML con datos manuales).

 1.  Sin autenticación → 401/302.
 2.  Payload vacío → 400.
 3.  Campo 'datos' inválido → 400.
 4.  NIF faltante sin NIF en perfil → 400.
 5.  NIF inválido en payload → 400.
 6.  Con NIF en perfil y datos válidos → 200, contiene XML.
 7.  Con NIF en payload y datos válidos → 200, contiene XML.
 8.  Override de precio manual → se aplica al XML.
 9.  Valor EUR negativo → 400.
10.  Valor EUR no numérico → 400.
11.  IDType de custodio inválido → 400.
12.  Override de custodio completo → OK (IDType 04).
13.  Sin nombre del declarante → 400.
14.  ErrXMLBloqueado si activos sin precio → 422.
"""

import io
import sys
import os
import tempfile
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

# ── Configurar entorno ────────────────────────────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-key-xml721-only")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db, limiter as flask_limiter
from models import User


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _app():
    flask_app.config["TESTING"]              = True
    flask_app.config["RATELIMIT_ENABLED"]    = False
    flask_app.config["WTF_CSRF_ENABLED"]     = False
    flask_app.config["SESSION_COOKIE_SECURE"] = False
    flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}
    # Resetear el almacenamiento en memoria del rate limiter para evitar que
    # los contadores de otros módulos de test provoquen 429 inesperados.
    try:
        flask_limiter.reset()
    except Exception:
        pass
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(_app):
    return _app.test_client()


@pytest.fixture
def user_sin_nif(_app):
    with _app.app_context():
        u = User(
            email="xml721_sinnif@example.com",
            full_name="Test Sin NIF",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("pass-xml-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture
def user_con_nif(_app):
    with _app.app_context():
        u = User(
            email="xml721_connif@example.com",
            full_name="Test Con NIF",
            email_verified_at=datetime.utcnow(),
            nif="12345678Z",
        )
        u.set_password("pass-xml-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


def _login(client, email, password="pass-xml-1234"):
    client.post("/api/login", json={"email": email, "password": password})
    return client


# ── Datos de prueba ────────────────────────────────────────────────────────────

# Datos mínimos de análisis 721 con un exchange extranjero y un activo con precio ya cargado
_DATOS_CON_PRECIO = {
    "modelo":   "721",
    "ejercicio": 2024,
    "potencialmente_obligado": True,
    "informe_orientativo": True,
    "advertencias": [],
    "exchanges": [
        {
            "exchange":       "Nexo",
            "exchange_key":   "nexo",
            "extranjero":     True,
            "nombre_legal":   "Nexo Capital Inc.",
            "nif_custodio":   None,
            "nif_esp":        None,
            "id_otro":        None,
            "codigo_pais_iso": None,
            "activos": [
                {
                    "activo":       "XRP",
                    "denominacion": "XRP",
                    "siglas":       "XRP",
                    "cantidad":     "2915.97",
                    "valor_eur":    "5999.99",   # precio ya disponible
                    "origen_valor": "CoinGecko",
                    "clave":        "T",
                    "origen_moneda_virtual": "A",
                }
            ],
        }
    ],
}

# Datos con activo SIN precio (bloqueante si no se aporta manualmente)
_DATOS_SIN_PRECIO = {
    "modelo":   "721",
    "ejercicio": 2024,
    "potencialmente_obligado": True,
    "informe_orientativo": True,
    "advertencias": [],
    "exchanges": [
        {
            "exchange":       "Nexo",
            "exchange_key":   "nexo",
            "extranjero":     True,
            "nombre_legal":   "Nexo Capital Inc.",
            "nif_custodio":   None,
            "nif_esp":        None,
            "id_otro":        None,
            "codigo_pais_iso": None,
            "activos": [
                {
                    "activo":       "XRP",
                    "denominacion": "XRP",
                    "siglas":       "XRP",
                    "cantidad":     "2915.97",
                    "valor_eur":    None,   # precio PENDIENTE
                    "origen_valor": None,
                    "clave":        "T",
                    "origen_moneda_virtual": "A",
                }
            ],
        }
    ],
}

# Validación mock que simula XML generable (datos completos)
_MOCK_GENERABLE = MagicMock(
    xml_generable=True,
    es_borrador=True,
    bloqueantes=[],
    advertencias=["ID custodio pendiente."],
    por_debajo_umbral=False,
)

# Validación mock bloqueada (activo sin precio)
_MOCK_BLOQUEADO = MagicMock(
    xml_generable=False,
    es_borrador=False,
    bloqueantes=["ValorMonedas no disponible para: XRP."],
    advertencias=[],
    por_debajo_umbral=False,
)

# XML de muestra (simplificado, basta con un string no vacío)
_XML_MUESTRA = '<?xml version="1.0" encoding="UTF-8"?>\n<ddiiD:Declaracion/>'


# ── Tests ─────────────────────────────────────────────────────────────────────

# 1. Sin autenticación
def test_sin_auth_redirige(client):
    """Sin cookie de sesión, /api/721/xml devuelve 401 o 302."""
    res = client.post("/api/721/xml", json={"datos": {}})
    assert res.status_code in (401, 302)


# 2. Payload vacío
def test_payload_vacio(client, user_sin_nif, _app):
    """Payload sin 'datos' → 400."""
    _login(client, "xml721_sinnif@example.com")
    res = client.post("/api/721/xml", json={}, content_type="application/json")
    assert res.status_code == 400
    assert "datos" in res.get_json().get("error", "").lower()


# 3. Campo 'datos' inválido
def test_datos_invalido(client, user_sin_nif):
    """Campo 'datos' sin 'exchanges' → 400."""
    _login(client, "xml721_sinnif@example.com")
    res = client.post("/api/721/xml",
                      json={"datos": {"sin_exchanges": True}},
                      content_type="application/json")
    assert res.status_code == 400


# 4. NIF faltante sin NIF en perfil
def test_nif_faltante_sin_perfil(client, user_sin_nif, _app):
    """Sin NIF en perfil ni en payload → 400."""
    _login(client, "xml721_sinnif@example.com")
    # Asegurar que no hay NIF en perfil
    with _app.app_context():
        u = User.query.filter_by(email="xml721_sinnif@example.com").first()
        u.nif = None
        db.session.commit()

    res = client.post("/api/721/xml",
                      json={"datos": _DATOS_CON_PRECIO},
                      content_type="application/json")
    data = res.get_json()
    assert res.status_code == 400, data
    assert "nif" in data.get("error", "").lower()


# 5. NIF inválido en payload
def test_nif_invalido_en_payload(client, user_sin_nif):
    """NIF con formato inválido en payload → 400."""
    _login(client, "xml721_sinnif@example.com")
    res = client.post("/api/721/xml",
                      json={
                          "datos":          _DATOS_CON_PRECIO,
                          "nif_declarante": "INVALIDO",
                          "nombre_declarante": "Test Usuario",
                      },
                      content_type="application/json")
    assert res.status_code == 400
    assert "válido" in res.get_json().get("error", "").lower() or \
           "formato" in res.get_json().get("error", "").lower()


# 6. Con NIF en perfil y datos válidos → genera XML
@patch("app.generar_xml_721", return_value=(_XML_MUESTRA, _MOCK_GENERABLE))
def test_nif_desde_perfil_genera_xml(mock_xml, client, user_con_nif, _app):
    """Con NIF en perfil y datos completos → 200 con XML."""
    _login(client, "xml721_connif@example.com")
    res = client.post("/api/721/xml",
                      json={"datos": _DATOS_CON_PRECIO},
                      content_type="application/json")
    data = res.get_json()
    assert res.status_code == 200, data
    assert data.get("ok") is True
    assert data.get("xml") == _XML_MUESTRA
    mock_xml.assert_called_once()


# 7. Con NIF en payload → genera XML
@patch("app.generar_xml_721", return_value=(_XML_MUESTRA, _MOCK_GENERABLE))
def test_nif_en_payload_genera_xml(mock_xml, client, user_sin_nif, _app):
    """NIF válido en payload → 200 con XML."""
    _login(client, "xml721_sinnif@example.com")
    with _app.app_context():
        u = User.query.filter_by(email="xml721_sinnif@example.com").first()
        u.nif = None
        db.session.commit()

    res = client.post("/api/721/xml",
                      json={
                          "datos":          _DATOS_CON_PRECIO,
                          "nif_declarante": "12345678Z",
                          "nombre_declarante": "Test Usuario",
                      },
                      content_type="application/json")
    data = res.get_json()
    assert res.status_code == 200, data
    assert data.get("xml") == _XML_MUESTRA


# 8. Override de precio manual se aplica
@patch("app.generar_xml_721", return_value=(_XML_MUESTRA, _MOCK_GENERABLE))
def test_override_precio_manual(mock_xml, client, user_con_nif):
    """Valor EUR manual se aplica al activo antes de generar el XML."""
    _login(client, "xml721_connif@example.com")
    res = client.post("/api/721/xml",
                      json={
                          "datos":   _DATOS_SIN_PRECIO,
                          "valores": {"XRP": {"valor_eur": 4500.00, "origen": "CoinGecko"}},
                      },
                      content_type="application/json")
    data = res.get_json()
    assert res.status_code == 200, data
    # El activo en los datos enviados a generar_xml_721 debe tener valor_eur
    call_datos = mock_xml.call_args[0][0]
    activo_xrp = call_datos["exchanges"][0]["activos"][0]
    assert activo_xrp["valor_eur"] == "4500.00"
    assert activo_xrp["origen_valor"] == "CoinGecko"


# 9. Valor EUR negativo → 400
def test_valor_eur_negativo(client, user_con_nif):
    """Valor EUR negativo → 400."""
    _login(client, "xml721_connif@example.com")
    res = client.post("/api/721/xml",
                      json={
                          "datos":   _DATOS_SIN_PRECIO,
                          "valores": {"XRP": {"valor_eur": -100.0, "origen": "CoinGecko"}},
                      },
                      content_type="application/json")
    assert res.status_code == 400
    assert "negativo" in res.get_json().get("error", "").lower()


# 10. Valor EUR no numérico → 400
def test_valor_eur_no_numerico(client, user_con_nif):
    """Valor EUR no numérico → 400."""
    _login(client, "xml721_connif@example.com")
    res = client.post("/api/721/xml",
                      json={
                          "datos":   _DATOS_SIN_PRECIO,
                          "valores": {"XRP": {"valor_eur": "no-es-numero", "origen": "CoinGecko"}},
                      },
                      content_type="application/json")
    assert res.status_code == 400
    assert "inválido" in res.get_json().get("error", "").lower() or \
           "invalid" in res.get_json().get("error", "").lower()


# 11. IDType de custodio inválido → 400
def test_idtype_custodio_invalido(client, user_con_nif):
    """IDType fuera del rango válido → 400."""
    _login(client, "xml721_connif@example.com")
    res = client.post("/api/721/xml",
                      json={
                          "datos": _DATOS_CON_PRECIO,
                          "custodios": {
                              "nexo": {"codigo_pais": "BG", "id_type": "99", "id": "BG123"}
                          },
                      },
                      content_type="application/json")
    assert res.status_code == 400
    assert "IDType" in res.get_json().get("error", "") or \
           "válido" in res.get_json().get("error", "").lower()


# 12. Override de custodio completo → OK
@patch("app.generar_xml_721", return_value=(_XML_MUESTRA, _MOCK_GENERABLE))
def test_override_custodio_ok(mock_xml, client, user_con_nif):
    """Custodio manual con IDType 04 se aplica correctamente."""
    _login(client, "xml721_connif@example.com")
    res = client.post("/api/721/xml",
                      json={
                          "datos": _DATOS_CON_PRECIO,
                          "custodios": {
                              "nexo": {
                                  "codigo_pais": "BG",
                                  "id_type":     "04",
                                  "id":          "BG123456789",
                                  "nombre":      "Nexo Capital Inc.",
                              }
                          },
                      },
                      content_type="application/json")
    data = res.get_json()
    assert res.status_code == 200, data
    # Verificar que el exchange recibió id_otro
    call_datos = mock_xml.call_args[0][0]
    exc = call_datos["exchanges"][0]
    assert exc.get("id_otro") is not None
    assert exc["id_otro"]["id"] == "BG123456789"
    assert exc["id_otro"]["id_type"] == "04"


# 13. Sin nombre del declarante → 400
def test_sin_nombre_declarante(client, _app):
    """Sin nombre en perfil ni en payload → 400.

    Crea un usuario sin full_name y sin NIF antes de hacer login,
    para evitar que el identity map de SQLAlchemy cachee el nombre.
    """
    email = "xml721_sinnombre@example.com"
    with _app.app_context():
        # Limpiar posible usuario previo
        User.query.filter_by(email=email).delete()
        db.session.commit()
        u = User(
            email=email,
            full_name="",        # sin nombre
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("pass-xml-1234")
        db.session.add(u)
        db.session.commit()

    try:
        _login(client, email)
        res = client.post("/api/721/xml",
                          json={
                              "datos":          _DATOS_CON_PRECIO,
                              "nif_declarante": "12345678Z",
                              # nombre_declarante omitido intencionalmente
                          },
                          content_type="application/json")
        data = res.get_json()
        assert res.status_code == 400, data
        assert "nombre" in data.get("error", "").lower()
    finally:
        with _app.app_context():
            User.query.filter_by(email=email).delete()
            db.session.commit()


# 14. ErrXMLBloqueado cuando activo sin precio (sin override)
from app import ErrXMLBloqueado

def test_xml_bloqueado_sin_precio(client, user_con_nif):
    """Si activo sin precio y sin override manual → 422 ErrXMLBloqueado."""
    _login(client, "xml721_connif@example.com")
    # No aportamos override de precio → generar_xml_721 real lanzará ErrXMLBloqueado
    res = client.post("/api/721/xml",
                      json={"datos": _DATOS_SIN_PRECIO},
                      content_type="application/json")
    data = res.get_json()
    assert res.status_code == 422, data
    assert "bloqueantes" in data or "datos obligatorios" in data.get("error", "").lower()
