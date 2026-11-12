from decimal import Decimal
"""Pruebas sintéticas del importador Binance multifuente.

Ningún fixture contiene datos de usuarios reales.
"""
from pathlib import Path
import csv
import sys
import zipfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clasificador_binance_multi import (
    BinanceMultiUserError,
    ClasificadorBinanceMulti,
    detect_binance_source,
)
from binance_uploads import BinanceUploadError, save_binance_uploads


SPOT_H = [
    "Número de pedido", "Tiempo", "Par", "Lado", "Precio", "Ejecutado",
    "Cantidad", "Tarifa", "Par de conversión de AOR", "Tasa de conversión de AOR",
]
SPOT_ORDER_H = [
    "Tiempo", "Número de pedido", "Par", "Tipo¹", "Lado", "Precio de la orden",
    "Cantidad de la orden", "Tiempo", "Ejecutado²", "Precio medio",
    "Total de trading³", "Estado",
]
CONVERT_H = [
    "Tiempo", "Billetera", "Par", "Tipo", "Vender", "Comprar", "Precio",
    "Precio inverso", "Fecha actualizada", "Estado",
]
FIAT_TRADE_H = [
    "Tiempo", "Método", "Cantidad a gastar", "Recibir cantidad", "Tarifa",
    "Precio", "Estado", "ID de transacción",
]
DEPOSIT_H = ["Tiempo", "Moneda", "Red", "Cantidad", "Dirección", "TXID", "Estado"]
WITHDRAW_H = DEPOSIT_H[:-1] + ["Tarifa", "Estado"]
TX_H = ["ID de usuario", "Tiempo", "Cuenta", "Operación", "Moneda", "Cambio", "Observación"]


def _csv(tmp_path, name, headers, rows):
    p = tmp_path / name
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)
    return str(p)


def _classify(paths, names=None):
    return ClasificadorBinanceMulti(paths, names or [Path(p).name for p in paths]).clasificar()


def test_detecta_fuentes_por_cabecera():
    assert detect_binance_source(SPOT_H) == "spot_trades"
    assert detect_binance_source(SPOT_ORDER_H) == "spot_orders"
    assert detect_binance_source(CONVERT_H) == "convert_orders"
    assert detect_binance_source(FIAT_TRADE_H) == "fiat_trade"
    assert detect_binance_source(DEPOSIT_H) == "crypto_deposit"
    assert detect_binance_source(WITHDRAW_H) == "crypto_withdrawal"
    assert detect_binance_source(TX_H) == "transaction_history"


def test_spot_preserva_fills_y_fee_en_activo_recibido(tmp_path):
    p = _csv(tmp_path, "spot.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "10XRP", "20EUR", "0.1XRP", "", ""],
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "5XRP", "10EUR", "0.05XRP", "", ""],
    ])
    c = _classify([p])
    assert len(c.compraventas) == 2
    assert [x.cantidad for x in c.compraventas] == [9.9, 4.95]
    assert sum(x.importe for x in c.compraventas) == 30.0
    assert c.comisiones_pendientes == []


def test_ordenes_spot_no_duplican_fills(tmp_path):
    trades = _csv(tmp_path, "trades.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "10XRP", "20EUR", "0XRP", "", ""],
    ])
    orders = _csv(tmp_path, "orders.csv", SPOT_ORDER_H, [
        ["2025-01-01 10:00:00", "42", "XRPEUR", "Market", "BUY", "0", "10XRP",
         "2025-01-01 10:00:00", "10XRP", "2", "20EUR", "Filled"],
    ])
    c = _classify([trades, orders])
    assert len(c.compraventas) == 1
    assert c.resumen_archivos["spot_orders"]["registros"] == 1
    assert any("solo para reconciliación" in x for x in c.advertencias)


def test_fee_en_tercer_activo_se_conserva_y_bloquea_aceptacion_posterior(tmp_path):
    p = _csv(tmp_path, "spot.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "10XRP", "20EUR", "0.001BNB", "", ""],
    ])
    c = _classify([p])
    assert len(c.compraventas) == 1
    assert c.comisiones_pendientes[0]["activo"] == "BNB"
    assert c.comisiones_pendientes[0]["cantidad"] == "0.001"


