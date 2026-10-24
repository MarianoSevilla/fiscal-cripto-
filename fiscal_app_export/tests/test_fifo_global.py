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


def test_bitvavo_fee_en_btc_omitida_por_parser_no_pasa_al_global(tmp_path):
    b, v = _sources(tmp_path)
    # El parser individual convierte esta comisión en fee_eur=0.
    fila = v.clasificador.df.loc[v.clasificador.df["Type"] == "sell"].index[0]
    v.clasificador.df.at[fila, "Fee currency"] = "BTC"
    v.clasificador.df.at[fila, "Fee amount"] = "-0.0001"
    with pytest.raises(FifoGlobalError, match="comisión material en cripto"):
        _calculate(b, v)


def test_bitvavo_precio_en_usdt_aunque_pague_eur_rechazado(tmp_path):
    b, v = _sources(tmp_path)
    fila = v.clasificador.df.index[0]
    v.clasificador.df.at[fila, "Quote Currency"] = "USDT"
    with pytest.raises(FifoGlobalError, match="precio de compraventa"):
        _calculate(b, v)


def test_bitvavo_fallback_cantidad_sin_precio_no_es_seguro(tmp_path):
    b, v = _sources(tmp_path)
    fila = v.clasificador.df.index[0]
    v.clasificador.df.at[fila, "Quote Price"] = "0"
    with pytest.raises(FifoGlobalError, match="precio EUR unitario"):
        _calculate(b, v)


def test_bitvavo_fee_excesiva_no_se_descarta_en_silencio(tmp_path):
    b, v = _sources(tmp_path)
    fila = v.clasificador.df.index[0]
    v.clasificador.df.at[fila, "Fee amount"] = "-90000"
    with pytest.raises(FifoGlobalError, match="comisión EUR implausible"):
        _calculate(b, v)


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


def test_global_fecha_sin_hora_no_inventa_medianoche(tmp_path):
    b, v = _sources(tmp_path)
    b.clasificador.compraventas[0].fecha = "2023-01-01"
    with pytest.raises(FifoGlobalError, match="sin hora"):
        _calculate(b, v)


def test_global_offset_contradictorio_no_ignora_zona_acreditada(tmp_path):
    b, v = _sources(tmp_path)
    b.clasificador.compraventas[0].fecha = "2023-01-01T10:00:00+04:00"
    with pytest.raises(FifoGlobalError, match="Desfase UTC incompatible"):
        _calculate(b, v)


def test_global_offset_coherente_con_zona_declarada(tmp_path):
    b, v = _sources(tmp_path)
    b.clasificador.compraventas[0].fecha = "2023-01-01T10:00:00+02:00"
    b = replace(b, zona_horaria="UTC+02:00")
    result = _calculate(b, v)
    assert result.operaciones[0].fecha_utc.hour == 8


# Fase 3 — auditoría de procedencia (sin tocar el cálculo ni emitir PDFs).
from fifo_global_trazabilidad import auditar_fifo_global


def test_fase3_lotes_interexchange_y_fuente_bitvavo(tmp_path):
    b, v = _sources(tmp_path)
    resultado = _calculate(b, v)
    audit = auditar_fifo_global(resultado, (b, v))
    assert len(audit.ventas) == 1
    assert audit.ventas[0].ganancia_perdida_eur == 20000
    assert audit.ventas[0].consumos[0].adquisicion_id == "b1:cv:0"
    assert audit.ventas[0].consumos[0].venta_id == "v1:cv:1"
    assert len(audit.fuentes) == 3
    assert audit.fuentes[0].archivo_sha256 == b.archivo_sha256
    assert audit.fuentes[0].tipo_vinculo == "indice_clasificador"
    assert audit.fuentes[1].tipo_vinculo == "fila_parseada_bitvavo"
    assert audit.fuentes[1].id_nativo == "2"
    assert audit.fuentes[2].id_nativo == "3"
    assert audit.historial_exhaustivo_acreditado is False
    assert audit.apto_informe_fiscal_publico is False
    assert audit.limitaciones


