"""CI-only R01-R04 HTTP/PDF/FifoReport acceptance on disposable PostgreSQL 18.

Guards exclude Railway/production. Entire dataset is synthetic.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap

import psycopg2
from psycopg2 import sql

DB = "fiscal_containment_r01_r04_ci"
HOST, PORT, USER, PASSWORD = "127.0.0.1", 5432, "postgres", "ci-only-test-password"
ROOT = Path(__file__).resolve().parents[1]


def guard():
    if not (os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("CI") == "true"
            and os.environ.get("FLASK_ENV") == "testing"):
        raise RuntimeError("Fiscal PostgreSQL acceptance is CI-only")
    if HOST != "127.0.0.1" or PORT != 5432 or DB != "fiscal_containment_r01_r04_ci":
        raise RuntimeError("Non-local PostgreSQL is forbidden")


def admin():
    guard()
    return psycopg2.connect(
        host=HOST, port=PORT, user=USER,
        password=PASSWORD, dbname="postgres", connect_timeout=5,
    )


def database(create):
    c = admin()
    try:
        c.autocommit = True
        with c.cursor() as cur:
            version_sql = "SELECT current_setting('server_version_num')::integer"
            cur.execute(version_sql)
            version = cur.fetchone()[0]
            assert 180000 <= version < 190000, ("Expected PostgreSQL 18", version)
            if create:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
            else:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(DB)))
    finally:
        c.close()


PROGRAM = r'''
import io
import os
from pathlib import Path
from types import SimpleNamespace
import flask_login.utils as login_utils
import app as application
from app import app
from models import db, User, FifoReport
from motor_fifo import MotorFIFO
from clasificador_nexo import ClasificadorNexo
from clasificador_uphold import ClasificadorUphold

app.config.update(TESTING=True, RATELIMIT_ENABLED=False)
with app.app_context():
    assert db.engine.dialect.name == "postgresql"
    db.create_all()
    user = User(email="r01-r04-pg18@example.invalid", full_name="Synthetic",
                role="user", plan="free", is_active=True)
    db.session.add(user)
    db.session.commit()
    user_id = user.id

login_utils._get_user = lambda: SimpleNamespace(
    id=user_id, email="r01-r04-pg18@example.invalid",
    role="user", is_authenticated=True, is_active=True
)
application._validar_csv = lambda *a, **kw: (True, "")
application.record_processing_error_safe = lambda **kw: None
application._guardar_token_pdf = lambda *args, **kw: None
pdf_calls = []
application.generar_pdf = lambda *args, **kw: pdf_calls.append(1) or b"%PDF-SYNTHETIC"
PDF = Path(os.environ["FISCAL_CI_PDF_PATH"])
application._derivar_ruta_pdf = lambda _path: str(PDF)


def fixture(mode):
    m = MotorFIFO()
    if mode != "none":
        m.registrar_compra("2024-01-01", "BTC", 1, 100, "EUR", "EUR", 0)
    if mode == "swap":
        m.registrar_swap("2025-01-01", "BTC", 1, "ETH", 2)
    elif mode == "none":
        m.registrar_venta("2025-01-01", "BTC", 1, 300, "EUR", "EUR", 0)
    elif mode == "partial":
        m.registrar_venta("2025-01-01", "BTC", 2, 400, "EUR", "EUR", 0)
    else:
        m.registrar_venta("2025-01-01", "BTC", 1, 150, "EUR", "EUR", 0)
    c = SimpleNamespace(swaps=[], compraventas=[], rendimientos=[],
                        movimientos=[], desconocidas=[], advertencias=[])
    if mode == "swap":
        c.swaps = [SimpleNamespace(activo_entregado="BTC", activo_recibido="ETH",
                                   precio_fmv_eur=300)]
    elif mode == "nexo":
        c = ClasificadorNexo.__new__(ClasificadorNexo)
        c.swaps, c.compraventas, c.rendimientos = [], [
            SimpleNamespace(contraparte="USD", importe=200)], []
        c.movimientos, c.desconocidas = [], []
        c.advertencias = ["Compraventa: importe almacenado en USD"]
    elif mode == "uphold":
        c = ClasificadorUphold.__new__(ClasificadorUphold)
        c.swaps, c.compraventas = [], []
        c.rendimientos = [SimpleNamespace(cantidad=1, valor_eur=0)]
        c.movimientos, c.desconocidas, c.advertencias = [], [], []
    return m, [], c


modes = ("swap", "nexo", "none", "partial", "uphold", "valid")
for mode in modes:
    exchange = "nexo" if mode == "nexo" else "uphold" if mode == "uphold" else "bitvavo"
    setattr(application, "procesar_" + exchange, lambda _p, k=mode: fixture(k))
    application.limiter.reset()
    with app.test_client() as client:
        response = client.post(
            "/api/analizar",
            data={"csv": (io.BytesIO(b"Date,Value\n2025-01-01,1\n"), "test.csv"),
                  "exchange": exchange, "nombre": "Synthetic", "ejercicio": "2025"},
            content_type="multipart/form-data",
        )
    if mode == "valid":
        assert response.status_code == 200, (mode, response.get_data(as_text=True)[:300])
        assert response.json["resumen"]["resultado_neto"] == 50
        assert response.json["token"] == PDF.name
        assert PDF.read_bytes() == b"%PDF-SYNTHETIC"
    else:
        assert response.status_code == 422, (mode, response.get_data(as_text=True)[:300])
        assert "token" not in response.json and "resumen" not in response.json
        assert not PDF.exists()
    with app.app_context():
        rows = list(FifoReport.query.order_by(FifoReport.id).all())
        assert len(rows) == modes.index(mode) + 1
        assert rows[-1].status == ("generated" if mode == "valid" else "failed")
        assert sum(r.status == "generated" for r in rows) == (1 if mode == "valid" else 0)
assert len(pdf_calls) == 1
print("PG18_FISCAL_R01_R04: PASS 5 failed + 1 generated")
'''


def main():
    guard()
    database(True)
    try:
        with tempfile.TemporaryDirectory(prefix="fiscal-r01-r04-pg18-") as temp:
            url = f"postgresql+psycopg2://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB}"
            env = {
                "GITHUB_ACTIONS": "true", "CI": "true", "FLASK_ENV": "testing",
                "DATABASE_URL": url,
                "PYTHONPATH": str(ROOT), "PATH": os.environ.get("PATH", ""),
                "HOME": temp, "FISCAL_CI_PDF_PATH": str(Path(temp) / "report.pdf"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            proc = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(PROGRAM)],
                cwd=ROOT, env=env, text=True, capture_output=True, timeout=110,
            )
            if proc.returncode:
                raise AssertionError((proc.stdout + "\n" + proc.stderr)[-6500:])
            assert "PG18_FISCAL_R01_R04: PASS" in proc.stdout, proc.stdout
            print(proc.stdout.strip())
    finally:
        database(False)


if __name__ == "__main__":
    main()