def test_spot_no_eur_es_permuta_y_no_paridad_estable(tmp_path):
    p = _csv(tmp_path, "spot.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPUSDC", "BUY", "2", "10XRP", "20USDC", "0XRP", "", ""],
    ])
    c = _classify([p])
    assert len(c.swaps) == 1
    assert c.swaps[0].activo_entregado == "USDC"
    assert c.valoraciones_pendientes[0]["motivo"] == "permuta_sin_valor_eur"


def test_convert_eur_y_crypto_crypto(tmp_path):
    p = _csv(tmp_path, "convert.csv", CONVERT_H, [
        ["2025-01-01 10:00:00", "SPOT", "XRPEUR", "Instant", "20 EUR", "10 XRP", "", "", "", "Successful"],
        ["2025-01-02 10:00:00", "SPOT", "XRPUSDC", "Instant", "20 USDC", "10 XRP", "", "", "", "Successful"],
    ])
    c = _classify([p])
    assert len(c.compraventas) == 1
    assert c.compraventas[0].tipo == "COMPRA"
    assert c.compraventas[0].importe == 20.0
    assert len(c.swaps) == 1
    assert len(c.valoraciones_pendientes) == 1


def test_fiat_compra_incluye_fee_eur_y_venta_es_transmision(tmp_path):
    p = _csv(tmp_path, "fiat.csv", FIAT_TRADE_H, [
        ["2025-01-01 10:00:00", "SEPA", "100 EUR", "110 USDC", "1 EUR", "", "Successful", "A1"],
        ["2025-01-02 10:00:00", "Saldo", "0.1 BNB", "60 EUR", "2 EUR", "", "Successful", "A2"],
    ])
    c = _classify([p])
    assert c.compraventas[0].tipo == "COMPRA"
    assert c.compraventas[0].importe == 101.0
    assert c.compraventas[1].tipo == "VENTA"
    assert c.compraventas[1].importe == 60.0
    assert c.compraventas[1].fee_cantidad == 2.0


def test_transferencias_no_se_convierten_en_compraventa(tmp_path):
    dep = _csv(tmp_path, "dep.csv", DEPOSIT_H, [
        ["2025-01-01 10:00:00", "XRP", "XRP", "10", "addr", "tx1", "Completed"],
    ])
    ret = _csv(tmp_path, "ret.csv", WITHDRAW_H, [
        ["2025-01-02 10:00:00", "XRP", "XRP", "5", "addr", "tx2", "0.01", "Completed"],
    ])
    c = _classify([dep, ret])
    assert len(c.movimientos) == 2
    assert c.compraventas == []
    assert c.swaps == []
    assert c.comisiones_pendientes[0]["fuente"] == "Retiro cripto"


def test_transaction_history_es_complementario_si_hay_spot(tmp_path):
    spot = _csv(tmp_path, "spot.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "10XRP", "20EUR", "0XRP", "", ""],
    ])
    tx = _csv(tmp_path, "tx.csv", TX_H, [
        ["1", "2025-01-01 10:00:00", "Spot", "Transaction Spend", "EUR", "-20", ""],
        ["1", "2025-01-01 10:00:00", "Spot", "Transaction Buy", "XRP", "10", ""],
        ["1", "2025-01-02 10:00:00", "Earn", "Simple Earn Flexible Interest", "XRP", "0.1", ""],
    ])
    c = _classify([spot, tx])
    assert len(c.compraventas) == 1
    assert len(c.rendimientos) == 1
    assert c.valoraciones_pendientes[-1]["motivo"] == "rendimiento_sin_valor_eur"


def test_variante_tx_2026_se_detecta(tmp_path):
    p = _csv(tmp_path, "tx.csv",
             ["ID de usuario", "Hora", "Cuenta", "Operación", "Moneda", "Cambiar", "Comentario"],
             [["1", "2025-01-01 10:00:00", "Earn", "Simple Earn Flexible Interest", "XRP", "0.1", ""]])
    c = _classify([p])
    assert c.resumen_archivos["transaction_history"]["detectado"] is True
    assert len(c.rendimientos) == 1


