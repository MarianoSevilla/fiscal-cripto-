"""R01-R04: containment regression on current production main.

No real CSV, user account or external database; all facts are synthetic.
R01 market valuation follows AEAT IRPF 2025 art. 37.1.h.
"""
import io
from types import SimpleNamespace

import pytest

from app import app, _motor_a_json, _validar_aceptacion_fifo
from clasificador_nexo import ClasificadorNexo
from clasificador_uphold import ClasificadorUphold
from motor_fifo import MotorFIFO


def _motor(mode):
    m = MotorFIFO()
    if mode != "none":
        m.registrar_compra("2024-01-01", "BTC", 1, 100, "EUR", "EUR", 0)
    if mode == "swap":
        m.registrar_swap("2025-01-01", "BTC", 1, "ETH", 2)
    elif mode == "partial":
        m.registrar_venta("2025-01-01", "BTC", 2, 400, "EUR", "EUR", 0)
    elif mode == "none":
        m.registrar_venta("2025-01-01", "BTC", 1, 300, "EUR", "EUR", 0)
    elif mode == "valid":
        m.registrar_venta("2025-01-01", "BTC", 1, 150, "EUR", "EUR", 0)
    return m


def _classifier(mode):
    c = SimpleNamespace(
        swaps=[], compraventas=[], rendimientos=[],
        movimientos=[], desconocidas=[], advertencias=[],
    )
    if mode == "swap":
        c.swaps = [SimpleNamespace(
            activo_entregado="BTC", activo_recibido="ETH",
            cantidad_entregada=1, cantidad_recibida=2, precio_fmv_eur=300,
        )]
    elif mode == "nexo":
        c = ClasificadorNexo.__new__(ClasificadorNexo)
        c.swaps, c.compraventas, c.rendimientos = [], [
            SimpleNamespace(contraparte="USD", importe=200)], []
        c.movimientos, c.desconocidas = [], []
        c.advertencias = ["Compraventa en USDT: importe almacenado en USD. Convierte manualmente."]
    elif mode == "uphold":
        c = ClasificadorUphold.__new__(ClasificadorUphold)
        c.swaps, c.compraventas = [], []
        c.rendimientos = [SimpleNamespace(cantidad=1, valor_eur=0, subtipo="Brave Rewards")]
        c.movimientos, c.desconocidas = [], []
        c.advertencias = ["Brave Rewards no provee valor EUR"]
    return c


@pytest.mark.parametrize("mode,why", [
    ("swap", "permutas"), ("nexo", "USD"),
    ("none", "historial de adquisiciones"),
    ("partial", "inventario FIFO insuficiente"),
    ("uphold", "rendimiento Uphold"),
])
def test_r01_r04_unsafe_fiscal_reports_blocked_before_success_json(mode, why):
    m = _motor("swap" if mode == "swap" else "none" if mode == "none" else "partial" if mode == "partial" else "valid")
    c = _classifier(mode)
    with pytest.raises(ValueError, match="Datos fiscales no seguros") as e:
        _motor_a_json(m, c)
    assert why in str(e.value)


def test_valid_eur_sale_retains_correct_gain_without_warning():
    m = _motor("valid")
    summary, _positions, operations = _motor_a_json(m, _classifier("valid"))
    assert summary["resultado_neto"] == 50.0
    assert operations[0]["ganancia_perdida"] == 50.0


def test_r01_even_valid_looking_positive_fmv_does_not_override_required_two_sided_market_pricing():
    m = _motor("swap")
    with pytest.raises(ValueError, match="permutas"):
        _validar_aceptacion_fifo(m, _classifier("swap"))


