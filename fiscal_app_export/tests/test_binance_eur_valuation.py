"""Regresiones solo con evidencias y trades sintéticos; cero datos de clientes."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import io
from pathlib import Path
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_eur_valuation import (
    BinanceHistoricalEURPrices,
    BinancePriceEvidenceError,
    TradePriceEvidence,
    parse_verified_binance_trade_zip,
    binance_export_time_to_utc,
)


T = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 64


def price(base, quote, value, *, when=T, id=1):
    return TradePriceEvidence(
        base, quote, Decimal(str(value)), when, id, SHA,
    )


def zipped_trades(rows, name="XRPEUR-trades-2025-01-01.zip"):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name[:-4] + ".csv", "\n".join(rows) + "\n")
    contents = bio.getvalue()
    return contents, f"{hashlib.sha256(contents).hexdigest()} {name}"


def test_trade_zip_checksum_y_timestamp_microsegundos():
    archive, checksum = zipped_trades([
        "42,2.5,10,25,1735732800000000,True,True",
    ])
    records = parse_verified_binance_trade_zip(
        archive, checksum, archive_name="XRPEUR-trades-2025-01-01.zip",
        symbol="XRPEUR", base="XRP", quote="EUR",
    )
    assert len(records) == 1
    assert records[0].price == Decimal("2.5")
    assert records[0].public_trade_id == 42
    assert records[0].observed_at == T


def test_trade_zip_timestamp_milisegundos_historicos():
    archive, checksum = zipped_trades(
        ["7,1.5,2,3,1704110400000,True,True"],
        name="XRPEUR-trades-2024-01-01.zip",
    )
    records = parse_verified_binance_trade_zip(
        archive, checksum, archive_name="XRPEUR-trades-2024-01-01.zip",
        symbol="XRPEUR", base="XRP", quote="EUR",
    )
    assert records[0].observed_at == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_checksum_incorrecto_impide_importar_cotizaciones():
    archive, _ = zipped_trades(["42,2,1,2,1735732800000000,True,True"])
    with pytest.raises(BinancePriceEvidenceError, match="checksum"):
        parse_verified_binance_trade_zip(
            archive, "0" * 64,
            archive_name="XRPEUR-trades-2025-01-01.zip",
            symbol="XRPEUR", base="XRP", quote="EUR",
        )


def test_no_se_admite_un_zip_con_ruta_traversal():
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w") as zf:
        zf.writestr("../evil.csv", "1,2,3,6,1735732800000000,True,True\n")
    raw = bio.getvalue()
    with pytest.raises(BinancePriceEvidenceError, match="no seguro"):
        parse_verified_binance_trade_zip(
            raw, hashlib.sha256(raw).hexdigest(),
            archive_name="XRPEUR-trades-2025-01-01.zip",
            symbol="XRPEUR", base="XRP", quote="EUR",
        )


def test_ruta_directa_eur_y_precision_decimal():
    book = BinanceHistoricalEURPrices([price("XRP", "EUR", "2.123456789")])
    found = book.price_eur("XRP", T + timedelta(seconds=1))
    assert found.unit_price_eur == Decimal("2.123456789")
    assert len(found.path) == 1


def test_buscador_no_utiliza_trade_futuro_ni_obsoleto():
    book = BinanceHistoricalEURPrices([
        price("XRP", "EUR", "1", when=T - timedelta(seconds=61)),
        price("XRP", "EUR", "3", when=T + timedelta(seconds=1), id=2),
    ])
    with pytest.raises(BinancePriceEvidenceError, match="No existe evidencia"):
        book.price_eur("XRP", T)
    assert book.price_eur("XRP", T + timedelta(seconds=1)).unit_price_eur == Decimal("3")


def test_puente_usdt_eur_toma_cotizacion_real_no_paridad():
    book = BinanceHistoricalEURPrices([
        price("XRP", "USDT", "2"),
        price("USDT", "EUR", "0.92"),
    ])
    found = book.price_eur("XRP", T)
    assert found.unit_price_eur == Decimal("1.84")
    assert len(found.path) == 2
    assert book.price_eur("USDT", T).unit_price_eur == Decimal("0.92")


def test_falta_eur_de_stablecoin_bloquea():
    book = BinanceHistoricalEURPrices([price("XRP", "USDT", "2")])
    with pytest.raises(BinancePriceEvidenceError, match="No existe evidencia"):
        book.price_eur("XRP", T)


def test_precio_eur_inverso_no_aplica_paridad():
    book = BinanceHistoricalEURPrices([price("EUR", "USDC", "1.25")])
    assert book.price_eur("USDC", T).unit_price_eur == Decimal("0.8")


def test_permuta_usa_maximo_entre_ambos_mercados_eur():
    book = BinanceHistoricalEURPrices([
        price("XRP", "EUR", "2.1"),
        price("BNB", "EUR", "4.5"),
    ])
    valuation = book.value_swap(
        timestamp=T, given_asset="XRP", given_amount=Decimal("10"),
        received_asset="BNB", received_amount=Decimal("5"),
    )
    assert valuation.given_value_eur == Decimal("21.0")
    assert valuation.received_value_eur == Decimal("22.5")
    assert valuation.fiscal_value_eur == Decimal("22.5")


def test_permuta_no_acepta_fecha_sin_zona_horaria():
    book = BinanceHistoricalEURPrices([price("XRP", "EUR", "2"), price("BNB", "EUR", "1")])
    with pytest.raises(BinancePriceEvidenceError, match="zona"):
        book.value_swap(
            timestamp=datetime(2025, 1, 1, 12, 0),
            given_asset="XRP", given_amount=Decimal("1"),
            received_asset="BNB", received_amount=Decimal("1"),
        )


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-1", "0"])
def test_rechaza_precio_ausente_o_no_finito(value):
    with pytest.raises(BinancePriceEvidenceError):
        price("XRP", "EUR", value)



def test_marca_temporal_microsegundos_preservados_exactamente():
    archive, checksum = zipped_trades([
        "43,2.5,10,25,1735732800123456,True,True",
    ])
    records = parse_verified_binance_trade_zip(
        archive, checksum, archive_name="XRPEUR-trades-2025-01-01.zip",
        symbol="XRPEUR", base="XRP", quote="EUR",
    )
    assert records[0].observed_at == T + timedelta(microseconds=123456)


def test_mismo_trade_id_publico_con_precios_distintos_bloquea():
    with pytest.raises(BinancePriceEvidenceError, match="Conflicto"):
        BinanceHistoricalEURPrices([
            price("XRP", "EUR", "2.0", id=51),
            price("XRP", "EUR", "2.1", id=51),
        ])


def test_cotizacion_duplicada_exacta_no_altera_libro():
    entry = price("XRP", "EUR", "2.0", id=51)
    book = BinanceHistoricalEURPrices([entry, entry])
    found = book.price_eur("XRP", T)
    assert found.unit_price_eur == Decimal("2.0")
    assert len(found.path) == 1



def test_export_binance_offset_a_utc_y_cruce_anual():
    assert binance_export_time_to_utc(
        "2025-01-01 00:30:00", "Binance-Spot-(UTC+1).zip::spot.csv"
    ) == datetime(2024, 12, 31, 23, 30, tzinfo=timezone.utc)
    assert binance_export_time_to_utc(
        "2025-01-01 23:30:00", "Binance-Spot-(UTC-5).zip"
    ) == datetime(2025, 1, 2, 4, 30, tzinfo=timezone.utc)


def test_export_binance_sin_zona_horaria_no_permite_valoracion():
    with pytest.raises(BinancePriceEvidenceError, match="zona horaria"):
        binance_export_time_to_utc("2025-01-01 12:00:00", "spot.csv")



def test_trade_publico_de_otro_dia_no_valida_archivo_por_nombre():
    archive, checksum = zipped_trades([
        "42,2.5,10,25,1735819200000000,True,True",
    ], name="XRPEUR-trades-2025-01-01.zip")
    with pytest.raises(BinancePriceEvidenceError, match="fuera del periodo"):
        parse_verified_binance_trade_zip(
            archive, checksum, archive_name="XRPEUR-trades-2025-01-01.zip",
            symbol="XRPEUR", base="XRP", quote="EUR",
        )


def test_trade_publico_qty_o_quoteqty_no_positivos_rechazados():
    for record in (
        "42,2.5,0,25,1735732800000000,True,True",
        "42,2.5,10,0,1735732800000000,True,True",
        "42,2.5,10,NaN,1735732800000000,True,True",
    ):
        archive, checksum = zipped_trades([record])
        with pytest.raises(BinancePriceEvidenceError, match="positivo y finito"):
            parse_verified_binance_trade_zip(
                archive, checksum, archive_name="XRPEUR-trades-2025-01-01.zip",
                symbol="XRPEUR", base="XRP", quote="EUR",
            )


def test_trades_mensuales_no_admiten_fecha_del_mes_siguiente():
    archive, checksum = zipped_trades([
        "42,2.5,10,25,1738368000000000,True,True",
    ], name="XRPEUR-trades-2025-01.zip")
    with pytest.raises(BinancePriceEvidenceError, match="fuera del periodo"):
        parse_verified_binance_trade_zip(
            archive, checksum, archive_name="XRPEUR-trades-2025-01.zip",
            symbol="XRPEUR", base="XRP", quote="EUR",
        )
