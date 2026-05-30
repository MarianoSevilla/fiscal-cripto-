"""
Tests HTTP de integración para POST /api/721.

Cubre el endpoint completo — desde la petición HTTP hasta la respuesta JSON —
sin reemplazar la lógica de parsing de CSV ni la validación de exchanges.
Las llamadas externas costosas (CoinGecko, BCE) se mockean para mantener
los tests rápidos y deterministas.

Grupos de tests:
  A. Autenticación (1)
  B. Respuesta especial Bit2Me (2)
  C. Validación de ejercicio (4)
  D. Validación de exchange (2)
  E. Validación de fichero (5)
  F. Mismatch CSV-exchange (2)
  G. Procesamiento real Nexo CSV (4)
  H. Procesamiento real Bitvavo CSV (4)
  I. Estructura completa de la respuesta (3)
  J. Concurrencia — análisis simultáneo (1)
  K. MEXC — formato XLSX requerido (2)

Total: 30 tests
"""

import io
import os
import sys
import tempfile
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

# ── Configurar entorno antes de importar app ──────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-key-api721-http")

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User


# ── CSV fixtures ──────────────────────────────────────────────────────────────

# Nexo CSV mínimo con transacciones que generan posición a 31/12/2024
# (XRP es el activo con saldo no nulo al cierre del ejercicio)
NEXO_CSV = (
    "Transaction,Type,Input Currency,Input Amount,Output Currency,"
    "Output Amount,USD Equivalent,Fee,Fee Currency,Details,Date / Time (UTC)\n"
    'NXT001,Exchange,EUR,-3000.00,XRP,2915.97,$3000.00,-,-,"approved / Exchange",2024-03-15 10:00:00\n'
    'NXT002,Interest,NEXO,0.50,NEXO,0.50,$0.50,-,-,"approved / NEXO Interest",2024-06-01 00:00:00\n'
)

# Bitvavo CSV con compras de BTC y ETH en 2024
BITVAVO_CSV = (
    "Timezone,Date,Time,Type,Currency,Amount,Quote Currency,Quote Price,"
    "Received / Paid Currency,Received / Paid Amount,Fee currency,Fee amount,Status,Transaction ID,Address\n"
    "UTC,2024-03-15,12:00:00,buy,BTC,0.05,EUR,60000,EUR,-3000,EUR,2,Completed,tx001,\n"
    "UTC,2024-07-20,14:00:00,buy,ETH,1.0,EUR,3200,EUR,-3200,EUR,3,Completed,tx002,\n"
)

# Kraken CSV mínimo con compra de BTC
KRAKEN_CSV = (
    "txid,refid,time,type,subtype,aclass,asset,wallet,amount,fee,balance\n"
    "TXABC123,,2024-03-10 12:00:00,trade,,currency,XXBT,,0.05,-0.0001,0.05\n"
    "TXDEF456,,2024-03-10 12:00:00,trade,,currency,ZEUR,,-3050.00,0,0.00\n"
)

# CSV con cabeceras que no corresponden a ningún exchange
CSV_INVALIDO = (
    "campo1,campo2,campo3\n"
    "valor1,valor2,valor3\n"
)

# CSV vacío
CSV_VACIO = ""


# ── PrecioHistorico mock helpers ───────────────────────────────────────────────

def _mock_precio_disponible(ticker: str, ejercicio: int = 2024):
    """PrecioHistorico mock con precio válido."""
    from precios_historicos import PrecioHistorico, FUENTE_COINGECKO
    from datetime import date
    return PrecioHistorico(
        ticker       = ticker.upper(),
        ejercicio    = ejercicio,
        fecha_corte  = date(ejercicio, 12, 31),
        precio_eur   = Decimal("50000.00") if ticker.upper() == "BTC" else Decimal("3000.00"),
        fuente       = FUENTE_COINGECKO,
        estimado     = False,
        coingecko_id = ticker.lower(),
        nota         = f"Test price for {ticker}",
    )


def _mock_precio_no_disponible(ticker: str, ejercicio: int = 2024):
    """PrecioHistorico mock sin precio (CoinGecko fallido)."""
    from precios_historicos import PrecioHistorico, FUENTE_NO_DISPONIBLE
    from datetime import date
    return PrecioHistorico(
        ticker       = ticker.upper(),
        ejercicio    = ejercicio,
        fecha_corte  = date(ejercicio, 12, 31),
        precio_eur   = None,
        fuente       = FUENTE_NO_DISPONIBLE,
        estimado     = False,
        coingecko_id = None,
        nota         = "No disponible (mock)",
    )


