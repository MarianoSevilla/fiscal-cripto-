"""Synthetic-only regression for private Binance market manifest extraction."""
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_market_manifest_cli import (
    build_private_market_manifest,
    extract_manifest_from_files,
    main,
)
from binance_market_cache_cli import parse_private_manifest
from binance_verified_price_catalog import BinanceCatalogError


SPOT_HEADER = (
    "Número de pedido,Tiempo,Par,Lado,Precio,Ejecutado,Cantidad,Tarifa,"
    "Par de conversión de AOR,Tasa de conversión de AOR\n"
)


def swap(*, timestamp="2025-01-01 13:00:00", filename="Spot-(UTC+1).csv",
         given="USDC", received="XRP", source="Spot BUY", amount="10"):
    return SimpleNamespace(
        source=source, local_time=timestamp, filename=filename,
        given_asset=given, received_asset=received,
        given_amount=amount, received_amount="5",
        fee_asset="BNB", fee_amount="0.001",
        private_account_id="should-not-leak",
    )


def classify(*events):
    return SimpleNamespace(intercambios_nativos=events)


def test_manifest_contains_only_timestamp_and_assets_not_money_or_identifiers():
    raw, summary = build_private_market_manifest(classify(
        swap(), swap(given="EUR", received="BTC"), 
    ))
    assert summary == {"native_swaps": 1, "market_events": 1}
    assert parse_private_manifest(raw)
    assert json.loads(raw) == {
        "schema_version": 1,
        "events": [{
            "timestamp_utc": "2025-01-01T12:00:00Z",
            "given_asset": "USDC",
            "received_asset": "XRP",
        }],
    }
    for forbidden in (b"10", b"0.001", b"BNB", b"should-not-leak",
                      b"Spot-(UTC+1).csv", b"private_account_id"):
        assert forbidden not in raw


def test_multiple_fills_at_same_second_only_need_one_market_request():
    raw, summary = build_private_market_manifest(classify(swap(), swap()))
    assert summary == {"native_swaps": 2, "market_events": 1}
    assert len(json.loads(raw)["events"]) == 1


def test_different_seconds_are_not_silently_combined():
    raw, summary = build_private_market_manifest(classify(
        swap(), swap(timestamp="2025-01-01 13:00:01"),
    ))
    assert summary["market_events"] == 2
    assert len(parse_private_manifest(raw)) == 2


@pytest.mark.parametrize("kwargs", [
    {"filename": "Binance-Spot.csv"},
    {"filename": "Spot-(UTC+15).csv"},
    {"timestamp": "2025-13-01 13:00:00"},
])
def test_missing_timezone_or_invalid_dates_fail_closed(kwargs):
    with pytest.raises(BinanceCatalogError):
        build_private_market_manifest(classify(swap(**kwargs)))


def test_unhandled_non_eur_native_exchange_cannot_be_silently_omitted():
    with pytest.raises(BinanceCatalogError, match="incompleto"):
        build_private_market_manifest(classify(
            swap(source="Fiat trade", given="USD", received="USDC"),
        ))


def test_only_eur_trades_are_not_market_swap_manifest():
    with pytest.raises(BinanceCatalogError, match="no contienen permutas"):
        build_private_market_manifest(classify(swap(given="EUR")))


def test_more_than_catalog_limit_fails_instead_of_truncating():
    events = [
        swap(timestamp=f"2025-01-{d:02d} 13:{minute:02d}:00")
        for d in range(1, 5) for minute in range(60)
    ]
    with pytest.raises(BinanceCatalogError, match="Demasiadas"):
        build_private_market_manifest(classify(*events))


def test_zip_and_csv_through_real_secure_importer_build_private_manifest(tmp_path):
    raw_spot = (
        SPOT_HEADER
        + "1,2025-01-01 13:00:00,XRPUSDC,BUY,2,5XRP,10USDC,0XRP,,\n"
        + "2,2025-01-02 13:00:00,XRPEUR,SELL,3,2XRP,6EUR,0EUR,,\n"
    ).encode("utf-8-sig")
    zipped = tmp_path / "Binance-Spot-2025-(UTC+1).zip"
    with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("original.csv", raw_spot)
    # A second simple EUR purchase proves that fiat events are omitted.
    euros = tmp_path / "Binance-EUR-(UTC+1).csv"
    euros.write_bytes((
        SPOT_HEADER
        + "3,2024-01-01 13:00:00,BTCEUR,BUY,100,1BTC,100EUR,0BTC,,\n"
    ).encode("utf-8-sig"))
    raw, summary = extract_manifest_from_files([zipped, euros])
    assert summary["native_swaps"] == 1
    assert parse_private_manifest(raw) == (
        (parse_private_manifest(raw)[0][0], "USDC", "XRP"),
    )
    assert json.loads(raw)["events"][0]["timestamp_utc"] == "2025-01-01T12:00:00Z"


