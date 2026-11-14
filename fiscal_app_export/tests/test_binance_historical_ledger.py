"""Pruebas puramente sintéticas para el lector de históricos voluminosos Binance."""
from decimal import Decimal
from pathlib import Path
import io
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from binance_historical_ledger import (
    BinanceHistoricalLedgerError, inspeccionar_historial_binance,
)

HEADER = "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"


def _zip(tmp_path, label, contents, *, member="history.csv"):
    path = tmp_path / f"Binance-{label}-(UTC+1).zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member, contents.encode("utf-8-sig") if isinstance(contents, str) else contents)
    return path


def test_ledger_multianual_preserva_saldo_y_movimientos_earn_sin_crear_fifo(tmp_path):
    first = _zip(tmp_path, "2019", HEADER + (
        "fake,2019-12-20 10:00:00,Spot,Deposit,BTC,2,\n"
        "fake,2019-12-20 10:00:00,Spot,Buy,BTC,-1,\n"
        "fake,2019-12-20 10:00:00,Spot,Buy,ABC,10,\n"
        "fake,2019-12-25 12:00:00,Spot,Simple Earn Flexible Subscription,BTC,-1,\n"
    ))
    second = _zip(tmp_path, "2020", HEADER + (
        "fake,2020-01-01 01:00:00,Earn,Simple Earn Flexible Redemption,BTC,0.5,\n"
        "fake,2020-01-01 01:00:00,Spot,Commission Rebate,ABC,0.1,\n"
        "fake,2020-01-01 01:00:00,Spot,Commission Rebate,ABC,0.1,\n"
    ))
    r = inspeccionar_historial_binance([first, second])
    assert r.registros == 7
    assert r.archivos == 2
    assert r.registros_por_ejercicio == ((2019, 4), (2020, 3))
    assert dict(r.saldos_netos)["BTC"] == Decimal("0.5")
    assert dict(r.saldos_netos)["ABC"] == Decimal("10.2")
    assert dict(r.netos_earn_flexible)["BTC"] == Decimal("0.5")
    assert r.sin_saldos_negativos_globales
    assert r.fifo_fiscal_acreditado is False
    assert dict(r.registros_por_operacion)["Commission Rebate"] == 2


def test_ledger_no_inventa_saldo_dentro_del_mismo_segundo(tmp_path):
    z = _zip(tmp_path, "same-second", HEADER + (
        "fake,2021-01-01 00:00:00,Spot,Sell,BTC,-2,\n"
        "fake,2021-01-01 00:00:00,Spot,Deposit,BTC,2,\n"
    ))
    r = inspeccionar_historial_binance([z])
    assert r.sin_saldos_negativos_globales
    assert dict(r.saldos_netos)["BTC"] == Decimal(0)


def test_ledger_no_oculta_deficit_real(tmp_path):
    z = _zip(tmp_path, "negative", HEADER + (
        "fake,2021-01-01 00:00:00,Spot,Sell,BTC,-3,\n"
        "fake,2021-01-02 00:00:00,Spot,Deposit,BTC,5,\n"
    ))
    r = inspeccionar_historial_binance([z])
    assert r.primeras_insuficiencias == (
        ("BTC", "2021-01-01 00:00:00", Decimal("-3")),)
    assert not r.sin_saldos_negativos_globales


def test_ledger_streaming_mas_de_100000_filas_y_preserva_multiplicidad(tmp_path):
    # Un único archivo superior al tope de la interfaz web, procesado localmente
    # sin construir una lista de filas ni cargar el CSV entero en memoria.
    count = 120_001
    # Repeticiones legítimas por parejas; el identificador sintético solo
    # evita una compresión artificial extrema que sería un ZIP bomb.
    z = _zip(tmp_path, "big", HEADER + "".join(
        f"fake,2021-05-01 00:00:00,Spot,Commission Rebate,ABC,0.00001,event-{i // 2:06d}\n"
        for i in range(count)
    ))
    r = inspeccionar_historial_binance([z], max_csv_bytes=12_000_000)
    assert r.registros == count
    assert dict(r.saldos_netos)["ABC"] == Decimal("1.20001")
    assert dict(r.registros_por_operacion)["Commission Rebate"] == count
    with pytest.raises(BinanceHistoricalLedgerError, match="límite de filas"):
        inspeccionar_historial_binance([z], max_registros=100_000)