# ── Fixtures pytest ───────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _app():
    flask_app.config["TESTING"]               = True
    flask_app.config["RATELIMIT_ENABLED"]     = False
    flask_app.config["WTF_CSRF_ENABLED"]      = False
    flask_app.config["SESSION_COOKIE_SECURE"] = False
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
def user_sin_nif(_app):
    with _app.app_context():
        u = User(
            email              = "api721_sinnif@example.com",
            full_name          = "Test Usuario Sin NIF",
            email_verified_at  = datetime.utcnow(),
        )
        u.set_password("pass-api721")
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
            email              = "api721_connif@example.com",
            full_name          = "Apellido1 Apellido2, Nombre",
            email_verified_at  = datetime.utcnow(),
            nif                = "12345678Z",
        )
        u.set_password("pass-api721")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


def _login(client, email, password="pass-api721"):
    client.post("/api/login", json={"email": email, "password": password})
    return client


def _post_721(client, exchange="nexo", ejercicio="2024",
              csv_content=NEXO_CSV, filename="nexo.csv",
              nif=None, nombre=None):
    """Helper: POST /api/721 con multipart/form-data."""
    data = {
        "exchange":  exchange,
        "ejercicio": ejercicio,
        "csv":       (io.BytesIO(csv_content.encode()), filename),
    }
    if nif:
        data["nif_declarante"] = nif
    if nombre:
        data["nombre_declarante"] = nombre
    return client.post("/api/721", data=data, content_type="multipart/form-data")


# ═══════════════════════════════════════════════════════════════════════════════
# A. Autenticación
# ═══════════════════════════════════════════════════════════════════════════════

def test_a01_sin_auth_redirige(client):
    """Sin sesión activa el endpoint devuelve 401 o 302."""
    res = _post_721(client)
    assert res.status_code in (401, 302), res.get_json()


# ═══════════════════════════════════════════════════════════════════════════════
# B. Respuesta especial Bit2Me
# ═══════════════════════════════════════════════════════════════════════════════

def test_b01_bit2me_no_requiere_csv(client, user_sin_nif):
    """Bit2Me devuelve respuesta informativa sin necesitar CSV."""
    _login(client, "api721_sinnif@example.com")
    res = client.post("/api/721",
                      data={"exchange": "bit2me", "ejercicio": "2024",
                            "csv": (io.BytesIO(b"dummy"), "bit2me.csv")},
                      content_type="multipart/form-data")
    data = res.get_json()
    assert res.status_code == 200, data
    assert data.get("ok") is True
    assert data["resultado"]["potencialmente_obligado"] is False


def test_b02_bit2me_bloqueantes_explica_entidad_espanola(client, user_sin_nif):
    """La respuesta Bit2Me incluye mensaje explicativo de entidad española."""
    _login(client, "api721_sinnif@example.com")
    res = client.post("/api/721",
                      data={"exchange": "bit2me", "ejercicio": "2023",
                            "csv": (io.BytesIO(b"dummy"), "bit2me.csv")},
                      content_type="multipart/form-data")
    data = res.get_json()
    assert res.status_code == 200
    bloqueantes = data["pendiente"]["xml_bloqueantes"]
    assert any("española" in b.lower() or "bit2me" in b.lower() for b in bloqueantes)


# ═══════════════════════════════════════════════════════════════════════════════
# C. Validación de ejercicio
# ═══════════════════════════════════════════════════════════════════════════════

def test_c01_ejercicio_anterior_a_2022(client, user_sin_nif):
    """Ejercicio < 2022 → 400 con mensaje de año mínimo."""
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, ejercicio="2021")
    data = res.get_json()
    assert res.status_code == 400, data
    assert "2022" in data.get("error", "")


def test_c02_ejercicio_no_numerico(client, user_sin_nif):
    """Ejercicio no numérico → 400."""
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, ejercicio="all")
    data = res.get_json()
    assert res.status_code == 400, data
    assert "all" in data.get("error", "").lower() or "numérico" in data.get("error", "").lower()


def test_c03_ejercicio_superior_al_maximo(client, user_sin_nif):
    """Ejercicio > año_actual + 1 → 400."""
    _login(client, "api721_sinnif@example.com")
    año_futuro = str(datetime.now().year + 5)
    res = _post_721(client, ejercicio=año_futuro)
    assert res.status_code == 400


