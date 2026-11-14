"""Catálogo público fijo (sin red), reproducible y probado con cotizaciones sintéticas."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_eur_valuation import BinancePriceEvidenceError, TradePriceEvidence
from binance_market_cache_cli import (
    BinanceCatalogError, parse_private_manifest, build_public_price_catalog,
)
from binance_verified_price_catalog import (
    load_pinned_verified_catalog, serialize_verified_catalog,
)


T = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def item(asset="XRP", quote="EUR", price="2", when=T, ident=1):
    return TradePriceEvidence(asset, quote, Decimal(price), when, ident, "a"*64)


def save(tmp_path, evidence):
    path = tmp_path / "prices.json"
    raw = serialize_verified_catalog(evidence)
    path.write_bytes(raw)
    return path, sha256(raw).hexdigest()


def test_pinned_catalog_loads_without_network(tmp_path, monkeypatch):
    path, digest = save(tmp_path, [item(), item("USDC", "EUR", "0.9", ident=2)])
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a,**kw: pytest.fail("Red prohibida"))
    book = load_pinned_verified_catalog(path.resolve(), expected_sha256=digest)
    assert book.price_eur("XRP", T).unit_price_eur == Decimal("2")
    assert book.value_swap(
        timestamp=T, given_asset="XRP", given_amount=Decimal("5"),
        received_asset="USDC", received_amount=Decimal("11")
    ).fiscal_value_eur == Decimal("10")


def test_pinned_catalog_fails_if_changed(tmp_path):
    path, sha = save(tmp_path, [item()])
    path.write_bytes(path.read_bytes().replace(b'"2"', b'"3"', 1))
    with pytest.raises(BinanceCatalogError, match="SHA256"):
        load_pinned_verified_catalog(path.resolve(), expected_sha256=sha)


def test_pinned_catalog_rejects_relative_path_symlink_and_unpinned(tmp_path):
    path, digest = save(tmp_path, [item()])
    with pytest.raises(BinanceCatalogError, match="absoluta"):
        load_pinned_verified_catalog("prices.json", expected_sha256=digest)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(BinanceCatalogError):
        load_pinned_verified_catalog(link, expected_sha256=digest)
    with pytest.raises(BinanceCatalogError, match="SHA256"):
        load_pinned_verified_catalog(path.resolve(), expected_sha256="oops")


def test_catalog_rejects_unknown_fields_or_duplicate_json_keys(tmp_path):
    path, _ = save(tmp_path, [item()])
    for data in (
        b'{"schema_version":1,"schema_version":1,"max_age_seconds":60,"trades":[]}',
        json.dumps({"schema_version": 1, "max_age_seconds": 60, "trades": [{
            "asset":"XRP","price":"2"
        }]}).encode(),
    ):
        path.write_bytes(data)
        with pytest.raises(BinanceCatalogError):
            load_pinned_verified_catalog(
                path.resolve(), expected_sha256=sha256(data).hexdigest()
            )


def test_catalog_rejects_duplicate_price_identity_and_future_spread():
    with pytest.raises(BinanceCatalogError, match="diferente"):
        serialize_verified_catalog([
            item(price="2", ident=33),
            item(price="4", ident=33),
        ])
    with pytest.raises(BinanceCatalogError, match="política"):
        serialize_verified_catalog([item()], max_age_seconds=300)


def test_private_manifest_parses_utc_without_amounts():
    raw = json.dumps({"schema_version": 1,"events":[{
        "timestamp_utc":"2025-01-01T12:00:00Z",
        "given_asset":"XRP","received_asset":"USDC"
    }]}).encode()
    assert parse_private_manifest(raw) == ((T, "XRP", "USDC"),)
    with pytest.raises(BinanceCatalogError):
        parse_private_manifest(raw.replace(b"Z",b"+01:00"))


def test_offline_fetch_builds_real_price_path_without_stablecoin_parity(tmp_path):
    events = ((T, "XRP", "USDC"),)
    observed = []

    def fake_download(*,symbol,base,quote,period,target_times,max_age_seconds):
        observed.append((symbol,period))
        if symbol == "XRPEUR":
            return [item("XRP","EUR","2",T-timedelta(seconds=1),1)]
        if symbol == "USDCUSDT":
            return [item("USDC","USDT","0.95",T-timedelta(seconds=1),2)]
        if symbol == "EURUSDT":
            return [item("EUR","USDT","1.055555555555555555",T-timedelta(seconds=1),3)]
        raise BinancePriceEvidenceError("Par no publicado")

    raw, info = build_public_price_catalog(events, fetcher=fake_download)
    assert info["events"] == 1
    assert info["unique_asset_days"] == 2
    assert info["archive_matched"] == 3
    output = tmp_path / "prices.json"
    output.write_bytes(raw)
    book = load_pinned_verified_catalog(output.resolve(), expected_sha256=sha256(raw).hexdigest())
    assert book.price_eur("XRP", T).unit_price_eur == Decimal("2")
    # USDC/EUR procede de mercado USDC/USDT * USDT/EUR; NO de USDC==EUR.
    assert Decimal("0.89") < book.price_eur("USDC", T).unit_price_eur < Decimal("0.91")
    assert ("EURUSDT", "2025-01-01") in observed


def test_offline_fetch_fails_without_both_market_sides():
    events = ((T, "XRP", "USDC"),)
    def fake_download(*,symbol,base,quote,period,target_times,max_age_seconds):
        if symbol == "XRPEUR":
            return [item()]
        raise BinancePriceEvidenceError("No hay mercado")
    with pytest.raises(BinanceCatalogError, match="No se acreditaron"):
        build_public_price_catalog(events, fetcher=fake_download)
