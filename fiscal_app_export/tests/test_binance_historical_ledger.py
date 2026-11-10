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