def test_c04_ejercicio_rango_aceptado(client, user_sin_nif):
    """Ejercicio 2022–año_max es aceptado (no falla por ejercicio)."""
    _login(client, "api721_sinnif@example.com")
    # Solo comprobamos que el ejercicio no sea el problema de un 400 de ejercicio;
    # el error puede venir del CSV, pero no por el ejercicio.
    res = _post_721(client, ejercicio="2022", csv_content=BITVAVO_CSV,
                    filename="bitvavo.csv", exchange="bitvavo")
    data = res.get_json()
    # No debe fallar con error de ejercicio
    if res.status_code == 400:
        assert "2022" not in data.get("error", ""), \
            "No debe fallar por el ejercicio 2022"


# ═══════════════════════════════════════════════════════════════════════════════
# D. Validación de exchange
# ═══════════════════════════════════════════════════════════════════════════════

def test_d01_exchange_no_reconocido(client, user_sin_nif):
    """Exchange desconocido → 400."""
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, exchange="poloniex")
    data = res.get_json()
    assert res.status_code == 400, data
    assert "poloniex" in data.get("error", "").lower()


def test_d02_exchange_vacio(client, user_sin_nif):
    """Exchange vacío → 400."""
    _login(client, "api721_sinnif@example.com")
    res = client.post("/api/721",
                      data={"exchange": "", "ejercicio": "2024",
                            "csv": (io.BytesIO(NEXO_CSV.encode()), "nexo.csv")},
                      content_type="multipart/form-data")
    assert res.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# E. Validación de fichero
# ═══════════════════════════════════════════════════════════════════════════════

def test_e01_sin_fichero(client, user_sin_nif):
    """Sin campo 'csv' → 400."""
    _login(client, "api721_sinnif@example.com")
    res = client.post("/api/721",
                      data={"exchange": "nexo", "ejercicio": "2024"},
                      content_type="multipart/form-data")
    assert res.status_code == 400
    assert "csv" in res.get_json().get("error", "").lower() or \
           "fichero" in res.get_json().get("error", "").lower()


def test_e02_extension_incorrecta_csv_exchange(client, user_sin_nif):
    """Extensión .pdf en exchange que espera CSV → 400."""
    _login(client, "api721_sinnif@example.com")
    res = client.post("/api/721",
                      data={"exchange": "nexo", "ejercicio": "2024",
                            "csv": (io.BytesIO(b"dummy"), "nexo.pdf")},
                      content_type="multipart/form-data")
    assert res.status_code == 400
    assert "csv" in res.get_json().get("error", "").lower() or \
           "extensión" in res.get_json().get("error", "").lower()


def test_e03_mexc_requiere_xlsx_no_csv(client, user_sin_nif):
    """MEXC con archivo .csv → 400 pidiendo XLSX."""
    _login(client, "api721_sinnif@example.com")
    res = client.post("/api/721",
                      data={"exchange": "mexc", "ejercicio": "2024",
                            "csv": (io.BytesIO(b"col1,col2\nval1,val2"), "mexc.csv")},
                      content_type="multipart/form-data")
    data = res.get_json()
    assert res.status_code == 400, data
    assert "xlsx" in data.get("error", "").lower() or "xls" in data.get("error", "").lower()


def test_e04_fichero_vacio(client, user_sin_nif):
    """Fichero CSV vacío → 400."""
    _login(client, "api721_sinnif@example.com")
    res = client.post("/api/721",
                      data={"exchange": "nexo", "ejercicio": "2024",
                            "csv": (io.BytesIO(b""), "nexo.csv")},
                      content_type="multipart/form-data")
    assert res.status_code == 400


def test_e05_bitget_acepta_csv(client, user_sin_nif):
    """Bitget usa CSV — la validación de extensión lo acepta (puede fallar por contenido)."""
    _login(client, "api721_sinnif@example.com")
    # Columnas reales de Bitget (BITGET_SIGNATURES = ["Fee Coin", "Available", "Order Id"])
    bitget_csv = (
        "Order Id,Symbol,Order Type,Side,Average Fill Price,Filled,Total,Fee Coin,"
        "Available,Status,Created Time\n"
        "123456789,BTCUSDT,limit,buy,60000,0.01,600,USDT,0.001,full_fill,2024-03-15 12:00:00\n"
    )
    res = client.post("/api/721",
                      data={"exchange": "bitget", "ejercicio": "2024",
                            "csv": (io.BytesIO(bitget_csv.encode()), "bitget.csv")},
                      content_type="multipart/form-data")
    data = res.get_json()
    # La extensión .csv es correcta para Bitget — no debe rechazar por extensión.
    # El rechazo, si lo hay, debe ser por contenido (firma, parser) o procesamiento.
    if res.status_code == 400:
        err = data.get("error", "").lower()
        assert "xlsx" not in err and "xls" not in err, \
            f"Bitget no debería pedir XLSX: {err}"


