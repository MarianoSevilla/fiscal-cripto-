"""Regresión sintética del núcleo FIFO global; sin Flask, DB, PDF ni datos reales."""
import csv
import hashlib
import os
import sys
from dataclasses import replace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from clasificador import ClasificadorBinance
from clasificador_bitvavo import ClasificadorBitvavo
from fifo_global import (
    FifoGlobalError, FuenteGlobal, TransferenciaConfirmada, calcular_fifo_global,
)


BINANCE_COLUMNS = ["Tiempo", "Operación", "Moneda", "Cambio", "Cuenta", "Observación"]
BITVAVO_COLUMNS = [
    "Timezone", "Date", "Time", "Type", "Currency", "Amount",
    "Quote Currency", "Quote Price", "Received / Paid Currency",
    "Received / Paid Amount", "Fee currency", "Fee amount",
    "Status", "Transaction ID", "Address",
]


def _binance(tmp_path, entries, *, timezone="UTC", titular=10):
    path = tmp_path / "binance.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(BINANCE_COLUMNS)
        w.writerows(entries)
    cls = ClasificadorBinance(str(path)).clasificar()
    return FuenteGlobal("binance", titular, "b1", hashlib.sha256(path.read_bytes()).hexdigest(), cls, timezone)


def _bt_row(date, time, kind, asset="BTC", qty="1", eur="30000", fee="0", tz="UTC", tid="a"):
    price = str(float(eur) / float(qty)) if qty != "0" else "0"
    return [
        tz, date, time, kind, asset, qty, "EUR", price, "EUR",
        str(-float(eur) if kind == "buy" else float(eur)) if kind in ("buy", "sell") else "",
        "EUR", fee, "Completed", tid, "",
    ]


def _bitvavo(tmp_path, entries, *, titular=10):
    path = tmp_path / "bitvavo.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(BITVAVO_COLUMNS)
        w.writerows(entries)
    cls = ClasificadorBitvavo(str(path)).clasificar()
    return FuenteGlobal("bitvavo", titular, "v1", hashlib.sha256(path.read_bytes()).hexdigest(), cls, "UTC")


def _buy(timestamp, asset="BTC", qty=1, eur=20000):
    return [
        [timestamp, "Transaction Buy", asset, qty, "Spot", ""],
        [timestamp, "Transaction Spend", "EUR", -eur, "Spot", ""],
    ]


def _sell(timestamp, asset="BTC", qty=1, eur=40000):
    return [
        [timestamp, "Transaction Buy", "EUR", eur, "Spot", ""],
        [timestamp, "Transaction Spend", asset, -qty, "Spot", ""],
    ]


def _sources(tmp_path, *, bitvavo_rows=None, binance_rows=None):
    b = _binance(tmp_path, binance_rows if binance_rows is not None
                 else _buy("2023-01-01 10:00:00"))
    v = _bitvavo(tmp_path, bitvavo_rows if bitvavo_rows is not None else [
        _bt_row("2024-01-01", "10:00:00", "buy", eur="30000", tid="2"),
        _bt_row("2025-01-01", "10:00:00", "sell", eur="40000", tid="3"),
    ])
    return b, v


def _calculate(b, v, ejercicio=2025, transferencias=()):
    return calcular_fifo_global(
        (b, v), titular_id=10, ejercicio=ejercicio, transferencias=transferencias,
    )


