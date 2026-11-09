"""Hipótesis explícita: Binance comenzó el 1/1/2025, con saldo Binance 0.

Los ejercicios se construyen con operaciones inventadas. No se publican
ZIP, órdenes, TXID, direcciones o cantidades de usuarios reales.
"""
from pathlib import Path
import csv
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_coverage_diagnostic import (
    BinanceCoverageError, diagnosticar_saldo_inicial_cero,
)
from clasificador_binance_multi import ClasificadorBinanceMulti


SPOT_H = ["Número de pedido", "Tiempo", "Par", "Lado", "Precio",
          "Ejecutado", "Cantidad", "Tarifa",
          "Par de conversión de AOR", "Tasa de conversión de AOR"]
FIAT_DEP_H = ["Tiempo", "Método", "Importe de depósito", "Recibir cantidad",
              "Tarifa", "Estado", "ID de transacción"]
FIAT_TRADE_H = ["Tiempo", "Método", "Cantidad a gastar", "Recibir cantidad",
                "Tarifa", "Precio", "Estado", "ID de transacción"]
CRYPTO_DEP_H = ["Tiempo", "Moneda", "Red", "Cantidad", "Dirección", "TXID", "Estado"]
CRYPTO_WD_H = ["Tiempo", "Moneda", "Red", "Cantidad", "Tarifa", "Dirección", "TXID", "Estado"]


def csvfile(tmp_path, name, headers, rows):
    p = tmp_path / name
    with p.open("w", newline="", encoding="utf-8-sig") as out:
        w = csv.writer(out)
        w.writerow(headers)
        w.writerows(rows)
    return p


def classify(*files):
    return ClasificadorBinanceMulti(
        [str(p) for p in files], [p.name for p in files],
    ).clasificar()


def test_inicio_2025_no_inventa_saldo_ni_coste_y_detecta_fee_bnb(tmp_path):
    fiat = csvfile(tmp_path, "fiat.csv", FIAT_DEP_H, [
        ["2025-01-01 09:00:00", "SEPA", "100 EUR", "99 EUR",
         "1 EUR", "Successful", "synthetic-dep"],
    ])
    spot = csvfile(tmp_path, "spot.csv", SPOT_H, [
        ["invented-order", "2025-01-02 09:00:00", "XRPEUR", "BUY",
         "2", "10XRP", "20EUR", "0.01BNB", "", ""],
    ])
    report = diagnosticar_saldo_inicial_cero(
        classify(fiat, spot), inicio="2025-01-01",
    )
    assert [d.activo for d in report.activos_con_deficit] == ["BNB"]
    assert report.activos_con_deficit[0].primera_fecha == "2025-01-02"
    assert report.activos_con_deficit[0].saldo_minimo == -__import__("decimal").Decimal("0.01")
    assert report.coste_fiscal_acreditado is False


def test_deposito_externo_no_aporta_base_fiscal_aunque_saldo_cuadre(tmp_path):
    deposit = csvfile(tmp_path, "deposit.csv", CRYPTO_DEP_H, [
        ["2025-01-02 09:00:00", "XRP", "XRP", "10", "synthetic-address",
         "synthetic-hash", "Completed"],
    ])
    report = diagnosticar_saldo_inicial_cero(
        classify(deposit), inicio="2025-01-01",
    )
    assert report.activos_con_deficit == ()
    assert report.conciliacion_saldos_ok
    assert report.activos_depositados_sin_coste_acreditado == ("XRP",)
    assert not report.coste_fiscal_acreditado


def test_salida_superior_a_ingreso_detecta_deficit_sin_inventar_compra(tmp_path):
    deposit = csvfile(tmp_path, "deposit.csv", CRYPTO_DEP_H, [
        ["2025-01-02 09:00:00", "XRP", "XRP", "10", "address",
         "hash", "Completed"],
    ])
    withdrawal = csvfile(tmp_path, "withdrawal.csv", CRYPTO_WD_H, [
        ["2025-01-03 09:00:00", "XRP", "XRP", "10", "0.01",
         "address", "hash", "Completed"],
    ])
    report = diagnosticar_saldo_inicial_cero(
        classify(deposit, withdrawal), inicio="2025-01-01",
    )
    assert [d.activo for d in report.activos_con_deficit] == ["XRP"]
    assert report.activos_con_deficit[0].primera_fecha == "2025-01-03"


def test_evento_anterior_al_inicio_hipotetico_se_rechaza(tmp_path):
    deposit = csvfile(tmp_path, "deposit.csv", CRYPTO_DEP_H, [
        ["2024-12-31 23:59:59", "XRP", "XRP", "10", "address",
         "hash", "Completed"],
    ])
    with pytest.raises(BinanceCoverageError, match="anterior"):
        diagnosticar_saldo_inicial_cero(
            classify(deposit), inicio="2025-01-01",
        )


