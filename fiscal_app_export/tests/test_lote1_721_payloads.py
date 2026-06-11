"""
LOTE 1 — Ajustes UX del Modelo 721 tras la validación XSD runtime.

Verifica los payloads exactos de /api/721 y /api/721/xml para los estados
que cambiaron al bloquear XML sin RegistroDeDetalle:

  1. Bit2Me (entidad española) → respuesta informativa idéntica a antes.
  2. Exchange extranjero con saldo cero a 31/12:
       /api/721 → HTTP 200, sin campo xml, pendiente.xml_generable=false,
       pendiente.completo=false, bloqueante con mensaje claro.
  3. /api/721/xml en el mismo caso → 422 con 'error' específico (no genérico)
     y 'bloqueantes' con el mismo motivo.
  4. Mixto español + extranjero → XML generado (solo registro extranjero).
  5. Solo extranjero con saldo positivo → XML generado.
"""

import io
import os
import sys
import tempfile
from datetime import datetime

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-key-lote1-721")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User

_EMAIL = "lote1_721@example.com"
_PASS  = "pass-lote1-721x"
_NIF   = "12345678Z"

# Mensaje claro que debe ver el usuario cuando no hay custodios extranjeros
_MSG_CLARO = "custodios extranjeros"


@pytest.fixture(scope="module")
def _app():
    flask_app.config["TESTING"]                   = True
    flask_app.config["RATELIMIT_ENABLED"]         = False
    flask_app.config["SESSION_COOKIE_SECURE"]     = False
    flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}
    with flask_app.app_context():
        db.create_all()
        u = User(
            email=_EMAIL,
            full_name="Lote1 Payloads",
            email_verified_at=datetime.utcnow(),
            nif=_NIF,
        )
        u.set_password(_PASS)
        db.session.add(u)
        db.session.commit()
        yield flask_app
        db.session.remove()


@pytest.fixture
def client(_app):
    c = _app.test_client()
    c.post("/api/login", json={"email": _EMAIL, "password": _PASS})
    return c


# CSV Binance real: compra y venta completa ANTES del 31/12 → saldo cero
_CSV_SALDO_CERO = """Tiempo,Operación,Moneda,Cambio,Cuenta,Observación
2024-01-10 09:00:00,Transaction Buy,BTC,0.5,Spot,
2024-01-10 09:00:00,Transaction Spend,USDC,-15000,Spot,
2024-06-10 10:00:00,Transaction Buy,USDC,20000,Spot,
2024-06-10 10:00:00,Transaction Spend,BTC,-0.5,Spot,
"""


def _datos_extranjero(con_activos=True):
    """Shape de 'resultado' con un custodio extranjero (Kraken)."""
    return {
        "modelo": "721", "ejercicio": 2024,
        "exchanges": [{
            "exchange": "Kraken", "exchange_key": "kraken", "extranjero": True,
            "nombre_legal": "Payward Inc.", "nif_custodio": None, "nif_esp": None,
            "id_otro": None, "codigo_pais_iso": "US",
            "activos": ([{
                "activo": "ETH", "denominacion": "Ethereum", "siglas": "ETH",
                "cantidad": "10.0", "valor_eur": "30000.00", "origen_valor": "O",
                "clave": "T", "origen_moneda_virtual": "A",
            }] if con_activos else []),
        }],
    }


def _datos_espanola():
    return {
        "modelo": "721", "ejercicio": 2024,
        "exchanges": [{
            "exchange": "Bit2Me", "exchange_key": "bit2me", "extranjero": False,
            "nombre_legal": "Bitnovo Solutions S.L.", "nif_custodio": "B98901912",
            "nif_esp": "B98901912", "id_otro": None, "codigo_pais_iso": "ES",
            "activos": [{
                "activo": "BTC", "denominacion": "Bitcoin", "siglas": "BTC",
                "cantidad": "1.0", "valor_eur": "5000.00", "origen_valor": "O",
                "clave": "T", "origen_moneda_virtual": "A",
            }],
        }],
    }


# ── 1. Bit2Me sigue exactamente igual ─────────────────────────────────────────

def test_1_bit2me_respuesta_informativa_sin_cambios(client):
    res = client.post("/api/721", data={
        "csv": (io.BytesIO(b"Bit2Me Informe Fiscal\nEstimado usuario\n"), "bit2me.csv"),
        "exchange": "bit2me", "ejercicio": "2024",
    }, content_type="multipart/form-data")
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert "xml" not in body
    assert body["resultado"]["potencialmente_obligado"] is False
    pend = body["pendiente"]
    assert pend["xml_generable"] is False
    assert pend["completo"]      is True   # no hay nada pendiente: simplemente no aplica
    assert any("entidad española" in b for b in pend["xml_bloqueantes"])


