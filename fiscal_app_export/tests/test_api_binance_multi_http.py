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



def test_http_deposito_externo_no_se_oculta_aunque_haya_compras_locales(client, usuario):
    """Una venta puede parecer cubierta por compra Spot pero requerir un lote
    anterior depositado desde fuera: no asignar el coste local a ciegas.
    """
    _login(client)
    spot_csv = (
        SPOT_HEADER
        + "invented-buy,2025-04-05 10:00:00,XRPEUR,BUY,2,10XRP,20EUR,0XRP,,\n"
        + "invented-sell,2025-04-10 10:00:00,XRPEUR,SELL,3,5XRP,15EUR,0EUR,,\n"
    ).encode("utf-8-sig")
    deposit_csv = (
        "Tiempo,Moneda,Red,Cantidad,Dirección,TXID,Estado\n"
        "2025-04-04 10:00:00,XRP,XRP,10,synthetic-address,"
        "synthetic-deposit,Completed\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={
            "csv": [
                (io.BytesIO(spot_csv), "Binance-Spot-(UTC+1).csv"),
                (io.BytesIO(deposit_csv), "Binance-Deposits-(UTC+1).csv"),
            ],
            "ejercicio": "2025",
            "nombre": "Ensayo de coste externo",
        },
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 422
    assert "depósitos cripto" in body["error"].lower()
    assert "lotes" in body["error"].lower()
    assert "token" not in body
    assert "resumen" not in body


def test_http_solo_deposito_externo_no_emite_posicion_fifo_vacia(client, usuario):
    """Un depósito sin coste no se traduce en una cartera FIFO vacía."""
    _login(client)
    deposit_csv = (
        "Tiempo,Moneda,Red,Cantidad,Dirección,TXID,Estado\n"
        "2025-04-04 10:00:00,XRP,XRP,10,synthetic-address,"
        "synthetic-deposit,Completed\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={
            "csv": (io.BytesIO(deposit_csv), "Binance-Deposits-(UTC+1).csv"),
            "ejercicio": "2025",
            "nombre": "Ensayo depósito sin compras",
        },
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 422
    assert "depósitos cripto" in body["error"].lower()
    assert "token" not in body



def test_http_earn_recompensa_no_se_emite_como_fifo_vacio(client, usuario):
    """Fuente Earn reconocida; sin base EUR de recompensa nunca hay PDF."""
    _login(client)
    reward_csv = (
        "Tiempo,Moneda,Cantidad,Tipo\n"
        "2025-05-03,ABC,0.00000001,Real-time APR Rewards\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={
            "csv": (io.BytesIO(reward_csv), "Binance-Earn-(UTC+1).csv"),
            "ejercicio": "2025",
            "nombre": "Prueba Earn inventada",
        },
        content_type="multipart/form-data",
    )
    data = r.get_json()
    assert r.status_code == 422
    assert "Simple Earn" in data["error"]
    assert "token" not in data
    assert "resumen" not in data


def test_http_conversion_small_assets_bnb_no_se_omite_como_movimiento(client, usuario):
    """El intercambio de polvo a BNB exige dos patas y valor EUR demostrable."""
    _login(client)
    tx = (
        "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"
        "synthetic,2025-06-10 12:00:00,Spot,Small Assets Exchange BNB,ABC,-1.25,\n"
        "synthetic,2025-06-10 12:00:00,Spot,Small Assets Exchange BNB,BNB,0.003,\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={
            "csv": (io.BytesIO(tx), "Binance-TX-(UTC+1).csv"),
            "ejercicio": "2025",
            "nombre": "Conversión sintética no valorada",
        },
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 422, r.get_data(as_text=True)[:400]
    assert "fuente" in body["error"].lower()
    assert "token" not in body
    assert "resumen" not in body