def test_archivo_vacio_binance_es_reconocido(tmp_path):
    p = _csv(tmp_path, "tx.csv", TX_H, [["No hay datos que se ajusten a los criterios."]])
    c = _classify([p])
    assert c.resumen_archivos["transaction_history"]["vacio"] is True
    assert c.compraventas == []


def test_zonas_horarias_mezcladas_bloquean(tmp_path):
    a = _csv(tmp_path, "a.csv", SPOT_H, [
        ["1", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "1XRP", "2EUR", "0XRP", "", ""],
    ])
    b = _csv(tmp_path, "b.csv", CONVERT_H, [
        ["2025-01-01 10:00:00", "SPOT", "XRPEUR", "Instant", "2 EUR", "1 XRP", "", "", "", "Successful"],
    ])
    with pytest.raises(BinanceMultiUserError, match="zonas horarias distintas"):
        _classify([a, b], ["A(UTC+1).csv", "B(UTC+2).csv"])


def test_fuente_opcional_no_vacia_no_se_ignora(tmp_path):
    headers = [
        "Momento de creación", "Billetera", "Frecuencia", "Cada hora",
        "Importe de origen", "Moneda de origen", "Importe de destino",
        "Moneda de destino", "Precio", "Precio inverso", "Fecha de liquidación",
        "ID del plan", "Estado",
    ]
    p = _csv(tmp_path, "recurring.csv", headers, [
        ["2025-01-01 10:00:00", "SPOT", "Daily", "", "10", "EUR", "5", "XRP", "", "", "", "P1", "Active"],
    ])
    c = _classify([p])
    assert c.fuentes_materiales_no_soportadas == ["recurring_convert"]


class _Upload:
    def __init__(self, path):
        self.filename = Path(path).name
        self._path = path

    def save(self, dest):
        Path(dest).write_bytes(Path(self._path).read_bytes())


def test_zip_binance_seguro_extrae_csv(tmp_path):
    zp = tmp_path / "binance.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("export.csv", "Tiempo,Cuenta,Operación,Moneda,Cambio\n")
    paths, names = save_binance_uploads([_Upload(zp)])
    try:
        assert len(paths) == 1
        assert names[0].endswith("::export.csv")
    finally:
        for p in paths:
            Path(p).unlink(missing_ok=True)


def test_zip_slip_se_rechaza(tmp_path):
    zp = tmp_path / "bad.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("../escape.csv", "x,y\n1,2\n")
    with pytest.raises(BinanceUploadError, match="rutas no permitidas"):
        save_binance_uploads([_Upload(zp)])


def test_csv_duplicado_se_rechaza(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("a,b\n1,2\n", encoding="utf-8")
    b.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(BinanceUploadError, match="dos veces"):
        save_binance_uploads([_Upload(a), _Upload(b)])


def test_spot_orden_dos_fills_conciliados_sin_perder_operaciones(tmp_path):
    fills = _csv(tmp_path, "fills.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "6XRP", "12EUR", "0XRP", "", ""],
        ["42", "2025-01-01 10:00:01", "XRPEUR", "BUY", "2", "4XRP", "8EUR", "0XRP", "", ""],
    ])
    orders = _csv(tmp_path, "orders.csv", SPOT_ORDER_H, [
        ["2025-01-01 09:59:59", "42", "XRPEUR", "Market", "BUY", "0", "10XRP",
         "2025-01-01 10:00:01", "10XRP", "2", "20EUR", "Filled"],
    ])
    c = _classify([fills, orders])
    assert len(c.compraventas) == 2
    assert c.fuentes_materiales_no_soportadas == []


def test_spot_orden_ejecutada_sin_fills_bloquea_aceptacion(tmp_path):
    orders = _csv(tmp_path, "orders.csv", SPOT_ORDER_H, [
        ["2025-01-01 09:59:59", "42", "XRPEUR", "Market", "BUY", "0", "10XRP",
         "2025-01-01 10:00:01", "10XRP", "2", "20EUR", "Filled"],
    ])
    c = _classify([orders])
    assert c.compraventas == []
    assert "spot_orders_ejecutadas_sin_fills_completos" in c.fuentes_materiales_no_soportadas