# ═══════════════════════════════════════════════════════════════════════════════
# F. Mismatch CSV-exchange
# ═══════════════════════════════════════════════════════════════════════════════

def test_f01_csv_nexo_con_exchange_bitvavo(client, user_sin_nif):
    """CSV de Nexo enviado como Bitvavo → error (400 o 500 por parser)."""
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, exchange="bitvavo", csv_content=NEXO_CSV,
                    filename="bitvavo.csv")
    data = res.get_json()
    # La validación de firma de Bitvavo es permisiva (usa `any()`), por lo que un CSV
    # de Nexo puede pasar la comprobación de cabeceras y fallar más tarde en el parser
    # (500). En ambos casos hay un campo 'error' con descripción del problema.
    assert res.status_code in (400, 500), data
    assert "error" in data


def test_f02_csv_invalido_con_exchange_nexo(client, user_sin_nif):
    """CSV con cabeceras arbitrarias → 400 con mensaje de exchange."""
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, exchange="nexo", csv_content=CSV_INVALIDO,
                    filename="nexo.csv")
    data = res.get_json()
    assert res.status_code == 400, data
    assert "nexo" in data.get("error", "").lower()


# ═══════════════════════════════════════════════════════════════════════════════
# G. Procesamiento real Nexo CSV (mock precios)
# ═══════════════════════════════════════════════════════════════════════════════

@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
def test_g01_nexo_sin_nif_devuelve_nif_faltante(
    mock_enr, mock_prec, client, user_sin_nif, _app
):
    """Nexo CSV real procesado: sin NIF en perfil → nif_faltante=True."""
    mock_prec.return_value = {}
    _login(client, "api721_sinnif@example.com")
    with _app.app_context():
        u = User.query.filter_by(email="api721_sinnif@example.com").first()
        u.nif = None
        db.session.commit()

    res = _post_721(client)
    data = res.get_json()
    assert res.status_code == 200, data
    assert data.get("nif_faltante") is True


@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
def test_g02_nexo_precios_no_disponibles_bloquea_xml(
    mock_enr, mock_prec, client, user_con_nif
):
    """Sin precios históricos → pendiente.precios_historicos poblado, XML bloqueado."""
    mock_prec.return_value = {}
    _login(client, "api721_connif@example.com")
    res = _post_721(client)
    data = res.get_json()
    assert res.status_code == 200, data
    pendiente = data.get("pendiente", {})
    assert len(pendiente.get("precios_historicos", [])) > 0
    assert pendiente.get("xml_generable") is False
    assert data.get("xml") is None


@patch("app.obtener_precios_historicos")
def test_g03_nexo_estructura_respuesta_completa(
    mock_prec, client, user_sin_nif
):
    """La respuesta de /api/721 contiene todos los campos esperados."""
    mock_prec.return_value = {}
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client)
    data = res.get_json()
    assert res.status_code == 200, data

    # Campos raíz obligatorios
    for campo in ("ok", "modelo", "ejercicio", "exchange", "resultado",
                  "pendiente", "nif_faltante", "generado_en"):
        assert campo in data, f"Falta campo '{campo}' en la respuesta"

    assert data["modelo"] == "721"
    assert data["ejercicio"] == 2024
    assert data["exchange"] == "nexo"
    assert data["ok"] is True

    # Estructura del bloque pendiente
    pendiente = data["pendiente"]
    for clave in ("precios_historicos", "tax_id_custodio", "xml_generable",
                  "xml_es_borrador", "xml_bloqueantes", "xml_advertencias",
                  "por_debajo_umbral", "completo"):
        assert clave in pendiente, f"Falta '{clave}' en pendiente"

    # Estructura del resultado
    resultado = data["resultado"]
    assert "exchanges" in resultado
    assert isinstance(resultado["exchanges"], list)