def test_anos_binance_earn_detecta_fechas_reales_y_no_el_anio_del_zip(client, usuario):
    """Un CSV Earn de 2025 puede traer recompensas de finales de 2024."""
    _login(client)
    data = (
        "Tiempo,Moneda,Cantidad,Tipo\n"
        "2024-12-31,ABC,0.00000001,Real-time APR Rewards\n"
        "2025-01-01,ABC,0.00000002,Real-time APR Rewards\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/anos",
        data={"csv": (io.BytesIO(data), "Binance-Earn-2025-(UTC+1).csv")},
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 200, r.get_data(as_text=True)[:400]
    assert body["anos"] == [2024, 2025]
    assert body["resumen"]["earn_flexible_rewards"]["registros"] == 2


def test_anos_binance_acepta_mas_de_100000_filas_por_streaming(client, usuario):
    """Historial real de 2021 supera el límite anterior de 100k."""
    _login(client)
    row = "synthetic,2021-01-01 00:00:00,Spot,Commission Rebate,ABC,0.00001,\n"
    txt = ("ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"
           + row * 100001)
    r = client.post(
        "/api/binance/anos",
        data={"csv": (io.BytesIO(txt.encode("utf-8")), "Binance-TX-(UTC+1).csv")},
        content_type="multipart/form-data",
    )
    body = r.get_json()
    assert r.status_code == 200, str(body)[:400]
    assert body["ok"] is True
    assert body["anos"] == [2021]
    assert body["resumen"]["transaction_history"]["registros"] == 100001


def test_anos_binance_rechaza_utf8_corrupto_sin_500(client, usuario):
    """No aceptar reemplazo silencioso de bytes en una fila monetaria."""
    _login(client)
    raw = (
        b"Tiempo,Moneda,Cantidad,Tipo\n"
        + b"2025-01-01,AB" + bytes((255,))
        + b",0.1,Real-time APR Rewards\n"
    )
    r = client.post(
        "/api/binance/anos",
        data={"csv": (io.BytesIO(raw), "Earn-corrupt-(UTC+1).csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400
    assert r.get_json()["ok"] is False
    assert "UTF-8" in r.get_json()["error"]


def test_http_solo_ledger_con_earn_bloquea_pdf_incompleto(client, usuario):
    """Sin ZIP Earn, una suscripción TX no demuestra un lote ni valor EUR."""
    _login(client)
    tx = (
        "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"
        "synthetic,2025-06-10 12:00:00,Spot,"
        "Simple Earn Flexible Subscription,BTC,-0.1,Binance Earn\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(tx), "Binance-TX-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Sintético"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 422, r.get_data(as_text=True)[:400]
    body = r.get_json()
    assert "fuente" in body["error"].lower()
    assert "token" not in body
    assert "resumen" not in body


def test_http_recompensa_nativa_y_ledger_no_emiten_pdf_por_cuadre_diario(client, usuario):
    """Una coincidencia diaria no es hora de adquisición ni valoración EUR."""
    _login(client)
    reward = (
        "Tiempo,Moneda,Cantidad,Tipo\n"
        "2025-06-10,ABC,0.125,Real-time APR Rewards\n"
    ).encode("utf-8-sig")
    ledger = (
        "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"
        "synthetic,2025-06-10 12:00:00,Spot,"
        "Simple Earn Flexible Interest,ABC,0.125,Prueba\n"
    ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": [
            (io.BytesIO(reward), "Earn-reward-(UTC+1).csv"),
            (io.BytesIO(ledger), "Binance-TX-(UTC+1).csv"),
        ], "ejercicio": "2025", "nombre": "Prueba sintética"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422, response.get_data(as_text=True)[:400]
    payload = response.get_json()
    assert "token" not in payload and "resumen" not in payload


def test_http_reward_sin_espejo_ledger_tampoco_autoriza_fifo(client, usuario):
    """Real-time APR Earn no requiere espejo Spot, pero sí valoración fiscal."""
    _login(client)
    reward = (
        "Tiempo,Moneda,Cantidad,Tipo\n"
        "2025-06-10,ABC,0.00000001,Real-time APR Rewards\n"
    ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(reward), "Earn-reward-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Prueba sintética"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422, response.get_data(as_text=True)[:400]
    payload = response.get_json()
    assert "token" not in payload and "resumen" not in payload


def _zipped_tx_rows(n, operation, basename):
    """ZIP sintético altamente compresible, con tamaño descomprimido limitado."""
    # No usar filas uniformes: un ZIP con compresión extrema debe seguir
    # rechazándose por el control anti zip-bomb antes del límite de filas.
    txt = ("ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"
           + "".join(
               f"synthetic,2021-01-01 00:00:00,Spot,{operation},"
               f"ABC,0.00001,x-{basename}-{i}\n"
               for i in range(n)
           ))
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(basename + ".csv", txt.encode("utf-8"))
    data.seek(0)
    return data


def test_anos_binance_350000_filas_sigue_bloqueando_exceso(client, usuario):
    _login(client)
    # Tres miembros distintos <10 MiB; juntos superan el tope por petición.
    uploads = [
        (_zipped_tx_rows(117001, "Commission Rebate", "part-a"), "a.zip"),
        (_zipped_tx_rows(117001, "Referrer Commission", "part-b"), "b.zip"),
        (_zipped_tx_rows(117001, "Commission History", "part-c"), "c.zip"),
    ]
    response = client.post("/api/binance/anos",
                           data={"csv": uploads},
                           content_type="multipart/form-data")
    assert response.status_code == 400
    assert "350,000" in response.get_json()["error"]


def test_anos_binance_acepta_31_zip_sin_perder_filas(client, usuario):
    _login(client)
    zips = [
        (_zipped_tx_rows(1, "Commission Rebate", str(i)), f"part-{i}.zip")
        for i in range(31)
    ]
    response = client.post("/api/binance/anos",
                           data={"csv": zips},
                           content_type="multipart/form-data")
    assert response.status_code == 200, response.get_data(as_text=True)[:400]
    payload = response.get_json()
    assert payload["anos"] == [2021]
    assert payload["resumen"]["transaction_history"]["registros"] == 31
    assert not any("conciliación" in a.lower() for a in payload["advertencias"])


def test_http_binance_dust_multi_asset_remains_blocked(client, usuario):
    _login(client)
    raw = (
        "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"
        "synthetic,2025-02-02 12:00:00,Spot,Small Assets Exchange BNB,AAA,-2,\n"
        "synthetic,2025-02-02 12:00:00,Spot,Small Assets Exchange BNB,BBB,-3,\n"
        "synthetic,2025-02-02 12:00:00,Spot,Small Assets Exchange BNB,BNB,0.005,\n"
    ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(raw), "Binance-TX-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Synthetic"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422, response.get_data(as_text=True)[:250]
    payload = response.get_json()
    assert "token" not in payload
    assert "resumen" not in payload


def test_aeat_eur_fifo_multiyear_fees_download_pdf_single_use(client, usuario):
    """Aceptación completa: FIFO 2025 con compras 2023/2024 y fees documentadas.

    Caso independiente calculado manualmente:
      compra A: 10 XRP - 0.1 XRP fee -> 9.9 XRP; coste 20 EUR
      compra B: 10 XRP, 1 EUR fee -> 10 XRP; coste 41 EUR
      venta 1: 12 XRP -> 60 EUR - 2 EUR fee; coste 20+2.1*4.1=28.61
      venta 2:  2 XRP -> 10 EUR - 0.5 EUR fee; coste 8.2
      ganancia 2025: 29.39+1.30 = 30.69 EUR
      posición: 5.9 XRP; coste total 24.19 EUR
    """
    _login(client)
    chunks = [
        (2023,
         "buy-a,2023-01-02 10:00:00,XRPEUR,BUY,2,10XRP,20EUR,0.1XRP,,\n"),
        (2024,
         "buy-b,2024-02-03 12:00:00,XRPEUR,BUY,4,10XRP,40EUR,1EUR,,\n"),
        (2025,
         "sale-a,2025-03-04 15:00:00,XRPEUR,SELL,5,12XRP,60EUR,2EUR,,\n"
         "sale-b,2025-07-08 16:00:00,XRPEUR,SELL,5,2XRP,10EUR,0.5EUR,,\n"),
    ]
    uploads = [
        (io.BytesIO((SPOT_HEADER + entries).encode("utf-8-sig")),
         f"Binance-Spot-{year}-(UTC+1).csv")
        for year, entries in chunks
    ]
    response = client.post(
        "/api/binance/analizar",
        data={"csv": uploads, "ejercicio": "2025", "nombre": "Ensayo AEAT sintético"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:450]
    payload = response.get_json()
    assert payload["ok"]
    assert payload["resumen_archivos"]["spot_trades"]["registros"] == 4
    assert payload["resumen"]["operaciones_con_resultado"] == 2
    assert payload["resumen"]["resultado_neto"] == pytest.approx(30.69, abs=0.0001)
    assert len(payload["operaciones"]) == 2
    by_date = {op["fecha"]: op for op in payload["operaciones"]}
    assert by_date["2025-03-04"]["coste_fifo"] == pytest.approx(28.61, abs=0.0001)
    assert by_date["2025-03-04"]["transmision"] == pytest.approx(58, abs=0.0001)
    assert by_date["2025-03-04"]["ganancia_perdida"] == pytest.approx(29.39, abs=0.0001)
    assert by_date["2025-07-08"]["coste_fifo"] == pytest.approx(8.2, abs=0.0001)
    assert by_date["2025-07-08"]["ganancia_perdida"] == pytest.approx(1.3, abs=0.0001)
    position = {p["activo"]: p for p in payload["posicion"]}
    assert position["XRP"]["cantidad"] == pytest.approx(5.9, abs=0.00000001)
    assert position["XRP"]["coste_total"] == pytest.approx(24.19, abs=0.0001)
    token = payload["token"]
    pdf = client.get(f"/api/descargar/{token}?exchange=binance")
    assert pdf.status_code == 200
    assert pdf.mimetype == "application/pdf"
    assert pdf.data.startswith(b"%PDF-")
    assert len(pdf.data) > 1000
    again = client.get(f"/api/descargar/{token}?exchange=binance")
    assert again.status_code == 403


def test_binance_same_second_eur_buy_sell_blocks_fifo_even_if_csv_ordered(client, usuario):
    """Un timestamp a segundos no acredita orden entre compra y venta XRP."""
    _login(client)
    raw = (
        SPOT_HEADER
        + "buy,2025-03-05 10:00:00,XRPEUR,BUY,2,10XRP,20EUR,0XRP,,\n"
        + "sell,2025-03-05 10:00:00,XRPEUR,SELL,3,5XRP,15EUR,0EUR,,\n"
    ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(raw), "Binance-Spot-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Ensayo simultáneo sintético"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    body = response.get_json()
    assert "token" not in body
    assert "Datos fiscales no seguros" in body["error"]


def test_binance_same_second_different_lot_cost_blocks_partial_sale(client, usuario):
    """No escoger lotes por orden accidental del ZIP cuando precios difieren."""
    _login(client)
    raw = (
        SPOT_HEADER
        + "buy-a,2025-01-05 10:00:00,XRPEUR,BUY,2,2XRP,4EUR,0XRP,,\n"
        + "buy-b,2025-01-05 10:00:00,XRPEUR,BUY,3,2XRP,6EUR,0XRP,,\n"
        + "sell-a,2025-01-06 10:00:00,XRPEUR,SELL,3,1XRP,3EUR,0EUR,,\n"
    ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(raw), "Binance-Spot-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Ensayo lotes sintéticos"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    assert "token" not in response.get_json()


def test_binance_2025_position_pdf_ignores_2026_with_full_history(client, usuario):
    """IRPF 2025 no puede mostrar en posición el saldo posterior de 2026."""
    _login(client)
    raw = (
        SPOT_HEADER
        + "buy-a,2024-06-01 10:00:00,XRPEUR,BUY,2,10XRP,20EUR,0XRP,,\n"
        + "sell-a,2025-06-01 10:00:00,XRPEUR,SELL,3,5XRP,15EUR,0EUR,,\n"
        + "buy-b,2026-05-01 10:00:00,XRPEUR,BUY,2,100XRP,200EUR,0XRP,,\n"
        + "sell-b,2026-05-02 10:00:00,XRPEUR,SELL,3,1XRP,3EUR,0EUR,,\n"
    ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(raw), "Binance-Spot-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Corte anual sintético"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:450]
    payload = response.get_json()
    assert payload["resumen_archivos"]["spot_trades"]["registros"] == 4
    assert payload["resumen"]["operaciones_con_resultado"] == 1
    assert payload["resumen"]["resultado_neto"] == pytest.approx(5.0)
    assert len(payload["operaciones"]) == 1
    assert payload["operaciones"][0]["fecha"] == "2025-06-01"
    positions = {p["activo"]: p for p in payload["posicion"]}
    assert positions["XRP"]["cantidad"] == pytest.approx(5.0)
    assert positions["XRP"]["coste_total"] == pytest.approx(10.0)
    downloaded = client.get(f"/api/descargar/{payload['token']}")
    assert downloaded.status_code == 200
    assert downloaded.data.startswith(b"%PDF-")


def test_binance_convert_aeat_precio_verificado_eur_y_pdf(client, usuario, monkeypatch):
    """Fase opt-in: compras EUR -> permuta valorada -> venta EUR -> PDF.

    XRP comprado 10 por 10 EUR; entrega 5 XRP y recibe 11 USDC.
    Mercado en el momento: XRP/EUR=2, USDC/EUR=0.9.
    Art. 37.1.h: mayor(10,9.9) = 10 EUR; FIFO=5 -> ganancia=5.
    Venta 11 USDC por 9 EUR: coste=10 -> pérdida=-1, neto 4 EUR.
    """
    from datetime import timezone
    from decimal import Decimal
    from binance_eur_valuation import BinanceHistoricalEURPrices, TradePriceEvidence

    at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    book = BinanceHistoricalEURPrices([
        TradePriceEvidence("XRP", "EUR", Decimal("2"), at, 1, "a"*64),
        TradePriceEvidence("USDC", "EUR", Decimal("0.9"), at, 2, "b"*64),
    ])
    monkeypatch.setitem(flask_app.config, "BINANCE_VERIFIED_MARKET_PRICES", book)
    _login(client)
    buy = (SPOT_HEADER
           + "buy,2024-12-01 10:00:00,XRPEUR,BUY,1,10XRP,10EUR,0XRP,,\n"
           + "sell,2025-01-02 13:00:00,USDCEUR,SELL,0.818181818,11USDC,9EUR,0EUR,,\n"
           ).encode("utf-8-sig")
    convert = (CONVERT_HEADER
               + "2025-01-01 13:00:00,SPOT,XRPUSDC,Instant,5 XRP,11 USDC,,,,Successful\n"
               ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": [(io.BytesIO(buy), "Binance-Spot-(UTC+1).csv"),
                      (io.BytesIO(convert), "Binance-Convert-(UTC+1).csv")],
              "ejercicio": "2025", "nombre": "Caso sintético fiscal"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_data(as_text=True)[:460]
    data = response.get_json()
    assert data["resumen"]["operaciones_con_resultado"] == 2
    assert data["resumen"]["resultado_neto"] == pytest.approx(4.0)
    by_type = {o["tipo"]: o for o in data["operaciones"]}
    assert by_type["swap"]["transmision"] == pytest.approx(10.0)
    assert by_type["swap"]["coste_fifo"] == pytest.approx(5.0)
    assert by_type["swap"]["ganancia_perdida"] == pytest.approx(5.0)
    assert by_type["venta"]["coste_fifo"] == pytest.approx(10.0)
    assert by_type["venta"]["ganancia_perdida"] == pytest.approx(-1.0)
    pdf = client.get(f"/api/descargar/{data['token']}?exchange=binance")
    assert pdf.status_code == 200
    assert pdf.data.startswith(b"%PDF-")


def test_binance_convert_sin_catalogo_eur_no_emite_pdf(client, usuario, monkeypatch):
    """El opt-in no autoriza un PDF cuando el servidor carece de precios."""
    monkeypatch.delitem(flask_app.config, "BINANCE_VERIFIED_MARKET_PRICES", raising=False)
    _login(client)
    raw = (CONVERT_HEADER
           + "2025-01-01 13:00:00,SPOT,XRPUSDC,Instant,5 XRP,11 USDC,,,,Successful\n"
           ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(raw), "Binance-Convert-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Caso sintético sin precios"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    assert "token" not in response.get_json()


def test_binance_convert_catalogo_incompleto_no_emite_pdf(client, usuario, monkeypatch):
    from datetime import timezone
    from decimal import Decimal
    from binance_eur_valuation import BinanceHistoricalEURPrices, TradePriceEvidence
    t = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    book = BinanceHistoricalEURPrices([
        TradePriceEvidence("XRP", "EUR", Decimal("2"), t, 1, "a"*64),
    ])
    monkeypatch.setitem(flask_app.config, "BINANCE_VERIFIED_MARKET_PRICES", book)
    _login(client)
    raw = (CONVERT_HEADER
           + "2025-01-01 13:00:00,SPOT,XRPUSDC,Instant,5 XRP,11 USDC,,,,Successful\n"
           ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": (io.BytesIO(raw), "Binance-Convert-(UTC+1).csv"),
              "ejercicio": "2025", "nombre": "Caso sintético sin mercado completo"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    assert "token" not in response.get_json()


def test_binance_precio_eur_verificado_no_acepta_compra_y_swap_mismo_segundo(
        client, usuario, monkeypatch):
    from datetime import timezone
    from decimal import Decimal
    from binance_eur_valuation import BinanceHistoricalEURPrices, TradePriceEvidence
    at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setitem(flask_app.config, "BINANCE_VERIFIED_MARKET_PRICES",
        BinanceHistoricalEURPrices([
            TradePriceEvidence("XRP", "EUR", Decimal("2"), at, 1, "a"*64),
            TradePriceEvidence("USDC", "EUR", Decimal("0.9"), at, 2, "b"*64),
        ]))
    _login(client)
    buy = (SPOT_HEADER
           + "buy,2025-01-01 13:00:00,XRPEUR,BUY,1,10XRP,10EUR,0XRP,,\n"
           ).encode("utf-8-sig")
    convert = (CONVERT_HEADER
               + "2025-01-01 13:00:00,SPOT,XRPUSDC,Instant,5 XRP,11 USDC,,,,Successful\n"
               ).encode("utf-8-sig")
    response = client.post(
        "/api/binance/analizar",
        data={"csv": [(io.BytesIO(buy), "Binance-Spot-(UTC+1).csv"),
                      (io.BytesIO(convert), "Binance-Convert-(UTC+1).csv")],
              "ejercicio": "2025", "nombre": "Sin orden intrasegundo"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    assert "token" not in response.get_json()


EARN_SUB_HEADER = (
    "Fecha de suscripción,Nombre del producto,Moneda,Cantidad,Tipo,De,Estado\n"
)
EARN_RED_HEADER = (
    "Fecha de canje,Nombre del producto,Moneda,Principal Reembolsado,"
    "Método,Canjear por,Estado\n"
)
EARN_REW_HEADER = "Tiempo,Moneda,Cantidad,Tipo\n"
TX_EARN_HEADER = (
    "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"
)


def _earn_principal_only_uploads(*, reward_line="", subscription_qty="10",
                                 redemption_qty="10", origin="SPOT",
                                 redemption_wallet="SPOT", time_shift=False):
    spot = (
        SPOT_HEADER
        + "buy,2024-06-01 10:00:00,XRPEUR,BUY,2,10XRP,20EUR,0XRP,,\n"
        + "sell,2025-06-01 10:00:00,XRPEUR,SELL,3,4XRP,12EUR,0EUR,,\n"
    )
    sub_time = "2024-07-01 12:00:00"
    ledger_sub = "2024-07-01 12:00:01" if time_shift else sub_time
    red_time = "2025-05-01 12:00:00"
    sub = (EARN_SUB_HEADER + f"{sub_time},XRP,XRP,{subscription_qty},Auto,{origin},Successful\n")
    red = (EARN_RED_HEADER + f"{red_time},XRP,XRP,{redemption_qty},Fast,{redemption_wallet},Successful\n")
    ledger = (TX_EARN_HEADER
              + f"synthetic,{ledger_sub},Spot,Simple Earn Flexible Subscription,XRP,-{subscription_qty},\n"
              + f"synthetic,{red_time},Spot,Simple Earn Flexible Redemption,XRP,{redemption_qty},\n")
    reward = EARN_REW_HEADER + reward_line
    return [
        (io.BytesIO(content.encode("utf-8-sig")), filename)
        for content, filename in [
            (spot, "Binance-Spot-(UTC+1).csv"),
            (sub, "Binance-Earn-Subscription-(UTC+1).csv"),
            (red, "Binance-Earn-Redemption-(UTC+1).csv"),
            (reward, "Binance-Earn-Reward-(UTC+1).csv"),
            (ledger, "Binance-TX-(UTC+1).csv"),
        ]
    ]


def test_binance_pure_earn_principal_without_period_coverage_fails_closed(client, usuario):
    """El CSV de recompensas vacío no acredita su rango de exportación.

    Binance permite seleccionar fechas: aunque Spot↔Earn cuadre exactamente,
    no cabe concluir que faltan cero ingresos en todo el período sin prueba.
    """
    _login(client)
    r = client.post(
        "/api/binance/analizar",
        data={"csv": _earn_principal_only_uploads(), "ejercicio": "2025",
              "nombre": "Principal sin cobertura de recompensas"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 422, r.get_data(as_text=True)[:500]
    assert "token" not in r.get_json()
    assert "no acredita el período de fechas" in str(r.get_json())


@pytest.mark.parametrize("mode", ["reward", "without_reward_evidence", "mismatched",
                                  "origin_mixed", "ledger_only_day", "overdraft"])
def test_binance_pure_earn_unsafe_variants_still_fail_closed(client, usuario, mode):
    _login(client)
    opts = {}
    if mode == "reward":
        opts["reward_line"] = "2025-01-03,XRP,0.01,Real-time APR Rewards\n"
    if mode == "mismatched":
        opts["redemption_qty"] = "9"
    if mode == "origin_mixed":
        opts["origin"] = "SPOT + FUNDING"
    if mode == "ledger_only_day":
        opts["time_shift"] = True
    if mode == "overdraft":
        opts["subscription_qty"] = "11"
        opts["redemption_qty"] = "11"
    uploads = _earn_principal_only_uploads(**opts)
    if mode == "without_reward_evidence":
        uploads = [upload for upload in uploads if "Reward" not in upload[1]]
    r = client.post(
        "/api/binance/analizar",
        data={"csv": uploads, "ejercicio": "2025",
              "nombre": "Earn no acreditado"},
        content_type="multipart/form-data",
    )
    assert r.status_code == 422, r.get_data(as_text=True)[:500]
    assert "token" not in r.get_json()


def test_binance_diagnostico_earn_en_previsualizacion(client, usuario):
    """Subir una recompensa nativa no autoriza por sí solo lotes ni PDF."""
    _login(client)
    raw = (
        "Tiempo,Moneda,Cantidad,Tipo\n"
        "2025-06-10,ABC,0.125,Real-time APR Rewards\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/anos",
        data={"csv": (io.BytesIO(raw), "Earn-(UTC+1).csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200, r.get_data(as_text=True)[:400]
    body = r.get_json()
    diag = body["diagnostico_binance"]
    assert diag["validez_fiscal_acreditada"] is False
    assert "earn_lotes" in {item["codigo"] for item in diag["incidencias"]}
    assert body["anos"] == [2025]


def test_binance_diagnostico_earn_en_error_422_sin_token(client, usuario):
    """Mostrar cómo subsanar sin emitir informe parcialmente calculado."""
    _login(client)
    raw = (
        "Tiempo,Moneda,Cantidad,Tipo\n"
        "2025-06-10,ABC,0.125,Real-time APR Rewards\n"
    ).encode("utf-8-sig")
    r = client.post(
        "/api/binance/analizar",
        data={
            "csv": (io.BytesIO(raw), "Earn-(UTC+1).csv"),
            "ejercicio": "2025",
            "nombre": "Ejemplo sintético",
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 422, r.get_data(as_text=True)[:400]
    body = r.get_json()
    assert "token" not in body and "resumen" not in body
    assert "earn_lotes" in {
        item["codigo"]
        for item in body["diagnostico_binance"]["incidencias"]
    }
    assert body["diagnostico_binance"]["validez_fiscal_acreditada"] is False


def test_binance_diagnostico_spot_no_infiere_fuentes_que_no_aparecen(client, usuario):
    """No declarar como perdido un historial que el usuario no tiene."""
    _login(client)
    r = client.post(
        "/api/binance/anos",
        data={"csv": (io.BytesIO(_spot_csv()), "Spot-(UTC+1).csv")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200, r.get_data(as_text=True)[:400]
    diag = r.get_json()["diagnostico_binance"]
    assert diag["incidencias"] == []
    assert diag["validez_fiscal_acreditada"] is False
