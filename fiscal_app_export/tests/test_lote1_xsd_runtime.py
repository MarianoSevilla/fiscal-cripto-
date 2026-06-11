"""
LOTE 1 — Tarea 5: validación XSD en runtime para el Modelo 721.

Antes: validar_xml_contra_xsd existía pero ningún endpoint la ejecutaba —
una regresión del generador habría entregado XML inválidos para la AEAT
sin detección.

Ahora generar_xml_721:
  · valida el XML contra Declaracion721.xsd antes de devolverlo
  · lanza ErrXMLInvalidoXSD si no pasa el esquema (no se entrega el XML)
  · fail-open SOLO si el validador no está disponible (ImportError /
    FileNotFoundError), manteniendo el comportamiento previo

Y /api/721/xml devuelve un error controlado (500 con mensaje claro) en
lugar de entregar un fichero que la AEAT rechazaría.
"""

import os
import sys
import tempfile
from datetime import datetime

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-key-lote1-xsd")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import generador_xml_721 as gx
from generador_xml_721 import (
    generar_xml_721,
    validar_xml_contra_xsd,
    ErrXMLInvalidoXSD,
)


# ── Datos 721 completos (mismo shape que produce /api/721) ───────────────────

def _datos_completos():
    return {
        "modelo":   "721",
        "ejercicio": 2024,
        "potencialmente_obligado": True,
        "informe_orientativo": True,
        "advertencias": [],
        "exchanges": [
            {
                "exchange":        "Nexo",
                "exchange_key":    "nexo",
                "extranjero":      True,
                "nombre_legal":    "Nexo Capital Inc.",
                "nif_custodio":    None,
                "nif_esp":         None,
                "id_otro":         None,
                "codigo_pais_iso": None,
                "activos": [
                    {
                        "activo":       "XRP",
                        "denominacion": "XRP",
                        "siglas":       "XRP",
                        "cantidad":     "2915.97",
                        "valor_eur":    "5999.99",
                        "origen_valor": "CoinGecko",
                        "clave":        "T",
                        "origen_moneda_virtual": "A",
                    }
                ],
            }
        ],
    }


# ── 1. El XML real generado pasa el XSD oficial ───────────────────────────────

def test_xml_generado_pasa_xsd_borrador():
    """Variante BORRADOR (custodio con placeholder PENDIENTE/06)."""
    xml, validacion = generar_xml_721(_datos_completos(), "12345678Z", "Nombre Test")
    ok, errores = validar_xml_contra_xsd(xml)
    assert ok, f"XML borrador no pasa XSD: {errores[:3]}"
    assert validacion.xml_generable


def test_xml_generado_pasa_xsd_custodio_completo():
    """Variante con IDOtro completo y domicilio."""
    datos = _datos_completos()
    datos["exchanges"][0].update({
        "id_otro":        {"codigo_pais": "CH", "id_type": "04", "id": "CHE123456789"},
        "codigo_pais_iso": "CH",
        "nif_custodio":    "CHE123456789",
        "direccion":       "Bahnhofstrasse 21, Zug",
    })
    xml, _ = generar_xml_721(datos, "12345678Z", "Nombre Test")
    ok, errores = validar_xml_contra_xsd(xml)
    assert ok, f"XML completo no pasa XSD: {errores[:3]}"


# ── 2. XML inválido → ErrXMLInvalidoXSD, no se entrega ────────────────────────

def test_xml_invalido_lanza_excepcion(monkeypatch):
    """Si la validación XSD reporta errores, generar_xml_721 no devuelve XML."""
    monkeypatch.setattr(
        gx, "validar_xml_contra_xsd",
        lambda xml: (False, ["Elemento 'X' inesperado (simulado)"]),
    )
    with pytest.raises(ErrXMLInvalidoXSD) as exc_info:
        generar_xml_721(_datos_completos(), "12345678Z", "Nombre Test")
    assert "simulado" in str(exc_info.value)
    assert exc_info.value.errores


def test_validador_no_disponible_mantiene_comportamiento(monkeypatch):
    """Fail-open: si xmlschema/XSD no están disponibles, se entrega el XML
    como antes del LOTE 1 (con warning en el log), sin romper producción."""
    def _raise_import(xml):
        raise ImportError("xmlschema no está instalado (simulado)")
    monkeypatch.setattr(gx, "validar_xml_contra_xsd", _raise_import)

    xml, validacion = generar_xml_721(_datos_completos(), "12345678Z", "Nombre Test")
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert validacion.xml_generable


def test_xml_manipulado_detectado_por_validador():
    """Sanidad del validador: un XML estructuralmente roto reporta errores."""
    xml, _ = generar_xml_721(_datos_completos(), "12345678Z", "Nombre Test")
    xml_roto = xml.replace("<ddii:Modelo>721</ddii:Modelo>", "")
    ok, errores = validar_xml_contra_xsd(xml_roto)
    assert not ok
    assert errores


# ── 3. Endpoint /api/721/xml: error controlado ────────────────────────────────

from unittest.mock import patch

from app import app as flask_app, db, limiter as flask_limiter
from models import User

_EMAIL = "lote1_xsd@example.com"
_PASS  = "pass-lote1-1234"


@pytest.fixture(scope="module")
def _app():
    flask_app.config["TESTING"]                   = True
    flask_app.config["RATELIMIT_ENABLED"]         = False
    flask_app.config["SESSION_COOKIE_SECURE"]     = False
    flask_app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {}
    try:
        flask_limiter.reset()
    except Exception:
        pass
    with flask_app.app_context():
        db.create_all()
        u = User(
            email=_EMAIL,
            full_name="Lote1 XSD",
            email_verified_at=datetime.utcnow(),
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


def test_endpoint_devuelve_error_controlado_si_xsd_falla(client):
    """Si el XML no pasa el XSD, /api/721/xml responde 500 con mensaje claro
    y SIN campo xml en la respuesta."""
    with patch(
        "app.generar_xml_721",
        side_effect=ErrXMLInvalidoXSD(["error XSD simulado"]),
    ):
        res = client.post("/api/721/xml", json={
            "datos":             _datos_completos(),
            "nif_declarante":    "12345678Z",
            "nombre_declarante": "Lote1 XSD",
        })
    assert res.status_code == 500
    body = res.get_json()
    assert "esquema oficial" in body["error"]
    assert "xml" not in body


def test_endpoint_flujo_real_sigue_entregando_xml(client):
    """Camino feliz sin mocks: el XML real se genera, pasa el XSD en runtime
    y se entrega normalmente."""
    res = client.post("/api/721/xml", json={
        "datos":             _datos_completos(),
        "nif_declarante":    "12345678Z",
        "nombre_declarante": "Lote1 XSD",
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["xml"].startswith('<?xml version="1.0" encoding="UTF-8"?>')