# ── 2. Extranjero con saldo cero a 31/12: /api/721 ───────────────────────────

def test_2_extranjero_saldo_cero_estado_bloqueado_coherente(client):
    res = client.post("/api/721", data={
        "csv": (io.BytesIO(_CSV_SALDO_CERO.encode()), "binance.csv"),
        "exchange": "binance", "ejercicio": "2024",
        "nif_declarante": _NIF, "nombre_declarante": "Lote1 Payloads",
    }, content_type="multipart/form-data")
    assert res.status_code == 200, res.get_json()
    body = res.get_json()

    # El análisis previo sigue siendo válido y completo
    assert body["ok"] is True
    assert body["resultado"]["exchanges"] == []

    # No se entrega XML
    assert "xml" not in body

    # Estado coherente para la UI: bloqueado, no "XML listo"
    pend = body["pendiente"]
    assert pend["xml_generable"] is False
    assert pend["completo"]      is False
    assert any(_MSG_CLARO in b for b in pend["xml_bloqueantes"]), pend["xml_bloqueantes"]


# ── 3. Mismo caso en /api/721/xml: 422 con error específico ──────────────────

def test_3_721xml_saldo_cero_error_especifico(client):
    datos_vacios = {"modelo": "721", "ejercicio": 2024, "exchanges": []}
    res = client.post("/api/721/xml", json={
        "datos":             datos_vacios,
        "nif_declarante":    _NIF,
        "nombre_declarante": "Lote1 Payloads",
    })
    assert res.status_code == 422
    body = res.get_json()
    # 'error' debe ser el mensaje claro (showXMLError solo pinta este campo)
    assert _MSG_CLARO in body["error"], body["error"]
    assert "faltan datos obligatorios" not in body["error"]
    # 'bloqueantes' contiene el mismo motivo
    assert any(_MSG_CLARO in b for b in body["bloqueantes"])


def test_3b_721xml_solo_espanola_error_especifico(client):
    res = client.post("/api/721/xml", json={
        "datos":             _datos_espanola(),
        "nif_declarante":    _NIF,
        "nombre_declarante": "Lote1 Payloads",
    })
    assert res.status_code == 422
    body = res.get_json()
    assert _MSG_CLARO in body["error"]


def test_3c_721xml_otros_bloqueantes_mantienen_mensaje_propio(client):
    """Regresión: un bloqueante distinto (activo sin precio) debe mostrarse
    igual de específico, no el mensaje de custodios extranjeros."""
    datos = _datos_extranjero()
    datos["exchanges"][0]["activos"][0]["valor_eur"] = None
    res = client.post("/api/721/xml", json={
        "datos":             datos,
        "nif_declarante":    _NIF,
        "nombre_declarante": "Lote1 Payloads",
    })
    assert res.status_code == 422
    body = res.get_json()
    assert "ValorMonedas" in body["error"]
    assert body["bloqueantes"]


# ── 4. Mixto español + extranjero sigue generando XML ────────────────────────

def test_4_mixto_espanola_mas_extranjero_genera_xml(client):
    datos = _datos_espanola()
    datos["exchanges"].append(_datos_extranjero()["exchanges"][0])
    res = client.post("/api/721/xml", json={
        "datos":             datos,
        "nif_declarante":    _NIF,
        "nombre_declarante": "Lote1 Payloads",
    })
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["ok"] is True
    xml = body["xml"]
    assert xml.count("<ddii:RegistroDeDetalle>") == 1   # solo el extranjero
    assert "Payward" in xml
    assert "Bitnovo" not in xml                          # la española no va al XML


# ── 5. Solo extranjero con saldo positivo sigue generando XML ────────────────

def test_5_solo_extranjero_con_saldo_genera_xml(client):
    res = client.post("/api/721/xml", json={
        "datos":             _datos_extranjero(),
        "nif_declarante":    _NIF,
        "nombre_declarante": "Lote1 Payloads",
    })
    assert res.status_code == 200, res.get_json()
    body = res.get_json()
    assert body["ok"] is True
    assert body["xml"].startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert body["xml"].count("<ddii:RegistroDeDetalle>") == 1
