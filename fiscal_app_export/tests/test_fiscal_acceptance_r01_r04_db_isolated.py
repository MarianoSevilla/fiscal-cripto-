"""End-to-end Flask/SQLite persistence without production secrets or connections.

Spawns an isolated interpreter with a fresh database and synthetic user.
Checks HTTP 422/200, PDF creation and actual FifoReport statuses.
"""
import os
from pathlib import Path
import subprocess
import sys
import textwrap


def test_isolated_sqlite_fiscal_fail_closed_persists_only_failed_records(tmp_path):
    app_dir = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "acceptance.sqlite"
    pdf_path = tmp_path / "valid-fifo.pdf"
    code = r'''
import io
from pathlib import Path
from types import SimpleNamespace
import flask_login.utils as login_utils
import app as app_module
from app import app
from models import db, User, FifoReport
from motor_fifo import MotorFIFO
from clasificador_nexo import ClasificadorNexo
from clasificador_uphold import ClasificadorUphold

app.config["TESTING"] = True
with app.app_context():
    db.create_all()
    user = User(email="isolated-user@example.invalid", full_name="Synthetic", role="user",
                plan="free", is_active=True)
    db.session.add(user)
    db.session.commit()
    user_id = user.id

fake = SimpleNamespace(id=user_id, email="isolated-user@example.invalid", role="user",
                       is_authenticated=True, is_active=True)
login_utils._get_user = lambda: fake
app_module._validar_csv = lambda *args, **kwargs: (True, "")
app_module.record_processing_error_safe = lambda **kwargs: None
app_module._guardar_token_pdf = lambda *args, **kwargs: None
pdf_calls = []
app_module.generar_pdf = lambda *args, **kwargs: pdf_calls.append(1) or b"%PDF-ISOLATED"
app_module._derivar_ruta_pdf = lambda _path: PDF_DEST

def build(mode):
    m = MotorFIFO()
    if mode != "none":
        m.registrar_compra("2024-01-01", "BTC", 1, 100, "EUR", "EUR", 0)
    if mode == "swap":
        m.registrar_swap("2025-01-01", "BTC", 1, "ETH", 2)
    if mode == "none":
        m.registrar_venta("2025-01-01", "BTC", 1, 300, "EUR", "EUR", 0)
    if mode == "partial":
        m.registrar_venta("2025-01-01", "BTC", 2, 400, "EUR", "EUR", 0)
    if mode == "valid":
        m.registrar_venta("2025-01-01", "BTC", 1, 150, "EUR", "EUR", 0)
    c = SimpleNamespace(swaps=[], compraventas=[], rendimientos=[],
                        movimientos=[], desconocidas=[], advertencias=[])
    if mode == "swap":
        c.swaps = [SimpleNamespace(activo_entregado="BTC", activo_recibido="ETH")]
    if mode == "nexo":
        c = ClasificadorNexo.__new__(ClasificadorNexo)
        c.swaps, c.compraventas, c.rendimientos = [], [SimpleNamespace(
            contraparte="USD", importe=200)], []
        c.movimientos, c.desconocidas, c.advertencias = [], [], []
    if mode == "uphold":
        c = ClasificadorUphold.__new__(ClasificadorUphold)
        c.swaps, c.compraventas, c.rendimientos = [], [], [
            SimpleNamespace(cantidad=1, valor_eur=0.0)]
        c.movimientos, c.desconocidas, c.advertencias = [], [], []
    return (m, [], c)

for mode in ("swap", "nexo", "none", "partial", "uphold", "valid"):
    exchange = "nexo" if mode == "nexo" else "uphold" if mode == "uphold" else "bitvavo"
    setattr(app_module, "procesar_"+exchange, lambda _path, m=mode: build(m))
    with app.test_client() as client:
        resp = client.post("/api/analizar", data={
            "csv": (io.BytesIO(b"Date,Value\n2025-01-01,1\n"), "synthetic.csv"),
            "exchange": exchange, "nombre": "Synthetic", "ejercicio": "2025",
        }, content_type="multipart/form-data")
    if mode == "valid":
        assert resp.status_code == 200, (mode, resp.get_data(as_text=True)[:400])
        assert resp.json["resumen"]["resultado_neto"] == 50
        assert Path(PDF_DEST).read_bytes() == b"%PDF-ISOLATED"
    else:
        assert resp.status_code == 422, (mode, resp.get_data(as_text=True)[:400])
        assert "token" not in resp.json and "resumen" not in resp.json
        assert not Path(PDF_DEST).exists()
    with app.app_context():
        reports = list(FifoReport.query.order_by(FifoReport.id).all())
        assert len(reports) == ["swap","nexo","none","partial","uphold","valid"].index(mode) + 1
        assert reports[-1].status == ("generated" if mode == "valid" else "failed")
        assert len([r for r in reports if r.status == "generated"]) == (1 if mode == "valid" else 0)
assert len(pdf_calls) == 1
print("ISOLATED_FISCAL_DB_HTTP_PDF: PASS 5 failed + 1 generated")
'''
    code = code.replace("PDF_DEST", repr(str(pdf_path)))
    env = {
        "FLASK_ENV": "testing",
        "DATABASE_URL": "sqlite:///" + str(db_path),
        "PYTHONPATH": str(app_dir),
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=app_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, (completed.stdout + "\n" + completed.stderr)[-4500:]
    assert "ISOLATED_FISCAL_DB_HTTP_PDF: PASS" in completed.stdout
    assert db_path.exists()
