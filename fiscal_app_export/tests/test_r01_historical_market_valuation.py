"""Automatic R01 IRPF valuation acceptance with synthetic hourly market data.

No external HTTP/network, client CSV, production DB or credentials.
Manually computed oracle: acquisition BTC 100; BTC FMV 300;
2 ETH FMV 310 -> taxable gain 210, ETH basis 310.
Subsequent sale of 1 ETH for 200 -> gain 45, total 255 EUR.
"""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import requests
import pytest

from app import _pipeline_motor, _preparar_motor_fiscal_irpf, _motor_a_json
from valoracion_permutas import ValoradorPermutasEUR, _fecha_utc


def data():
    buy = SimpleNamespace(
        fecha="2024-01-01 10:00:00", tipo="COMPRA", activo="BTC",
        cantidad=1, contraparte="EUR", importe=100,
        fee_activo="EUR", fee_cantidad=0,
    )
    swap = SimpleNamespace(
        fecha="2025-01-01 10:00:00", activo_entregado="BTC", cantidad_entregada=1,
        activo_recibido="ETH", cantidad_recibida=2, nota="synthetic swap",
        precio_fmv_eur=0,
    )
    sale = SimpleNamespace(
        fecha="2025-01-02 10:00:00", tipo="VENTA", activo="ETH",
        cantidad=1, contraparte="EUR", importe=200,
        fee_activo="EUR", fee_cantidad=0,
    )
    return SimpleNamespace(compraventas=[buy, sale], swaps=[swap], rendimientos=[])


class FakeResp:
    status_code = 200

    def __init__(self, prices):
        self._prices = prices

    def json(self):
        return {"prices": self._prices}


def mock_prices(monkeypatch, prices=None, offset_seconds=0, status=200):
    import valoracion_permutas as vp
    prices = prices or {"bitcoin": 300, "ethereum": 155}
    calls = []

    def get(url, *, params, headers, timeout):
        calls.append(url)
        assert url.startswith("https://") and timeout <= 4
        assert params["vs_currency"] == "eur"
        coin = url.rsplit("/", 3)[1]  # /coins/{id}/market_chart/range
        # URL ends in range. Extract by segment instead.
        coin = url.split("/coins/", 1)[1].split("/", 1)[0]
        centre = int((params["from"] + params["to"]) / 2)
        result = FakeResp([[((centre + offset_seconds) * 1000), prices[coin]]])
        result.status_code = status
        return result

    monkeypatch.setattr(vp.requests, "get", get)
    return calls


def test_r01_automatic_two_leg_prices_correct_fifo_and_future_sale(monkeypatch):
    calls = mock_prices(monkeypatch)
    c = data()
    old_motor = _pipeline_motor(c)
    assert old_motor.resumen_fiscal()["resultado_neto"] != 255
    m = _preparar_motor_fiscal_irpf(old_motor, c)
    summary, pos, ops = _motor_a_json(m, c)
    assert summary["resultado_neto"] == 255
    assert [(r.tipo_operacion, r.precio_transmision, r.precio_coste,
             r.ganancia_perdida) for r in m.resultados] == [
                 ("swap", 310, 100, 210), ("venta", 200, 155, 45)]
    assert len(m.permutas_valoradas) == 1
    assert "CoinGecko/bitcoin" in m.permutas_valoradas[0]
    assert "CoinGecko/ethereum" in m.permutas_valoradas[0]
    assert "310" in m.permutas_valoradas[0]
    assert any("Valoración de mercado" in a for a in m.advertencias)
    assert len(calls) == 2


def test_r01_coinbase_fmv_for_received_leg_avoids_second_external_request(monkeypatch):
    calls = mock_prices(monkeypatch, {"bitcoin": 300})
    c = data()
    # Trusted EUR convert subtotal from Coinbase; includes validation in parser.
    coinbase = type("ClasificadorCoinbase", (), {})()
    coinbase.compraventas, coinbase.swaps, coinbase.rendimientos = (
        c.compraventas, c.swaps, c.rendimientos)
    c = coinbase
    c.swaps[0].precio_fmv_eur = 320.0
    m = _preparar_motor_fiscal_irpf(_pipeline_motor(c), c)
    assert _motor_a_json(m, c)[0]["resultado_neto"] == 260
    assert len(calls) == 1
    assert "Coinbase/Convert EUR" in m.permutas_valoradas[0]


