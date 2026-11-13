"""Adquisiciones EUR explícitas, sin asumir USD estable ni FIFO completo."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_eur_acquisition_evidence import (
    BinanceEURAcquisitionError, auditar_adquisiciones_eur_nativas,
)


def event(source, timestamp, given_asset, given, received_asset, received,
          *, fee_asset=None, fee="0"):
    return SimpleNamespace(
        source=source, local_time=timestamp,
        given_asset=given_asset, given_amount=Decimal(given),
        received_asset=received_asset, received_amount=Decimal(received),
        fee_asset=fee_asset, fee_amount=Decimal(fee),
    )


def test_convert_eur_a_cripto_crea_evidencia_coste_sin_autorizar_fifo():
    audit = auditar_adquisiciones_eur_nativas([
        event("Convert", "2025-05-03 10:00:00",
              "EUR", "100", "ABC", "20"),
    ])
    assert len(audit.candidates) == 1
    c = audit.candidates[0]
    assert c.asset == "ABC" and c.gross_quantity == Decimal("20")
    assert c.net_quantity == Decimal("20")
    assert c.eur_outlay == c.complete_cost_eur == Decimal("100")
    assert c.outstanding_reason is None
    assert c.native_ordinal == 0
    assert audit.by_year_source == ((2025, "Convert", 1),)
    assert audit.complete_cost_candidates == 1
    assert not c.fiscal_ready and not audit.fiscal_ready


def test_spot_eur_fee_en_activo_recibido_resta_unidades_no_coste():
    audit = auditar_adquisiciones_eur_nativas([
        event("Spot BUY", "2024-06-01 10:00:00",
              "EUR", "200", "XYZ", "10", fee_asset="XYZ", fee="0.1"),
    ])
    c = audit.candidates[0]
    assert c.gross_quantity == Decimal("10")
    assert c.net_quantity == Decimal("9.9")
    assert c.complete_cost_eur == Decimal("200")
    assert c.fee_quantity == Decimal("0.1")


def test_spot_eur_fee_en_eur_suma_coste_documentado():
    audit = auditar_adquisiciones_eur_nativas([
        event("Spot BUY", "2024-06-01 10:00:00",
              "EUR", "200", "XYZ", "10", fee_asset="EUR", fee="1"),
    ])
    assert audit.candidates[0].complete_cost_eur == Decimal("201")


def test_fiat_compra_eur_con_fee_exige_verificar_si_ya_esta_incluida():
    audit = auditar_adquisiciones_eur_nativas([
        event("Fiat trade", "2025-01-20 16:17:16", "EUR", "300",
              "USDC", "307.64731901", fee_asset="EUR", fee="1"),
    ])
    assert audit.candidates[0].eur_outlay == Decimal("300")
    assert audit.candidates[0].complete_cost_eur is None
    assert audit.candidates[0].outstanding_reason == (
        "comision_fiat_incluida_o_adicional_no_acreditada"
    )
    assert audit.incomplete_cost_candidates == 1
    assert not audit.fiscal_ready


def test_fee_en_bnb_no_se_convierte_a_eur_por_paridad():
    audit = auditar_adquisiciones_eur_nativas([
        event("Spot BUY", "2025-02-03 09:00:00", "EUR", "100",
              "ABC", "10", fee_asset="BNB", fee="0.002"),
    ])
    c = audit.candidates[0]
    assert c.complete_cost_eur is None
    assert c.outstanding_reason == "comision_en_tercer_activo_sin_eur"
    assert c.net_quantity == Decimal("10")


def test_par_usdt_usdc_sin_eur_no_crea_coste_euro():
    events = [
        event("Spot BUY", "2025-02-03 09:00:00",
              "USDC", "100", "ABC", "10"),
        event("Convert", "2025-02-03 09:00:01",
              "USDT", "100", "USDC", "100"),
        event("Spot SELL", "2025-02-03 09:00:02",
              "EUR", "100", "ABC", "10"),
    ]
    audit = auditar_adquisiciones_eur_nativas(events)
    assert audit.candidates == ()
    assert audit.by_year_source == ()


def test_repeticiones_mismo_segundo_no_se_deduplican_sin_id():
    e = event("Convert", "2025-02-03 09:00:00", "EUR", "20", "ABC", "3")
    audit = auditar_adquisiciones_eur_nativas([e, e])
    assert len(audit.candidates) == 2
    assert [x.native_ordinal for x in audit.candidates] == [0, 1]
    assert audit.by_year_source == ((2025, "Convert", 2),)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "0"])
def test_coste_o_cantidad_no_finita_rechazada(bad):
    e = SimpleNamespace(
        source="Convert", local_time="2025-01-01 12:00:00",
        given_asset="EUR", given_amount=bad,
        received_asset="ABC", received_amount=Decimal("1"),
        fee_asset=None, fee_amount=0,
    )
    with pytest.raises(BinanceEURAcquisitionError, match="Importe"):
        auditar_adquisiciones_eur_nativas([e])


def test_comision_superior_al_recibido_no_genera_lote():
    e = event("Spot BUY", "2025-01-01 12:00:00",
              "EUR", "100", "ABC", "1", fee_asset="ABC", fee="2")
    with pytest.raises(BinanceEURAcquisitionError, match="excede"):
        auditar_adquisiciones_eur_nativas([e])


def test_fecha_incompleta_no_crea_hora_fiscal():
    e = event("Convert", "2025-01-01",
              "EUR", "100", "ABC", "2")
    with pytest.raises(BinanceEURAcquisitionError, match="Fecha"):
        auditar_adquisiciones_eur_nativas([e])


def test_total_eur_estricto_por_fuente_y_anual():
    e = [
        event("Convert", "2024-01-01 12:00:00",
              "EUR", "50", "USDT", "60"),
        event("Convert", "2025-01-01 12:00:00",
              "EUR", "50", "USDC", "60"),
        event("Fiat trade", "2025-01-01 12:00:01",
              "EUR", "30", "USDC", "35", fee_asset="EUR", fee="1"),
    ]
    audit = auditar_adquisiciones_eur_nativas(e)
    assert audit.by_year_source == (
        (2024, "Convert", 1),
        (2025, "Convert", 1),
        (2025, "Fiat trade", 1),
    )
    assert audit.complete_cost_candidates == 2
    assert audit.incomplete_cost_candidates == 1


def test_clasificador_reconoce_convert_eur_nativo_sin_cotizacion_usdt(tmp_path):
    import csv
    from clasificador_binance_multi import ClasificadorBinanceMulti
    p = tmp_path / "convert.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        writer.writerow([
            "Tiempo", "Billetera", "Par", "Tipo", "Vender", "Comprar",
            "Precio", "Precio inverso", "Fecha actualizada", "Estado",
        ])
        writer.writerow([
            "2025-03-01 10:00:00", "SPOT", "EURABC", "Instant",
            "25.00 EUR", "12.5 ABC", "1 EUR=0.5 ABC",
            "1 ABC=2 EUR", "2025-03-01 10:00:00", "Successful",
        ])
    classifier = ClasificadorBinanceMulti([str(p)]).clasificar()
    report = classifier.eur_acquisition_evidence
    assert report is not None
    assert len(report.candidates) == 1
    assert report.candidates[0].source == "Convert"
    assert report.candidates[0].asset == "ABC"
    assert report.candidates[0].complete_cost_eur == Decimal("25.00")
    assert report.by_year_source == ((2025, "Convert", 1),)
    assert report.fiscal_ready is False


def test_clasificador_fiat_con_fee_eur_no_inventa_coste_total(tmp_path):
    import csv
    from clasificador_binance_multi import ClasificadorBinanceMulti
    p = tmp_path / "fiat.csv"
    with p.open("w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        writer.writerow([
            "Tiempo", "Método", "Cantidad a gastar", "Recibir cantidad",
            "Tarifa", "Precio", "Estado", "ID de transacción",
        ])
        writer.writerow([
            "2025-01-20 16:17:16", "SEPA Instant",
            "300.00 EUR", "307.64731901 USDC", "1.00 EUR",
            "0.9718921 USDC/EUR", "Successful", "synthetic-identifier",
        ])
    classifier = ClasificadorBinanceMulti([str(p)]).clasificar()
    report = classifier.eur_acquisition_evidence
    assert report is not None
    assert report.incomplete_cost_candidates == 1
    assert report.candidates[0].eur_outlay == Decimal("300")
    assert report.candidates[0].complete_cost_eur is None
    assert report.candidates[0].outstanding_reason == (
        "comision_fiat_incluida_o_adicional_no_acreditada"
    )
    assert report.fiscal_ready is False
