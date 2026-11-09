"""HTTP integration tests for the Binance multisource importer.

All fixtures are synthetic. No user exports or identifiers are stored here.
"""
import io
import os
import sys
import tempfile
import zipfile
from datetime import datetime

import pytest

_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY", "test-secret-binance-multi-http")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User


SPOT_HEADER = (
    "Número de pedido,Tiempo,Par,Lado,Precio,Ejecutado,Cantidad,Tarifa,"
    "Par de conversión de AOR,Tasa de conversión de AOR\n"
)
CONVERT_HEADER = (
    "Tiempo,Billetera,Par,Tipo,Vender,Comprar,Precio,Precio inverso,"
    "Fecha actualizada,Estado\n"
)


@pytest.fixture(scope="module")
def _app():
    flask_app.config.update(
        TESTING=True,
        RATELIMIT_ENABLED=False,
        WTF_CSRF_ENABLED=False,
        SESSION_COOKIE_SECURE=False,
        SQLALCHEMY_ENGINE_OPTIONS={},
    )
    with flask_app.app_context():
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(_app):
    return _app.test_client()


@pytest.fixture
def usuario(_app):
    with _app.app_context():
        u = User(
            email="binance-multi@example.invalid",
            full_name="Binance Multi",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("p")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


def _login(client):
    client.post(
        "/api/login",
        json={"email": "binance-multi@example.invalid", "password": "p"},
    )
    return client


def _spot_csv():
    return (
        SPOT_HEADER
        + "1,2025-01-01 10:00:00,XRPEUR,BUY,2,10XRP,20EUR,0XRP,,\n"
        + "2,2025-02-01 10:00:00,XRPEUR,SELL,3,5XRP,15EUR,0EUR,,\n"
    ).encode("utf-8-sig")


def test_anos_binance_multi_detecta_fuente_y_ejercicio(client, usuario):
    _login(client)
    r = client.post(
        "/api/binance/anos",
        data={"csv": (io.BytesIO(_spot_csv()), "Binance-Spot-(UTC+1).csv")},
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 200
    assert body["ok"] is True
    assert body["anos"] == [2025]
    assert body["resumen"]["spot_trades"]["registros"] == 2


def test_analizar_binance_multi_genera_fifo_sintetico(client, usuario):
    _login(client)
    r = client.post(
        "/api/binance/analizar",
        data={
            "csv": (io.BytesIO(_spot_csv()), "Binance-Spot-(UTC+1).csv"),
            "ejercicio": "2025",
            "nombre": "Prueba sintética",
        },
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 200, r.get_data(as_text=True)[:400]
    assert body["ok"] is True
    assert body["resumen_archivos"]["spot_trades"]["registros"] == 2
    assert body["resumen"]["operaciones_con_resultado"] == 1
    assert len(body["operaciones"]) == 1
    assert body["operaciones"][0]["activo"] == "XRP"
    assert "token" in body and body["token"]


def test_permuta_convert_sin_valor_eur_da_422_sin_pdf(client, usuario):
    _login(client)
    csv_bytes = (
        CONVERT_HEADER
        + "2025-03-01 10:00:00,SPOT,XRPUSDC,Instant,20 USDC,10 XRP,,,,Successful\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={
            "csv": (io.BytesIO(csv_bytes), "Binance-Convert-(UTC+1).csv"),
            "ejercicio": "2025",
            "nombre": "Prueba sintética",
        },
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 422
    assert "Datos fiscales no seguros" in body["error"]
    assert "valoración" in body["error"].lower()
    assert "token" not in body
    assert "resumen" not in body


def test_zip_slip_rechazado_en_frontera_http(client, usuario):
    _login(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../escape.csv", SPOT_HEADER)
    buf.seek(0)

    r = client.post(
        "/api/binance/anos",
        data={"csv": (buf, "Binance-export.zip")},
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 400
    assert body["ok"] is False
    assert "rutas no permitidas" in body["error"]


def test_dos_csv_identicos_se_rechazan_antes_de_calcular(client, usuario):
    _login(client)
    payload = _spot_csv()
    r = client.post(
        "/api/binance/anos",
        data={
            "csv": [
                (io.BytesIO(payload), "spot-a.csv"),
                (io.BytesIO(payload), "spot-b.csv"),
            ]
        },
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 400
    assert body["ok"] is False
    assert "dos veces" in body["error"]


def test_http_mas_de_32000_fills_spot_sin_truncamiento_fifo_pdf(client, usuario):
    """Regresión sintética >32k: origen histórico completo, venta, FIFO e informe."""
    _login(client)
    lines = [SPOT_HEADER]
    for n in range(32_005):
        lines.append(
            f"{1000+n},2025-01-01 10:00:00,XRPEUR,BUY,2,1XRP,2EUR,0XRP,,\n"
        )
    lines.append("999999,2025-01-02 10:00:00,XRPEUR,SELL,3,1XRP,3EUR,0EUR,,\n")
    payload = "".join(lines).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={
            "csv": (io.BytesIO(payload), "Binance-Spot-32k-(UTC+1).csv"),
            "ejercicio": "2025",
            "nombre": "Caso sintético más de 32000",
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 200, r.get_data(as_text=True)[:400]
    body = r.get_json()
    assert body["ok"] is True
    assert body["resumen_archivos"]["spot_trades"]["registros"] == 32_006
    assert body["resumen"]["operaciones_con_resultado"] == 1
    assert body["resumen"]["resultado_neto"] == pytest.approx(1.0)
    assert "token" in body and body["token"]



def test_http_spot_par_inconsistente_422_sin_pdf(client, usuario):
    _login(client)
    incorrect = (
        SPOT_HEADER
        + "100,2025-01-01 10:00:00,BTCEUR,BUY,2,1XRP,2EUR,0XRP,,\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(incorrect), "Binance-Spot-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Sintético"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 422
    body = r.get_json()
    assert "token" not in body
    assert "Datos fiscales no seguros" in body["error"]


def test_http_convert_estado_desconocido_422_sin_pdf(client, usuario):
    _login(client)
    future_state = (
        CONVERT_HEADER
        + "2025-01-01 10:00:00,SPOT,XRPEUR,Instant,2 EUR,1 XRP,,,,NewFutureState\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(future_state), "Binance-Convert-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Sintético"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 422
    body = r.get_json()
    assert "token" not in body


def test_http_csv_columnas_desalineadas_400_sin_pdf(client, usuario):
    _login(client)
    malformed = (
        SPOT_HEADER
        + "100,2025-01-01 10:00:00,XRPEUR,BUY,2,1XRP\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(malformed), "Binance-Spot-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Sintético"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert "token" not in r.get_json()
    assert "número de columnas" in r.get_json()["error"]


def test_http_filas_iguales_entre_csv_distintos_422(client, usuario):
    _login(client)
    duplicated = "100,2025-01-01 10:00:00,XRPEUR,BUY,2,1XRP,2EUR,0XRP,,\n"
    extra = "101,2025-01-01 10:01:00,XRPEUR,BUY,2,1XRP,2EUR,0XRP,,\n"
    r = client.post(
        "/api/binance/analizar",
        data={"csv": [
            (io.BytesIO((SPOT_HEADER + duplicated + extra).encode("utf-8")),
             "spot-part1.csv"),
            (io.BytesIO((SPOT_HEADER + duplicated).encode("utf-8")),
             "spot-part2.csv"),
        ], "ejercicio": "2025", "nombre": "Sintético"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 422
    assert "token" not in r.get_json()



def test_http_spot_aor_no_reconstruido_422_sin_token(client, usuario):
    _login(client)
    aor = (
        SPOT_HEADER
        + "42,2025-02-01 12:00:00,XRPEUR,BUY,2,10XRP,20EUR,0XRP,XRPEUR,1\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(aor), "Binance-Spot-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Prueba sintética AOR"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 422
    body = r.get_json()
    assert "Datos fiscales no seguros" in body["error"]
    assert "token" not in body