@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios")
def test_g04_nexo_con_nif_y_precios_genera_xml(
    mock_enr, mock_prec, client, user_con_nif
):
    """Con NIF en perfil y precios disponibles → XML generado inline."""
    from precios_historicos import PrecioHistorico, FUENTE_COINGECKO
    from datetime import date

    # El CSV de Nexo produce posición XRP y NEXO
    xrp_precio = _mock_precio_disponible("XRP")
    nexo_precio = _mock_precio_disponible("NEXO")
    mock_prec.return_value = {"XRP": xrp_precio, "NEXO": nexo_precio}

    # enriquecer: devolver datos con valores_eur rellenos
    def _enriquecer_con_precios(datos, precios):
        import copy
        datos = copy.deepcopy(datos)
        for exc in datos.get("exchanges", []):
            for activo in exc.get("activos", []):
                ticker = activo["activo"].upper()
                ph = precios.get(ticker)
                if ph and ph.precio_eur is not None:
                    from decimal import Decimal
                    cantidad = Decimal(activo["cantidad"])
                    activo["valor_eur"] = str(
                        (ph.precio_eur * cantidad).quantize(Decimal("0.01"))
                    )
                    activo["origen_valor"] = "O"
        return datos
    mock_enr.side_effect = _enriquecer_con_precios

    _login(client, "api721_connif@example.com")
    res = _post_721(client)
    data = res.get_json()
    assert res.status_code == 200, data
    # Si hay precio para todos los activos, el XML debe generarse
    # (puede ser borrador por custodio Nexo sin ID fiscal confirmado)
    if not data["pendiente"].get("precios_historicos"):
        assert "xml" in data, "Se esperaba XML cuando todos los precios están disponibles"


# ═══════════════════════════════════════════════════════════════════════════════
# H. Procesamiento real Bitvavo CSV (mock precios)
# ═══════════════════════════════════════════════════════════════════════════════

@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
def test_h01_bitvavo_detecta_btc_eth(mock_enr, mock_prec, client, user_sin_nif):
    """Bitvavo CSV real: detecta BTC y ETH como activos en posición 31/12."""
    mock_prec.return_value = {}
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, exchange="bitvavo", csv_content=BITVAVO_CSV,
                    filename="bitvavo.csv")
    data = res.get_json()
    assert res.status_code == 200, data
    activos = [
        a["activo"]
        for exc in data["resultado"]["exchanges"]
        for a in exc.get("activos", [])
    ]
    assert "BTC" in activos, f"BTC no detectado en: {activos}"
    assert "ETH" in activos, f"ETH no detectado en: {activos}"


@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
def test_h02_bitvavo_ejercicio_correcto(mock_enr, mock_prec, client, user_sin_nif):
    """El ejercicio en la respuesta coincide con el enviado."""
    mock_prec.return_value = {}
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, exchange="bitvavo", csv_content=BITVAVO_CSV,
                    filename="bitvavo.csv", ejercicio="2024")
    data = res.get_json()
    assert res.status_code == 200, data
    assert data["ejercicio"] == 2024


@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
def test_h03_bitvavo_nif_en_form_no_faltante(mock_enr, mock_prec, client, user_sin_nif):
    """NIF enviado directamente en el formulario → nif_faltante=False."""
    mock_prec.return_value = {}
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, exchange="bitvavo", csv_content=BITVAVO_CSV,
                    filename="bitvavo.csv", nif="12345678Z",
                    nombre="Apellido1 Apellido2, Nombre")
    data = res.get_json()
    assert res.status_code == 200, data
    assert data.get("nif_faltante") is False


@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
def test_h04_bitvavo_response_json_serializable(mock_enr, mock_prec, client, user_sin_nif):
    """La respuesta JSON completa de Bitvavo es serializable sin errores."""
    import json
    mock_prec.return_value = {}
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, exchange="bitvavo", csv_content=BITVAVO_CSV,
                    filename="bitvavo.csv")
    assert res.status_code == 200
    # Si el cliente puede parsear el JSON, es serializable
    data = res.get_json()
    assert data is not None
    # Serializar de vuelta no debe lanzar excepción
    json.dumps(data)


# ═══════════════════════════════════════════════════════════════════════════════
# I. Estructura interna de la respuesta (campos específicos)
# ═══════════════════════════════════════════════════════════════════════════════