def test_compra_binance_venta_bitvavo_usa_lote_mas_antiguo(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    assert len(result.resultados_ejercicio) == 1
    venta = result.resultados_ejercicio[0]
    assert venta.precio_coste == pytest.approx(20000)
    assert venta.precio_transmision == pytest.approx(40000)
    assert venta.ganancia_perdida == pytest.approx(20000)
    assert [op.source_id for op in result.operaciones] == ["b1", "v1", "v1"]
    assert result.motor.posicion_actual()[0].coste_total == pytest.approx(30000)


def test_historico_completo_y_salida_limitada_al_ejercicio(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v, 2024)
    assert len(result.resultados_ejercicio) == 0
    assert len(result.motor.resultados) == 1
    assert len(result.operaciones) == 3


def test_orden_utc_con_offset_explicito_binance(tmp_path):
    b, v = _sources(tmp_path,
        binance_rows=_buy("2025-01-01 10:00:00"),
        bitvavo_rows=[_bt_row("2025-01-01", "08:30:00", "sell", eur="40000")])
    # Binance UTC+02 purchase occurs 08:00 UTC, before Bitvavo sale at 08:30.
    b = replace(b, zona_horaria="UTC+02:00")
    result = _calculate(b, v)
    assert result.resultados_ejercicio[0].precio_coste == pytest.approx(20000)
    assert result.operaciones[0].fecha_utc.hour == 8


def test_venta_temporalmente_previa_no_fabrica_coste(tmp_path):
    b, v = _sources(tmp_path,
        binance_rows=_buy("2025-01-01 10:00:00"),
        bitvavo_rows=[_bt_row("2025-01-01", "09:00:00", "sell", eur="40000")])
    with pytest.raises(FifoGlobalError, match="Inventario global"):
        _calculate(b, v)


def test_venta_sin_compra_suficiente_no_emite(tmp_path):
    b, v = _sources(tmp_path, binance_rows=_buy("2023-01-01 10:00:00", qty=0.1),
                    bitvavo_rows=[_bt_row("2025-01-01", "10:00:00", "sell", qty="1", eur="40000")])
    with pytest.raises(FifoGlobalError, match="Inventario global"):
        _calculate(b, v)


def test_comision_compra_y_venta_eur_altera_coste_y_transmision(tmp_path):
    b, v = _sources(tmp_path,
        bitvavo_rows=[_bt_row("2025-01-01", "10:00:00", "sell", eur="40000", fee="-20")])
    # Binance compra sin fee; Bitvavo venta comisión 20 EUR.
    result = _calculate(b, v)
    assert result.resultados_ejercicio[0].ganancia_perdida == pytest.approx(19980)


def test_dos_operaciones_distintas_mismo_importe_no_se_deduplican(tmp_path):
    b, v = _sources(tmp_path, binance_rows=(
        _buy("2023-01-01 10:00:00", qty=0.5, eur=10000) +
        _buy("2023-01-02 10:00:00", qty=0.5, eur=10000)),
        bitvavo_rows=[_bt_row("2025-01-01", "10:00:00", "sell", eur="40000")])
    result = _calculate(b, v)
    assert len(result.operaciones) == 3
    assert result.resultados_ejercicio[0].precio_coste == pytest.approx(20000)


def test_sin_dobles_fuentes_ni_hash_repetido(tmp_path):
    b, v = _sources(tmp_path)
    with pytest.raises(FifoGlobalError, match="Binance y Bitvavo"):
        calcular_fifo_global((b, b), titular_id=10, ejercicio=2025)
    with pytest.raises(FifoGlobalError, match="archivo"):
        _calculate(b, replace(v, archivo_sha256=b.archivo_sha256))


def test_no_se_pueden_mezclar_titulares(tmp_path):
    b, v = _sources(tmp_path)
    with pytest.raises(FifoGlobalError, match="distinto titular"):
        _calculate(b, replace(v, titular_id=11))


def test_divisa_no_eur_no_se_interpreta_como_euros(tmp_path):
    b, v = _sources(tmp_path)
    b.clasificador.compraventas[0].contraparte = "USDT"
    with pytest.raises(FifoGlobalError, match="EUR"):
        _calculate(b, v)


def test_fee_cripto_distinta_de_eur_se_rechaza(tmp_path):
    b, v = _sources(tmp_path)
    b.clasificador.compraventas[0].fee_activo = "BNB"
    b.clasificador.compraventas[0].fee_cantidad = 0.1
    with pytest.raises(FifoGlobalError, match="Comisión en cripto"):
        _calculate(b, v)


def test_swap_y_operaciones_desconocidas_rechazados(tmp_path):
    b, v = _sources(tmp_path)
    b.clasificador.swaps.append(object())
    with pytest.raises(FifoGlobalError, match="Permutas"):
        _calculate(b, v)
    b.clasificador.swaps.clear()
    v.clasificador.desconocidas.append(object())
    with pytest.raises(FifoGlobalError, match="no interpretadas"):
        _calculate(b, v)


def test_recompensa_sin_eur_no_crea_lote_gratis(tmp_path):
    b, v = _sources(tmp_path)
    from clasificador import OperacionRendimiento
    b.clasificador.rendimientos.append(
        OperacionRendimiento("2024-01-01 10:00:00", "Staking", "BTC", 1, "Spot"))
    with pytest.raises(FifoGlobalError, match="EUR"):
        _calculate(b, v)


def test_recompensa_bitvavo_eur_crea_un_unico_lote(tmp_path):
    b, v = _sources(tmp_path,
        bitvavo_rows=[_bt_row("2024-01-01", "10:00:00", "staking",
                              "ETH", "0.1", "100", tid="stake")])
    result = _calculate(b, v, 2024)
    eth = next(p for p in result.motor.posicion_actual() if p.activo == "ETH")
    assert eth.cantidad_total == pytest.approx(0.1)
    assert eth.coste_total == pytest.approx(100)
    assert len([o for o in result.operaciones if o.tipo == "RENDIMIENTO"]) == 1


def test_bitvavo_con_timezone_no_utc_rechazado(tmp_path):
    b, v = _sources(tmp_path,
        bitvavo_rows=[_bt_row("2025-01-01", "10:00:00", "sell", tz="CET")])
    with pytest.raises(FifoGlobalError, match="UTC"):
        _calculate(b, v)


def _with_transfer(tmp_path):
    b, v = _sources(tmp_path,
        binance_rows=_buy("2023-01-01 10:00:00") +
            [["2024-01-01 10:00:00", "Withdraw", "BTC", "-0.5", "Spot", "Wallet"]],
        bitvavo_rows=[
            _bt_row("2024-01-01", "11:00:00", "deposit", "BTC", "0.5", "0", tid="dep"),
            _bt_row("2025-01-01", "10:00:00", "sell", "BTC", "0.5", "20000", tid="sale"),
        ])
    return b, v


def test_transferencia_exige_confirmacion_explicita(tmp_path):
    b, v = _with_transfer(tmp_path)
    with pytest.raises(FifoGlobalError, match="sin conciliación"):
        _calculate(b, v)
    pair = TransferenciaConfirmada("b1:movement:0", "v1:movement:0", True)
    report = _calculate(b, v, transferencias=(pair,))
    assert len(report.transferencias_conciliadas) == 1
    assert report.resultados_ejercicio[0].precio_coste == pytest.approx(10000)
    assert report.resultados_ejercicio[0].ganancia_perdida == pytest.approx(10000)


def test_transferencia_sin_titularidad_confirmada_bloqueada(tmp_path):
    b, v = _with_transfer(tmp_path)
    pair = TransferenciaConfirmada("b1:movement:0", "v1:movement:0", False)
    with pytest.raises(FifoGlobalError, match="titularidad"):
        _calculate(b, v, transferencias=(pair,))


def test_transferencia_cantidad_diferente_no_ignora_fee_red(tmp_path):
    b, v = _with_transfer(tmp_path)
    v.clasificador.movimientos[0].cantidad = 0.49
    pair = TransferenciaConfirmada("b1:movement:0", "v1:movement:0", True)
    with pytest.raises(FifoGlobalError, match="comisión"):
        _calculate(b, v, transferencias=(pair,))


def test_transferencia_sin_paridad_y_reutilizacion_bloqueadas(tmp_path):
    b, v = _with_transfer(tmp_path)
    wrong = TransferenciaConfirmada("v1:movement:0", "b1:movement:0", True)
    with pytest.raises(FifoGlobalError, match="incompatibles"):
        _calculate(b, v, transferencias=(wrong,))
    same = TransferenciaConfirmada("b1:movement:0", "v1:movement:0", True)
    with pytest.raises(FifoGlobalError, match="dos veces"):
        _calculate(b, v, transferencias=(same, same))


def test_movimiento_stablecoin_no_puede_desaparecer(tmp_path):
    b, v = _sources(tmp_path)
    from clasificador_bitvavo import OperacionMovimiento
    v.clasificador.movimientos.append(
        OperacionMovimiento("2024-01-01 10:00:00", "buy_stable", "USDT", 100, "EUR"))
    with pytest.raises(FifoGlobalError, match="Movimiento no conciliable"):
        _calculate(b, v)


def test_fecha_compra_venta_simultanea_ambigua(tmp_path):
    b, v = _sources(tmp_path, binance_rows=_buy("2025-01-01 10:00:00"),
                    bitvavo_rows=[_bt_row("2025-01-01", "10:00:00", "sell")])
    with pytest.raises(FifoGlobalError, match="temporal ambiguo"):
        _calculate(b, v)


def test_no_crea_pdf_ni_registra_informe(tmp_path):
    b, v = _sources(tmp_path)
    r = _calculate(b, v)
    assert r.motor.resultados
    assert list(tmp_path.glob("*.pdf")) == []
