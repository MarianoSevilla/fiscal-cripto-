"""Ensayo con 12 ZIP Binance SINTÉTICOS, sin movimientos ni IDs de clientes.

El número de fuentes y sus cabeceras reproducen las familias reales de
exportación de Binance. Los valores, fechas, IDs y contrapartes son inventados.
No demuestra cobertura histórica completa de una cuenta real.
"""
import csv
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_uploads import save_binance_uploads
from clasificador_binance_multi import ClasificadorBinanceMulti


SPOT = ["Número de pedido", "Tiempo", "Par", "Lado", "Precio", "Ejecutado",
        "Cantidad", "Tarifa", "Par de conversión de AOR", "Tasa de conversión de AOR"]
ORDERS = ["Tiempo", "Número de pedido", "Par", "Tipo¹", "Lado", "Precio de la orden",
          "Cantidad de la orden", "Tiempo", "Ejecutado²", "Precio medio",
          "Total de trading³", "Estado"]
CONVERT = ["Tiempo", "Billetera", "Par", "Tipo", "Vender", "Comprar",
           "Precio", "Precio inverso", "Fecha actualizada", "Estado"]
FIAT = ["Tiempo", "Método", "Cantidad a gastar", "Recibir cantidad",
        "Tarifa", "Precio", "Estado", "ID de transacción"]
FIAT_DEP = ["Tiempo", "Método", "Importe de depósito", "Recibir cantidad",
            "Tarifa", "Estado", "ID de transacción"]
FIAT_WD = ["Tiempo", "Método", "Importe de retiro", "Recibir cantidad",
           "Tarifa", "Estado", "ID de transacción"]
CRYPTO_DEP = ["Tiempo", "Moneda", "Red", "Cantidad", "Dirección", "TXID", "Estado"]
CRYPTO_WD = ["Tiempo", "Moneda", "Red", "Cantidad", "Tarifa", "Dirección", "TXID", "Estado"]
REC = ["Momento de creación", "Billetera", "Frecuencia", "Cada hora", "Importe de origen",
       "Moneda de origen", "Importe de destino", "Moneda de destino", "Precio",
       "Precio inverso", "Fecha de liquidación", "ID del plan", "Estado"]
FIAT_X = ["Método", "Cantidad", "Precio", "Cantidad final", "Hora de creación",
          "Estado", "ID de transacción"]
TX = ["ID de usuario", "Tiempo", "Cuenta", "Operación", "Moneda", "Cambio", "Observación"]

TIME = "2025-02-01 10:00:00"
NO_DATA = [["No hay datos que se ajusten a los criterios."]]


class _FakeUpload:
    def __init__(self, path):
        self._path = path
        self.filename = path.name

    def save(self, path):
        Path(path).write_bytes(self._path.read_bytes())


def _fake_archive(tmp_path, tag, columns, records):
    text = io.StringIO(newline="")
    writer = csv.writer(text)
    writer.writerow(columns)
    writer.writerows(records)
    target = tmp_path / f"Binance-{tag}-(UTC+1).zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{tag}-part1-of1.csv", text.getvalue().encode("utf-8-sig"))
    return _FakeUpload(target)


def test_bundle_12_zip_se_reconoce_completo_sin_duplicar_ordenes(tmp_path):
    """Prueba conjunta de upload, extracción, detección, parseo y conciliación."""
    bundles = [
        ("spot-fills", SPOT, [
            ["synthetic-1", TIME, "XRPEUR", "BUY", "2", "10XRP",
             "20EUR", "0.01BNB", "", ""],
        ]),
        ("spot-orders", ORDERS, [
            [TIME, "synthetic-1", "XRPEUR", "Market", "BUY", "0", "10XRP",
             TIME, "10XRP", "2", "20EUR", "FILLED"],
        ]),
        ("convert", CONVERT, [
            [TIME, "Spot", "USDC-EUR", "Instant", "10 EUR", "11 USDC",
             "", "", TIME, "Successful"],
            [TIME, "Spot", "XRP-USDC", "Instant", "5 USDC", "2 XRP",
             "", "", TIME, "Successful"],
        ]),
        ("recurring", REC, NO_DATA),
        ("fiat-buy", FIAT, [
            [TIME, "SEPA", "100 EUR", "110 USDC", "1 EUR",
             "0.9", "Successful", "fake-fiat-1"],
        ]),
        ("fiat-sell", FIAT, [
            [TIME, "Balance", "1 BNB", "50 EUR", "0 EUR",
             "50", "Successful", "fake-fiat-2"],
        ]),
        ("fiat-deposit", FIAT_DEP, [
            [TIME, "SEPA", "100 EUR", "99 EUR", "1 EUR", "Successful", "fake-dep-1"],
            [TIME, "SEPA", "10 EUR", "9 EUR", "1 EUR", "Failed", "fake-dep-2"],
        ]),
        ("fiat-withdraw", FIAT_WD, [
            [TIME, "SEPA", "50 EUR", "49 EUR", "1 EUR", "Successful", "fake-wd-1"],
        ]),
        ("fiat-exchange", FIAT_X, NO_DATA),
        ("crypto-deposit", CRYPTO_DEP, [
            [TIME, "XLM", "XLM", "9", "synthetic-address", "synthetic-tx-1", "Completed"],
        ]),
        ("crypto-withdraw", CRYPTO_WD, [
            [TIME, "XLM", "XLM", "2", "0.01", "synthetic-address", "synthetic-tx-2", "Completed"],
        ]),
        ("transaction", TX, NO_DATA),
    ]
    assert len(bundles) == 12
    uploads = [
        _fake_archive(tmp_path, tag, headers, rows)
        for tag, headers, rows in bundles
    ]
    csv_paths, names = save_binance_uploads(uploads)
    try:
        assert len(csv_paths) == 12
        c = ClasificadorBinanceMulti(csv_paths, names).clasificar()
        assert c.resumen_archivos["no_reconocidos"] == 0
        assert all(
            c.resumen_archivos[group]["detectado"]
            for group in ClasificadorBinanceMulti.SOURCE_KEYS
            if not group.startswith("earn_flexible_")
        )
        for group in ("recurring_convert", "fiat_exchange", "transaction_history"):
            assert c.resumen_archivos[group]["vacio"]
        assert c.resumen_archivos["spot_trades"]["registros"] == 1
        assert c.resumen_archivos["spot_orders"]["registros"] == 1
        assert c.resumen_archivos["fiat_trade"]["registros"] == 2
        assert c.resumen_archivos["fiat_deposit"]["registros"] == 2
        assert len(c.intercambios_nativos) == 5
        assert len(c.compraventas) == 4
        assert len(c.swaps) == 1
        assert len(c.valoraciones_pendientes) == 1
        assert len(c.movimientos) == 4
        assert {m.cantidad for m in c.movimientos if m.activo == "EUR"} == {99, -50}
        assert {f["activo"] for f in c.comisiones_pendientes} == {"BNB", "XLM"}
        assert c.fuentes_materiales_no_soportadas == []
    finally:
        for p in csv_paths:
            Path(p).unlink(missing_ok=True)