@pytest.mark.parametrize("mode,exchange", [
    ("swap", "bitvavo"), ("nexo", "nexo"),
    ("none", "bitvavo"), ("partial", "bitvavo"),
    ("uphold", "uphold"),
])
def test_http_422_no_token_no_pdf_no_generated_record(monkeypatch, tmp_path, mode, exchange):
    import app as application
    import flask_login.utils as login_utils
    user = SimpleNamespace(id=730011, role="user", email="synthetic@example.invalid",
                           is_authenticated=True, is_active=True)
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)
    monkeypatch.setattr(application, "_validar_csv", lambda *args, **kwargs: (True, ""))
    # External price provider is mocked. Historical failure must produce HTTP 422.
    import valoracion_permutas
    class NoQuote:
        status_code = 429
    monkeypatch.setattr(valoracion_permutas.requests, "get", lambda *args, **kwargs: NoQuote())
    m = _motor("swap" if mode == "swap" else "none" if mode == "none" else "partial" if mode == "partial" else "valid")
    c = _classifier(mode)
    processor = {"nexo": "procesar_nexo", "uphold": "procesar_uphold"}.get(exchange, "procesar_bitvavo")
    monkeypatch.setattr(application, processor, lambda _path: (m, [], c))
    reports, pdf_calls, tokens = [], [], []
    monkeypatch.setattr(application, "_registrar_informe", lambda **kw: reports.append(kw) or 1)
    monkeypatch.setattr(application, "record_processing_error_safe", lambda **kw: None)
    monkeypatch.setattr(application, "_guardar_token_pdf", lambda *a: tokens.append(a))
    monkeypatch.setattr(application, "generar_pdf", lambda *a, **kw: pdf_calls.append(1) or b"%PDF")
    with app.test_client() as client:
        resp = client.post("/api/analizar", data={
            "csv": (io.BytesIO(b"Date,Test\\n2025-01-01,1\\n"), "synthetic.csv"),
            "exchange": exchange, "nombre": "synthetic", "ejercicio": "2025",
        }, content_type="multipart/form-data")
    assert resp.status_code == 422, resp.get_data(as_text=True)[:350]
    assert resp.json and "Datos fiscales no seguros" in resp.json["error"]
    assert "token" not in resp.json and "resumen" not in resp.json
    assert not pdf_calls and not tokens
    assert reports and all(row.get("status") == "failed" for row in reports)


def test_http_valid_eur_200_json_pdf_and_success_record(monkeypatch, tmp_path):
    import app as application
    import flask_login.utils as login_utils
    user = SimpleNamespace(id=730012, role="user", email="synthetic@example.invalid",
                           is_authenticated=True, is_active=True)
    monkeypatch.setattr(login_utils, "_get_user", lambda: user)
    monkeypatch.setattr(application, "_validar_csv", lambda *args, **kwargs: (True, ""))
    # External price provider is mocked. Historical failure must produce HTTP 422.
    import valoracion_permutas
    class NoQuote:
        status_code = 429
    monkeypatch.setattr(valoracion_permutas.requests, "get", lambda *args, **kwargs: NoQuote())
    monkeypatch.setattr(application, "procesar_bitvavo", lambda p: (_motor("valid"), [], _classifier("valid")))
    reports, tokens, pdf_calls = [], [], []
    monkeypatch.setattr(application, "_registrar_informe", lambda **kw: reports.append(kw) or 123)
    monkeypatch.setattr(application, "_guardar_token_pdf", lambda *a: tokens.append(a))
    monkeypatch.setattr(application, "generar_pdf", lambda *a, **kw: pdf_calls.append(1) or b"%PDF-TEST")
    path = tmp_path / "synthetic-report.pdf"
    monkeypatch.setattr(application, "_derivar_ruta_pdf", lambda _p: str(path))
    with app.test_client() as client:
        resp = client.post("/api/analizar", data={
            "csv": (io.BytesIO(b"Date,Test\\n2025-01-01,1\\n"), "synthetic.csv"),
            "exchange": "bitvavo", "nombre": "synthetic", "ejercicio": "2025",
        }, content_type="multipart/form-data")
    assert resp.status_code == 200, resp.get_data(as_text=True)[:350]
    assert resp.json["resumen"]["resultado_neto"] == 50
    assert resp.json["token"] == "synthetic-report.pdf"
    assert path.read_bytes() == b"%PDF-TEST"
    assert pdf_calls == [1] and len(tokens) == 1
    assert reports and all(row.get("status", "generated") == "generated" for row in reports)