def test_spot_orden_sin_uno_de_sus_fills_bloquea_aceptacion(tmp_path):
    fills = _csv(tmp_path, "fills.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "6XRP", "12EUR", "0XRP", "", ""],
    ])
    orders = _csv(tmp_path, "orders.csv", SPOT_ORDER_H, [
        ["2025-01-01 09:59:59", "42", "XRPEUR", "Market", "BUY", "0", "10XRP",
         "2025-01-01 10:00:01", "10XRP", "2", "20EUR", "Filled"],
    ])
    c = _classify([fills, orders])
    assert len(c.compraventas) == 1
    assert "spot_orders_ejecutadas_sin_fills_completos" in c.fuentes_materiales_no_soportadas


def test_spot_orden_cancelada_no_ejecutada_no_exige_fills(tmp_path):
    orders = _csv(tmp_path, "orders.csv", SPOT_ORDER_H, [
        ["2025-01-01 09:59:59", "43", "XRPEUR", "Limit", "BUY", "2", "10XRP",
         "2025-01-01 10:00:01", "0XRP", "0", "0EUR", "Canceled"],
    ])
    c = _classify([orders])
    assert c.fuentes_materiales_no_soportadas == []


def test_tx_fee_no_conciliada_con_spot_no_se_descarta(tmp_path):
    spot = _csv(tmp_path, "spot.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "10XRP", "20EUR", "0XRP", "", ""],
    ])
    tx = _csv(tmp_path, "tx.csv", TX_H, [
        ["1", "2025-01-01 10:00:00", "Spot", "Transaction Spend", "EUR", "-20", ""],
        ["1", "2025-01-01 10:00:00", "Spot", "Transaction Buy", "XRP", "10", ""],
        ["1", "2025-01-01 10:00:00", "Spot", "Transaction Fee", "BNB", "-0.01", ""],
    ])
    with pytest.raises(BinanceMultiUserError) as exc:
        _classify([spot, tx])
    assert exc.value.code == "native_tx_fee_mismatch"


def test_tx_fee_identica_a_spot_se_deduplica_preservando_neto(tmp_path):
    spot = _csv(tmp_path, "spot.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "10XRP", "20EUR", "0.1XRP", "", ""],
    ])
    tx = _csv(tmp_path, "tx.csv", TX_H, [
        ["1", "2025-01-01 10:00:00", "Spot", "Transaction Spend", "EUR", "-20", ""],
        ["1", "2025-01-01 10:00:00", "Spot", "Transaction Buy", "XRP", "10", ""],
        ["1", "2025-01-01 10:00:00", "Spot", "Transaction Fee", "XRP", "-0.1", ""],
    ])
    c = _classify([spot, tx])
    assert len(c.compraventas) == 1
    assert c.compraventas[0].cantidad == 9.9
    assert c.comisiones_pendientes == []


def test_filas_spot_identicas_en_exportaciones_diferentes_bloquean_sin_omitir(tmp_path):
    row = ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "1XRP", "2EUR", "0XRP", "", ""]
    a = _csv(tmp_path, "spot_a.csv", SPOT_H, [row])
    b = _csv(tmp_path, "spot_b.csv", SPOT_H, [row])
    c = _classify([a, b])
    assert len(c.compraventas) == 2
    assert c.compraventas[0].cantidad == 1.0
    assert c.compraventas[1].cantidad == 1.0
    assert "filas_identicas_entre_exportaciones_sin_id_unico" in c.fuentes_materiales_no_soportadas


def test_dos_fills_spot_identicos_dentro_del_mismo_csv_no_se_deduplican(tmp_path):
    row = ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "1XRP", "2EUR", "0XRP", "", ""]
    p = _csv(tmp_path, "spot.csv", SPOT_H, [row, row])
    c = _classify([p])
    assert len(c.compraventas) == 2
    assert not c.fuentes_materiales_no_soportadas


def test_spot_par_no_coincide_con_activos_no_pasa_al_fifo(tmp_path):
    p = _csv(tmp_path, "spot.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "BTCEUR", "BUY", "2", "1XRP", "2EUR", "0XRP", "", ""],
    ])
    c = _classify([p])
    assert not c.compraventas
    assert "par_spot_inconsistente" in c.fuentes_materiales_no_soportadas


