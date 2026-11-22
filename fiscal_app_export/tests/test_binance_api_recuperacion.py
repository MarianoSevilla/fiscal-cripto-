"""Conector Binance Spot solo lectura: ensayos sin red ni credenciales reales."""
from pathlib import Path
import csv
import io
import sys
from urllib.parse import parse_qs, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_api_recuperacion import BinanceReadOnlySpot, BinanceApiRecoveryError


def _trade(tid=5, **extra):
    return dict({
        "symbol": "BTCUSDT", "id": tid, "orderId": 99, "time": 1735689600000,
        "isBuyer": True, "price": "90000.01", "qty": "0.01",
        "quoteQty": "900.0001", "commission": "0.0001", "commissionAsset": "BNB",
    }, **extra)


class FakeTransport:
    def __init__(self, *, trading=False, prices=None):
        self.calls = []
        self.trading = trading
        self.prices = prices

    def __call__(self, url, headers):
        parsed = urlsplit(url)
        self.calls.append((parsed.path, dict(headers), parse_qs(parsed.query)))
        if parsed.path == "/sapi/v1/account/apiRestrictions":
            return {"enableReading": True, "enableSpotAndMarginTrading": self.trading,
                    "enableWithdrawals": False, "enableFutures": False,
                    "enableMargin": False, "enableInternalTransfer": False}
        if parsed.path == "/api/v3/exchangeInfo":
            return {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC",
                                 "quoteAsset": "USDT"}]}
        if parsed.path == "/api/v3/myTrades":
            return self.prices if self.prices is not None else [_trade()]
        raise AssertionError(f"Unexpected GET {parsed.path}")


def test_api_spot_privada_exporta_identidades_fills_y_comisiones():
    fake = FakeTransport()
    reader = BinanceReadOnlySpot("K" * 64, "S" * 64,
                                 transport=fake, now_ms=lambda: 1736000000000)
    result = reader.retrieve("BTCUSDT")
    assert result["records"] == 1
    assert not result["has_more"]
    assert result["next_id"] == 6
    data = result["csv"].decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(data)))
    assert rows[0]["Número de pedido"] == "99"
    assert rows[0]["ID de ejecución API"] == "5"
    assert rows[0]["Ejecutado"] == "0.01BTC"
    assert rows[0]["Cantidad"] == "900.0001USDT"
    assert rows[0]["Tarifa"] == "0.0001BNB"
    assert rows[0]["Tiempo"] == "2025-01-01 00:00:00"
    signed = [call for call in fake.calls if call[0].endswith("myTrades")]
    assert len(signed) == 1
    assert signed[0][1]["X-MBX-APIKEY"] == "K" * 64
    assert signed[0][2]["fromId"] == ["0"]
    assert "signature" in signed[0][2]
    assert "K" * 64 not in data and "S" * 64 not in data
    assert all(path in (
        "/sapi/v1/account/apiRestrictions", "/api/v3/exchangeInfo",
        "/api/v3/myTrades",
    ) for path, _, _ in fake.calls)


def test_api_mercado_con_permiso_de_trading_se_rechaza_sin_leer_historial():
    fake = FakeTransport(trading=True)
    with pytest.raises(BinanceApiRecoveryError, match="permisos adicionales"):
        BinanceReadOnlySpot("K" * 64, "S" * 64, transport=fake).retrieve("BTCUSDT")
    assert [name for name, _, _ in fake.calls] == [
        "/sapi/v1/account/apiRestrictions"
    ]


@pytest.mark.parametrize("symbol", [
    "", "BTCUSDT/", "../orders", "BTCUSDT?trade=1", "BTC USDT", "btcUSDT",
])
def test_api_rechaza_simbolo_invalido_sin_red(symbol):
    fake = FakeTransport()
    with pytest.raises(BinanceApiRecoveryError):
        BinanceReadOnlySpot("K" * 64, "S" * 64,
                            transport=fake).retrieve(symbol)
    assert fake.calls == []


def test_api_rechaza_importes_y_identidad_invalidos_sin_csv():
    fake = FakeTransport(prices=[_trade(price="-1")])
    with pytest.raises(BinanceApiRecoveryError, match="cantidades"):
        BinanceReadOnlySpot("K" * 64, "S" * 64, transport=fake).retrieve("BTCUSDT")


def test_api_no_exagera_cobertura_de_1000_fills():
    fake = FakeTransport(prices=[_trade(tid=i) for i in range(1000)])
    reader = BinanceReadOnlySpot("K" * 64, "S" * 64, transport=fake)
    # Cuando un proveedor repite la misma página pese a fromId, falla cerrado.
    with pytest.raises(BinanceApiRecoveryError, match="Secuencia"):
        reader.retrieve("BTCUSDT")