def test_ledger_no_acepta_solapamiento_ni_inversion(tmp_path):
    old = _zip(tmp_path, "old", HEADER + (
        "fake,2021-01-01 10:00:00,Spot,Deposit,BTC,2,\n"
    ))
    overlap = _zip(tmp_path, "overlap", HEADER + (
        "fake,2021-01-01 10:00:00,Spot,Deposit,BTC,2,\n"
    ))
    with pytest.raises(BinanceHistoricalLedgerError, match="solapan"):
        inspeccionar_historial_binance([old, overlap])
    inverted = _zip(tmp_path, "inverted", HEADER + (
        "fake,2021-01-02 10:00:00,Spot,Deposit,BTC,2,\n"
        "fake,2021-01-01 10:00:00,Spot,Deposit,BTC,3,\n"
    ))
    with pytest.raises(BinanceHistoricalLedgerError, match="orden cronológico"):
        inspeccionar_historial_binance([inverted])


@pytest.mark.parametrize("bad", [
    HEADER + "fake,2021-01-01 10:00:00,Spot,Deposit,BTC,NaN,\n",
    HEADER + "fake,2021-01-01 10:00:00,Spot,Deposit,BTC,Infinity,\n",
    HEADER + "fake,2021-01-01 10:00:00,Spot,Deposit,BTC,1,extra,bad\n",
    HEADER + "fake,2021-02-30 10:00:00,Spot,Deposit,BTC,1,\n",
])
def test_ledger_rechaza_datos_invalidos(tmp_path, bad):
    z = _zip(tmp_path, "invalid", bad)
    with pytest.raises(BinanceHistoricalLedgerError):
        inspeccionar_historial_binance([z])


def test_ledger_rechaza_rutas_zip_y_bytes_danados(tmp_path):
    unsafe = _zip(tmp_path, "unsafe", HEADER, member="../history.csv")
    with pytest.raises(BinanceHistoricalLedgerError, match="no seguro"):
        inspeccionar_historial_binance([unsafe])
    bad = _zip(tmp_path, "bad-utf8", HEADER.encode() + bytes((255,)))
    with pytest.raises(BinanceHistoricalLedgerError, match="ZIP histórico"):
        inspeccionar_historial_binance([bad])



def test_ledger_asof_cutoff_wallets_and_empty_export(tmp_path):
    old = _zip(tmp_path, "2019", HEADER + (
        "synthetic,2019-01-01 09:00:00,Spot,Deposit,BTC,0.7,\n"
        "synthetic,2019-01-02 09:00:00,Funding,Pool Distribution,BTC,0.3,\n"
        "synthetic,2019-01-03 09:00:00,Spot,Simple Earn Flexible Subscription,BTC,-0.7,\n"
    ))
    no_data = _zip(tmp_path, "empty", HEADER +
        "No hay datos que se ajusten a los criterios.\n")
    recent = _zip(tmp_path, "2025", HEADER + (
        "synthetic,2025-09-27 11:00:00,Spot,Simple Earn Flexible Redemption,BTC,0.7,\n"
        "synthetic,2025-09-27 11:01:00,Funding,Binance Convert,BTC,-0.3,\n"
        "synthetic,2025-09-27 11:01:00,Spot,Binance Convert,BTC,0.3,\n"
        "synthetic,2025-09-27 11:02:00,Spot,Binance Convert,BTC,-1,\n"
    ))
    sources = [old, no_data, recent]
    cut = inspeccionar_historial_binance(
        sources, hasta_local="2025-09-27 11:00:00")
    wallets = {(a, asset): q for a, asset, q in cut.saldos_por_cuenta}
    assert wallets[("Spot", "BTC")] == Decimal("0.7")
    assert wallets[("Funding", "BTC")] == Decimal("0.3")
    assert dict(cut.saldos_netos)["BTC"] == Decimal("1.0")
    assert cut.registros == 4
    assert cut.sin_saldos_negativos_globales and not cut.fifo_fiscal_acreditado
    middle = inspeccionar_historial_binance(
        sources, hasta_local="2025-09-27 11:01:00")
    assert dict(middle.saldos_netos)["BTC"] == Decimal("1")
    w2 = {(a, asset): q for a, asset, q in middle.saldos_por_cuenta}
    assert w2[("Spot", "BTC")] == Decimal("1")
    assert w2[("Funding", "BTC")] == Decimal("0")
    final = inspeccionar_historial_binance(sources)
    assert final.registros == 7
    assert dict(final.saldos_netos)["BTC"] == Decimal("0")
    assert final.sin_saldos_negativos_globales and not final.fifo_fiscal_acreditado


