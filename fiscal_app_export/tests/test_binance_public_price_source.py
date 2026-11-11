"""Pruebas sin conectividad externa para el proveedor histórico de Binance."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import io
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import binance_public_price_source as provider
from binance_public_price_source import (
    BinanceMarketDownloadError, fetch_official_spot_trades,
)


def test_provider_construye_zip_checksum_oficial_y_valida_trades(monkeypatch):
    name = "XRPEUR-trades-2025-01-01.zip"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name[:-4] + ".csv", "42,2.5,10,25,1735732800000000,True,True\n")
    archive = b.getvalue()
    digest = sha256(archive).hexdigest()
    seen = []

    def fake_read(url, *, limit):
        seen.append((url, limit))
        if url.endswith(".CHECKSUM"):
            return (digest + " " + name + "\n").encode("ascii")
        return archive

    monkeypatch.setattr(provider, "_read_official_https", fake_read)
    prices = fetch_official_spot_trades(
        symbol="XRPEUR", base="XRP", quote="EUR",
        period="2025-01-01",
    )
    assert len(prices) == 1
    assert prices[0].price == 2.5
    assert prices[0].archive_sha256 == digest
    assert seen == [
        ("https://data.binance.vision/data/spot/daily/trades/XRPEUR/"
         + name, provider.ZIP_LIMIT),
        ("https://data.binance.vision/data/spot/daily/trades/XRPEUR/"
         + name + ".CHECKSUM", provider.CHECKSUM_LIMIT),
    ]


def test_proveedor_rechaza_hash_incoherente(monkeypatch):
    name = "XRPEUR-trades-2025-01-01.zip"
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name[:-4] + ".csv", "42,2.5,10,25,1735732800000000,True,True\n")
    monkeypatch.setattr(provider, "_read_official_https",
                        lambda url, *, limit: b"0" * 64 if url.endswith(".CHECKSUM") else b.getvalue())
    with pytest.raises(BinanceMarketDownloadError):
        fetch_official_spot_trades(
            symbol="XRPEUR", base="XRP", quote="EUR", period="2025-01-01",
        )


@pytest.mark.parametrize("args", [
    {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT", "period": "2025-01-01"},
    {"symbol": "BTCUSDT", "base": "BTC", "quote": "EUR", "period": "2025-01-01"},
    {"symbol": "XRPEUR", "base": "XRP", "quote": "EUR", "period": "../2025-01-01"},
    {"symbol": "XRPEUR", "base": "XRP", "quote": "EUR", "period": "2025-02-30"},
    {"symbol": "XRPEUR", "base": "XRP", "quote": "EUR", "period": "2025-01-01", "granularity": "weekly"},
])
def test_proveedor_no_construye_urls_inseguras_o_fechas_invalidas(args, monkeypatch):
    def no_network(*a, **k):
        pytest.fail("No debe consultar la red")
    monkeypatch.setattr(provider, "_read_official_https", no_network)
    with pytest.raises(BinanceMarketDownloadError):
        fetch_official_spot_trades(**args)


def test_host_ajeno_no_se_abre(monkeypatch):
    def no_network(*a, **k):
        pytest.fail("No se permite ninguna llamada de red")
    monkeypatch.setattr(provider.urllib.request, "build_opener", no_network)
    with pytest.raises(BinanceMarketDownloadError):
        provider._read_official_https("https://other.example/data/spot/daily/trades", limit=1024)


def test_lectura_no_admite_redireccion(monkeypatch):
    class FakeResponse:
        status = 302
        headers = {"Content-Length": "4"}
        def __enter__(self): return self
        def __exit__(self, *_): return False

    class FakeOpener:
        def open(self, req, timeout):
            return FakeResponse()

    monkeypatch.setattr(provider.urllib.request, "build_opener", lambda *a: FakeOpener())
    with pytest.raises(BinanceMarketDownloadError, match="HTTP 200"):
        provider._read_official_https(
            "https://data.binance.vision/data/spot/daily/trades/XRPEUR/test.zip",
            limit=1024,
        )


def test_http_content_length_excede_limite(monkeypatch):
    class FakeResponse:
        status = 200
        headers = {"Content-Length": "999999"}
        def __enter__(self): return self
        def __exit__(self, *_): return False
    class FakeOpener:
        def open(self, req, timeout):
            return FakeResponse()
    monkeypatch.setattr(provider.urllib.request, "build_opener", lambda *a: FakeOpener())
    with pytest.raises(BinanceMarketDownloadError, match="límite"):
        provider._read_official_https(
            "https://data.binance.vision/data/spot/daily/trades/XRPEUR/test.zip",
            limit=32,
        )


def test_provider_forwards_sparse_targets_to_verified_parser(monkeypatch):
    from datetime import timedelta
    target = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
    name = "XRPEUR-trades-2025-01-01.zip"
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name[:-4] + ".csv", "\n".join([
            "1,2.1,1,2.1,1735732799000000,True,True",
            "2,999,1,999,1735732801000000,True,True",
        ]) + "\n")
    digest = sha256(raw.getvalue()).hexdigest()
    monkeypatch.setattr(provider, "_read_official_https",
        lambda url, *, limit: (digest+" "+name).encode("ascii")
        if url.endswith(".CHECKSUM") else raw.getvalue())
    data = fetch_official_spot_trades(
        symbol="XRPEUR", base="XRP", quote="EUR",
        period="2025-01-01", target_times=[target],
    )
    assert len(data) == 1
    assert data[0].price == 2.1
    assert data[0].observed_at == target - timedelta(seconds=1)
