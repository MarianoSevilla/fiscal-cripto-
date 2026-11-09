"""Auditoría sintética offline: clasificador Binance -> mercado EUR trazable."""
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_eur_valuation import (
    BinanceHistoricalEURPrices, BinancePriceEvidenceError, TradePriceEvidence,
)
from binance_valuation_audit import valorar_permutas_nativas
from clasificador_binance_multi import ClasificadorBinanceMulti


CONVERT = [
    "Tiempo", "Billetera", "Par", "Tipo", "Vender", "Comprar",
    "Precio", "Precio inverso", "Fecha actualizada", "Estado",
]
SPOT = [
    "Número de pedido", "Tiempo", "Par", "Lado", "Precio",
    "Ejecutado", "Cantidad", "Tarifa",
    "Par de conversión de AOR", "Tasa de conversión de AOR",
]
AT = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def source(tmp_path, headers, rows, name="source.csv"):
    path = tmp_path / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)
    return str(path)


def book():
    return BinanceHistoricalEURPrices([
        TradePriceEvidence("XRP", "EUR", Decimal("2"), AT, 1, "a" * 64),
        TradePriceEvidence("USDC", "EUR", Decimal("0.9"), AT, 2, "b" * 64),
    ])


def test_2_convert_mismo_segundo_siguen_independientes_y_valorados(tmp_path):
    path = source(tmp_path, CONVERT, [
        ["2025-01-01 13:00:00", "SPOT", "XRPUSDC", "Instant",
         "20 USDC", "10 XRP", "", "", "", "Successful"],
        ["2025-01-01 13:00:00", "SPOT", "XRPUSDC", "Instant",
         "10 USDC", "5 XRP", "", "", "", "Successful"],
    ])
    classified = ClasificadorBinanceMulti(
        [path], ["Binance-Convert-(UTC+1).zip::convert.csv"],
    ).clasificar()
    records = valorar_permutas_nativas(classified, book())
    assert len(records) == 2
    assert records[0].source.local_time == records[1].source.local_time
    assert records[0].valuation.at_utc == AT
    assert records[0].valuation.fiscal_value_eur == Decimal("20")
    assert records[1].valuation.fiscal_value_eur == Decimal("10")
    assert len(classified.swaps) == 2


def test_no_se_confunde_spot_eur_con_permuta_nativa(tmp_path):
    convert = source(tmp_path, CONVERT, [
        ["2025-01-01 13:00:00", "SPOT", "XRPUSDC", "Instant",
         "20 USDC", "10 XRP", "", "", "", "Successful"],
    ], name="convert.csv")
    spot = source(tmp_path, SPOT, [
        ["1", "2025-01-01 13:00:00", "XRPEUR", "BUY", "2",
         "5XRP", "10EUR", "0XRP", "", ""],
    ], name="spot.csv")
    classified = ClasificadorBinanceMulti(
        [convert, spot], ["Convert-(UTC+1).zip::convert.csv", "Spot-(UTC+1).csv"],
    ).clasificar()
    records = valorar_permutas_nativas(classified, book())
    assert len(records) == 1
    assert records[0].source.source == "Convert"
    assert len(classified.compraventas) == 1


def test_sin_zona_horaria_no_se_emite_valoracion(tmp_path):
    path = source(tmp_path, CONVERT, [
        ["2025-01-01 13:00:00", "SPOT", "XRPUSDC", "Instant",
         "20 USDC", "10 XRP", "", "", "", "Successful"],
    ])
    classified = ClasificadorBinanceMulti([path], ["convert.csv"]).clasificar()
    with pytest.raises(BinancePriceEvidenceError, match="zona horaria"):
        valorar_permutas_nativas(classified, book())


def test_swap_con_fee_no_se_valora_ni_omite(tmp_path):
    path = source(tmp_path, SPOT, [
        ["1", "2025-01-01 13:00:00", "XRPUSDC", "BUY", "2",
         "10XRP", "20USDC", "0.1XRP", "", ""],
    ])
    classified = ClasificadorBinanceMulti(
        [path], ["Spot-(UTC+1).csv"],
    ).clasificar()
    with pytest.raises(BinancePriceEvidenceError, match="comisiones"):
        valorar_permutas_nativas(classified, book())


def test_permuta_sin_precio_eur_de_un_activo_se_rechaza(tmp_path):
    path = source(tmp_path, CONVERT, [
        ["2025-01-01 13:00:00", "SPOT", "XRPUSDC", "Instant",
         "20 USDC", "10 XRP", "", "", "", "Successful"],
    ])
    classified = ClasificadorBinanceMulti(
        [path], ["Convert-(UTC+1).csv"],
    ).clasificar()
    prices = BinanceHistoricalEURPrices([
        TradePriceEvidence("XRP", "EUR", Decimal("2"), AT, 1, "a" * 64),
    ])
    with pytest.raises(BinancePriceEvidenceError, match="No existe evidencia"):
        valorar_permutas_nativas(classified, prices)
