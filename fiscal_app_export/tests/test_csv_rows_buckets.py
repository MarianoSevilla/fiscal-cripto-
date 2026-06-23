"""
Tests para la bucketización de csv_rows en /api/stats.

Valida:
  - Todos los límites exactos de los 7 rangos propuestos.
  - Orden correcto de VOL_ORDER en la respuesta JSON.
  - Que el frontend reciba siempre los 7 rangos (incluso con total 0).
  - Que un valor NULL no rompa el conteo.

Rangos:
  0–100        (≤ 100)
  101–1.000    (101–1000)
  1.001–3.000  (1001–3000)
  3.001–10.000 (3001–10000)
  10.001–25.000 (10001–25000)
  25.001–50.000 (25001–50000)
  > 50.000     (> 50000)
"""

import sys
import os
import tempfile
from datetime import datetime

import pytest

# ── Entorno antes de importar app ──────────────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-vol-buckets")
os.environ["ADMIN_EMAILS"] = "admin_vol_test@example.com"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app as flask_app, db
from models import User, FifoReport


# ── Fixtures ────────────────────────────────────────────────────────────────

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


@pytest.fixture(scope="module")
def admin_user(_app):
    """Usuario admin — puede llamar a /api/stats.

    Usa role='admin' (no depende de ADMIN_EMAILS) para ser independiente del
    orden de import: ADMIN_EMAILS se congela en auth.py al primer import de app,
    y si otro módulo de test lo importa antes que este, quedaría vacío. El rol en
    BD lo evalúa _role_is_admin() en cada request. Mismo patrón que
    test_contactos_admin.py y test_campaign_delete.py.
    """
    with _app.app_context():
        u = User(
            email="admin_vol_test@example.com",
            full_name="Admin Vol Test",
            role="admin",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("admin-vol-pass-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture(scope="module")
def normal_user(_app):
    """Usuario normal — sus informes SÍ cuentan en _no_adm_rep."""
    with _app.app_context():
        u = User(
            email="user_vol_test@example.com",
            full_name="User Vol Test",
            role="user",
            email_verified_at=datetime.utcnow(),
        )
        u.set_password("user-vol-pass-1234")
        db.session.add(u)
        db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()


@pytest.fixture
def client(_app):
    return _app.test_client()


def _login_admin(client):
    r = client.post("/api/login",
                    json={"email": "admin_vol_test@example.com",
                          "password": "admin-vol-pass-1234"})
    assert r.status_code == 200, f"Login falló: {r.get_json()}"
    return client


def _make_report(_app, user_uid, csv_rows):
    """Crea un FifoReport con status='generated' y csv_rows dado.
    Debe usarse con normal_user, no con admin_user, para que no sea
    filtrado por _no_adm_rep en _api_stats_data().
    """
    with _app.app_context():
        r = FifoReport(
            user_id         = user_uid,
            exchange        = "binance",
            fiscal_year     = 2024,
            csv_rows        = csv_rows,
            distinct_assets = 1,
            processing_ms   = 100,
            status          = "generated",
        )
        db.session.add(r)
        db.session.commit()
        return r.id


def _get_por_volumen(client):
    r = client.get("/api/stats")
    assert r.status_code == 200, r.get_json()
    return {item["rango"]: item["total"] for item in r.get_json()["informes"]["por_volumen"]}


def _clean(_app, *report_ids):
    with _app.app_context():
        FifoReport.query.filter(FifoReport.id.in_(report_ids)).delete()
        db.session.commit()


# ── HELPERS para el test de límites exactos ─────────────────────────────────

# Tabla de (csv_rows, bucket_esperado)
BOUNDARY_CASES = [
    (0,     "0–100"),
    (1,     "0–100"),
    (100,   "0–100"),        # límite superior inclusivo del primer rango
    (101,   "101–1.000"),    # primer valor del segundo rango
    (1000,  "101–1.000"),    # límite superior inclusivo
    (1001,  "1.001–3.000"),  # primer valor del tercer rango
    (3000,  "1.001–3.000"),  # límite superior inclusivo
    (3001,  "3.001–10.000"), # primer valor del cuarto rango
    (10000, "3.001–10.000"), # límite superior inclusivo
    (10001, "10.001–25.000"),
    (25000, "10.001–25.000"),
    (25001, "25.001–50.000"),
    (50000, "25.001–50.000"),
    (50001, "> 50.000"),
    (99999, "> 50.000"),
]

VOL_ORDER_EXPECTED = [
    "0–100",
    "101–1.000",
    "1.001–3.000",
    "3.001–10.000",
    "10.001–25.000",
    "25.001–50.000",
    "> 50.000",
]


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("csv_rows,expected_bucket", BOUNDARY_CASES)
def test_limite_exacto(csv_rows, expected_bucket, client, admin_user, normal_user, _app):
    """Cada valor en el límite cae en el bucket correcto."""
    _login_admin(client)

    # Obtener baseline sin el nuevo informe
    baseline = _get_por_volumen(client)

    rid = _make_report(_app, normal_user, csv_rows)

    after = _get_por_volumen(client)
    delta = {k: after.get(k, 0) - baseline.get(k, 0) for k in VOL_ORDER_EXPECTED}

    assert delta[expected_bucket] == 1, (
        f"csv_rows={csv_rows} debería estar en '{expected_bucket}' "
        f"pero los deltas son: {delta}"
    )
    # Ningún otro bucket debe haber cambiado
    for k, v in delta.items():
        if k != expected_bucket:
            assert v == 0, f"Bucket inesperado '{k}' incrementado con csv_rows={csv_rows}"

    _clean(_app, rid)


def test_orden_vol_order(client, admin_user, _app):
    """por_volumen devuelve los 7 rangos en el orden correcto."""
    _login_admin(client)
    r = client.get("/api/stats")
    assert r.status_code == 200
    rangos = [item["rango"] for item in r.get_json()["informes"]["por_volumen"]]
    assert rangos == VOL_ORDER_EXPECTED, f"Orden incorrecto: {rangos}"


def test_todos_los_rangos_presentes(client, admin_user, _app):
    """Siempre se devuelven los 7 rangos aunque alguno tenga total=0."""
    _login_admin(client)
    r = client.get("/api/stats")
    rangos = {item["rango"] for item in r.get_json()["informes"]["por_volumen"]}
    for rango in VOL_ORDER_EXPECTED:
        assert rango in rangos, f"Rango '{rango}' ausente de la respuesta"


def test_null_csv_rows_no_cuenta(client, admin_user, normal_user, _app):
    """Un informe con csv_rows=NULL no aparece en ningún bucket."""
    _login_admin(client)
    baseline = _get_por_volumen(client)
    total_antes = sum(baseline.values())

    rid = _make_report(_app, normal_user, None)

    after = _get_por_volumen(client)
    total_despues = sum(after.values())

    assert total_despues == total_antes, "Un informe con csv_rows=NULL no debe contar en ningún bucket"
    _clean(_app, rid)


def test_no_hay_rangos_viejos(client, admin_user, _app):
    """Los rangos del sistema anterior no deben aparecer en la respuesta."""
    rangos_viejos = {"< 50", "50–250", "250–1.000", "1.000–10.000", "> 10.000"}
    _login_admin(client)
    r = client.get("/api/stats")
    rangos_actuales = {item["rango"] for item in r.get_json()["informes"]["por_volumen"]}
    solapamiento = rangos_viejos & rangos_actuales
    assert not solapamiento, f"Rangos del sistema antiguo presentes: {solapamiento}"
