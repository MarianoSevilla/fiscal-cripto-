"""
Tests para la nueva métrica por_exchange_volumen en /api/stats.

Casos cubiertos:
  1. La clave por_exchange_volumen existe en la respuesta.
  2. Cada exchange devuelve exactamente 7 buckets.
  3. Los buckets siguen el mismo orden que VOL_ORDER.
  4. avg_rows, max_rows y total son correctos para un exchange conocido.
  5. Informes con csv_rows=NULL no aparecen en ningún bucket ni en el total.
  6. Informes de usuarios admin se excluyen (_no_adm_rep).
  7. Exchanges con < 5 informes no aparecen en la respuesta.
  8. Exchanges con ≥ 5 informes sí aparecen.
  9. Orden descendente por avg_rows.
"""

import sys
import os
import tempfile
from datetime import datetime

import pytest

# ── Entorno antes de importar app ──────────────────────────────────────────
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ.setdefault("SECRET_KEY",   "test-secret-exc-vol")
os.environ["ADMIN_EMAILS"] = "admin_ev_test@example.com"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as _app_module
import auth as _auth_module
from app import app as flask_app, db
from models import User, FifoReport

# ADMIN_EMAILS es un frozenset evaluado al importar el módulo.
# Si otro test suite importó la app primero con un email distinto,
# necesitamos dos parches:
#   1. auth.ADMIN_EMAILS  → lo lee _role_is_admin() → controla el 403
#   2. app.ADMIN_EMAILS   → lo lee _api_stats_data() → controla _no_adm_rep
_auth_module.ADMIN_EMAILS = frozenset(
    _auth_module.ADMIN_EMAILS | {"admin_ev_test@example.com"}
)
_app_module.ADMIN_EMAILS = frozenset(
    _app_module.ADMIN_EMAILS | {"admin_ev_test@example.com"}
)

VOL_ORDER = [
    "0–100", "101–1.000", "1.001–3.000", "3.001–10.000",
    "10.001–25.000", "25.001–50.000", "> 50.000",
]


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
    """En ADMIN_EMAILS — puede llamar /api/stats pero sus informes se excluyen."""
    with _app.app_context():
        u = User(email="admin_ev_test@example.com", full_name="Admin EV",
                 role="user", email_verified_at=datetime.utcnow())
        u.set_password("admin-ev-1234")
        db.session.add(u); db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete(); db.session.commit()


@pytest.fixture(scope="module")
def normal_user(_app):
    """Usuario normal — sus informes cuentan en stats."""
    with _app.app_context():
        u = User(email="user_ev_test@example.com", full_name="User EV",
                 role="user", email_verified_at=datetime.utcnow())
        u.set_password("user-ev-1234")
        db.session.add(u); db.session.commit()
        uid = u.id
    yield uid
    with _app.app_context():
        User.query.filter_by(id=uid).delete(); db.session.commit()


@pytest.fixture
def client(_app):
    return _app.test_client()


def _login_admin(client):
    r = client.post("/api/login",
                    json={"email": "admin_ev_test@example.com", "password": "admin-ev-1234"})
    assert r.status_code == 200, r.get_json()
    return client


def _make_reports(_app, user_id, exchange, csv_rows_list):
    """Crea múltiples informes para un exchange dado. Devuelve lista de ids."""
    ids = []
    with _app.app_context():
        for rows in csv_rows_list:
            r = FifoReport(
                user_id=user_id, exchange=exchange, fiscal_year=2024,
                csv_rows=rows, distinct_assets=1, processing_ms=100,
                status="generated",
            )
            db.session.add(r)
        db.session.commit()
        # Recuperar ids insertados
        ids = [
            r.id for r in FifoReport.query
            .filter_by(user_id=user_id, exchange=exchange)
            .order_by(FifoReport.id.desc())
            .limit(len(csv_rows_list))
            .all()
        ]
    return ids


def _clean(_app, *ids):
    with _app.app_context():
        FifoReport.query.filter(FifoReport.id.in_(ids)).delete()
        db.session.commit()


def _get_exc_vol(client):
    r = client.get("/api/stats")
    assert r.status_code == 200, r.get_json()
    return r.get_json()["informes"]["por_exchange_volumen"]


# ── Tests ────────────────────────────────────────────────────────────────────

def test_clave_existe_en_respuesta(client, admin_user, _app):
    """por_exchange_volumen existe en informes."""
    _login_admin(client)
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert "por_exchange_volumen" in r.get_json()["informes"]


def test_cada_exchange_tiene_7_buckets(client, admin_user, normal_user, _app):
    """Cada entrada de por_exchange_volumen tiene exactamente 7 buckets."""
    ids = _make_reports(_app, normal_user, "test_exc_7b",
                        [10, 200, 500, 1500, 4000, 12000, 30000, 60000, 100, 200])
    _login_admin(client)
    exc_vol = _get_exc_vol(client)
    entry = next((e for e in exc_vol if e["exchange"] == "test_exc_7b"), None)
    assert entry is not None, "exchange test_exc_7b no encontrado"
    assert len(entry["buckets"]) == 7, f"Esperados 7 buckets, obtenidos {len(entry['buckets'])}"
    _clean(_app, *ids)