@pytest.mark.parametrize("status,offset", [(429, 0), (200, 31 * 60)])
def test_r01_missing_or_stale_market_data_fails_closed(monkeypatch, status, offset):
    mock_prices(monkeypatch, status=status, offset_seconds=offset)
    c = data()
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        _preparar_motor_fiscal_irpf(_pipeline_motor(c), c)


def test_r01_unknown_ticker_never_calls_provider(monkeypatch):
    calls = mock_prices(monkeypatch)
    c = data()
    c.swaps[0].activo_recibido = "NONEXISTENT_FAKE_999"
    with pytest.raises(ValueError, match="NONEXISTENT_FAKE_999"):
        _preparar_motor_fiscal_irpf(_pipeline_motor(c), c)
    assert len(calls) == 1


def test_r01_legacy_model_721_pipeline_not_implicitly_repriced(monkeypatch):
    calls = mock_prices(monkeypatch)
    c = data()
    m = _pipeline_motor(c)
    assert not m.permutas_valoradas
    assert calls == []


def test_r01_no_swap_never_uses_provider(monkeypatch):
    calls = mock_prices(monkeypatch)
    c = data()
    c.swaps = []
    m = _pipeline_motor(c)
    assert _preparar_motor_fiscal_irpf(m, c) is m
    assert not calls


def test_r01_resolver_caches_provider_response_for_same_hour(monkeypatch):
    calls = mock_prices(monkeypatch)
    resolver = ValoradorPermutasEUR()
    when = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert resolver.precio("BTC", when)
    assert resolver.precio("BTC", when + timedelta(minutes=5))
    assert len(calls) == 1


@pytest.mark.parametrize("bad", ["invalid", "", "2025-12-60"])
def test_r01_bad_timestamp_rejected(bad):
    with pytest.raises(ValueError, match="Datos fiscales no seguros"):
        _fecha_utc(bad)


def test_r01_real_http_swap_200_only_when_both_eur_prices_available(monkeypatch, tmp_path):
    """Complete JSON/PDF/token path with independent synthetic market quotes."""
    import io
    import app as application
    import flask_login.utils as login_utils
    mock_prices(monkeypatch)
    c = data()
    # Direct HTTP parser stub keeps classification real and SQL writes mocked:
    # exact pipeline, historical quotes, and generation order are exercised.
    fake_user = SimpleNamespace(
        id=93111, email="synthetic@example.invalid", role="user",
        is_authenticated=True, is_active=True,
    )
    monkeypatch.setattr(login_utils, "_get_user", lambda: fake_user)
    monkeypatch.setattr(application, "_validar_csv", lambda *args, **kwargs: (True, ""))
    monkeypatch.setattr(
        application, "procesar_bitvavo", lambda _path: (_pipeline_motor(c), [], c)
    )
    writes, tokens, pdf_calls = [], [], []
    def pdf(motor, *args, **kwargs):
        pdf_calls.append(motor.resumen_fiscal()["resultado_neto"])
        assert len(motor.permutas_valoradas) == 1
        return b"%PDF-SYNTHETIC"
    monkeypatch.setattr(application, "generar_pdf", pdf)
    monkeypatch.setattr(application, "_registrar_informe",
                        lambda **kw: writes.append(kw) or 101)
    monkeypatch.setattr(application, "record_processing_error_safe",
                        lambda **kw: None)
    monkeypatch.setattr(application, "_guardar_token_pdf",
                        lambda *args: tokens.append(args))
    output = tmp_path / "market-valued.pdf"
    monkeypatch.setattr(application, "_derivar_ruta_pdf", lambda _path: str(output))
    with application.app.test_client() as client:
        response = client.post(
            "/api/analizar", data={
                "csv": (io.BytesIO(b"Date,Operation\\n2025-01-01,synthetic\\n"),
                        "synthetic.csv"),
                "exchange": "bitvavo", "nombre": "Synthetic",
                "ejercicio": "2025",
            },
            content_type="multipart/form-data",
        )
    assert response.status_code == 200, response.get_data(as_text=True)[:350]
    assert response.json["resumen"]["resultado_neto"] == 255
    assert response.json["token"] == "market-valued.pdf"
    assert output.read_bytes() == b"%PDF-SYNTHETIC"
    assert pdf_calls == [255] and len(tokens) == 1
    assert writes and writes[0].get("status", "generated") == "generated"