def test_fase3_dos_lotes_binance_distintos_mismo_valor(tmp_path):
    b, v = _sources(
        tmp_path,
        binance_rows=_buy("2023-01-01 10:00:00", qty=0.5, eur=10000)
                     + _buy("2023-01-02 10:00:00", qty=0.5, eur=10000),
        bitvavo_rows=[_bt_row("2025-01-01", "10:00:00", "sell", eur="40000")],
    )
    audit = auditar_fifo_global(_calculate(b, v), (b, v))
    consumes = audit.ventas[0].consumos
    assert [x.adquisicion_id for x in consumes] == ["b1:cv:0", "b1:cv:1"]
    assert [x.cantidad for x in consumes] == [0.5, 0.5]
    assert [x.coste_eur for x in consumes] == [10000, 10000]


def test_fase3_solo_ventas_del_ejercicio_sin_perder_historico(tmp_path):
    b, v = _sources(tmp_path)
    audit = auditar_fifo_global(_calculate(b, v, ejercicio=2024), (b, v))
    assert len(audit.ventas) == 1
    assert audit.ventas_ejercicio == ()


def test_fase3_comisiones_eur_y_coste_adquisicion_trazados(tmp_path):
    b, v = _sources(tmp_path, bitvavo_rows=[
        _bt_row("2024-01-01", "10:00:00", "buy", eur="30000", fee="-15", tid="bfee"),
        _bt_row("2025-01-01", "10:00:00", "sell", eur="40000", fee="-20", tid="sfee"),
    ])
    # A venta uses oldest Binance lot; fee on the later Bitvavo buy stays
    # attached to that non-consumed inventory lot.
    audit = auditar_fifo_global(_calculate(b, v), (b, v))
    assert audit.ventas[0].transmision_neta_eur == 39980
    assert audit.ventas[0].coste_fifo_eur == 20000
    assert audit.ventas[0].ganancia_perdida_eur == 19980


def test_fase3_transferencia_confirmada_preserva_origen_lote(tmp_path):
    b, v = _with_transfer(tmp_path)
    pair = TransferenciaConfirmada("b1:movement:0", "v1:movement:0", True)
    audit = auditar_fifo_global(_calculate(b, v, transferencias=(pair,)), (b, v))
    assert audit.ventas[0].consumos[0].adquisicion_id == "b1:cv:0"
    assert audit.ventas[0].coste_fifo_eur == 10000
    assert any("booleano" in x for x in audit.limitaciones)
    assert not audit.apto_informe_fiscal_publico


def test_fase3_detecta_id_nativo_bitvavo_duplicado(tmp_path):
    b, v = _sources(tmp_path, bitvavo_rows=[
        _bt_row("2024-01-01", "10:00:00", "buy", eur="30000", tid="duplicate"),
        _bt_row("2025-01-01", "10:00:00", "sell", eur="40000", tid="duplicate"),
    ])
    with pytest.raises(FifoGlobalError, match="Transaction ID Bitvavo duplicado"):
        auditar_fifo_global(_calculate(b, v), (b, v))


def test_fase3_sin_id_nativo_no_inventa_evidencia(tmp_path):
    b, v = _sources(tmp_path, bitvavo_rows=[
        _bt_row("2024-01-01", "10:00:00", "buy", eur="30000", tid=""),
        _bt_row("2025-01-01", "10:00:00", "sell", eur="40000", tid=""),
    ])
    audit = auditar_fifo_global(_calculate(b, v), (b, v))
    assert audit.fuentes[1].id_nativo is None
    assert any("sin identificador nativo" in x for x in audit.limitaciones)