def test_orden_buckets_igual_que_vol_order(client, admin_user, normal_user, _app):
    """El orden de los buckets coincide con VOL_ORDER."""
    # Crear 5 informes con valores conocidos: 1 por cada uno de los primeros 5 rangos
    csv_vals = [50, 500, 2000, 7000, 15000, 50, 500]  # 7 informes, ≥ 5 umbrales
    ids = _make_reports(_app, normal_user, "test_exc_order", csv_vals)
    _login_admin(client)
    exc_vol = _get_exc_vol(client)
    entry = next((e for e in exc_vol if e["exchange"] == "test_exc_order"), None)
    assert entry is not None
    # Los buckets deben ser [2,2,1,1,1,0,0] con esos valores
    assert entry["buckets"][0] == 2   # 0–100: 50, 50
    assert entry["buckets"][1] == 2   # 101–1.000: 500, 500
    assert entry["buckets"][2] == 1   # 1.001–3.000: 2000
    assert entry["buckets"][3] == 1   # 3.001–10.000: 7000
    assert entry["buckets"][4] == 1   # 10.001–25.000: 15000
    assert entry["buckets"][5] == 0   # 25.001–50.000: vacío
    assert entry["buckets"][6] == 0   # > 50.000: vacío
    _clean(_app, *ids)


def test_avg_max_total_correctos(client, admin_user, normal_user, _app):
    """avg_rows, max_rows y total reflejan correctamente los datos del exchange."""
    vals = [100, 200, 300, 400, 500]   # media=300, max=500, total=5
    ids  = _make_reports(_app, normal_user, "test_exc_stats", vals)
    _login_admin(client)
    exc_vol = _get_exc_vol(client)
    entry = next((e for e in exc_vol if e["exchange"] == "test_exc_stats"), None)
    assert entry is not None
    assert entry["total"]    == 5
    assert entry["max_rows"] == 500
    assert entry["avg_rows"] == 300
    _clean(_app, *ids)


def test_null_csv_rows_ignorados(client, admin_user, normal_user, _app):
    """Informes con csv_rows=NULL no aparecen en ningún bucket ni en el total."""
    ids_normal = _make_reports(_app, normal_user, "test_exc_null", [100, 200, 300, 400, 500])
    # Añadir uno con NULL
    with _app.app_context():
        r = FifoReport(user_id=normal_user, exchange="test_exc_null",
                       fiscal_year=2024, csv_rows=None, distinct_assets=1,
                       processing_ms=100, status="generated")
        db.session.add(r); db.session.commit()
        null_id = r.id

    _login_admin(client)
    exc_vol = _get_exc_vol(client)
    entry = next((e for e in exc_vol if e["exchange"] == "test_exc_null"), None)
    assert entry is not None
    assert entry["total"] == 5                    # NULL no cuenta en el total
    assert sum(entry["buckets"]) == 5             # NULL no va a ningún bucket
    _clean(_app, *ids_normal, null_id)


def test_admin_informes_excluidos(client, admin_user, normal_user, _app):
    """Informes del usuario admin no aparecen en por_exchange_volumen."""
    # Crear 5 informes del admin para que supere el umbral mínimo
    ids_admin = _make_reports(_app, admin_user, "test_exc_admin",
                              [100, 200, 300, 400, 500])
    _login_admin(client)
    exc_vol = _get_exc_vol(client)
    entry = next((e for e in exc_vol if e["exchange"] == "test_exc_admin"), None)
    # El exchange no debe aparecer porque todos sus informes son de admin
    assert entry is None, "Los informes de admin no deben aparecer en por_exchange_volumen"
    _clean(_app, *ids_admin)


def test_exchange_menos_de_5_excluido(client, admin_user, normal_user, _app):
    """Exchange con < 5 informes no aparece en la respuesta."""
    ids = _make_reports(_app, normal_user, "test_exc_small", [100, 200, 300, 400])  # 4 < 5
    _login_admin(client)
    exc_vol = _get_exc_vol(client)
    entry = next((e for e in exc_vol if e["exchange"] == "test_exc_small"), None)
    assert entry is None, "Exchange con 4 informes no debe aparecer (mínimo 5)"
    _clean(_app, *ids)


def test_exchange_con_5_o_mas_aparece(client, admin_user, normal_user, _app):
    """Exchange con exactamente 5 informes sí aparece."""
    ids = _make_reports(_app, normal_user, "test_exc_exact5",
                        [100, 200, 300, 400, 500])  # exactamente 5
    _login_admin(client)
    exc_vol = _get_exc_vol(client)
    entry = next((e for e in exc_vol if e["exchange"] == "test_exc_exact5"), None)
    assert entry is not None, "Exchange con 5 informes debe aparecer"
    _clean(_app, *ids)


def test_orden_por_avg_rows_descendente(client, admin_user, normal_user, _app):
    """Los exchanges aparecen ordenados por avg_rows descendente."""
    # Exchange A: media alta (10000)
    ids_a = _make_reports(_app, normal_user, "test_exc_hi",
                          [10000, 10000, 10000, 10000, 10000])
    # Exchange B: media baja (50)
    ids_b = _make_reports(_app, normal_user, "test_exc_lo",
                          [50, 50, 50, 50, 50])

    _login_admin(client)
    exc_vol = _get_exc_vol(client)
    exchanges = [e["exchange"] for e in exc_vol]
    pos_a = next((i for i, e in enumerate(exc_vol) if e["exchange"] == "test_exc_hi"), None)
    pos_b = next((i for i, e in enumerate(exc_vol) if e["exchange"] == "test_exc_lo"), None)
    assert pos_a is not None and pos_b is not None
    assert pos_a < pos_b, (
        f"test_exc_hi (avg alto) debe ir antes que test_exc_lo (avg bajo). "
        f"Posiciones: hi={pos_a}, lo={pos_b}. Orden: {exchanges}"
    )
    _clean(_app, *ids_a, *ids_b)
