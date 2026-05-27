"""
Tests para ClasificadorBitget.

Cubre:
  1.  Detecta detalles de órdenes.
  2.  Detecta transacciones.
  3.  Detecta historial de órdenes.
  4.  Buy spot parsea correctamente.
  5.  Sell spot parsea correctamente.
  6.  Multi-fill se mantiene separado (operaciones FIFO independientes).
  7.  Fee Buy en base asset — campo fee_activo y fee_cantidad correctos.
  8.  Fee Sell en USDT — campo fee_activo y fee_cantidad correctos.
  9.  Depósitos se clasifican como OperacionMovimiento subtipo Deposit.
  10. Retiros se clasifican como OperacionMovimiento subtipo Withdrawal.
  11. Transfer out se clasifica como OperacionMovimiento subtipo Transfer.
  12. Historial de órdenes devuelve ValueError descriptivo.
  13. Pipeline FIFO completo genera resultados sin crash.
  14. No rompe clasificadores de otros exchanges (importar en paralelo OK).
  15. BOM UTF-8-SIG no rompe la lectura.
  16. Columna None (trailing comma) ignorada silenciosamente.
  17. TAB prefijado en IDs de orden no rompe la lectura.
  18. Advertencia USDT generada para pares X/USDT.
  19. Tipo desconocido en TRANSACCIONES → OperacionDesconocida.
"""

import csv
import io
import os
import tempfile
import pytest

from fiscal_app_export.clasificador_bitget import (
    ClasificadorBitget,
    detect_bitget_file_type,
    _leer_csv,
)

# ── RUTAS A CSV REALES ────────────────────────────────────────────────────────

_DETALLES_REAL     = os.path.expanduser(
    "~/Downloads/Exportar_detalles_de_órdenes_en_spot_6758568031_2026_04_29_23_01.csv"
)
_TRANSACCIONES_REAL = os.path.expanduser(
    "~/Downloads/Exportar_transacciones_en_spot_6758568031_2026_04_29_23_01_27_428.csv"
)
_HISTORIAL_REAL    = os.path.expanduser(
    "~/Downloads/Exportar_historial_de_órdenes_en_spot_6758568031_2026_04_29_23_01.csv"
)

_REAL_DISPONIBLE = (
    os.path.exists(_DETALLES_REAL)
    and os.path.exists(_TRANSACCIONES_REAL)
    and os.path.exists(_HISTORIAL_REAL)
)


# ── HELPERS: CREAR CSV TEMPORALES ─────────────────────────────────────────────