def test_fase3_doble_fila_identica_sin_id_nativo_bloqueada(tmp_path):
    b, v = _sources(tmp_path, bitvavo_rows=[
        _bt_row("2024-01-01", "10:00:00", "buy", eur="30000", tid=""),
        _bt_row("2024-01-01", "10:00:00", "buy", eur="30000", tid=""),
        _bt_row("2025-01-01", "10:00:00", "sell", eur="40000", tid="sale"),
    ])
    with pytest.raises(FifoGlobalError, match="fila Bitvavo repetida"):
        auditar_fifo_global(_calculate(b, v), (b, v))


def test_fase3_rechaza_detalle_lotes_del_motor_manipulado(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    result.motor.resultados[0].lotes_consumidos[0]["coste_parcial"] += 1
    with pytest.raises(FifoGlobalError, match="coste de lote"):
        auditar_fifo_global(result, (b, v))


def test_fase3_rechaza_plusvalia_alterada(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    result.motor.resultados[0].ganancia_perdida += 9
    with pytest.raises(FifoGlobalError, match="ganancia patrimonial"):
        auditar_fifo_global(result, (b, v))


def test_fase3_rechaza_fila_bitvavo_desincronizada(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    fila = v.clasificador.df.index[0]
    v.clasificador.df.at[fila, "Received / Paid Amount"] = "-999"
    with pytest.raises(FifoGlobalError, match="importe de fila Bitvavo"):
        auditar_fifo_global(result, (b, v))


def test_fase3_rechaza_fuente_modificada_tras_calculo(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    v.clasificador.compraventas[0].importe += 900
    with pytest.raises(FifoGlobalError, match="fuentes alteradas"):
        auditar_fifo_global(result, (b, v))


def test_fase3_no_certifica_historial_aunque_tenga_inventario(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    audit = auditar_fifo_global(result, (b, v))
    assert result.motor.advertencias == []
    assert any("No se acredita" in x for x in audit.limitaciones)
    assert not audit.historial_exhaustivo_acreditado
    assert not audit.apto_informe_fiscal_publico


def test_fase3_rendimiento_bitvavo_vinculado_sin_duplicar_lote(tmp_path):
    b, v = _sources(tmp_path, bitvavo_rows=[
        _bt_row("2024-01-01", "10:00:00", "staking", "ETH", "0.1", "100", tid="stake")])
    audit = auditar_fifo_global(_calculate(b, v, ejercicio=2024), (b, v))
    rewards = [e for e in audit.fuentes if e.operacion_id == "v1:reward:0"]
    assert len(rewards) == 1
    assert rewards[0].id_nativo == "stake"
    assert audit.ventas == ()


# Casos adversariales de cierre: evidencia de origen y metadatos de lotes.
def test_fase3_no_inventa_linea_fisica_csv_tras_salto_vacio(tmp_path):
    b, v = _sources(tmp_path)
    path = tmp_path / "bitvavo.csv"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    # pandas.read_csv omite líneas vacías: índice DF+2 NO equivale a línea CSV.
    path.write_text("\n".join([lines[0], lines[1], "", *lines[2:]]) + "\n",
                    encoding="utf-8-sig")
    v = replace(v,
        archivo_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        clasificador=ClasificadorBitvavo(str(path)).clasificar())
    audit = auditar_fifo_global(_calculate(b, v), (b, v))
    sell = next(e for e in audit.fuentes if e.operacion_id == "v1:cv:1")
    assert sell.indice_fila_parseada == 1
    assert sell.fila_csv is None  # La fila física real es 4; no acreditada.
    assert sell.id_nativo == "3"


def test_fase3_rechaza_precio_raw_alterado_antes_del_calculo(tmp_path):
    b, v = _sources(tmp_path)
    # El clasificador ya ha almacenado la cantidad; Fase 2 solo ve que
    # el nuevo Quote Price es positivo. Fase 3 debe verificar cantidad.
    v.clasificador.df.at[v.clasificador.df.index[0], "Quote Price"] = "15000"
    result = _calculate(b, v)
    with pytest.raises(FifoGlobalError, match="cantidad de operación Bitvavo"):
        auditar_fifo_global(result, (b, v))


def test_fase3_rechaza_valoracion_reward_inconsistente_con_precio_raw(tmp_path):
    b, v = _sources(tmp_path, bitvavo_rows=[
        _bt_row("2024-01-01", "10:00:00", "staking", "ETH", "0.1", "100",
                tid="stake")
    ])
    v.clasificador.df.at[v.clasificador.df.index[0], "Quote Price"] = "2000"
    with pytest.raises(FifoGlobalError, match="valor EUR de rendimiento"):
        auditar_fifo_global(_calculate(b, v), (b, v))


def test_fase3_rechaza_reward_fee_original_ignorada(tmp_path):
    b, v = _sources(tmp_path, bitvavo_rows=[
        _bt_row("2024-01-01", "10:00:00", "staking", "ETH", "0.1", "100",
                tid="stake")
    ])
    v.clasificador.df.at[v.clasificador.df.index[0], "Fee amount"] = "-2"
    with pytest.raises(FifoGlobalError, match="comisión de rendimiento"):
        auditar_fifo_global(_calculate(b, v), (b, v))


def test_fase3_rechaza_precio_unitario_lote_alterado(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    result.motor.resultados[0].lotes_consumidos[0]["precio_unitario"] += 100
    with pytest.raises(FifoGlobalError, match="precio unitario de lote"):
        auditar_fifo_global(result, (b, v))


def test_fase3_rechaza_contraparte_lote_alterada(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    result.motor.resultados[0].lotes_consumidos[0]["contraparte"] = "USDT"
    with pytest.raises(FifoGlobalError, match="contraparte del lote"):
        auditar_fifo_global(result, (b, v))


def test_fase3_rechaza_saldo_residual_adulterado(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    # Las ventas siguen con el mismo coste y ganancia, pero una posición
    # superviviente queda inflada. Antes no se auditaba el inventario final.
    result.motor.inventario["BTC"][1].cantidad_restante += 0.5
    with pytest.raises(FifoGlobalError, match="cantidad restante residual"):
        auditar_fifo_global(result, (b, v))


def test_fase3_rechaza_coste_unitario_residual_adulterado(tmp_path):
    b, v = _sources(tmp_path)
    result = _calculate(b, v)
    result.motor.inventario["BTC"][1].precio_coste_unitario += 100
    with pytest.raises(FifoGlobalError, match="coste unitario residual"):
        auditar_fifo_global(result, (b, v))


def test_fase3_compra_simultanea_coste_distinto_no_inventa_precedencia(tmp_path):
    # Binance y Bitvavo adquieren BTC en el mismo instante UTC.
    # Orden por source_id decide qué base se atribuye a la venta parcial.
    b, v = _sources(tmp_path,
        binance_rows=_buy("2024-01-01 10:00:00", eur=20000),
        bitvavo_rows=[
            _bt_row("2024-01-01", "10:00:00", "buy", eur="30000", tid="buy"),
            _bt_row("2025-01-01", "10:00:00", "sell", eur="40000", tid="sell"),
        ])
    # El núcleo previo produce un resultado definido por la clave técnica;
    # la capa de evidencia debe impedir tratarlo como FIFO inequívoco.
    resultado = _calculate(b, v)
    assert resultado.resultados_ejercicio[0].precio_coste == pytest.approx(20000)
    with pytest.raises(FifoGlobalError, match="adquisiciones simultáneas"):
        auditar_fifo_global(resultado, (b, v))


def test_fase3_compras_simultaneas_igual_coste_no_bloqueadas(tmp_path):
    b, v = _sources(tmp_path,
        binance_rows=_buy("2024-01-01 10:00:00", eur=20000),
        bitvavo_rows=[
            _bt_row("2024-01-01", "10:00:00", "buy", eur="20000", tid="buy"),
            _bt_row("2025-01-01", "10:00:00", "sell", eur="40000", tid="sell"),
        ])
    audit = auditar_fifo_global(_calculate(b, v), (b, v))
    assert audit.ventas[0].ganancia_perdida_eur == 20000