def test_ledger_cutoff_does_not_skip_validation_after_cut(tmp_path):
    z = _zip(tmp_path, "corrupted", HEADER + (
        "synthetic,2024-01-01 10:00:00,Spot,Deposit,BTC,1,\n"
        "synthetic,2026-01-01 10:00:00,Spot,Deposit,BTC,NaN,\n"
    ))
    with pytest.raises(BinanceHistoricalLedgerError, match="no finita"):
        inspeccionar_historial_binance(
            [z], hasta_local="2024-12-31 23:59:59")


@pytest.mark.parametrize("cut", [
    "2025-02-30 00:00:00", "2025-01-01T00:00:00",
    "", 2025, "2025-01-01 00:00:00Z",
])
def test_ledger_cutoff_rejects_invalid_dates(tmp_path, cut):
    z = _zip(tmp_path, "valid", HEADER +
        "synthetic,2025-01-01 10:00:00,Spot,Deposit,BTC,1,\n")
    with pytest.raises(BinanceHistoricalLedgerError):
        inspeccionar_historial_binance([z], hasta_local=cut)


def test_ledger_no_data_sentinel_cannot_hide_other_fields(tmp_path):
    z = _zip(tmp_path, "bad-sentinel", HEADER +
        "No hay datos que se ajusten a los criterios.,2024-01-01 10:00:00,Spot,Deposit,BTC,3,\n")
    with pytest.raises(BinanceHistoricalLedgerError):
        inspeccionar_historial_binance([z])


def test_ledger_cutoff_same_second_buy_and_fee_not_false_shortfall(tmp_path):
    z = _zip(tmp_path, "same-second-fee", HEADER + (
        "synthetic,2021-01-01 00:00:00,Spot,Fee,BTC,-0.01,\n"
        "synthetic,2021-01-01 00:00:00,Spot,Buy,BTC,1,\n"
        "synthetic,2022-01-01 00:00:00,Spot,Sell,BTC,-0.99,\n"
    ))
    r = inspeccionar_historial_binance(
        [z], hasta_local="2021-12-31 23:59:59")
    assert r.sin_saldos_negativos_globales
    assert dict(r.saldos_netos)["BTC"] == Decimal("0.99")
    assert r.fifo_fiscal_acreditado is False



def test_ledger_no_data_sentinel_does_not_bypass_row_limit(tmp_path):
    z = _zip(tmp_path, "repeated-empty", HEADER +
        "No hay datos que se ajusten a los criterios.\n" * 3)
    with pytest.raises(BinanceHistoricalLedgerError, match="límite de filas"):
        inspeccionar_historial_binance([z], max_registros=2)


def test_ledger_deficit_custodia_oculto_por_saldo_global(tmp_path):
    """Saldo global correcto no acredita la custodia de otra billetera."""
    z = _zip(tmp_path, "custody-deficit", HEADER + (
        "synthetic,2024-01-01 09:00:00,Spot,Deposit,BTC,5,\n"
        "synthetic,2024-01-02 09:00:00,USD-M Futures,Fee,BTC,-2,\n"
        "synthetic,2024-01-03 09:00:00,USD-M Futures,Transfer,BTC,2,\n"
    ))
    report = inspeccionar_historial_binance([z])
    assert report.sin_saldos_negativos_globales
    assert not report.sin_saldos_negativos_por_cuenta
    assert report.primeras_insuficiencias_por_cuenta == (
        ("USD-M Futures", "BTC", "2024-01-02 09:00:00", Decimal("-2")),
    )
    assert dict(report.saldos_netos)["BTC"] == Decimal("5")
    assert report.fifo_fiscal_acreditado is False