def test_csv_binance_fila_con_columnas_incompletas_se_rechaza(tmp_path):
    p = _csv(tmp_path, "spot.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "1XRP", "2EUR"],
    ])
    with pytest.raises(BinanceMultiUserError) as exc:
        _classify([p])
    assert exc.value.code == "inconsistent_csv_columns"


def test_convert_estado_desconocido_no_omite_operacion(tmp_path):
    p = _csv(tmp_path, "convert.csv", CONVERT_H, [
        ["2025-01-01 10:00:00", "SPOT", "XRPEUR", "Instant", "20 EUR", "10 XRP", "", "", "", "UnknownNewStatus"],
    ])
    c = _classify([p])
    assert not c.compraventas
    assert "estado_no_reconocido_convert_orders" in c.fuentes_materiales_no_soportadas


def test_convert_failed_no_es_operacion_ejecutada(tmp_path):
    p = _csv(tmp_path, "convert.csv", CONVERT_H, [
        ["2025-01-01 10:00:00", "SPOT", "XRPEUR", "Instant", "20 EUR", "10 XRP", "", "", "", "Failed"],
    ])
    c = _classify([p])
    assert not c.compraventas
    assert c.fuentes_materiales_no_soportadas == []



def test_transferencia_cripto_sin_activo_se_rechaza(tmp_path):
    p = _csv(tmp_path, "deposit.csv", DEPOSIT_H, [
        ["2025-01-01 10:00:00", "", "XRP", "10", "addr", "synthetic", "Completed"],
    ])
    with pytest.raises(BinanceMultiUserError) as exc:
        _classify([p])
    assert exc.value.code == "invalid_transfer_asset"


def test_movimiento_fiat_no_positivo_se_rechaza(tmp_path):
    headers = [
        "Tiempo", "Método", "Importe de depósito",
        "Recibir cantidad", "Tarifa", "Estado", "ID de transacción",
    ]
    p = _csv(tmp_path, "fiat.csv", headers, [
        ["2025-01-01 10:00:00", "SEPA", "-10 EUR", "-10 EUR", "0 EUR", "Completed", "synthetic"],
    ])
    with pytest.raises(BinanceMultiUserError) as exc:
        _classify([p])
    assert exc.value.code == "invalid_fiat_cash_amount"



def test_intercambios_nativos_preservan_cada_fill_y_archivo_para_valoracion(tmp_path):
    source = _csv(tmp_path, "spot.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2",
         "10XRP", "20EUR", "0.1BNB", "", ""],
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2",
         "5XRP", "10EUR", "0BNB", "", ""],
    ])
    c = _classify([source], ["Binance-Spot-(UTC+1).zip::trades.csv"])
    assert len(c.intercambios_nativos) == 2
    first, second = c.intercambios_nativos
    assert first.filename == "Binance-Spot-(UTC+1).zip::trades.csv"
    assert first.local_time == "2025-01-01 10:00:00"
    assert first.given_asset == "EUR"
    assert first.received_asset == "XRP"
    assert str(first.given_amount) == "20"
    assert str(first.received_amount) == "10"
    assert first.fee_asset == "BNB"
    assert str(first.fee_amount) == "0.1"
    assert str(second.received_amount) == "5"
    assert len(c.compraventas) == 2


def test_intercambios_nativos_convert_conservan_origen_y_precision(tmp_path):
    source = _csv(tmp_path, "convert.csv", CONVERT_H, [
        ["2025-01-01 10:00:00", "SPOT", "XRPUSDC", "Instant",
         "20.12345678 USDC", "10.87654321 XRP", "", "", "", "Successful"],
    ])
    c = _classify([source], ["Binance-Convert-(UTC+1).zip::convert.csv"])
    assert len(c.intercambios_nativos) == 1
    event = c.intercambios_nativos[0]
    assert event.source == "Convert"
    assert str(event.given_amount) == "20.12345678"
    assert str(event.received_amount) == "10.87654321"
    assert event.filename.endswith("::convert.csv")
    assert c.valoraciones_pendientes