def _csv_tmp(headers: list, rows: list, bom: bool = True) -> str:
    """Crea un CSV temporal UTF-8-SIG (con BOM por defecto) y devuelve la ruta."""
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    encoding = "utf-8-sig" if bom else "utf-8"
    with open(path, "w", encoding=encoding, newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


DETALLES_HEADERS = [
    "Date", "Trading pair", "Base Asset", "Quote Asset",
    "Direction", "Price", "Amount", "Total", "Fee", "Fee Coin", "",
]
TRANSACCIONES_HEADERS = [
    "order", "Date", "Coin", "Type", "Amount", "Fee", "Available",
]
HISTORIAL_HEADERS = [
    "Date", "Type", "Order Id", "Trading pair", "Base Asset", "Quote Asset",
    "Direction", "Price", "Order amount", "Executed", "Average Price",
    "Trading volume", "Status",
]


# ── FIXTURES ──────────────────────────────────────────────────────────────────

@pytest.fixture
def detalles_xrp_buy():
    """Una compra de XRP/USDT con fee en base asset."""
    rows = [
        ["2025-12-01 17:34:15", "XRP/USDT", "XRP", "USDT",
         "Buy", "2", "334.1339", "668.2678", "0.3341339", "XRP", ""],
    ]
    path = _csv_tmp(DETALLES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def detalles_xrp_sell():
    """Una venta de XRP/USDT con fee en USDT."""
    rows = [
        ["2025-07-03 15:53:59", "XRP/USDT", "XRP", "USDT",
         "Sell", "2.3", "500", "1150", "1.15", "USDT", ""],
    ]
    path = _csv_tmp(DETALLES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def detalles_multi_fill():
    """Multi-fill: 3 compras XRP en el mismo timestamp (misma orden)."""
    rows = [
        ["2025-06-17 22:15:27", "XRP/USDT", "XRP", "USDT",
         "Buy", "2.18", "133.4718", "290.968524", "0.1334718", "XRP", ""],
        ["2025-06-17 22:15:27", "XRP/USDT", "XRP", "USDT",
         "Buy", "2.18", "18.7671",  "40.912278",  "0.0187671", "XRP", ""],
        ["2025-06-17 22:15:27", "XRP/USDT", "XRP", "USDT",
         "Buy", "2.18", "21.7611",  "47.439198",  "0.0217611", "XRP", ""],
    ]
    path = _csv_tmp(DETALLES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def detalles_pi_sell():
    """6 fills de venta PI/USDT con fee en USDT."""
    rows = [
        ["2025-03-15 20:14:47", "PI/USDT", "PI", "USDT",
         "Sell", "1.4447", "158.92", "229.591724", "0.229591724", "USDT", ""],
        ["2025-03-15 20:14:47", "PI/USDT", "PI", "USDT",
         "Sell", "1.4447", "301.67", "435.822649", "0.435822649", "USDT", ""],
        ["2025-03-15 20:14:47", "PI/USDT", "PI", "USDT",
         "Sell", "1.4448", "245.9",  "355.27632",  "0.35527632",  "USDT", ""],
        ["2025-03-15 20:14:47", "PI/USDT", "PI", "USDT",
         "Sell", "1.4448", "1.22",   "1.762656",   "0.001762656", "USDT", ""],
        ["2025-03-15 20:14:47", "PI/USDT", "PI", "USDT",
         "Sell", "1.4448", "6.23",   "9.001104",   "0.009001104", "USDT", ""],
        ["2025-03-15 20:14:47", "PI/USDT", "PI", "USDT",
         "Sell", "1.4449", "204.06", "294.846294", "0.294846294", "USDT", ""],
    ]
    path = _csv_tmp(DETALLES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_mixto():
    """CSV de transacciones con Deposit, Withdrawal, Transfer out y Buy/Sell."""
    rows = [
        ["\t1379378002405007360", "2025-12-01 15:21:04", "USDT",
         "Deposit", "668.2677", "0", "668.267840915"],
        ["\t1374435316954734592", "2025-11-18 00:00:36", "POL",
         "Ordinary Withdrawal", "-67.852", "-0.08", "0"],
        ["\t1286240547709112339", "2025-03-19 15:06:04", "USDT",
         "Transfer out", "-150", "0", "121.187446253"],
        ["\t1379411522364022790", "2025-12-01 17:34:15", "USDT",
         "Sell", "-668.2678", "0", "0.000040915"],
        ["\t1379411522364022788", "2025-12-01 17:34:15", "XRP",
         "Buy", "334.1339", "-0.3341339", "778.9146264"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def historial_simple():
    """CSV de historial de órdenes (debe lanzar ValueError)."""
    rows = [
        ["2025-12-01 15:21:57", "GTC", "\t1379378226485698563", "XRP/USDT",
         "XRP", "USDT", "Buy", "2", "334.1339", "334.1339", "2",
         "668.2678", "fully executed"],
    ]
    path = _csv_tmp(HISTORIAL_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def detalles_tipo_desconocido():
    """Fila con Direction no reconocida → OperacionDesconocida."""
    rows = [
        ["2025-06-01 10:00:00", "XRP/USDT", "XRP", "USDT",
         "Convert", "2.0", "100", "200", "0.1", "XRP", ""],
    ]
    path = _csv_tmp(DETALLES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_tipo_desconocido():
    """Tipo no reconocido en transacciones → OperacionDesconocida."""
    rows = [
        ["\t123", "2025-06-01 10:00:00", "USDT",
         "UnknownType", "100", "0", "100"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


# ── TESTS: DETECCIÓN DE TIPO ──────────────────────────────────────────────────

class TestDeteccion:

    def test_detalles_detectado(self, detalles_xrp_buy):
        assert detect_bitget_file_type(detalles_xrp_buy) == "detalles"

    def test_transacciones_detectado(self, transacciones_mixto):
        assert detect_bitget_file_type(transacciones_mixto) == "transacciones"

    def test_historial_detectado(self, historial_simple):
        assert detect_bitget_file_type(historial_simple) == "historial"

    def test_tipo_export_detalles(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert c.tipo_export == "detalles"

    def test_tipo_export_transacciones(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        assert c.tipo_export == "transacciones"

    def test_unknown_detectado(self):
        path = _csv_tmp(["foo", "bar"], [["a", "b"]])
        try:
            assert detect_bitget_file_type(path) == "unknown"
        finally:
            os.unlink(path)


# ── TESTS: BUY SPOT ───────────────────────────────────────────────────────────

class TestBuySpot:

    def test_compra_generada(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert len(c.compraventas) == 1
        op = c.compraventas[0]
        assert op.tipo == "COMPRA"

    def test_activo_xrp(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert c.compraventas[0].activo == "XRP"

    def test_contraparte_usdt(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert c.compraventas[0].contraparte == "USDT"

    def test_cantidad_bruta(self, detalles_xrp_buy):
        """cantidad = Amount del CSV (bruto, antes de fee)."""
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert abs(c.compraventas[0].cantidad - 334.1339) < 1e-6

    def test_importe_total(self, detalles_xrp_buy):
        """importe = Total del CSV (coste en USDT)."""
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert abs(c.compraventas[0].importe - 668.2678) < 1e-6

    def test_fecha_parseada(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert c.compraventas[0].fecha == "2025-12-01 17:34:15"

    def test_sin_desconocidas(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert len(c.desconocidas) == 0


# ── TESTS: FEE EN BASE ASSET (Buy) ────────────────────────────────────────────

class TestFeeBuyBaseAsset:

    def test_fee_activo_base_asset(self, detalles_xrp_buy):
        """Fee Coin = XRP (base asset) en compra."""
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert c.compraventas[0].fee_activo == "XRP"

    def test_fee_cantidad_correcta(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert abs(c.compraventas[0].fee_cantidad - 0.3341339) < 1e-8

    def test_fee_nonzero(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert c.compraventas[0].fee_cantidad > 0


# ── TESTS: SELL SPOT ──────────────────────────────────────────────────────────

class TestSellSpot:

    def test_venta_generada(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert len(c.compraventas) == 1
        op = c.compraventas[0]
        assert op.tipo == "VENTA"

    def test_activo_xrp(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert c.compraventas[0].activo == "XRP"

    def test_cantidad_vendida(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert abs(c.compraventas[0].cantidad - 500.0) < 1e-6

    def test_importe_total_usdt(self, detalles_xrp_sell):
        """importe = Total del CSV (1150 USDT bruto antes de fee)."""
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert abs(c.compraventas[0].importe - 1150.0) < 1e-6


# ── TESTS: FEE EN USDT (Sell) ─────────────────────────────────────────────────

class TestFeeSellUsdt:

    def test_fee_activo_usdt(self, detalles_xrp_sell):
        """Fee Coin = USDT en venta."""
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert c.compraventas[0].fee_activo == "USDT"

    def test_fee_cantidad_correcta(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert abs(c.compraventas[0].fee_cantidad - 1.15) < 1e-8


# ── TESTS: MULTI-FILL ─────────────────────────────────────────────────────────

class TestMultiFill:

    def test_tres_fills_independientes(self, detalles_multi_fill):
        """3 fills del mismo timestamp y par → 3 OperacionCompraventa distintas."""
        c = ClasificadorBitget(detalles_multi_fill).clasificar()
        assert len(c.compraventas) == 3

    def test_cantidades_individuales(self, detalles_multi_fill):
        """Cada fill tiene su propia cantidad, NO la suma."""
        c = ClasificadorBitget(detalles_multi_fill).clasificar()
        cantidades = sorted(op.cantidad for op in c.compraventas)
        esperadas  = sorted([133.4718, 18.7671, 21.7611])
        for got, exp in zip(cantidades, esperadas):
            assert abs(got - exp) < 1e-4

    def test_mismo_activo(self, detalles_multi_fill):
        c = ClasificadorBitget(detalles_multi_fill).clasificar()
        assert all(op.activo == "XRP" for op in c.compraventas)

    def test_pi_seis_fills(self, detalles_pi_sell):
        """6 fills de venta PI → 6 OperacionCompraventa."""
        c = ClasificadorBitget(detalles_pi_sell).clasificar()
        assert len(c.compraventas) == 6

    def test_pi_total_cantidad(self, detalles_pi_sell):
        c = ClasificadorBitget(detalles_pi_sell).clasificar()
        total_pi = sum(op.cantidad for op in c.compraventas)
        assert abs(total_pi - 918.0) < 1e-4


# ── TESTS: TRANSACCIONES — DEPÓSITOS ─────────────────────────────────────────

class TestDepositos:

    def test_deposito_clasificado(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        deposits = [m for m in c.movimientos if m.subtipo == "Deposit"]
        assert len(deposits) == 1

    def test_deposito_subtipo(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        dep = [m for m in c.movimientos if m.subtipo == "Deposit"][0]
        assert dep.subtipo == "Deposit"

    def test_deposito_activo(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        dep = [m for m in c.movimientos if m.subtipo == "Deposit"][0]
        assert dep.activo == "USDT"

    def test_deposito_cantidad_positiva(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        dep = [m for m in c.movimientos if m.subtipo == "Deposit"][0]
        assert dep.cantidad > 0

    def test_deposito_no_genera_compraventa(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        assert len(c.compraventas) == 0


# ── TESTS: TRANSACCIONES — RETIROS ────────────────────────────────────────────

class TestRetiros:

    def test_retiro_clasificado(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        withdrawals = [m for m in c.movimientos if m.subtipo == "Withdrawal"]
        assert len(withdrawals) == 1

    def test_retiro_activo(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        w = [m for m in c.movimientos if m.subtipo == "Withdrawal"][0]
        assert w.activo == "POL"

    def test_retiro_cantidad_positiva(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        w = [m for m in c.movimientos if m.subtipo == "Withdrawal"][0]
        assert abs(w.cantidad - 67.852) < 1e-6

    def test_retiro_incluye_fee_en_observacion(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        w = [m for m in c.movimientos if m.subtipo == "Withdrawal"][0]
        assert "Fee" in w.observacion


# ── TESTS: TRANSACCIONES — TRANSFER OUT ───────────────────────────────────────

class TestTransferOut:

    def test_transfer_clasificado(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        transfers = [m for m in c.movimientos if m.subtipo == "Transfer"]
        assert len(transfers) == 1

    def test_transfer_activo_usdt(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        t = [m for m in c.movimientos if m.subtipo == "Transfer"][0]
        assert t.activo == "USDT"

    def test_transfer_cantidad_positiva(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        t = [m for m in c.movimientos if m.subtipo == "Transfer"][0]
        assert abs(t.cantidad - 150.0) < 1e-6


# ── TESTS: HISTORIAL → ERROR DESCRIPTIVO ─────────────────────────────────────

class TestHistorialOrdenesError:

    def test_historial_lanza_valueerror(self, historial_simple):
        with pytest.raises(ValueError) as exc_info:
            ClasificadorBitget(historial_simple).clasificar()
        assert "historial" in str(exc_info.value).lower() or "detalles" in str(exc_info.value).lower()

    def test_mensaje_descriptivo(self, historial_simple):
        with pytest.raises(ValueError) as exc_info:
            ClasificadorBitget(historial_simple).clasificar()
        msg = str(exc_info.value)
        assert len(msg) > 50, "El mensaje debe ser descriptivo para el usuario"

    def test_mensaje_indica_detalles(self, historial_simple):
        with pytest.raises(ValueError) as exc_info:
            ClasificadorBitget(historial_simple).clasificar()
        assert "detalles" in str(exc_info.value).lower()


# ── TESTS: ADVERTENCIA USDT ───────────────────────────────────────────────────

class TestAdvertenciaUsdt:

    def test_advertencia_usdt_buy(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        usdt_warns = [a for a in c.advertencias if "USDT" in a]
        assert len(usdt_warns) == 1

    def test_advertencia_usdt_sell(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert any("USDT" in a for a in c.advertencias)

    def test_advertencia_solo_una(self, detalles_multi_fill):
        """Aunque haya 3 fills en USDT, solo 1 advertencia USDT al final."""
        c = ClasificadorBitget(detalles_multi_fill).clasificar()
        usdt_warns = [a for a in c.advertencias if "USDT" in a]
        assert len(usdt_warns) == 1


# ── TESTS: TIPO DESCONOCIDO ───────────────────────────────────────────────────

class TestTipoDesconocido:

    def test_direction_desconocida(self, detalles_tipo_desconocido):
        c = ClasificadorBitget(detalles_tipo_desconocido).clasificar()
        assert len(c.desconocidas) == 1
        assert "direction" in c.desconocidas[0].subtipo.lower() or "Convert" in c.desconocidas[0].subtipo

    def test_tipo_tx_desconocido(self, transacciones_tipo_desconocido):
        c = ClasificadorBitget(transacciones_tipo_desconocido).clasificar()
        assert len(c.desconocidas) == 1

    def test_tipo_tx_desconocido_advertencia(self, transacciones_tipo_desconocido):
        c = ClasificadorBitget(transacciones_tipo_desconocido).clasificar()
        assert any("no reconocida" in a for a in c.advertencias)


# ── TESTS: PIPELINE FIFO COMPLETO ────────────────────────────────────────────

class TestPipelineFiloCompleto:

    def test_pipeline_buy_sell_sin_crash(self):
        """Compra + venta → motor FIFO genera resultado sin error."""
        from fiscal_app_export.motor_fifo import MotorFIFO

        rows_buy = [
            ["2025-03-01 10:00:00", "XRP/USDT", "XRP", "USDT",
             "Buy", "2.0", "100", "200", "0.1", "XRP", ""],
        ]
        rows_sell = [
            ["2025-07-01 10:00:00", "XRP/USDT", "XRP", "USDT",
             "Sell", "2.5", "80", "200", "0.2", "USDT", ""],
        ]
        # Compra
        path_buy = _csv_tmp(DETALLES_HEADERS, rows_buy)
        c_buy = ClasificadorBitget(path_buy).clasificar()
        os.unlink(path_buy)

        # Venta (creamos clasificador separado y fusionamos)
        path_sell = _csv_tmp(DETALLES_HEADERS, rows_sell)
        c_sell = ClasificadorBitget(path_sell).clasificar()
        os.unlink(path_sell)

        # Fusionar en un clasificador temporal y pasar al motor
        motor = MotorFIFO()
        ops = []
        for op in c_buy.compraventas + c_sell.compraventas:
            ops.append(op)
        ops.sort(key=lambda x: x.fecha)
        for op in ops:
            if op.tipo == "COMPRA":
                motor.registrar_compra(
                    fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                    importe=op.importe, contraparte=op.contraparte,
                    fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad,
                )
            else:
                motor.registrar_venta(
                    fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                    importe=op.importe, contraparte=op.contraparte,
                    fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad,
                )

        assert len(motor.resultados) == 1
        r = motor.resultados[0]
        assert r.activo == "XRP"
        assert r.ganancia_perdida != 0

    def test_pipeline_inventario_insuficiente_pi(self, detalles_pi_sell):
        """
        Venta de PI sin compras previas → inventario insuficiente detectado.
        El motor NO debe bloquearse: debe generar resultado con advertencia.
        """
        from fiscal_app_export.motor_fifo import MotorFIFO

        c = ClasificadorBitget(detalles_pi_sell).clasificar()
        motor = MotorFIFO()
        for op in sorted(c.compraventas, key=lambda x: x.fecha):
            motor.registrar_venta(
                fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                importe=op.importe, contraparte=op.contraparte,
                fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad,
            )

        # Debe haber resultados o advertencias de inventario insuficiente
        assert len(motor.resultados) > 0 or len(motor.advertencias) > 0
        # Si hay resultados, al menos uno debe marcar inventario_incompleto o
        # debe haber advertencias en el motor
        tiene_aviso = (
            any(r.inventario_incompleto for r in motor.resultados)
            or len(motor.advertencias) > 0
        )
        assert tiene_aviso, "Debe advertir sobre inventario insuficiente para PI"


# ── TESTS: NO ROMPE OTROS CLASIFICADORES ─────────────────────────────────────

class TestNoRompeOtrosExchanges:

    def test_import_binance_ok(self):
        from fiscal_app_export.clasificador import ClasificadorBinance  # noqa: F401

    def test_import_mexc_ok(self):
        from fiscal_app_export.clasificador_mexc import ClasificadorMEXC  # noqa: F401

    def test_import_nexo_ok(self):
        from fiscal_app_export.clasificador_nexo import ClasificadorNexo  # noqa: F401

    def test_import_kraken_ok(self):
        from fiscal_app_export.clasificador_kraken import ClasificadorKraken  # noqa: F401

    def test_import_bitvavo_ok(self):
        from fiscal_app_export.clasificador_bitvavo import ClasificadorBitvavo  # noqa: F401

    def test_import_coinbase_ok(self):
        from fiscal_app_export.clasificador_coinbase import ClasificadorCoinbase  # noqa: F401

    def test_import_uphold_ok(self):
        from fiscal_app_export.clasificador_uphold import ClasificadorUphold  # noqa: F401


# ── TESTS: BOM Y TRAILING COMMA ───────────────────────────────────────────────

class TestBomYTrailingComma:

    def test_bom_utf8_sig_ok(self, detalles_xrp_buy):
        """El archivo con BOM (UTF-8-SIG) se lee correctamente."""
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert len(c.compraventas) == 1

    def test_trailing_comma_no_crash(self, detalles_xrp_buy):
        """La columna vacía por trailing comma no genera crash ni desconocidas."""
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert len(c.desconocidas) == 0

    def test_tab_en_order_id_ignorado(self, transacciones_mixto):
        """Los IDs con TAB prefijado en TRANSACCIONES no generan crash."""
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        assert c.tipo_export == "transacciones"


# ── TESTS CON ARCHIVOS REALES ─────────────────────────────────────────────────

@pytest.mark.skipif(not _REAL_DISPONIBLE, reason="Archivos CSV reales de Bitget no disponibles en ~/Downloads/")
class TestArchivosReales:

    def test_detalles_real_no_crash(self):
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        assert c.tipo_export == "detalles"
        assert len(c.compraventas) > 0

    def test_detalles_real_33_fills(self):
        """El archivo real tiene 33 fills (confirmado en auditoría)."""
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        assert len(c.compraventas) == 33

    def test_detalles_real_sin_desconocidas(self):
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        assert len(c.desconocidas) == 0

    def test_detalles_real_advertencia_usdt(self):
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        assert any("USDT" in a for a in c.advertencias)

    def test_detalles_real_compras_y_ventas(self):
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        tipos = {op.tipo for op in c.compraventas}
        assert "COMPRA" in tipos
        assert "VENTA" in tipos

    def test_transacciones_real_no_crash(self):
        c = ClasificadorBitget(_TRANSACCIONES_REAL).clasificar()
        assert c.tipo_export == "transacciones"

    def test_transacciones_real_11_depositos(self):
        """El archivo real tiene 11 depósitos (confirmado en auditoría)."""
        c = ClasificadorBitget(_TRANSACCIONES_REAL).clasificar()
        deposits = [m for m in c.movimientos if m.subtipo == "Deposit"]
        assert len(deposits) == 11

    def test_transacciones_real_3_retiros(self):
        """El archivo real tiene 3 retiros (confirmado en auditoría)."""
        c = ClasificadorBitget(_TRANSACCIONES_REAL).clasificar()
        withdrawals = [m for m in c.movimientos if m.subtipo == "Withdrawal"]
        assert len(withdrawals) == 3

    def test_transacciones_real_1_transfer(self):
        """El archivo real tiene 1 Transfer out (confirmado en auditoría)."""
        c = ClasificadorBitget(_TRANSACCIONES_REAL).clasificar()
        transfers = [m for m in c.movimientos if m.subtipo == "Transfer"]
        assert len(transfers) == 1

    def test_historial_real_error_descriptivo(self):
        with pytest.raises(ValueError) as exc_info:
            ClasificadorBitget(_HISTORIAL_REAL).clasificar()
        assert "detalles" in str(exc_info.value).lower()

    def test_detalles_real_multifill_xrp(self):
        """El archivo real tiene 3 fills XRP en 2025-06-17 22:15:27."""
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        xrp_17jun = [
            op for op in c.compraventas
            if op.activo == "XRP" and op.fecha.startswith("2025-06-17 22:15:27")
        ]
        assert len(xrp_17jun) == 3

    def test_detalles_real_multifill_pi(self):
        """El archivo real tiene 6 fills PI en 2025-03-15 20:14:47."""
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        pi_15mar = [
            op for op in c.compraventas
            if op.activo == "PI" and op.fecha.startswith("2025-03-15 20:14:47")
        ]
        assert len(pi_15mar) == 6

    def test_detalles_real_fee_buy_base_asset(self):
        """En compras, fee_activo es el base asset (XRP)."""
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        xrp_buys = [op for op in c.compraventas if op.tipo == "COMPRA" and op.activo == "XRP"]
        assert len(xrp_buys) > 0
        assert all(op.fee_activo == "XRP" for op in xrp_buys)

    def test_detalles_real_fee_sell_usdt(self):
        """En ventas X/USDT, fee_activo es USDT."""
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        xrp_sells = [op for op in c.compraventas if op.tipo == "VENTA" and op.activo == "XRP"]
        assert len(xrp_sells) > 0
        assert all(op.fee_activo == "USDT" for op in xrp_sells)

    def test_detalles_real_fechas_utc(self):
        """Todas las fechas están en formato YYYY-MM-DD HH:MM:SS."""
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        import re
        for op in c.compraventas:
            assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", op.fecha), \
                f"Fecha inesperada: {op.fecha}"

    def test_pipeline_real_detalles_fifo(self):
        """Pipeline completo sobre el CSV real de detalles no crash."""
        from fiscal_app_export.motor_fifo import MotorFIFO

        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        motor = MotorFIFO()
        ops = sorted(c.compraventas, key=lambda x: x.fecha)
        for op in ops:
            if op.tipo == "COMPRA":
                motor.registrar_compra(
                    fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                    importe=op.importe, contraparte=op.contraparte,
                    fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad,
                )
            else:
                motor.registrar_venta(
                    fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                    importe=op.importe, contraparte=op.contraparte,
                    fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad,
                )

        # Debe haber resultados de ventas
        assert len(motor.resultados) > 0
        # Todos los resultados tienen activo conocido
        assert all(r.activo for r in motor.resultados)
