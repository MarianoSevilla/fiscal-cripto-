"""Pruebas sintéticas del importador Binance multifuente.

Los esquemas imitan únicamente cabeceras y relaciones observadas en exports
reales de Binance. Todos los importes, IDs y fechas son ficticios.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clasificador_binance_multi import ClasificadorBinanceMulti, BinanceMultiUserError


def _csv(tmp_path, name, header, *rows):
    p = tmp_path / name
    p.write_text(header + "".join(rows), encoding="utf-8")
    return str(p), name


SPOT_HEADER = (
    "Número de pedido,Tiempo,Par,Lado,Precio,Ejecutado,Cantidad,Tarifa,"
    "Par de conversión de AOR,Tasa de conversión de AOR\n"
)
CONVERT_HEADER = "Tiempo,Billetera,Par,Tipo,Vender,Comprar,Precio,Precio inverso,Fecha actualizada,Estado\n"
TX_HEADER_ALT = "ID de usuario,Hora,Cuenta,Operación,Moneda,Cambiar,Comentario\n"
SPOT_ORDER_HEADER = (
    "Tiempo,Número de pedido,Par,Tipo¹,Lado,Precio de la orden,Cantidad de la orden,"
    "Tiempo.1,Ejecutado²,Precio medio,Total de trading³,Estado\n"
)
FIAT_HEADER = "Tiempo,Método,Cantidad a gastar,Recibir cantidad,Tarifa,Precio,Estado,ID de transacción\n"
CRYPTO_DEPOSIT_HEADER = "Tiempo,Moneda,Red,Cantidad,Dirección,TXID,Estado\n"
CRYPTO_WITHDRAW_HEADER = "Tiempo,Moneda,Red,Cantidad,Tarifa,Dirección,TXID,Estado\n"


def test_spot_trades_preserva_fills_y_no_usa_ordenes_como_operaciones(tmp_path):
    trades, n1 = _csv(
        tmp_path, "Binance-Historial-de-operaciones-de-spot-20260101(UTC+1)_a.csv",
        SPOT_HEADER,
        "OID-1,2025-01-02 10:00:00,BTCEUR,BUY,50000,0.001 BTC,50 EUR,0 BTC,,\n",
        "OID-1,2025-01-02 10:00:01,BTCEUR,BUY,51000,0.002 BTC,102 EUR,0 BTC,,\n",
    )
    orders, n2 = _csv(
        tmp_path, "Binance-Historial-de-órdenes-de-spot-20260101(UTC+1)_b.csv",
        SPOT_ORDER_HEADER,
        "2025-01-02 09:59:59,OID-1,BTCEUR,LIMIT,BUY,51000 EUR,0.003 BTC,"
        "2025-01-02 10:00:01,0.003 BTC,50666,152 EUR,FILLED\n",
    )
    c = ClasificadorBinanceMulti([trades, orders], [n1, n2]).clasificar()
    assert len([e for e in c.eventos if e.fuente == "spot_trade"]) == 2
    assert len(c.compraventas) == 2
    assert c.bloqueos_valoracion == []
    assert c.resumen_archivos["spot_order"]["detectado"] is True


def test_spot_buy_fee_en_activo_comprado_reduce_cantidad_neta(tmp_path):
    trades, name = _csv(
        tmp_path, "Binance-Historial-de-operaciones-de-spot-20260101(UTC+1)_a.csv",
        SPOT_HEADER,
        "OID-2,2025-01-02 10:00:00,XRPEUR,BUY,2,100 XRP,200 EUR,0.5 XRP,,\n",
    )
    c = ClasificadorBinanceMulti([trades], [name]).clasificar()
    assert len(c.compraventas) == 1
    op = c.compraventas[0]
    assert op.tipo == "COMPRA"
    assert op.cantidad == pytest.approx(99.5)
    assert op.importe == pytest.approx(200)
    assert op.fee_cantidad == 0


def test_spot_buy_fee_eur_incrementa_coste(tmp_path):
    trades, name = _csv(
        tmp_path, "Binance-Historial-de-operaciones-de-spot-20260101(UTC+1)_a.csv",
        SPOT_HEADER,
        "OID-3,2025-01-02 10:00:00,XRPEUR,BUY,2,100 XRP,200 EUR,1 EUR,,\n",
    )
    c = ClasificadorBinanceMulti([trades], [name]).clasificar()
    assert c.compraventas[0].importe == pytest.approx(201)


def test_spot_fee_tercer_activo_bloquea_sin_inventar_eur(tmp_path):
    trades, name = _csv(
        tmp_path, "Binance-Historial-de-operaciones-de-spot-20260101(UTC+1)_a.csv",
        SPOT_HEADER,
        "OID-4,2025-01-02 10:00:00,XRPEUR,BUY,2,100 XRP,200 EUR,0.001 BNB,,\n",
    )
    c = ClasificadorBinanceMulti([trades], [name]).clasificar()
    assert not c.compraventas
    assert {g.code for g in c.bloqueos_valoracion} == {"spot_fee_third_asset"}
    with pytest.raises(ValueError, match="No se puede emitir un informe parcial"):
        c.validar_aceptacion()


def test_spot_no_eur_queda_canonico_pero_bloqueado(tmp_path):
    trades, name = _csv(
        tmp_path, "Binance-Historial-de-operaciones-de-spot-20260101(UTC+1)_a.csv",
        SPOT_HEADER,
        "OID-5,2025-01-02 10:00:00,XRPUSDT,SELL,2,100 XRP,200 USDT,0.2 USDT,,\n",
    )
    c = ClasificadorBinanceMulti([trades], [name]).clasificar()
    assert len(c.eventos) == 1
    assert not c.compraventas
    assert c.eventos[0].valoracion == "PENDIENTE"
    assert "spot_non_eur" in {g.code for g in c.bloqueos_valoracion}


def test_convert_eur_directo_y_crypto_crypto_bloqueado(tmp_path):
    path, name = _csv(
        tmp_path, "Binance-Historial-de-órdenes-de-Convert-20260101(UTC+1)_a.csv",
        CONVERT_HEADER,
        "2025-02-01 10:00:00,SPOT,EUR/XRP,MARKET,100 EUR,50 XRP,2,0.5,2025-02-01,Successful\n",
        "2025-02-02 10:00:00,SPOT,BTC/XRP,MARKET,0.01 BTC,300 XRP,30000,0,2025-02-02,Successful\n",
    )
    c = ClasificadorBinanceMulti([path], [name]).clasificar()
    assert len(c.compraventas) == 1
    assert c.compraventas[0].tipo == "COMPRA"
    assert len(c.eventos) == 2
    assert "convert_non_eur" in {g.code for g in c.bloqueos_valoracion}


def test_fiat_buy_no_suma_dos_veces_tarifa_exportada(tmp_path):
    path, name = _csv(
        tmp_path, "Binance-Historial-de-compras-de-fiat-20260101(UTC+1)_a.csv",
        FIAT_HEADER,
        "2025-03-01 10:00:00,Tarjeta,300 EUR,299 USDC,1 EUR,1,Successful,F-1\n",
    )
    c = ClasificadorBinanceMulti([path], [name]).clasificar()
    op = c.compraventas[0]
    assert op.tipo == "COMPRA"
    assert op.activo == "USDC"
    assert op.cantidad == pytest.approx(299)
    assert op.importe == pytest.approx(300)
    assert op.fee_cantidad == 0


def test_fiat_sell_fee_eur_se_conserva(tmp_path):
    path, name = _csv(
        tmp_path, "Binance-Historial-de-ventas-de-fiat-20260101(UTC+1)_a.csv",
        FIAT_HEADER,
        "2025-03-02 10:00:00,Tarjeta,1 BNB,599 EUR,1 EUR,600,Successful,F-2\n",
    )
    c = ClasificadorBinanceMulti([path], [name]).clasificar()
    op = c.compraventas[0]
    assert (op.tipo, op.activo, op.contraparte) == ("VENTA", "BNB", "EUR")
    assert op.importe == pytest.approx(599)
    assert op.fee_activo == "EUR"
    assert op.fee_cantidad == pytest.approx(1)


def test_transferencias_crypto_no_se_convierten_en_compraventas(tmp_path):
    dep, n1 = _csv(
        tmp_path, "Binance-Historial-de-depósitos-20260101(UTC+1)_a.csv",
        CRYPTO_DEPOSIT_HEADER,
        "2025-04-01 10:00:00,XRP,XRP,100,rAddress,TX-1,Completed\n",
    )
    wd, n2 = _csv(
        tmp_path, "Binance-Historial-de-retiros-20260101(UTC+1)_b.csv",
        CRYPTO_WITHDRAW_HEADER,
        "2025-04-02 10:00:00,XRP,XRP,50,0.1,rAddress2,TX-2,Completed\n",
    )
    c = ClasificadorBinanceMulti([dep, wd], [n1, n2]).clasificar()
    assert not c.compraventas
    assert len(c.movimientos) == 2
    assert len(c.eventos) == 2


def test_spot_orders_sin_fills_bloquean(tmp_path):
    orders, name = _csv(
        tmp_path, "Binance-Historial-de-órdenes-de-spot-20260101(UTC+1)_b.csv",
        SPOT_ORDER_HEADER,
        "2025-01-02 09:59:59,OID-1,BTCEUR,LIMIT,BUY,51000 EUR,0.003 BTC,"
        "2025-01-02 10:00:01,0.003 BTC,50666,152 EUR,FILLED\n",
    )
    c = ClasificadorBinanceMulti([orders], [name]).clasificar()
    assert "spot_orders_without_trades" in {g.code for g in c.bloqueos_valoracion}


def test_transaction_history_alt_headers_funciona_como_fallback(tmp_path):
    tx, name = _csv(
        tmp_path, "Binance-Historial-de-transacciones-20260101(UTC+1)_a.csv",
        TX_HEADER_ALT,
        "999,2025-05-01 10:00:00,Spot,Transaction Spend,EUR,-100,\n",
        "999,2025-05-01 10:00:00,Spot,Transaction Buy,BTC,0.002,\n",
    )
    c = ClasificadorBinanceMulti([tx], [name]).clasificar()
    assert len(c.compraventas) == 1
    assert c.compraventas[0].activo == "BTC"


def test_transaction_history_es_complementario_y_no_duplica_trades_especializados(tmp_path):
    tx, ntx = _csv(
        tmp_path, "Binance-Historial-de-transacciones-20260101(UTC+1)_tx.csv",
        TX_HEADER_ALT,
        "999,2025-06-01 10:00:00,Spot,Transaction Spend,EUR,-100,\n",
        "999,2025-06-01 10:00:00,Spot,Transaction Buy,BTC,0.002,\n",
        "999,2025-06-02 10:00:00,Spot,Simple Earn Flexible Interest,BTC,0.0001,\n",
    )
    spot, nspot = _csv(
        tmp_path, "Binance-Historial-de-operaciones-de-spot-20260101(UTC+1)_spot.csv",
        SPOT_HEADER,
        "OID-9,2025-06-01 10:00:00,BTCEUR,BUY,50000,0.002 BTC,100 EUR,0 BTC,,\n",
    )
    c = ClasificadorBinanceMulti([tx, spot], [ntx, nspot]).clasificar()
    assert len(c.compraventas) == 1
    assert len(c.rendimientos) == 1


def test_export_tx_vacio_no_invalida_fuentes_especializadas(tmp_path):
    tx, ntx = _csv(
        tmp_path, "Binance-Historial-de-transacciones-20260101(UTC+1)_tx.csv",
        TX_HEADER_ALT,
        "No hay datos que se ajusten a los criterios.,,,,,,\n",
    )
    spot, nspot = _csv(
        tmp_path, "Binance-Historial-de-operaciones-de-spot-20260101(UTC+1)_spot.csv",
        SPOT_HEADER,
        "OID-10,2025-06-01 10:00:00,BTCEUR,BUY,50000,0.002 BTC,100 EUR,0 BTC,,\n",
    )
    c = ClasificadorBinanceMulti([tx, spot], [ntx, nspot]).clasificar()
    assert len(c.compraventas) == 1
    assert c.resumen_archivos["transaction_history"]["vacio"] is True


def test_fiat_ambiguo_renombrado_se_bloquea(tmp_path):
    path, _ = _csv(
        tmp_path, "renombrado.csv", FIAT_HEADER,
        "2025-03-01 10:00:00,Tarjeta,300 EUR,299 USDC,1 EUR,1,Successful,F-1\n",
    )
    with pytest.raises(BinanceMultiUserError, match="sin renombrarlo"):
        ClasificadorBinanceMulti([path], ["renombrado.csv"]).clasificar()


def test_archivo_duplicado_se_rechaza_antes_de_clasificar(tmp_path):
    path, name = _csv(
        tmp_path, "Binance-Historial-de-operaciones-de-spot-20260101(UTC+1)_a.csv",
        SPOT_HEADER,
        "OID-11,2025-01-02 10:00:00,BTCEUR,BUY,50000,0.001 BTC,50 EUR,0 BTC,,\n",
    )
    with pytest.raises(BinanceMultiUserError, match="mismo archivo"):
        ClasificadorBinanceMulti([path, path], [name, name])