def test_spot_con_conversion_aor_no_se_interpreta_como_operacion_simple(tmp_path):
    p = _csv(tmp_path, "spot-aor.csv", SPOT_H, [
        ["42", "2025-02-01 12:00:00", "XRPEUR", "BUY", "2",
         "10XRP", "20EUR", "0XRP", "XRPEUR", "1"],
    ])
    c = _classify([p])
    assert c.compraventas == []
    assert "spot_aor_conversion_no_reconstruida" in c.fuentes_materiales_no_soportadas
    assert c.intercambios_nativos == []


def test_spot_sin_aor_sigue_funcionando(tmp_path):
    p = _csv(tmp_path, "spot-plain.csv", SPOT_H, [
        ["42", "2025-02-01 12:00:00", "XRPEUR", "BUY", "2",
         "10XRP", "20EUR", "0XRP", "", ""],
    ])
    c = _classify([p])
    assert len(c.compraventas) == 1
    assert len(c.intercambios_nativos) == 1
    assert c.fuentes_materiales_no_soportadas == []


def test_spot_rechaza_fills_sin_orden_correspondiente(tmp_path):
    fills = _csv(tmp_path, "fills.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "10XRP", "20EUR", "0XRP", "", ""],
        ["43", "2025-01-01 10:01:00", "XRPEUR", "BUY", "2", "5XRP", "10EUR", "0XRP", "", ""],
    ])
    orders = _csv(tmp_path, "orders.csv", SPOT_ORDER_H, [
        ["2025-01-01 10:00:00", "42", "XRPEUR", "Market", "BUY", "0", "10XRP",
         "2025-01-01 10:00:00", "10XRP", "2", "20EUR", "Filled"],
    ])
    c = _classify([fills, orders])
    assert len(c.compraventas) == 2
    assert "spot_orders_ejecutadas_sin_fills_completos" in c.fuentes_materiales_no_soportadas


def test_spot_con_archivo_ordenes_vacio_y_fills_bloquea(tmp_path):
    fills = _csv(tmp_path, "fills.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "10XRP", "20EUR", "0XRP", "", ""],
    ])
    orders = _csv(tmp_path, "orders.csv", SPOT_ORDER_H, [])
    c = _classify([fills, orders])
    assert len(c.compraventas) == 1
    assert "spot_orders_ejecutadas_sin_fills_completos" in c.fuentes_materiales_no_soportadas


def test_spot_sin_archivo_ordenes_acepta_fills_y_no_infiere_ordenes(tmp_path):
    fills = _csv(tmp_path, "fills.csv", SPOT_H, [
        ["42", "2025-01-01 10:00:00", "XRPEUR", "BUY", "2", "10XRP", "20EUR", "0XRP", "", ""],
    ])
    c = _classify([fills])
    assert len(c.compraventas) == 1
    assert not c.fuentes_materiales_no_soportadas


def test_dos_deposit_tx_con_una_transferencia_nativa_no_se_borran_ambos(tmp_path):
    dep = _csv(tmp_path, "deposit.csv", DEPOSIT_H, [
        ["2025-01-01 10:00:00", "XRP", "XRP", "10", "synthetic", "tx-id-1", "Completed"],
    ])
    tx = _csv(tmp_path, "tx.csv", TX_H, [
        ["1", "2025-01-01 10:00:00", "Spot", "Deposit", "XRP", "10", ""],
        ["1", "2025-01-01 10:00:00", "Spot", "Deposit", "XRP", "10", ""],
    ])
    c = _classify([dep, tx])
    assert len(c.movimientos) >= 1
    assert "transferencias_duplicadas_sin_identidad_univoca" in c.fuentes_materiales_no_soportadas


def test_dos_deposit_tx_reconciliados_con_dos_deposit_nativos(tmp_path):
    dep = _csv(tmp_path, "deposit.csv", DEPOSIT_H, [
        ["2025-01-01 10:00:00", "XRP", "XRP", "10", "synthetic-a", "tx-id-1", "Completed"],
        ["2025-01-01 10:00:00", "XRP", "XRP", "10", "synthetic-b", "tx-id-2", "Completed"],
    ])
    tx = _csv(tmp_path, "tx.csv", TX_H, [
        ["1", "2025-01-01 10:00:00", "Spot", "Deposit", "XRP", "10", ""],
        ["1", "2025-01-01 10:00:00", "Spot", "Deposit", "XRP", "10", ""],
    ])
    c = _classify([dep, tx])
    assert len(c.movimientos) == 2
    assert "transferencias_duplicadas_sin_identidad_univoca" not in c.fuentes_materiales_no_soportadas


