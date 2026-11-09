"""Regresiones sintéticas de cabeceras Binance ES observadas en 2026.

No se utilizan ni se almacenan operaciones ni identificadores reales.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clasificador_binance_tx import ClasificadorBinanceTx

HEADER_CANONICA = "ID de usuario,Tiempo,Cuenta,Operación,Moneda,Cambio,Observación\n"
HEADER_VARIANTE = "ID de usuario,Hora,Cuenta,Operación,Moneda,Cambiar,Comentario\n"


def _crear(tmp_path, header, rows, *, bom=False):
    ruta = tmp_path / "historial_binance_sintetico.csv"
    ruta.write_text(("\ufeff" if bom else "") + header + rows, encoding="utf-8")
    return str(ruta)


def test_variante_es_hora_cambiar_comentario_admitida(tmp_path):
    rows = (
        "12345678,2024-04-01 12:00:00,Spot,Transaction Spend,EUR,-150,\n"
        "12345678,2024-04-01 12:00:00,Spot,Transaction Buy,BTC,0.003,\n"
        "12345678,2024-04-01 12:05:00,Spot,Simple Earn Flexible Interest,BTC,0.000001,\n"
    )
    clasificador = ClasificadorBinanceTx(
        _crear(tmp_path, HEADER_VARIANTE, rows, bom=True)
    ).clasificar()
    assert len(clasificador.compraventas) == 1
    assert len(clasificador.rendimientos) == 1
    assert clasificador.desconocidas == []
    compra = clasificador.compraventas[0]
    assert compra.tipo == "COMPRA"
    assert compra.activo == "BTC"
    assert compra.cantidad == 0.003
    assert compra.importe == 150.0


def test_variante_es_mismo_resultado_que_cabecera_canonica(tmp_path):
    rows = (
        "12345678,2024-04-01 12:00:00,Spot,Transaction Spend,EUR,-150,\n"
        "12345678,2024-04-01 12:00:00,Spot,Transaction Buy,BTC,0.003,\n"
    )
    canonico = ClasificadorBinanceTx(
        _crear(tmp_path, HEADER_CANONICA, rows)
    ).clasificar()
    alternativo = ClasificadorBinanceTx(
        _crear(tmp_path, HEADER_VARIANTE, rows)
    ).clasificar()
    assert alternativo.resumen() == canonico.resumen()
    assert alternativo.compraventas == canonico.compraventas


def test_comentario_se_utiliza_como_observacion_wallet(tmp_path):
    rows = (
        "12345678,2024-04-02 10:00:00,Spot,Buy Crypto With Fiat,EUR,-600,Wallet/ABC123\n"
        "12345678,2024-04-02 10:00:00,Spot,Buy Crypto With Fiat,BTC,0.02,Wallet/ABC123\n"
    )
    clasificador = ClasificadorBinanceTx(
        _crear(tmp_path, HEADER_VARIANTE, rows)
    ).clasificar()
    assert len(clasificador.compraventas) == 1
    compra = clasificador.compraventas[0]
    assert compra.tipo == "COMPRA"
    assert compra.importe == 600.0
    assert compra.cantidad == 0.02
    assert clasificador.desconocidas == []