def test_ledger_custodia_mismo_segundo_compensa_sin_falso_deficit(tmp_path):
    z = _zip(tmp_path, "custody-same-second", HEADER + (
        "synthetic,2024-01-01 09:00:00,Funding,Fee,ETH,-0.2,\n"
        "synthetic,2024-01-01 09:00:00,Funding,Deposit,ETH,0.2,\n"
    ))
    report = inspeccionar_historial_binance([z])
    assert report.sin_saldos_negativos_globales
    assert report.sin_saldos_negativos_por_cuenta
    assert report.primeras_insuficiencias_por_cuenta == ()


def test_ledger_custodia_diversas_billeteras_sin_mezclar_sus_saldos(tmp_path):
    z = _zip(tmp_path, "custody-separated", HEADER + (
        "synthetic,2024-01-01 09:00:00,Spot,Deposit,BTC,2,\n"
        "synthetic,2024-01-02 09:00:00,Spot,Transfer,BTC,-1,\n"
        "synthetic,2024-01-02 09:00:00,Funding,Transfer,BTC,1,\n"
        "synthetic,2024-01-03 09:00:00,Coin-M Futures,Deposit,BTC,1,\n"
        "synthetic,2024-01-04 09:00:00,Pool,Pool Distribution,BTC,1,\n"
        "synthetic,2024-01-05 09:00:00,Alpha,Deposit,BTC,1,\n"
    ))
    report = inspeccionar_historial_binance([z])
    assert report.sin_saldos_negativos_por_cuenta
    assert report.sin_saldos_negativos_globales
    accounts = {(wallet, asset): qty
                for wallet, asset, qty in report.saldos_por_cuenta}
    assert accounts[("Spot", "BTC")] == Decimal("1")
    assert accounts[("Funding", "BTC")] == Decimal("1")
    assert accounts[("Coin-M Futures", "BTC")] == Decimal("1")
    assert accounts[("Pool", "BTC")] == Decimal("1")
    assert accounts[("Alpha", "BTC")] == Decimal("1")
    assert dict(report.saldos_netos)["BTC"] == Decimal("5")
    assert not report.fifo_fiscal_acreditado


def test_ledger_transferencia_um_con_patas_exactas_y_deficit_de_custodia(tmp_path):
    """El déficit temporal en Futuros no convierte un traspaso en una compra."""
    z = _zip(tmp_path, "um-neutral", HEADER + (
        "synthetic,2025-01-01 00:00:00,Spot,Deposit,USDT,3,\n"
        "synthetic,2025-01-01 00:00:00,USD-M Futures,Deposit,USDT,0.1,\n"
        "synthetic,2025-04-05 11:06:02,Spot,Transfer Between Spot and UM Futures,USDT,0.8,\n"
        "synthetic,2025-04-05 11:06:02,USD-M Futures,Transfer Between Spot and UM Futures,USDT,-0.8,\n"
    ))
    report = inspeccionar_historial_binance([z])
    assert dict(report.traspasos_pareados_por_tipo) == {
        "Transfer Between Spot and UM Futures": 1
    }
    assert report.patas_traspasos_no_pareadas_por_tipo == ()
    assert report.sin_saldos_negativos_globales
    assert not report.sin_saldos_negativos_por_cuenta
    assert report.primeras_insuficiencias_por_cuenta == (
        ("USD-M Futures", "USDT", "2025-04-05 11:06:02", Decimal("-0.7")),
    )
    assert report.fifo_fiscal_acreditado is False