def test_csv_cabeceras_normalizadas_duplicadas_se_rechazan(tmp_path):
    headers = [
        "ID de usuario", "Tiempo", "Hora", "Cuenta",
        "Operación", "Moneda", "Cambio", "Observación",
    ]
    p = _csv(tmp_path, "duplicate_headers.csv", headers, [
        ["1", "2025-01-01 09:00:00", "2025-01-01 10:00:00", "Spot",
         "Deposit", "XRP", "10", ""],
    ])
    with pytest.raises(BinanceMultiUserError) as exc:
        _classify([p])
    assert exc.value.code == "ambiguous_csv_headers"


def test_csv_cabecera_vacia_se_rechaza(tmp_path):
    headers = ["Tiempo", "", "Par", "Lado", "Precio",
               "Ejecutado", "Cantidad", "Tarifa", "AOR", "Tasa"]
    p = _csv(tmp_path, "empty_header.csv", headers, [])
    with pytest.raises(BinanceMultiUserError) as exc:
        _classify([p])
    assert exc.value.code == "invalid_csv_headers"



def test_fiat_cash_usa_neto_recibido_en_depositos_y_bruto_sustraido_en_retiros(tmp_path):
    deposit = _csv(tmp_path, "fiat_deposit.csv", [
        "Tiempo", "Método", "Importe de depósito", "Recibir cantidad",
        "Tarifa", "Estado", "ID de transacción",
    ], [
        ["2025-01-05 09:00:00", "SEPA", "100 EUR", "99 EUR", "1 EUR", "Successful", "fake-1"],
        ["2025-01-05 10:00:00", "SEPA", "100 EUR", "99 EUR", "1 EUR", "Failed", "fake-2"],
    ])
    withdrawal = _csv(tmp_path, "fiat_withdrawal.csv", [
        "Tiempo", "Método", "Importe de retiro", "Recibir cantidad",
        "Tarifa", "Estado", "ID de transacción",
    ], [
        ["2025-01-06 09:00:00", "SEPA", "50 EUR", "49.5 EUR", "0.5 EUR", "Successful", "fake-3"],
    ])
    c = _classify([deposit, withdrawal])
    assert len(c.movimientos) == 2
    assert [m.cantidad for m in c.movimientos] == [99, -50]
    assert "Comisión fiat: 1 EUR" in c.movimientos[0].observacion
    assert "Comisión fiat: 0.5 EUR" in c.movimientos[1].observacion
    assert c.compraventas == []
    assert c.swaps == []
    assert c.comisiones_pendientes == []


def test_fiat_cash_importes_no_conciliados_se_rechazan(tmp_path):
    deposit = _csv(tmp_path, "fiat_inconsistent.csv", [
        "Tiempo", "Método", "Importe de depósito", "Recibir cantidad",
        "Tarifa", "Estado", "ID de transacción",
    ], [
        ["2025-01-05 09:00:00", "SEPA", "100 EUR", "98 EUR", "1 EUR", "Successful", "fake-1"],
    ])
    with pytest.raises(BinanceMultiUserError) as exc:
        _classify([deposit])
    assert exc.value.code == "fiat_cash_fee_mismatch"


def test_fiat_cash_nunca_convierte_a_otra_moneda_sin_fuente_valorada(tmp_path):
    deposit = _csv(tmp_path, "fiat_cross_currency.csv", [
        "Tiempo", "Método", "Importe de depósito", "Recibir cantidad",
        "Tarifa", "Estado", "ID de transacción",
    ], [
        ["2025-01-05 09:00:00", "SEPA", "100 EUR", "109 USD", "1 EUR", "Successful", "fake-1"],
    ])
    with pytest.raises(BinanceMultiUserError) as exc:
        _classify([deposit])
    assert exc.value.code == "fiat_cash_fee_mismatch"