def test_command_writes_private_mode_and_does_not_replace_previous_manifest(
    tmp_path, capsys,
):
    spot = tmp_path / "Binance-Spot-(UTC+1).csv"
    spot.write_bytes((
        SPOT_HEADER
        + "1,2025-01-01 13:00:00,XRPUSDC,BUY,2,5XRP,10USDC,0XRP,,\n"
    ).encode("utf-8-sig"))
    output = tmp_path / "private.json"
    args = ["--source", str(spot), "--output", str(output)]
    main(args)
    assert parse_private_manifest(output.read_bytes())
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    msg = capsys.readouterr().out
    assert "MANIFIESTO_PRIVADO_OK" in msg
    assert "2025-01-01" not in msg
    with pytest.raises(FileExistsError):
        main(args)



def test_offline_catalog_cli_accepts_original_zip_without_manual_manifest(
    tmp_path, monkeypatch, capsys,
):
    """One operator command, source ZIP to pinned catalogue, never network."""
    import binance_market_cache_cli as offline
    from hashlib import sha256
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from binance_eur_valuation import TradePriceEvidence
    from binance_verified_price_catalog import (
        load_pinned_verified_catalog, serialize_verified_catalog,
    )

    raw_spot = (SPOT_HEADER
                + "1,2025-01-01 13:00:00,XRPUSDC,BUY,2,5XRP,10USDC,0XRP,,\n")
    path = tmp_path / "Spot-(UTC+1).zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("spot.csv", raw_spot.encode("utf-8-sig"))
    observed = []

    def offline_fetch(events):
        observed.extend(events)
        at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        prices = [
            TradePriceEvidence("XRP", "EUR", Decimal("2"),
                               at-timedelta(seconds=1), 1, "a"*64),
            TradePriceEvidence("USDC", "EUR", Decimal("0.9"),
                               at-timedelta(seconds=1), 2, "b"*64),
        ]
        return serialize_verified_catalog(prices), {"events": len(events)}

    monkeypatch.setattr(offline, "build_public_price_catalog", offline_fetch)
    target = tmp_path / "catalog.json"
    offline.main(["--source", str(path), "--output", str(target)])
    assert len(observed) == 1
    assert observed[0][1:] == ("USDC", "XRP")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    digest = sha256(target.read_bytes()).hexdigest()
    catalogue = load_pinned_verified_catalog(target.resolve(),
                                              expected_sha256=digest)
    assert catalogue.price_eur("XRP", observed[0][0]).unit_price_eur == 2
    assert "CATALOGO_PUBLICO_OK SHA256=" in capsys.readouterr().out
    assert not list(tmp_path.glob("*manifest*"))
    with pytest.raises(FileExistsError):
        offline.main(["--source", str(path), "--output", str(target)])


def test_offline_catalog_cli_remains_compatible_with_private_manifest(
    tmp_path, monkeypatch,
):
    from datetime import datetime, timezone
    from decimal import Decimal
    import binance_market_cache_cli as offline
    from binance_eur_valuation import TradePriceEvidence
    from binance_verified_price_catalog import serialize_verified_catalog

    original, _ = build_private_market_manifest(classify(swap()))
    source = tmp_path / "private_manifest.json"
    source.write_bytes(original)
    recorded = []

    def fake_market(events):
        recorded.extend(events)
        at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        return serialize_verified_catalog([
            TradePriceEvidence("XRP", "EUR", Decimal("2"), at, 1, "a"*64),
        ]), {"events": len(events)}

    monkeypatch.setattr(offline, "build_public_price_catalog", fake_market)
    output = tmp_path / "prices.json"
    offline.main(["--manifest", str(source), "--output", str(output)])
    assert output.is_file() and len(recorded) == 1
    assert stat.S_IMODE(output.stat().st_mode) == 0o600



def test_rejects_non_native_swaps_missing_from_market_manifest():
    """No successful catalogue when a legacy crypto swap was silently omitted."""
    classifier = classify(swap())
    classifier.swaps = [object(), object()]
    with pytest.raises(BinanceCatalogError, match="incompleto"):
        build_private_market_manifest(classifier)


def test_native_swap_count_matches_classifier_swaps():
    classifier = classify(swap())
    classifier.swaps = [object()]
    raw, summary = build_private_market_manifest(classifier)
    assert summary["native_swaps"] == 1
    assert parse_private_manifest(raw)
