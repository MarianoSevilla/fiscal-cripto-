"""
Tests para ClasificadorMEXC.

Cubre:
  · Detección de tipo de export (spot, withdrawal, futures, unknown)
  · Spot BUY — par EUR
  · Spot BUY — par USDT
  · Spot SELL — par EUR
  · Spot SELL — par USDT
  · Multi-fill: mismo order_id, distinto timestamp → lotes independientes
  · Withdrawal Completed
  · Withdrawal ignorado (Pending)
  · Fees MAKER (0) y TAKER (non-zero)
  · Pares USDT → advertencia suave generada
  · Futuros → ValueError descriptivo
  · Archivo vacío / sin datos → clasificador vacío sin crash
  · Precisión Decimal: price × quantity (no amount_usdt)
  · Timezone naive: el string de fecha se parsea correctamente
"""

import io
import os
import tempfile
import pytest
import openpyxl

from fiscal_app_export.clasificador_mexc import (
    ClasificadorMEXC,
    _detectar_tipo_mexc,
    _contar_filas_xlsx,
)


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _xlsx_tmpfile(sheet_name: str, headers: list, rows: list) -> str:
    """Crea un XLSX temporal y devuelve la ruta."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(path)
    return path


SPOT_HEADERS = [
    "UID", "order_id", "symbol", "create_time(UTC+01:00)", "side", "source",
    "currency", "quantity", "price", "amount_usdt", "fee_currency", "fee",
    "fee_usdt", "liquidity", "trade_type",
]

WITHDRAWAL_HEADERS = [
    "Date(UTC)", "Coin", "Network", "Amount", "TransactionFee",
    "Address", "TXID", "SourceAddress", "PaymentID", "Status",
]

FUTURES_HEADERS = [
    "UID", "copy_trader_uid", "copy_state", "futures", "used_margin",
    "leverage", "open_type", "vol(Cont)", "copy_amount(USDT)",
    "deal_avg_price", "close_avg_price", "Position Profit/Loss(USDT)",
    "fee", "create_time(UTC+01:00)", "close_time(UTC+01:00)",
]


# ── FIXTURES ──────────────────────────────────────────────────────────────────

@pytest.fixture
def spot_eur_buy():
    """ETH-EUR BUY, 1 fill, fee=0 (MAKER)."""
    rows = [[
        "15682261", "ORD001", "ETH-EUR", "2025-07-07 10:45:58", "BUY", "APP",
        "ETH", "0.04470000", "2195.680000000000000000000000000000",
        "115.213514852030484649",   # amount_usdt: distinto del EUR real
        "EUR", "0.000000000000000000", "0.000000000000000000", "MAKER", "SPOT",
    ]]
    path = _xlsx_tmpfile("Sheet1", SPOT_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def spot_usdt_buy():
    """TICS-USDT BUY, 1 fill, fee=0 (MAKER)."""
    rows = [[
        "15682261", "ORD002", "TICS-USDT", "2025-07-06 02:52:05", "BUY", "APP",
        "TICS", "11.09000000", "1.683800000000000000000000000000",
        "18.673342000000000000",
        "USDT", "0.000000000000000000", "0.000000000000000000", "MAKER", "SPOT",
    ]]
    path = _xlsx_tmpfile("Sheet1", SPOT_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def spot_eur_sell():
    """ETH-EUR SELL, 1 fill, fee TAKER."""
    rows = [[
        "15682261", "ORD003", "ETH-EUR", "2025-08-01 14:30:00", "SELL", "WEB",
        "ETH", "0.10000000", "2500.000000000000000000000000000000",
        "277.000000000000000000",
        "EUR", "0.250000000000000000", "0.293000000000000000", "TAKER", "SPOT",
    ]]
    path = _xlsx_tmpfile("Sheet1", SPOT_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def spot_usdt_sell():
    """BTC-USDT SELL, 1 fill."""
    rows = [[
        "12345678", "ORD004", "BTC-USDT", "2025-09-10 09:00:00", "SELL", "APP",
        "BTC", "0.00500000", "60000.000000000000000000000000000000",
        "300.000000000000000000",
        "USDT", "0.300000000000000000", "0.300000000000000000", "TAKER", "SPOT",
    ]]
    path = _xlsx_tmpfile("Sheet1", SPOT_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def spot_multi_fill():
    """TICS-USDT BUY — 3 fills del mismo order_id con timestamps distintos."""
    rows = [
        ["15682261", "ORD005", "TICS-USDT", "2025-07-06 00:15:54", "BUY", "APP",
         "TICS", "7.15000000", "1.683800000000000000000000000000",
         "12.039170000000000000", "USDT", "0.000000000000000000", "0.000000000000000000", "MAKER", "SPOT"],
        ["15682261", "ORD005", "TICS-USDT", "2025-07-06 02:13:47", "BUY", "APP",
         "TICS", "0.76000000", "1.683800000000000000000000000000",
         "1.279688000000000000", "USDT", "0.000000000000000000", "0.000000000000000000", "MAKER", "SPOT"],
        ["15682261", "ORD005", "TICS-USDT", "2025-07-06 02:52:05", "BUY", "APP",
         "TICS", "11.09000000", "1.683800000000000000000000000000",
         "18.673342000000000000", "USDT", "0.000000000000000000", "0.000000000000000000", "MAKER", "SPOT"],
    ]
    path = _xlsx_tmpfile("Sheet1", SPOT_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def withdrawal_completed():
    """3 retiros completados (BTC, SLP)."""
    rows = [
        ["2022-05-01 16:53:10", "BTC", "BTC", "0.07787", "0.0002",
         "39x2Z7MJqViRcFUcJ", "6c766dbfb32bec12d6", "", "", "Completed"],
        ["2022-04-18 14:19:58", "SLP", "RON", "18535", "1",
         "0x54424d7d8f7f1b24", "0x527c161e188ed2c6", "", "", "Completed"],
        ["2022-04-04 21:34:17", "BTC", "BTC", "0.01139754", "0.0005",
         "12mfgztYeouHvb7u", "752996f7e80dbf1a9", "", "", "Completed"],
    ]
    path = _xlsx_tmpfile("sheet1", WITHDRAWAL_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def withdrawal_mixed_status():
    """Un Completed + un Pending + un Failed → solo se registra el Completed."""
    rows = [
        ["2022-05-01 10:00:00", "BTC", "BTC", "0.05", "0.0002",
         "addr1", "txid1", "", "", "Completed"],
        ["2022-05-02 11:00:00", "ETH", "ETH", "1.0", "0.003",
         "addr2", "txid2", "", "", "Pending"],
        ["2022-05-03 12:00:00", "USDT", "TRC20", "200", "1",
         "addr3", "txid3", "", "", "Failed"],
    ]
    path = _xlsx_tmpfile("sheet1", WITHDRAWAL_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def futures_file():
    """Archivo de futuros copy trading — debe lanzar ValueError."""
    rows = []  # sin datos, solo cabecera
    path = _xlsx_tmpfile("Sheet1", FUTURES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def empty_spot():
    """Archivo con cabeceras spot pero sin filas de datos."""
    path = _xlsx_tmpfile("Sheet1", SPOT_HEADERS, [])
    yield path
    os.unlink(path)


@pytest.fixture
def spot_taker_fee():
    """TICS-USDT BUY TAKER con fee no nulo."""
    rows = [[
        "15682261", "ORD009", "TICS-USDT", "2025-07-05 23:18:29", "BUY", "APP",
        "TICS", "0.02000000", "1.684300000000000000000000000000",
        "0.033686000000000000",
        "USDT", "0.000016843000000000", "0.000016843000000000", "TAKER", "SPOT",
    ]]
    path = _xlsx_tmpfile("Sheet1", SPOT_HEADERS, rows)
    yield path
    os.unlink(path)


# ── TESTS: DETECCIÓN DE TIPO ──────────────────────────────────────────────────

class TestDeteccion:

    def test_spot_detectado(self, spot_eur_buy):
        assert _detectar_tipo_mexc(spot_eur_buy) == "spot"

    def test_withdrawal_detectado(self, withdrawal_completed):
        assert _detectar_tipo_mexc(withdrawal_completed) == "withdrawal"

    def test_futures_detectado(self, futures_file):
        assert _detectar_tipo_mexc(futures_file) == "futures"

    def test_unknown_detectado(self):
        headers = ["foo", "bar", "baz"]
        path = _xlsx_tmpfile("Sheet1", headers, [])
        try:
            assert _detectar_tipo_mexc(path) == "unknown"
        finally:
            os.unlink(path)


# ── TESTS: SPOT BUY EUR ───────────────────────────────────────────────────────

class TestSpotBuyEur:

    def setup_method(self, _):
        pass

    def test_compra_generada(self, spot_eur_buy):
        c = ClasificadorMEXC(spot_eur_buy).clasificar()
        assert len(c.compraventas) == 1
        op = c.compraventas[0]
        assert op.tipo == "COMPRA"
        assert op.activo == "ETH"
        assert op.contraparte == "EUR"

    def test_importe_correcto_no_amount_usdt(self, spot_eur_buy):
        """Importe debe ser price × quantity (98.15 EUR), no amount_usdt (115.21 USD)."""
        c = ClasificadorMEXC(spot_eur_buy).clasificar()
        op = c.compraventas[0]
        # 0.0447 × 2195.68 = 98.146896 EUR
        assert abs(op.importe - 98.146896) < 0.001

    def test_cantidad_correcta(self, spot_eur_buy):
        c = ClasificadorMEXC(spot_eur_buy).clasificar()
        op = c.compraventas[0]
        assert abs(op.cantidad - 0.0447) < 1e-7

    def test_fee_cero_maker(self, spot_eur_buy):
        c = ClasificadorMEXC(spot_eur_buy).clasificar()
        op = c.compraventas[0]
        assert op.fee_cantidad == 0.0
        assert op.fee_activo == "EUR"

    def test_fecha_parseada(self, spot_eur_buy):
        c = ClasificadorMEXC(spot_eur_buy).clasificar()
        op = c.compraventas[0]
        assert op.fecha == "2025-07-07 10:45:58"

    def test_sin_advertencias_usdt(self, spot_eur_buy):
        c = ClasificadorMEXC(spot_eur_buy).clasificar()
        usdt_warnings = [a for a in c.advertencias if "USDT" in a or "usdt" in a.lower()]
        assert not usdt_warnings, "No debe haber advertencias USDT para par EUR"

    def test_tipo_export(self, spot_eur_buy):
        c = ClasificadorMEXC(spot_eur_buy).clasificar()
        assert c.tipo_export == "spot"


# ── TESTS: SPOT BUY USDT ─────────────────────────────────────────────────────

class TestSpotBuyUsdt:

    def test_compra_generada(self, spot_usdt_buy):
        c = ClasificadorMEXC(spot_usdt_buy).clasificar()
        assert len(c.compraventas) == 1
        op = c.compraventas[0]
        assert op.tipo == "COMPRA"
        assert op.activo == "TICS"
        assert op.contraparte == "USDT"

    def test_importe_correcto(self, spot_usdt_buy):
        """Para par USDT: price × quantity = amount_usdt (son iguales)."""
        c = ClasificadorMEXC(spot_usdt_buy).clasificar()
        op = c.compraventas[0]
        # 11.09 × 1.6838 = 18.673342
        assert abs(op.importe - 18.673342) < 0.0001

    def test_advertencia_usdt_generada(self, spot_usdt_buy):
        """Debe haber exactamente una advertencia sobre USDT."""
        c = ClasificadorMEXC(spot_usdt_buy).clasificar()
        usdt_warnings = [a for a in c.advertencias if "USDT" in a]
        assert len(usdt_warnings) == 1

    def test_sin_errores(self, spot_usdt_buy):
        c = ClasificadorMEXC(spot_usdt_buy).clasificar()
        assert len(c.desconocidas) == 0


# ── TESTS: SPOT SELL EUR ─────────────────────────────────────────────────────

class TestSpotSellEur:

    def test_venta_generada(self, spot_eur_sell):
        c = ClasificadorMEXC(spot_eur_sell).clasificar()
        assert len(c.compraventas) == 1
        op = c.compraventas[0]
        assert op.tipo == "VENTA"
        assert op.activo == "ETH"
        assert op.contraparte == "EUR"

    def test_importe_venta(self, spot_eur_sell):
        """0.10 × 2500 = 250.0 EUR"""
        c = ClasificadorMEXC(spot_eur_sell).clasificar()
        op = c.compraventas[0]
        assert abs(op.importe - 250.0) < 0.0001

    def test_fee_taker(self, spot_eur_sell):
        c = ClasificadorMEXC(spot_eur_sell).clasificar()
        op = c.compraventas[0]
        assert op.fee_cantidad > 0
        assert op.fee_activo == "EUR"


# ── TESTS: SPOT SELL USDT ─────────────────────────────────────────────────────

class TestSpotSellUsdt:

    def test_venta_generada(self, spot_usdt_sell):
        c = ClasificadorMEXC(spot_usdt_sell).clasificar()
        assert len(c.compraventas) == 1
        op = c.compraventas[0]
        assert op.tipo == "VENTA"
        assert op.activo == "BTC"
        assert op.contraparte == "USDT"

    def test_importe_venta_usdt(self, spot_usdt_sell):
        """0.005 × 60000 = 300.0 USDT"""
        c = ClasificadorMEXC(spot_usdt_sell).clasificar()
        op = c.compraventas[0]
        assert abs(op.importe - 300.0) < 0.0001

    def test_advertencia_usdt(self, spot_usdt_sell):
        c = ClasificadorMEXC(spot_usdt_sell).clasificar()
        assert any("USDT" in a for a in c.advertencias)


# ── TESTS: MULTI-FILL ─────────────────────────────────────────────────────────

class TestMultiFill:

    def test_tres_operaciones_independientes(self, spot_multi_fill):
        """3 fills → 3 OperacionCompraventa distintas, NO agrupadas."""
        c = ClasificadorMEXC(spot_multi_fill).clasificar()
        assert len(c.compraventas) == 3

    def test_fechas_distintas(self, spot_multi_fill):
        """Cada fill tiene su propia fecha (distintos lotes FIFO)."""
        c = ClasificadorMEXC(spot_multi_fill).clasificar()
        fechas = [op.fecha for op in c.compraventas]
        assert len(set(fechas)) == 3, f"Se esperaban 3 fechas distintas, got: {fechas}"

    def test_cantidades_individuales(self, spot_multi_fill):
        """Las cantidades son las individuales de cada fill, no la suma."""
        c = ClasificadorMEXC(spot_multi_fill).clasificar()
        cantidades = sorted(op.cantidad for op in c.compraventas)
        esperadas  = sorted([7.15, 0.76, 11.09])
        for got, exp in zip(cantidades, esperadas):
            assert abs(got - exp) < 1e-6

    def test_mismo_activo(self, spot_multi_fill):
        c = ClasificadorMEXC(spot_multi_fill).clasificar()
        assert all(op.activo == "TICS" for op in c.compraventas)


# ── TESTS: FEES ───────────────────────────────────────────────────────────────

class TestFees:

    def test_maker_fee_cero(self, spot_eur_buy):
        c = ClasificadorMEXC(spot_eur_buy).clasificar()
        assert c.compraventas[0].fee_cantidad == 0.0

    def test_taker_fee_nonzero(self, spot_taker_fee):
        c = ClasificadorMEXC(spot_taker_fee).clasificar()
        op = c.compraventas[0]
        assert op.fee_cantidad > 0
        assert abs(op.fee_cantidad - 0.000016843) < 1e-10
        assert op.fee_activo == "USDT"


# ── TESTS: WITHDRAWALS ────────────────────────────────────────────────────────

class TestWithdrawals:

    def test_tres_movimientos_completados(self, withdrawal_completed):
        c = ClasificadorMEXC(withdrawal_completed).clasificar()
        assert len(c.movimientos) == 3

    def test_sin_compraventas(self, withdrawal_completed):
        """Un retiro NO genera compraventa ni resultado FIFO."""
        c = ClasificadorMEXC(withdrawal_completed).clasificar()
        assert len(c.compraventas) == 0

    def test_subtipo_withdrawal(self, withdrawal_completed):
        c = ClasificadorMEXC(withdrawal_completed).clasificar()
        assert all(op.subtipo == "Withdrawal" for op in c.movimientos)

    def test_activos_correctos(self, withdrawal_completed):
        c = ClasificadorMEXC(withdrawal_completed).clasificar()
        activos = {op.activo for op in c.movimientos}
        assert activos == {"BTC", "SLP"}

    def test_cantidades_correctas(self, withdrawal_completed):
        c = ClasificadorMEXC(withdrawal_completed).clasificar()
        btc_ops = [op for op in c.movimientos if op.activo == "BTC"]
        assert len(btc_ops) == 2
        btc_amounts = sorted(op.cantidad for op in btc_ops)
        assert abs(btc_amounts[0] - 0.01139754) < 1e-8
        assert abs(btc_amounts[1] - 0.07787) < 1e-8

    def test_solo_completed_registrado(self, withdrawal_mixed_status):
        c = ClasificadorMEXC(withdrawal_mixed_status).clasificar()
        assert len(c.movimientos) == 1
        assert c.movimientos[0].activo == "BTC"

    def test_tipo_export_withdrawal(self, withdrawal_completed):
        c = ClasificadorMEXC(withdrawal_completed).clasificar()
        assert c.tipo_export == "withdrawal"

    def test_observacion_incluye_red(self, withdrawal_completed):
        c = ClasificadorMEXC(withdrawal_completed).clasificar()
        # Al menos un movimiento debe tener la red en la observación
        assert any("BTC" in op.observacion or "RON" in op.observacion for op in c.movimientos)


# ── TESTS: FUTUROS ────────────────────────────────────────────────────────────

class TestFuturos:

    def test_futures_lanza_valueerror(self, futures_file):
        with pytest.raises(ValueError) as exc_info:
            ClasificadorMEXC(futures_file).clasificar()
        assert "futuros" in str(exc_info.value).lower()

    def test_mensaje_descriptivo(self, futures_file):
        with pytest.raises(ValueError) as exc_info:
            ClasificadorMEXC(futures_file).clasificar()
        msg = str(exc_info.value)
        assert len(msg) > 30, "El mensaje debe ser descriptivo para el usuario"


# ── TESTS: ARCHIVO VACÍO ─────────────────────────────────────────────────────

class TestArchivoVacio:

    def test_sin_datos_no_crash(self, empty_spot):
        c = ClasificadorMEXC(empty_spot).clasificar()
        assert len(c.compraventas) == 0
        assert len(c.movimientos) == 0
        assert len(c.desconocidas) == 0


# ── TESTS: PRECISIÓN DECIMAL ─────────────────────────────────────────────────

class TestDecimalPrecision:

    def test_price_30_decimales(self):
        """price con 30 decimales decimales se parsea sin pérdida de precisión."""
        headers = SPOT_HEADERS
        rows = [[
            "99999999", "ORD_DEC", "ETH-EUR", "2025-01-01 12:00:00", "BUY", "APP",
            "ETH", "1.00000000",
            "2195.680000000000000000000000000000",  # 30 decimales
            "2577.000000000000000000",
            "EUR", "0.000000000000000000", "0.000000000000000000", "MAKER", "SPOT",
        ]]
        path = _xlsx_tmpfile("Sheet1", headers, rows)
        try:
            c = ClasificadorMEXC(path).clasificar()
            op = c.compraventas[0]
            # 1.0 × 2195.68 = 2195.68 exacto
            assert abs(op.importe - 2195.68) < 0.001
        finally:
            os.unlink(path)

    def test_amount_usdt_no_usado(self):
        """
        ETH-EUR: amount_usdt=999.99 (valor falso inventado).
        El importe debe ser price × quantity, nunca amount_usdt.
        """
        headers = SPOT_HEADERS
        rows = [[
            "99999999", "ORD_NODIFF", "ETH-EUR", "2025-01-01 12:00:00", "BUY", "APP",
            "ETH", "1.00000000", "2000.000000000000000000",
            "999.99",    # valor falso — NO debe usarse
            "EUR", "0.000000000000000000", "0.000000000000000000", "MAKER", "SPOT",
        ]]
        path = _xlsx_tmpfile("Sheet1", headers, rows)
        try:
            c = ClasificadorMEXC(path).clasificar()
            op = c.compraventas[0]
            assert abs(op.importe - 2000.0) < 0.001
            assert abs(op.importe - 999.99) > 100, "No debe usar amount_usdt"
        finally:
            os.unlink(path)


# ── TESTS: TIMEZONE / FECHA ───────────────────────────────────────────────────

class TestFecha:

    def test_formato_ymd_hms(self, spot_eur_buy):
        """Fecha en formato 'YYYY-MM-DD HH:MM:SS' se parsea correctamente."""
        c = ClasificadorMEXC(spot_eur_buy).clasificar()
        assert c.compraventas[0].fecha == "2025-07-07 10:45:58"

    def test_año_correcto(self, spot_usdt_buy):
        c = ClasificadorMEXC(spot_usdt_buy).clasificar()
        assert c.compraventas[0].fecha.startswith("2025")

    def test_fecha_withdrawal_utc(self, withdrawal_completed):
        """Withdrawal usa Date(UTC) — se parsea igual que spot."""
        c = ClasificadorMEXC(withdrawal_completed).clasificar()
        fechas = [op.fecha for op in c.movimientos]
        # Todas deben ser 2022
        assert all(f.startswith("2022") for f in fechas)


# ── TESTS: CONTEO DE FILAS ────────────────────────────────────────────────────

class TestConteoFilas:

    def test_contar_filas_spot(self, spot_multi_fill):
        assert _contar_filas_xlsx(spot_multi_fill) == 3

    def test_contar_filas_vacias(self, empty_spot):
        assert _contar_filas_xlsx(empty_spot) == 0

    def test_contar_filas_withdrawal(self, withdrawal_completed):
        assert _contar_filas_xlsx(withdrawal_completed) == 3


# ── TESTS: ARCHIVOS REALES MEXC ──────────────────────────────────────────────

class TestArchivosReales:
    """Ejecuta el clasificador sobre los XLS/XLSX reales de usuario si existen."""

    MEXC_SPOT_PATH       = os.path.expanduser("~/Downloads/mexc-02.xlsx")
    MEXC_FUTURES_PATH    = os.path.expanduser("~/Downloads/mexc-01.xlsx")
    MEXC_WITHDRAWAL_PATH = os.path.expanduser("~/Downloads/withdrawal_history.xlsx")

    @pytest.mark.skipif(
        not os.path.exists(os.path.expanduser("~/Downloads/mexc-02.xlsx")),
        reason="Archivo real mexc-02.xlsx no disponible",
    )
    def test_spot_real_no_crash(self):
        c = ClasificadorMEXC(self.MEXC_SPOT_PATH).clasificar()
        assert len(c.compraventas) > 0
        assert len(c.desconocidas) == 0

    @pytest.mark.skipif(
        not os.path.exists(os.path.expanduser("~/Downloads/mexc-02.xlsx")),
        reason="Archivo real mexc-02.xlsx no disponible",
    )
    def test_spot_real_importe_no_amount_usdt(self):
        """Para ETH-EUR: importe < 120 (EUR), no ~115 USD del amount_usdt."""
        c = ClasificadorMEXC(self.MEXC_SPOT_PATH).clasificar()
        eth_eur = [op for op in c.compraventas if op.activo == "ETH" and op.contraparte == "EUR"]
        if eth_eur:
            op = eth_eur[0]
            # El importe correcto en EUR (98.15) es muy distinto de amount_usdt (115.21 USD)
            assert op.importe < 110, (
                f"Importe {op.importe} parece amount_usdt (USD) en lugar de price×qty (EUR)"
            )

    @pytest.mark.skipif(
        not os.path.exists(os.path.expanduser("~/Downloads/mexc-01.xlsx")),
        reason="Archivo real mexc-01.xlsx no disponible",
    )
    def test_futures_real_lanza_error(self):
        with pytest.raises(ValueError) as exc:
            ClasificadorMEXC(self.MEXC_FUTURES_PATH).clasificar()
        assert "futuros" in str(exc.value).lower()

    @pytest.mark.skipif(
        not os.path.exists(os.path.expanduser("~/Downloads/withdrawal_history.xlsx")),
        reason="Archivo real withdrawal_history.xlsx no disponible",
    )
    def test_withdrawal_real_no_crash(self):
        c = ClasificadorMEXC(self.MEXC_WITHDRAWAL_PATH).clasificar()
        assert len(c.movimientos) > 0
        assert len(c.compraventas) == 0