def test_ledger_rebates_iguales_mismo_csv_conservan_multiplicidad(tmp_path):
    """Binance puede registrar dos bonos iguales en la misma marca temporal.

    Sin ID único no se puede colapsar dos filas idénticas en una.
    Solo se emplean cantidades, fechas y activos completamente sintéticos.
    """
    same_row = [
        "fake-user", "2022-06-01 10:00:00", "Spot",
        "Commission Rebate", "ABC", "0.00000004", "",
    ]
    ledger = _csv(tmp_path, "synthetic_2022_ledger.csv", TX_H, [
        same_row, same_row,
    ])
    c = _classify([ledger])
    assert c.resumen_archivos["transaction_history"]["registros"] == 2
    # Dos eventos económicos separados, sin asignar renta fiscal o valor EUR
    # hasta reconstruir su origen exacto; no son compras ni se descartan.
    assert c.rendimientos == []
    assert c.commission_evidence_summary.records == 2
    entries = list(c.iter_commission_evidence())
    assert [r.source_operation for r in entries] == [
        "Commission Rebate", "Commission Rebate",
    ]
    assert [r.ordinal for r in entries] == [0, 1]
    assert sum((r.quantity for r in entries), Decimal(0)) == Decimal("0.00000008")
    assert "binance_comisiones_sin_valoracion_ni_categoria_fiscal" in (
        c.fuentes_materiales_no_soportadas
    )


def test_binance_multi_csv_utf8_invalido_falla_cerrado(tmp_path):
    """El clasificador no reemplaza bytes ilegales antes de calcular FIFO."""
    p = tmp_path / "earn_corrupt.csv"
    p.write_bytes(
        b"Tiempo,Moneda,Cantidad,Tipo\n"
        + b"2025-01-01,AB" + bytes((255,))
        + b",0.01,Real-time APR Rewards\n"
    )
    with pytest.raises(BinanceMultiUserError) as exc:
        _classify([p])
    assert exc.value.code == "invalid_csv_encoding"
    assert exc.value.category == "parser_error"


def test_earn_overlap_realistic_stays_fail_closed(tmp_path):
    """Dos ZIP Earn solapados no deben borrar una recompensa sin identidad."""
    headers = ["Tiempo", "Moneda", "Cantidad", "Tipo"]
    shared = ["2025-12-30", "ABC", "0.00000012", "Real-time APR Rewards"]
    first = _csv(tmp_path, "earn-year.csv", headers, [
        ["2025-12-29", "ABC", "0.00000011", "Real-time APR Rewards"],
        shared,
    ])
    second = _csv(tmp_path, "earn-boundary.csv", headers, [
        shared,
        ["2026-01-01", "ABC", "0.00000013", "Real-time APR Rewards"],
    ])
    classified = _classify([first, second])
    assert classified.resumen_archivos["earn_flexible_rewards"]["registros"] == 4
    assert len(classified.earn_events) == 4
    assert "filas_identicas_entre_exportaciones_sin_id_unico" in (
        classified.fuentes_materiales_no_soportadas
    )
    assert "earn_flexible_requiere_inventario_y_valoracion_fiscal" in (
        classified.fuentes_materiales_no_soportadas
    )


def test_earn_ledger_historico_sin_zip_nativo_no_se_concilia(tmp_path):
    """Una exportacion Earn parcial no acredita suscripciones anteriores."""
    headers = ["Fecha de suscripción", "Nombre del producto", "Moneda",
               "Cantidad", "Tipo", "De", "Estado"]
    native = _csv(tmp_path, "earn-native.csv", headers, [
        ["2025-05-01 12:00:00", "ABC", "ABC", "100",
         "Auto", "SPOT", "Success"],
    ])
    ledger = _csv(tmp_path, "ledger.csv", TX_H, [
        ["synthetic", "2025-05-01 12:00:00", "Spot",
         "Simple Earn Flexible Subscription", "ABC", "-100", ""],
        ["synthetic", "2025-05-03 12:00:00", "Spot",
         "Simple Earn Flexible Subscription", "ABC", "-50", ""],
    ])
    classified = _classify([native, ledger])
    assert classified.earn_reconciliation.ledger_unmatched == 1
    assert classified.earn_reconciliation.native_unmatched == 0
    assert "earn_fuentes_no_conciliadas" in (
        classified.fuentes_materiales_no_soportadas
    )
