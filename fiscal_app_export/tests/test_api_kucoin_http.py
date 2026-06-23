"""
Tests HTTP del soporte KuCoin (flujo multiarchivo, endpoint dedicado).

Cubre:
  · /api/kucoin/anos — detección de años + resumen de archivos (multiarchivo)
  · /api/kucoin/analizar — análisis FIFO completo con varios CSV a la vez
  · subir un solo CSV
  · fichero vacío "No matching records found." no rompe el proceso
  · ficheros no reconocidos → error amigable
  · auth requerida
"""

import io
import os
import sys
import tempfile
from datetime import datetime

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-kucoin-http")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "kucoin")
F_VACIO    = os.path.join(FIXTURES, "Historial de depósitos_retiradas_Historial de depósitos.csv")
F_FINANC   = os.path.join(FIXTURES, "Historial de la cuenta_Cuenta de financiación.csv")
F_TRADING  = os.path.join(FIXTURES, "Historial de la cuenta_Cuenta de trading.csv")
F_FIAT_ORD = os.path.join(FIXTURES, "Órdenes fiat_Depósitos fiat.csv")


def _file(path):
    with open(path, "rb") as f:
        return (io.BytesIO(f.read()), os.path.basename(path))


@pytest.fixture(scope="module")
def _app():
    flask_app.config.update(TESTING=True, RATELIMIT_ENABLED=False,
                            WTF_CSRF_ENABLED=False, SESSION_COOKIE_SECURE=False,
                            SQLALCHEMY_ENGINE_OPTIONS={})
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove(); db.drop_all()


@pytest.fixture
def client(_app):
    return _app.test_client()


@pytest.fixture
def usuario(_app):
    with _app.app_context():
        u = User(email="kucoin@e.com", full_name="K", email_verified_at=datetime.utcnow())
        u.set_password("p"); db.session.add(u); db.session.commit(); uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete(); db.session.commit()


def _login(client):
    client.post("/api/login", json={"email": "kucoin@e.com", "password": "p"})
    return client


# ── AUTH ───────────────────────────────────────────────────────────────────────

def test_anos_requiere_login(client):
    r = client.post("/api/kucoin/anos",
                    data={"csv": [_file(F_TRADING)]},
                    content_type="multipart/form-data")
    assert r.status_code in (401, 302)


# ── /api/kucoin/anos ───────────────────────────────────────────────────────────

def test_anos_multiarchivo_detecta_anos_y_resumen(client, usuario):
    _login(client)
    r = client.post("/api/kucoin/anos",
                    data={"csv": [_file(F_TRADING), _file(F_FINANC),
                                  _file(F_FIAT_ORD), _file(F_VACIO)]},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert 2025 in body["anos"]
    res = body["resumen"]
    assert res["trading"]["detectado"] is True
    assert res["financiacion"]["detectado"] is True
    assert res["deposito_cripto"]["vacio"] is True
    assert isinstance(body["advertencias"], list)


def test_anos_un_solo_fichero(client, usuario):
    _login(client)
    r = client.post("/api/kucoin/anos",
                    data={"csv": [_file(F_TRADING)]},
                    content_type="multipart/form-data")
    body = r.get_json()
    assert body["ok"] is True
    assert 2025 in body["anos"]


def test_anos_solo_vacio_no_rompe(client, usuario):
    _login(client)
    r = client.post("/api/kucoin/anos",
                    data={"csv": [_file(F_VACIO)]},
                    content_type="multipart/form-data")
    body = r.get_json()
    assert body["ok"] is True
    assert body["resumen"]["deposito_cripto"]["vacio"] is True


def test_anos_fichero_no_reconocido(client, usuario):
    _login(client)
    r = client.post("/api/kucoin/anos",
                    data={"csv": [(io.BytesIO(b"foo,bar,baz\n1,2,3\n"), "raro.csv")]},
                    content_type="multipart/form-data")
    body = r.get_json()
    assert body["ok"] is False
    assert "kucoin" in body["error"].lower() or "reconoce" in body["error"].lower()


# ── /api/kucoin/analizar ───────────────────────────────────────────────────────

def test_analizar_multiarchivo_ok(client, usuario):
    _login(client)
    r = client.post("/api/kucoin/analizar",
                    data={"csv": [_file(F_TRADING), _file(F_FINANC),
                                  _file(F_FIAT_ORD), _file(F_VACIO)],
                          "ejercicio": "all", "nombre": "K"},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert "token" in body and body["token"]
    assert "resumen" in body and "resultado_neto" in body["resumen"]
    assert "resumen_archivos" in body
    assert body["resumen_archivos"]["trading"]["detectado"] is True
    assert isinstance(body["advertencias"], list)
    # Aviso de productos no cubiertos siempre presente
    assert any("staking" in a.lower() for a in body["advertencias"])


def test_analizar_un_solo_fichero(client, usuario):
    _login(client)
    r = client.post("/api/kucoin/analizar",
                    data={"csv": [_file(F_TRADING)], "ejercicio": "all"},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_analizar_solo_vacio_no_rompe(client, usuario):
    _login(client)
    r = client.post("/api/kucoin/analizar",
                    data={"csv": [_file(F_VACIO)], "ejercicio": "all"},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True


def test_analizar_no_csv_rechazado(client, usuario):
    _login(client)
    r = client.post("/api/kucoin/analizar",
                    data={"csv": [(io.BytesIO(b"x"), "f.txt")], "ejercicio": "all"},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert ".csv" in r.get_json()["error"]


def test_analizar_sin_ficheros(client, usuario):
    _login(client)
    r = client.post("/api/kucoin/analizar",
                    data={"ejercicio": "all"},
                    content_type="multipart/form-data")
    assert r.status_code == 400