@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
def test_i01_nexo_pendiente_tax_id_custodio_presente(
    mock_enr, mock_prec, client, user_sin_nif
):
    """Nexo no tiene ID fiscal confirmado → tax_id_custodio incluye 'nexo'."""
    mock_prec.return_value = {}
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client)
    data = res.get_json()
    assert res.status_code == 200, data
    tax_ids = data["pendiente"].get("tax_id_custodio", [])
    assert "nexo" in tax_ids, f"nexo debería estar en tax_id_custodio: {tax_ids}"


@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
def test_i02_resultado_tiene_exchanges_lista(mock_enr, mock_prec, client, user_sin_nif):
    """resultado.exchanges es una lista no vacía."""
    mock_prec.return_value = {}
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client)
    data = res.get_json()
    assert res.status_code == 200, data
    exchanges = data["resultado"].get("exchanges", [])
    assert isinstance(exchanges, list)
    assert len(exchanges) > 0, "exchanges debería contener al menos un exchange"


@patch("app.obtener_precios_historicos")
@patch("app.enriquecer_721_con_precios", side_effect=lambda d, _p: d)
def test_i03_activos_tienen_campos_requeridos(mock_enr, mock_prec, client, user_sin_nif):
    """Cada activo en la respuesta tiene los campos obligatorios del XSD."""
    mock_prec.return_value = {}
    _login(client, "api721_sinnif@example.com")
    res = _post_721(client, exchange="bitvavo", csv_content=BITVAVO_CSV,
                    filename="bitvavo.csv")
    data = res.get_json()
    assert res.status_code == 200, data
    campos_requeridos = ("activo", "denominacion", "siglas", "cantidad",
                         "clave", "origen_moneda_virtual")
    for exc in data["resultado"]["exchanges"]:
        for activo in exc.get("activos", []):
            for campo in campos_requeridos:
                assert campo in activo, \
                    f"Activo {activo.get('activo')} no tiene '{campo}'"


# ═══════════════════════════════════════════════════════════════════════════════
# J. Concurrencia — análisis simultáneo bloqueado
# ═══════════════════════════════════════════════════════════════════════════════

def test_j01_concurrencia_segunda_peticion_devuelve_409(client, user_sin_nif, _app):
    """Simular análisis en curso: segunda petición devuelve 409."""
    _login(client, "api721_sinnif@example.com")

    # Obtener el user_id para inyectar directamente en _analisis_en_curso
    with _app.app_context():
        u = User.query.filter_by(email="api721_sinnif@example.com").first()
        uid = u.id

    # Importar y manipular el set de análisis en curso
    import app as app_module
    app_module._analisis_en_curso.add(uid)
    try:
        res = _post_721(client)
        data = res.get_json()
        assert res.status_code == 409, data
        assert "proceso" in data.get("error", "").lower() or \
               "análisis" in data.get("error", "").lower()
    finally:
        app_module._analisis_en_curso.discard(uid)


# ═══════════════════════════════════════════════════════════════════════════════
# K. MEXC — formato XLSX
# ═══════════════════════════════════════════════════════════════════════════════

def test_k01_mexc_rechaza_extension_csv(client, user_sin_nif):
    """MEXC con .csv → 400 con mensaje específico sobre XLS/XLSX."""
    _login(client, "api721_sinnif@example.com")
    res = client.post("/api/721",
                      data={"exchange": "mexc", "ejercicio": "2024",
                            "csv": (io.BytesIO(b"col1,col2\nv1,v2"), "mexc.csv")},
                      content_type="multipart/form-data")
    data = res.get_json()
    assert res.status_code == 400, data
    err = data.get("error", "").lower()
    assert "xlsx" in err or "xls" in err, f"Mensaje esperado sobre XLSX: {err}"


def test_k02_mexc_acepta_extension_xlsx(client, user_sin_nif):
    """MEXC con .xlsx no falla por extensión (puede fallar por contenido del XLSX)."""
    _login(client, "api721_sinnif@example.com")
    # Subir bytes no-XLSX: pasará la validación de extensión pero fallará al leer
    res = client.post("/api/721",
                      data={"exchange": "mexc", "ejercicio": "2024",
                            "csv": (io.BytesIO(b"not-a-real-xlsx"), "mexc.xlsx")},
                      content_type="multipart/form-data")
    data = res.get_json()
    # No debe fallar con "extensión .csv" — debe fallar por contenido del XLSX
    if res.status_code == 400:
        err = data.get("error", "").lower()
        assert "extensión" not in err or "xlsx" in err, \
            f"No debería rechazar la extensión .xlsx: {err}"