def test_ledger_transferencias_de_tipos_distintos_no_se_cruzan(tmp_path):
    z = _zip(tmp_path, "separate-transfer-types", HEADER + (
        "synthetic,2025-01-01 00:00:00,Spot,Deposit,BTC,4,\n"
        "synthetic,2025-01-02 00:00:00,Spot,Transfer Between Spot and CM Futures,BTC,-1,\n"
        "synthetic,2025-01-02 00:00:00,Coin-M Futures,Transfer Between Spot and CM Futures,BTC,1,\n"
        "synthetic,2025-01-03 00:00:00,Spot,Transfer Between Spot and Funding,BTC,-1,\n"
        "synthetic,2025-01-03 00:00:00,Funding,Transfer Between Spot and Funding,BTC,1,\n"
        "synthetic,2025-01-04 00:00:00,Spot,Transfer Between Spot and Mining,BTC,-1,\n"
        "synthetic,2025-01-04 00:00:00,Pool,Transfer Between Spot and Mining,BTC,1,\n"
    ))
    report = inspeccionar_historial_binance([z])
    assert dict(report.traspasos_pareados_por_tipo) == {
        "Transfer Between Spot and CM Futures": 1,
        "Transfer Between Spot and Funding": 1,
        "Transfer Between Spot and Mining": 1,
    }
    assert report.sin_saldos_negativos_por_cuenta
    assert report.patas_traspasos_no_pareadas_por_tipo == ()
    assert report.fifo_fiscal_acreditado is False


def test_ledger_transferencias_ausentes_no_se_casaran_por_proximidad(tmp_path):
    z = _zip(tmp_path, "transfer-different-seconds", HEADER + (
        "synthetic,2025-01-01 00:00:00,Spot,Deposit,USDT,2,\n"
        "synthetic,2025-01-02 10:00:00,Spot,Transfer Between Spot and Funding,USDT,-1,\n"
        "synthetic,2025-01-02 10:00:01,Funding,Transfer Between Spot and Funding,USDT,1,\n"
    ))
    report = inspeccionar_historial_binance([z])
    assert report.traspasos_pareados_por_tipo == ()
    assert dict(report.patas_traspasos_no_pareadas_por_tipo) == {
        "Transfer Between Spot and Funding": 2
    }
    assert report.sin_saldos_negativos_globales
    assert report.fifo_fiscal_acreditado is False


@pytest.mark.parametrize("legs", [
    (
        "synthetic,2025-01-02 10:00:00,Spot,Transfer Between Spot and UM Futures,BTC,-1,\n"
        "synthetic,2025-01-02 10:00:00,USD-M Futures,Transfer Between Spot and UM Futures,BTC,0.9,\n"
    ),
    (
        "synthetic,2025-01-02 10:00:00,Spot,Transfer Between Spot and UM Futures,BTC,-1,\n"
        "synthetic,2025-01-02 10:00:00,Funding,Transfer Between Spot and UM Futures,BTC,1,\n"
    ),
    (
        "synthetic,2025-01-02 10:00:00,Spot,Transfer Between Spot and UM Futures,BTC,-1,\n"
        "synthetic,2025-01-02 10:00:00,USD-M Futures,Transfer Between Spot and UM Futures,BTC,1,\n"
        "synthetic,2025-01-02 10:00:00,Spot,Transfer Between Spot and UM Futures,BTC,-1,\n"
        "synthetic,2025-01-02 10:00:00,USD-M Futures,Transfer Between Spot and UM Futures,BTC,1,\n"
    ),
])
def test_ledger_transferencia_inexacta_o_ambigua_no_cuenta_como_pareja(tmp_path, legs):
    z = _zip(tmp_path, "transfer-inexact", HEADER +
        "synthetic,2025-01-01 00:00:00,Spot,Deposit,BTC,5,\n" + legs)
    report = inspeccionar_historial_binance([z])
    assert report.traspasos_pareados_por_tipo == ()
    assert dict(report.patas_traspasos_no_pareadas_por_tipo) == {
        "Transfer Between Spot and UM Futures": len(legs.strip().splitlines())
    }
    assert report.fifo_fiscal_acreditado is False