def test_compra_en_activo_recibido_consume_comision_y_no_duplica_lotes(tmp_path):
    fiat = csvfile(tmp_path, "fiat.csv", FIAT_DEP_H, [
        ["2025-01-01 09:00:00", "SEPA", "50 EUR", "50 EUR",
         "0 EUR", "Successful", "synthetic-dep"],
    ])
    spot = csvfile(tmp_path, "spot.csv", SPOT_H, [
        ["invented-order", "2025-01-02 09:00:00", "XRPEUR", "BUY",
         "2", "10XRP", "20EUR", "0.1XRP", "", ""],
    ])
    report = diagnosticar_saldo_inicial_cero(
        classify(fiat, spot), inicio="2025-01-01",
    )
    assert report.activos_con_deficit == ()
    assert report.operaciones_contabilizadas == 4
    assert report.coste_fiscal_acreditado is False



def test_compra_fiat_por_transferencia_externa_no_gasta_saldo_binance_si_se_supone(tmp_path):
    purchase = csvfile(tmp_path, "fiat_bank_purchase.csv", FIAT_TRADE_H, [
        ["2025-06-15 10:00:00", "Banco de prueba (ficticio)",
         "10 EUR", "5 XRP", "1 EUR", "2", "Successful", "synthetic-1"],
    ])
    classified = classify(purchase)
    assert classified.intercambios_nativos[0].payment_method == (
        "Banco de prueba (ficticio)"
    )
    baseline = diagnosticar_saldo_inicial_cero(classified, inicio="2025-01-01")
    assert [d.activo for d in baseline.activos_con_deficit] == ["EUR"]

    external = diagnosticar_saldo_inicial_cero(
        classified, inicio="2025-01-01",
        metodos_pago_externo=("Banco de prueba (ficticio)",),
    )
    assert external.activos_con_deficit == ()
    assert external.pagos_externos_supuestos == 1
    assert external.operaciones_contabilizadas == 1
    assert not external.conciliacion_saldos_ok  # hipótesis externa no acreditada
    assert not external.coste_fiscal_acreditado


def test_metodo_saldo_no_se_excluye_por_inferencia_de_banco(tmp_path):
    purchase = csvfile(tmp_path, "fiat_balance_purchase.csv", FIAT_TRADE_H, [
        ["2025-06-15 10:00:00", "Saldo",
         "10 EUR", "5 XRP", "1 EUR", "2", "Successful", "synthetic-2"],
    ])
    report = diagnosticar_saldo_inicial_cero(
        classify(purchase), inicio="2025-01-01",
        metodos_pago_externo=("Banco de prueba (ficticio)",),
    )
    assert [d.activo for d in report.activos_con_deficit] == ["EUR"]
    assert report.pagos_externos_supuestos == 0


def test_hipotesis_fiat_externa_invalida_se_rechaza(tmp_path):
    purchase = csvfile(tmp_path, "fiat.csv", FIAT_TRADE_H, [
        ["2025-06-15 10:00:00", "Saldo",
         "10 EUR", "5 XRP", "0 EUR", "2", "Successful", "synthetic-3"],
    ])
    with pytest.raises(BinanceCoverageError, match="Métodos externos"):
        diagnosticar_saldo_inicial_cero(
            classify(purchase), inicio="2025-01-01",
            metodos_pago_externo=("",),
        )



def test_eventos_mismo_segundo_se_agregan_sin_deficit_artificial(tmp_path):
    """Dentro del mismo segundo no se presume un orden del CSV entre fuentes."""
    fiat = csvfile(tmp_path, "deposit.csv", FIAT_DEP_H, [
        ["2025-02-01 10:00:00", "SEPA", "20 EUR", "20 EUR",
         "0 EUR", "Successful", "invented-deposit"],
    ])
    trade = csvfile(tmp_path, "spot.csv", SPOT_H, [
        ["invented-order", "2025-02-01 10:00:00", "XRPEUR", "BUY",
         "2", "10XRP", "20EUR", "0XRP", "", ""],
    ])
    report = diagnosticar_saldo_inicial_cero(
        classify(trade, fiat), inicio="2025-01-01",
    )
    assert report.activos_con_deficit == ()
    assert report.pagos_externos_supuestos == 0


def test_deficit_transitorio_y_posterior_mas_grave_se_preservan(tmp_path):
    """Un ingreso posterior no prueba que una disposición anterior fuese válida."""
    spot = csvfile(tmp_path, "spot.csv", SPOT_H, [
        ["invented-1", "2025-01-02 10:00:00", "XRPUSDC", "BUY",
         "10", "1XRP", "10USDC", "0XRP", "", ""],
        ["invented-2", "2025-01-04 10:00:00", "XRPUSDC", "BUY",
         "40", "1XRP", "40USDC", "0XRP", "", ""],
    ])
    deposit = csvfile(tmp_path, "deposit.csv", CRYPTO_DEP_H, [
        ["2025-01-03 10:00:00", "USDC", "ETH", "30",
         "invented-address", "invented-hash", "Completed"],
    ])
    report = diagnosticar_saldo_inicial_cero(
        classify(spot, deposit), inicio="2025-01-01",
    )
    assert [d.activo for d in report.activos_con_deficit] == ["USDC"]
    deficit = report.activos_con_deficit[0]
    assert deficit.primera_fecha == "2025-01-02"
    assert deficit.saldo_minimo == __import__("decimal").Decimal("-20")
    assert report.activos_depositados_sin_coste_acreditado == ("USDC",)
    assert not report.coste_fiscal_acreditado
