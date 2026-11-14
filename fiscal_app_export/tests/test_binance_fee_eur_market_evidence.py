"""Cotización sintética de fee BNB: no contiene datos de clientes."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_fee_eur_market_evidence import (
    BinanceFeeMarketError, auditar_precio_eur_comisiones_bnb,
)


SHA = "a" * 64  # solo fixture, NO hash de Binance Vision verificado


def fee(at="2025-05-03 10:00:00", qty="0.0002", ordinal=0,
        reason="comision_en_tercer_activo_sin_eur", asset="BNB"):
    return SimpleNamespace(
        outstanding_reason=reason, fee_asset=asset,
        fee_quantity=Decimal(qty), native_ordinal=ordinal, local_time=at,
    )


def catalog(*trades, age=60):
    return {"schema_version": 1, "max_age_seconds": age,
            "trades": list(trades)}


def trade(at="2025-05-03T08:59:58.456Z", price="600.00",
          sha=SHA, market="BNB", quote="EUR", id=100):
    return {"base": market, "quote": quote,
            "observed_at_utc": at, "price": price,
            "archive_sha256": sha, "public_trade_id": id}


def audit(fees, cat, sha=frozenset((SHA,)), offset=60):
    return auditar_precio_eur_comisiones_bnb(
        SimpleNamespace(candidates=tuple(fees)), cat,
        export_utc_offset_minutes=offset,
        independently_verified_archive_sha256=sha,
    )


def test_fee_bnb_mercado_eur_y_hora_offset_se_calculan_con_decimal():
    report = audit([fee()], catalog(trade()))
    row = report.candidates[0]
    assert row.timestamp_utc == "2025-05-03T09:00:00Z"
    assert row.observed_at_utc == "2025-05-03T08:59:58.456000Z"
    assert row.fee_quantity == Decimal("0.0002")
    assert row.price_bnb_eur == Decimal("600.00")
    assert row.market_value_eur == Decimal("0.120000")
    assert row.public_trade_id == 100 and row.archive_sha256 == SHA
    assert row.reason == "referencia_mercado_verificada"
    assert report.market_reference_count == 1
    assert report.pending_market_reference_count == 0
    assert not row.fiscal_ready and not report.fiscal_ready


def test_duplicados_que_se_pagan_en_bnb_no_se_eliminan():
    report = audit([fee(ordinal=0), fee(ordinal=1)], catalog(trade()))
    assert [r.native_ordinal for r in report.candidates] == [0, 1]
    assert [r.market_value_eur for r in report.candidates] == [
        Decimal("0.12"), Decimal("0.12"),
    ]
    assert report.market_reference_count == 2
    assert report.fiscal_ready is False


def test_ausencia_de_archivos_de_fecha_correcta_deja_precio_pendiente():
    report = audit([fee(), fee(ordinal=3)], catalog(
        trade(at="2025-01-11T22:36:45.425674Z", price="681.84"),
    ))
    assert report.market_reference_count == 0
    assert report.pending_market_reference_count == 2
    assert all(e.market_value_eur is None for e in report.candidates)
    assert all(e.reason == "sin_cotizacion_en_ventana"
               for e in report.candidates)


def test_checksum_que_solo_esta_en_catalogo_no_prueba_integridad():
    report = audit([fee()], catalog(trade()), sha=frozenset())
    assert report.candidates[0].reason == "archivo_publico_no_verificado"
    assert report.candidates[0].market_value_eur is None


def test_no_acepta_trades_posteriores_a_la_comision():
    report = audit(
        [fee()],
        catalog(trade(at="2025-05-03T09:00:00.001Z", price="600")),
    )
    assert report.candidates[0].market_value_eur is None


def test_trade_de_hace_61_segundos_no_valora_fee():
    report = audit(
        [fee()],
        catalog(trade(at="2025-05-03T08:58:59Z", price="600")),
    )
    assert report.candidates[0].reason == "sin_cotizacion_en_ventana"


def test_no_se_asume_bnbusdt_ni_stablecoin_como_eur():
    report = audit([fee()], catalog(trade(quote="USDT")))
    assert report.candidates[0].market_value_eur is None


def test_muestras_igualmente_recientes_con_precios_distintos_quedan_pendientes():
    report = audit([fee()], catalog(
        trade(at="2025-05-03T08:59:59Z", price="600", id=1),
        trade(at="2025-05-03T08:59:59Z", price="601", id=2),
    ))
    assert report.candidates[0].reason == "trades_publicos_ambiguos"
    assert report.pending_market_reference_count == 1


def test_interesa_solo_fee_de_tercer_activo_bnb():
    report = audit([
        fee(asset="USDT"), fee(reason=None, ordinal=1),
    ], catalog(trade()))
    assert report.candidates == ()


@pytest.mark.parametrize("bad", [None, "60", True, 901, -721])
def test_zona_horaria_de_export_invalida(bad):
    with pytest.raises(BinanceFeeMarketError, match="Zona horaria"):
        audit([fee()], catalog(trade()), offset=bad)


@pytest.mark.parametrize("bad", [
    "NaN", "Infinity", "0", "-1", "abc",
])
def test_trade_con_precio_invalido_rechazado(bad):
    with pytest.raises(BinanceFeeMarketError, match="Cotización"):
        audit([fee()], catalog(trade(price=bad)))


@pytest.mark.parametrize("bad", ["not-a-hash", "A" * 64, "1" * 63])
def test_archivo_publico_sin_sha256_normalizado_rechazado(bad):
    with pytest.raises(BinanceFeeMarketError, match="Procedencia"):
        audit([fee()], catalog(trade(sha=bad)))


def test_trade_valido_no_significa_compra_ni_coste_fiscal_del_lote_bnb():
    report = audit([fee()], catalog(trade()))
    assert report.market_reference_count == 1
    assert report.candidates[0].market_value_eur is not None
    assert report.fiscal_ready is False
    assert report.candidates[0].fiscal_ready is False


def test_utc_cero_es_valido_si_exportacion_declara_offset_cero():
    report = audit([fee(at="2025-05-03 09:00:00")],
                   catalog(trade()), offset=0)
    assert report.market_reference_count == 1
    assert report.candidates[0].timestamp_utc == "2025-05-03T09:00:00Z"
    assert not report.fiscal_ready
