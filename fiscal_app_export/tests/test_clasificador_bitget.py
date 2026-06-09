"""
Tests para ClasificadorBitget.

Cubre:
  DETECCIÓN
  1.  Detecta detalles de órdenes.
  2.  Detecta transacciones.
  3.  Detecta historial de órdenes.

  DETALLES — Buy/Sell/Fee/Multi-fill
  4.  Buy spot parsea correctamente.
  5.  Sell spot parsea correctamente.
  6.  Multi-fill se mantiene separado (operaciones FIFO independientes).
  7.  Fee Buy en base asset — campo fee_activo y fee_cantidad correctos.
  8.  Fee Sell en USDT — campo fee_activo y fee_cantidad correctos.

  TRANSACCIONES — Movimientos
  9.  Depósitos se clasifican como OperacionMovimiento subtipo Deposit.
  10. Retiros se clasifican como OperacionMovimiento subtipo Withdrawal.
  11. Transfer out se clasifica como OperacionMovimiento subtipo Transfer.

  TRANSACCIONES — Compraventas desde ledger (fase 2)
  12. Buy+Sell simples → 1 COMPRA FIFO.
  13. Buy+Sell simples → 1 VENTA FIFO.
  14. Multi-sub-fill mismo timestamp: N buys + N sells → N operaciones.
  15. Advertencia de posible duplicidad cuando hay compraventas desde ledger.
  16. Sin compraventas → advertencia de "sin operaciones, usa detalles".

  TRANSACCIONES — Swaps internos (fase 2)
  17. Exchange income + spending → 1 OperacionSwap.
  18. Increase + Reduce exchange rate → 1 OperacionSwap.

  TRANSACCIONES — Rendimientos (fase 2)
  19. Interest → OperacionRendimiento subtipo Staking/Earn.
  20. Interest → advertencia con moneda y referencia LIRPF.
  21. Interest amount <= 0 → ignorado.

  TRANSACCIONES — Tipos conocidos no usados (fase 2)
  22. Buy with card → movimiento Deposit (no genera FIFO).
  23. Fiat USDT positivo → movimiento Deposit (no genera FIFO).
  24. Fiat EUR negativo → ignorado (no genera nada).
  25. Transaction fee deduct → ignorado.
  26. Financial → movimiento Transfer (neutral fiscal).
  27. Redemption → movimiento Deposit (neutral fiscal).

  ERRORES
  28. Historial de órdenes devuelve ValueError descriptivo.

  ADVERTENCIAS
  29. Advertencia USDT generada para pares X/USDT.
  30. Tipo desconocido en TRANSACCIONES → OperacionDesconocida.
  31. Tipo desconocido → advertencia "no reconocida".

  PIPELINE
  32. Pipeline FIFO completo genera resultados sin crash.
  33. Pipeline FIFO desde ledger (transacciones Buy/Sell) no crash.
  34. Inventario insuficiente PI detectado por motor.

  OTROS EXCHANGES
  35. No rompe clasificadores de otros exchanges (importar en paralelo OK).

  BOM Y FORMATO
  36. BOM UTF-8-SIG no rompe la lectura.
  37. Columna None (trailing comma) ignorada silenciosamente.
  38. TAB prefijado en IDs de orden no rompe la lectura.

  ARCHIVO REAL DE USUARIO
  39-52. Tests con CSV real del usuario (skipped si no disponible).
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
# CSV completo enviado por usuario real (octubre 2024 – mayo 2026)
_USUARIO_REAL      = os.path.expanduser(
    "~/Downloads/Csv Bitget octubre 2024 hasta mayo 2026.csv"
)

_REAL_DISPONIBLE = (
    os.path.exists(_DETALLES_REAL)
    and os.path.exists(_TRANSACCIONES_REAL)
    and os.path.exists(_HISTORIAL_REAL)
)
_USUARIO_REAL_DISPONIBLE = os.path.exists(_USUARIO_REAL)


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
def transacciones_solo_movimientos():
    """CSV de transacciones solo con Deposit, Withdrawal y Transfer out — sin Buy/Sell."""
    rows = [
        ["\t1379378002405007360", "2025-12-01 15:21:04", "USDT",
         "Deposit", "668.2677", "0", "668.267840915"],
        ["\t1374435316954734592", "2025-11-18 00:00:36", "POL",
         "Ordinary Withdrawal", "-67.852", "-0.08", "0"],
        ["\t1286240547709112339", "2025-03-19 15:06:04", "USDT",
         "Transfer out", "-150", "0", "121.187446253"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_mixto():
    """CSV de transacciones con Deposit, Withdrawal, Transfer out y un par Buy/Sell."""
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
def transacciones_compra_simple():
    """1 par Buy XRP + Sell USDT → COMPRA XRP."""
    rows = [
        ["\t001", "2025-01-15 10:00:00", "USDT",
         "Sell", "-100.0", "0", "0"],
        ["\t002", "2025-01-15 10:00:00", "XRP",
         "Buy", "40.0", "-0.04", "40.0"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_venta_simple():
    """1 par Sell XRP + Buy USDT → VENTA XRP."""
    rows = [
        ["\t003", "2025-03-10 12:00:00", "XRP",
         "Sell", "-50.0", "0", "0"],
        ["\t004", "2025-03-10 12:00:00", "USDT",
         "Buy", "130.5", "0", "130.5"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_multi_subfill():
    """2 sub-fills de la misma compra LINK en el mismo timestamp."""
    rows = [
        ["\t005", "2025-11-04 18:37:04", "USDT",
         "Sell", "-84.040355", "0", "92.8944050946"],
        ["\t006", "2025-11-04 18:37:04", "LINK",
         "Buy", "5.705", "-0.005705", "6.299694"],
        ["\t007", "2025-11-04 18:37:04", "USDT",
         "Sell", "-8.851528", "0", "0.000040915"],
        ["\t008", "2025-11-04 18:37:04", "LINK",
         "Buy", "0.601", "-0.000601", "0.600399"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_exchange_swap():
    """Exchange spending BTC + Exchange income BGB → swap BTC→BGB."""
    rows = [
        ["\t009", "2025-01-14 08:02:19", "BGB",
         "Exchange income", "0.01048489", "-0.0002097", "0.01027519"],
        ["\t010", "2025-01-14 08:02:19", "BTC",
         "Exchange spending", "-0.00000071", "0", "0"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_exchange_rate():
    """Increase exchange rate ACN + Reduce exchange rate AITECH → swap AITECH→ACN."""
    rows = [
        ["\t011", "2026-04-24 05:18:42", "ACN",
         "Increase exchange rate", "0.00464", "0", "0.00464"],
        ["\t012", "2026-04-24 05:18:42", "AITECH",
         "Reduce exchange rate", "-0.00464", "0", "0"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_interest():
    """3 filas de Interest en XPL → rendimientos."""
    rows = [
        ["\t013", "2025-09-28 12:07:18", "XPL",
         "Interest", "0.00220833", "0", "0.14722201"],
        ["\t014", "2025-09-28 13:07:14", "XPL",
         "Interest", "0.00220833", "0", "0.14943034"],
        ["\t015", "2025-09-28 14:07:18", "XPL",
         "Interest", "0.00220833", "0", "0.15163867"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_buy_with_card():
    """Buy with card → movimiento Deposit, no FIFO."""
    rows = [
        ["\t016", "2025-01-16 20:00:33", "USDT",
         "Buy with card", "244.463", "0", "488.807336244"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_fiat():
    """Fiat EUR negativo + Fiat USDT positivo → solo USDT se registra."""
    rows = [
        ["\t017", "2025-01-02 03:57:10", "EUR",
         "Fiat", "-200", "0", "0"],
        ["\t018", "2025-01-02 03:57:15", "USDT",
         "Fiat", "204.3245", "0", "262.668978184"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_fee_deduct():
    """Transaction fee deduct → ignorado, sin movimiento ni FIFO."""
    rows = [
        ["\t019", "2025-03-04 19:40:40", "BGB",
         "Transaction fee deduct", "0", "-0.01", "0.0002391755177407"],
    ]
    path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
    yield path
    os.unlink(path)


@pytest.fixture
def transacciones_financial_redemption():
    """Financial (bloqueo earn) + Redemption (rescate earn) en BGB."""
    rows = [
        ["\t020", "2025-09-25 18:38:30", "BGB",
         "Financial", "-7.4", "0", "0.0402391755177407"],
        ["\t021", "2025-09-28 14:11:32", "BGB",
         "Redemption", "7.4", "0", "7.4402391755177407"],
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


# ── TESTS: BUY SPOT (detalles) ────────────────────────────────────────────────

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
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert abs(c.compraventas[0].cantidad - 334.1339) < 1e-6

    def test_importe_total(self, detalles_xrp_buy):
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
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert c.compraventas[0].fee_activo == "XRP"

    def test_fee_cantidad_correcta(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert abs(c.compraventas[0].fee_cantidad - 0.3341339) < 1e-8

    def test_fee_nonzero(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert c.compraventas[0].fee_cantidad > 0


# ── TESTS: SELL SPOT (detalles) ───────────────────────────────────────────────

class TestSellSpot:

    def test_venta_generada(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert len(c.compraventas) == 1
        assert c.compraventas[0].tipo == "VENTA"

    def test_activo_xrp(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert c.compraventas[0].activo == "XRP"

    def test_cantidad_vendida(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert abs(c.compraventas[0].cantidad - 500.0) < 1e-6

    def test_importe_total_usdt(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert abs(c.compraventas[0].importe - 1150.0) < 1e-6


# ── TESTS: FEE EN USDT (Sell) ─────────────────────────────────────────────────

class TestFeeSellUsdt:

    def test_fee_activo_usdt(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert c.compraventas[0].fee_activo == "USDT"

    def test_fee_cantidad_correcta(self, detalles_xrp_sell):
        c = ClasificadorBitget(detalles_xrp_sell).clasificar()
        assert abs(c.compraventas[0].fee_cantidad - 1.15) < 1e-8


# ── TESTS: MULTI-FILL (detalles) ──────────────────────────────────────────────

class TestMultiFill:

    def test_tres_fills_independientes(self, detalles_multi_fill):
        c = ClasificadorBitget(detalles_multi_fill).clasificar()
        assert len(c.compraventas) == 3

    def test_cantidades_individuales(self, detalles_multi_fill):
        c = ClasificadorBitget(detalles_multi_fill).clasificar()
        cantidades = sorted(op.cantidad for op in c.compraventas)
        esperadas  = sorted([133.4718, 18.7671, 21.7611])
        for got, exp in zip(cantidades, esperadas):
            assert abs(got - exp) < 1e-4

    def test_mismo_activo(self, detalles_multi_fill):
        c = ClasificadorBitget(detalles_multi_fill).clasificar()
        assert all(op.activo == "XRP" for op in c.compraventas)

    def test_pi_seis_fills(self, detalles_pi_sell):
        c = ClasificadorBitget(detalles_pi_sell).clasificar()
        assert len(c.compraventas) == 6

    def test_pi_total_cantidad(self, detalles_pi_sell):
        c = ClasificadorBitget(detalles_pi_sell).clasificar()
        total_pi = sum(op.cantidad for op in c.compraventas)
        assert abs(total_pi - 918.0) < 1e-4


# ── TESTS: TRANSACCIONES — DEPÓSITOS ─────────────────────────────────────────

class TestDepositos:

    def test_deposito_clasificado(self, transacciones_solo_movimientos):
        c = ClasificadorBitget(transacciones_solo_movimientos).clasificar()
        deposits = [m for m in c.movimientos if m.subtipo == "Deposit"]
        assert len(deposits) == 1

    def test_deposito_subtipo(self, transacciones_solo_movimientos):
        c = ClasificadorBitget(transacciones_solo_movimientos).clasificar()
        dep = [m for m in c.movimientos if m.subtipo == "Deposit"][0]
        assert dep.subtipo == "Deposit"

    def test_deposito_activo(self, transacciones_solo_movimientos):
        c = ClasificadorBitget(transacciones_solo_movimientos).clasificar()
        dep = [m for m in c.movimientos if m.subtipo == "Deposit"][0]
        assert dep.activo == "USDT"

    def test_deposito_cantidad_positiva(self, transacciones_solo_movimientos):
        c = ClasificadorBitget(transacciones_solo_movimientos).clasificar()
        dep = [m for m in c.movimientos if m.subtipo == "Deposit"][0]
        assert dep.cantidad > 0

    def test_deposito_no_genera_compraventa(self, transacciones_solo_movimientos):
        """Depósito puro (sin Buy/Sell) no genera compraventa."""
        c = ClasificadorBitget(transacciones_solo_movimientos).clasificar()
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
        assert len(transfers) >= 1

    def test_transfer_activo_usdt(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        # Solo el Transfer out normal (el Buy/Sell es compraventa, no Transfer)
        t = [m for m in c.movimientos
             if m.subtipo == "Transfer" and "spot" in m.observacion.lower()][0]
        assert t.activo == "USDT"

    def test_transfer_cantidad_positiva(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        t = [m for m in c.movimientos
             if m.subtipo == "Transfer" and "spot" in m.observacion.lower()][0]
        assert abs(t.cantidad - 150.0) < 1e-6


# ── TESTS: COMPRAVENTAS DESDE LEDGER (fase 2) ─────────────────────────────────

class TestCompraventasLedger:

    def test_compra_simple(self, transacciones_compra_simple):
        """Par Buy XRP + Sell USDT → 1 COMPRA XRP."""
        c = ClasificadorBitget(transacciones_compra_simple).clasificar()
        compras = [op for op in c.compraventas if op.tipo == "COMPRA"]
        assert len(compras) == 1
        op = compras[0]
        assert op.activo == "XRP"
        assert op.contraparte == "USDT"
        assert abs(op.cantidad - 40.0) < 1e-6
        assert abs(op.importe - 100.0) < 1e-6
        assert op.fee_activo == "XRP"
        assert abs(op.fee_cantidad - 0.04) < 1e-8

    def test_venta_simple(self, transacciones_venta_simple):
        """Par Sell XRP + Buy USDT → 1 VENTA XRP."""
        c = ClasificadorBitget(transacciones_venta_simple).clasificar()
        ventas = [op for op in c.compraventas if op.tipo == "VENTA"]
        assert len(ventas) == 1
        op = ventas[0]
        assert op.activo == "XRP"
        assert op.contraparte == "USDT"
        assert abs(op.cantidad - 50.0) < 1e-6
        assert abs(op.importe - 130.5) < 1e-6

    def test_multi_subfill_dos_ops(self, transacciones_multi_subfill):
        """2 sub-fills de LINK en el mismo timestamp → 2 OperacionCompraventa."""
        c = ClasificadorBitget(transacciones_multi_subfill).clasificar()
        assert len(c.compraventas) == 2
        assert all(op.activo == "LINK" for op in c.compraventas)
        assert all(op.tipo == "COMPRA" for op in c.compraventas)

    def test_multi_subfill_cantidades_independientes(self, transacciones_multi_subfill):
        """Cada sub-fill tiene su propia cantidad, NO la suma."""
        c = ClasificadorBitget(transacciones_multi_subfill).clasificar()
        cantidades = sorted(op.cantidad for op in c.compraventas)
        assert abs(cantidades[0] - 0.601) < 1e-4
        assert abs(cantidades[1] - 5.705) < 1e-4

    def test_buy_sell_en_mixto_genera_compraventa(self, transacciones_mixto):
        """El fixture mixto incluye Buy XRP + Sell USDT → debe generar 1 compraventa."""
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        assert len(c.compraventas) == 1
        assert c.compraventas[0].activo == "XRP"
        assert c.compraventas[0].tipo == "COMPRA"

    def test_advertencia_duplicidad_cuando_hay_compraventas(self, transacciones_compra_simple):
        """Con compraventas del ledger, la primera advertencia menciona posible duplicidad."""
        c = ClasificadorBitget(transacciones_compra_simple).clasificar()
        assert len(c.advertencias) > 0
        primera = c.advertencias[0]
        assert "duplicar" in primera.lower() or "ledger" in primera.lower()

    def test_advertencia_sin_compraventas_indica_detalles(self, transacciones_solo_movimientos):
        """Sin compraventas, la primera advertencia indica usar CSV de detalles."""
        c = ClasificadorBitget(transacciones_solo_movimientos).clasificar()
        assert len(c.advertencias) > 0
        primera = c.advertencias[0]
        assert "detalles" in primera.lower()


# ── TESTS: SWAPS INTERNOS (fase 2) ────────────────────────────────────────────

class TestSwapsInternos:

    def test_exchange_spending_income_genera_swap(self, transacciones_exchange_swap):
        """Exchange spending + income → 1 OperacionSwap BTC→BGB."""
        c = ClasificadorBitget(transacciones_exchange_swap).clasificar()
        assert len(c.swaps) == 1
        swap = c.swaps[0]
        assert swap.activo_entregado == "BTC"
        assert swap.activo_recibido == "BGB"
        assert abs(swap.cantidad_entregada - 0.00000071) < 1e-10
        assert abs(swap.cantidad_recibida - 0.01048489) < 1e-10

    def test_exchange_swap_no_genera_compraventa(self, transacciones_exchange_swap):
        c = ClasificadorBitget(transacciones_exchange_swap).clasificar()
        assert len(c.compraventas) == 0

    def test_increase_reduce_exchange_rate_genera_swap(self, transacciones_exchange_rate):
        """Increase + Reduce exchange rate → 1 OperacionSwap AITECH→ACN."""
        c = ClasificadorBitget(transacciones_exchange_rate).clasificar()
        assert len(c.swaps) == 1
        swap = c.swaps[0]
        assert swap.activo_entregado == "AITECH"
        assert swap.activo_recibido == "ACN"
        assert abs(swap.cantidad_entregada - 0.00464) < 1e-8
        assert abs(swap.cantidad_recibida - 0.00464) < 1e-8

    def test_swap_advertencia_valoracion(self, transacciones_exchange_swap):
        """Cuando hay swaps, la advertencia menciona valoración manual."""
        c = ClasificadorBitget(transacciones_exchange_swap).clasificar()
        assert any("swap" in a.lower() or "valoración" in a.lower()
                   for a in c.advertencias)


# ── TESTS: RENDIMIENTOS / INTEREST (fase 2) ───────────────────────────────────

class TestRendimientos:

    def test_interest_genera_rendimiento(self, transacciones_interest):
        """Interest rows → OperacionRendimiento subtipo Staking/Earn."""
        c = ClasificadorBitget(transacciones_interest).clasificar()
        assert len(c.rendimientos) == 3

    def test_interest_subtipo(self, transacciones_interest):
        c = ClasificadorBitget(transacciones_interest).clasificar()
        assert all(r.subtipo == "Staking/Earn" for r in c.rendimientos)

    def test_interest_activo(self, transacciones_interest):
        c = ClasificadorBitget(transacciones_interest).clasificar()
        assert all(r.activo == "XPL" for r in c.rendimientos)

    def test_interest_cantidad_positiva(self, transacciones_interest):
        c = ClasificadorBitget(transacciones_interest).clasificar()
        assert all(r.cantidad > 0 for r in c.rendimientos)

    def test_interest_no_genera_compraventa(self, transacciones_interest):
        c = ClasificadorBitget(transacciones_interest).clasificar()
        assert len(c.compraventas) == 0

    def test_interest_advertencia_irpf(self, transacciones_interest):
        """Advertencia menciona valoración en euros y/o capital mobiliario."""
        c = ClasificadorBitget(transacciones_interest).clasificar()
        aviso_rend = [a for a in c.advertencias
                      if "rendimiento" in a.lower() or "capital" in a.lower()]
        assert len(aviso_rend) >= 1

    def test_interest_cero_ignorado(self):
        """Interest con amount = 0 se ignora."""
        rows = [
            ["\t099", "2025-09-28 10:00:00", "XPL",
             "Interest", "0", "0", "0.0"],
        ]
        path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
        try:
            c = ClasificadorBitget(path).clasificar()
            assert len(c.rendimientos) == 0
        finally:
            os.unlink(path)


# ── TESTS: TIPOS CONOCIDOS NO USADOS (fase 2) ─────────────────────────────────

class TestTiposConocidosNoUsados:

    def test_buy_with_card_no_fifo(self, transacciones_buy_with_card):
        """Buy with card no genera compraventa FIFO."""
        c = ClasificadorBitget(transacciones_buy_with_card).clasificar()
        assert len(c.compraventas) == 0

    def test_buy_with_card_genera_movimiento(self, transacciones_buy_with_card):
        """Buy with card se registra como movimiento Deposit informativo."""
        c = ClasificadorBitget(transacciones_buy_with_card).clasificar()
        deposits = [m for m in c.movimientos if m.subtipo == "Deposit"]
        assert len(deposits) == 1
        assert deposits[0].activo == "USDT"

    def test_buy_with_card_no_desconocida(self, transacciones_buy_with_card):
        """Buy with card no debe aparecer como desconocida."""
        c = ClasificadorBitget(transacciones_buy_with_card).clasificar()
        assert len(c.desconocidas) == 0

    def test_fiat_usdt_positivo_genera_movimiento(self, transacciones_fiat):
        """Fiat USDT positivo → movimiento Deposit."""
        c = ClasificadorBitget(transacciones_fiat).clasificar()
        deposits = [m for m in c.movimientos if m.subtipo == "Deposit"]
        assert len(deposits) == 1
        assert deposits[0].activo == "USDT"

    def test_fiat_eur_negativo_ignorado(self, transacciones_fiat):
        """Fiat EUR negativo no genera ninguna entrada."""
        c = ClasificadorBitget(transacciones_fiat).clasificar()
        # Solo debe haber 1 movimiento (el USDT positivo)
        assert len(c.movimientos) == 1

    def test_fiat_no_genera_fifo(self, transacciones_fiat):
        c = ClasificadorBitget(transacciones_fiat).clasificar()
        assert len(c.compraventas) == 0

    def test_transaction_fee_deduct_ignorado(self, transacciones_fee_deduct):
        """Transaction fee deduct no genera movimiento, compraventa ni desconocida."""
        c = ClasificadorBitget(transacciones_fee_deduct).clasificar()
        assert len(c.compraventas) == 0
        assert len(c.movimientos) == 0
        assert len(c.desconocidas) == 0

    def test_financial_genera_movimiento_transfer(self, transacciones_financial_redemption):
        """Financial (bloqueo earn) → movimiento Transfer."""
        c = ClasificadorBitget(transacciones_financial_redemption).clasificar()
        transfers = [m for m in c.movimientos if m.subtipo == "Transfer"]
        assert len(transfers) == 1
        assert transfers[0].activo == "BGB"

    def test_redemption_genera_movimiento_deposit(self, transacciones_financial_redemption):
        """Redemption (rescate earn) → movimiento Deposit."""
        c = ClasificadorBitget(transacciones_financial_redemption).clasificar()
        earn_deposits = [m for m in c.movimientos
                         if m.subtipo == "Deposit" and "earn" in m.observacion.lower()]
        assert len(earn_deposits) == 1
        assert earn_deposits[0].activo == "BGB"

    def test_financial_redemption_no_fifo(self, transacciones_financial_redemption):
        """Financial + Redemption no generan compraventas FIFO."""
        c = ClasificadorBitget(transacciones_financial_redemption).clasificar()
        assert len(c.compraventas) == 0


# ── TESTS: HISTORIAL → ERROR DESCRIPTIVO ─────────────────────────────────────

class TestHistorialOrdenesError:

    def test_historial_lanza_valueerror(self, historial_simple):
        with pytest.raises(ValueError) as exc_info:
            ClasificadorBitget(historial_simple).clasificar()
        assert "historial" in str(exc_info.value).lower() or "detalles" in str(exc_info.value).lower()

    def test_mensaje_descriptivo(self, historial_simple):
        with pytest.raises(ValueError) as exc_info:
            ClasificadorBitget(historial_simple).clasificar()
        assert len(str(exc_info.value)) > 50

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

    def test_advertencia_usdt_ledger_compra(self, transacciones_compra_simple):
        """Compra XRP con USDT desde ledger activa la advertencia USDT."""
        c = ClasificadorBitget(transacciones_compra_simple).clasificar()
        assert any("USDT" in a for a in c.advertencias)


# ── TESTS: TIPO DESCONOCIDO ───────────────────────────────────────────────────

class TestTipoDesconocido:

    def test_direction_desconocida(self, detalles_tipo_desconocido):
        c = ClasificadorBitget(detalles_tipo_desconocido).clasificar()
        assert len(c.desconocidas) == 1

    def test_tipo_tx_desconocido(self, transacciones_tipo_desconocido):
        c = ClasificadorBitget(transacciones_tipo_desconocido).clasificar()
        assert len(c.desconocidas) == 1

    def test_tipo_tx_desconocido_advertencia(self, transacciones_tipo_desconocido):
        c = ClasificadorBitget(transacciones_tipo_desconocido).clasificar()
        assert any("no reconocida" in a for a in c.advertencias)


# ── TESTS: PIPELINE FIFO COMPLETO ────────────────────────────────────────────

class TestPipelineFiloCompleto:

    def test_pipeline_detalles_buy_sell_sin_crash(self):
        """Compra + venta desde detalles → motor FIFO genera resultado."""
        from fiscal_app_export.motor_fifo import MotorFIFO

        rows_buy = [
            ["2025-03-01 10:00:00", "XRP/USDT", "XRP", "USDT",
             "Buy", "2.0", "100", "200", "0.1", "XRP", ""],
        ]
        rows_sell = [
            ["2025-07-01 10:00:00", "XRP/USDT", "XRP", "USDT",
             "Sell", "2.5", "80", "200", "0.2", "USDT", ""],
        ]
        path_buy = _csv_tmp(DETALLES_HEADERS, rows_buy)
        c_buy = ClasificadorBitget(path_buy).clasificar()
        os.unlink(path_buy)

        path_sell = _csv_tmp(DETALLES_HEADERS, rows_sell)
        c_sell = ClasificadorBitget(path_sell).clasificar()
        os.unlink(path_sell)

        motor = MotorFIFO()
        ops = sorted(c_buy.compraventas + c_sell.compraventas, key=lambda x: x.fecha)
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

    def test_pipeline_ledger_buy_sell_sin_crash(self, transacciones_compra_simple,
                                                 transacciones_venta_simple):
        """Compra + venta desde ledger transacciones → motor FIFO sin crash."""
        from fiscal_app_export.motor_fifo import MotorFIFO

        c_compra = ClasificadorBitget(transacciones_compra_simple).clasificar()
        c_venta  = ClasificadorBitget(transacciones_venta_simple).clasificar()

        motor = MotorFIFO()
        ops = sorted(
            c_compra.compraventas + c_venta.compraventas,
            key=lambda x: x.fecha,
        )
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

    def test_pipeline_inventario_insuficiente_pi(self, detalles_pi_sell):
        """Venta PI sin compras → inventario insuficiente detectado."""
        from fiscal_app_export.motor_fifo import MotorFIFO

        c = ClasificadorBitget(detalles_pi_sell).clasificar()
        motor = MotorFIFO()
        for op in sorted(c.compraventas, key=lambda x: x.fecha):
            motor.registrar_venta(
                fecha=op.fecha, activo=op.activo, cantidad=op.cantidad,
                importe=op.importe, contraparte=op.contraparte,
                fee_activo=op.fee_activo, fee_cantidad=op.fee_cantidad,
            )

        tiene_aviso = (
            any(r.inventario_incompleto for r in motor.resultados)
            or len(motor.advertencias) > 0
        )
        assert tiene_aviso


# ── TESTS: NO ROMPE OTROS EXCHANGES ──────────────────────────────────────────

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

    def test_detalles_no_afectados_por_fase2(self, detalles_xrp_buy):
        """El CSV de detalles sigue funcionando exactamente igual que en fase 1."""
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert c.tipo_export == "detalles"
        assert len(c.compraventas) == 1
        assert c.compraventas[0].tipo == "COMPRA"
        assert c.compraventas[0].activo == "XRP"


# ── TESTS: BOM Y TRAILING COMMA ───────────────────────────────────────────────

class TestBomYTrailingComma:

    def test_bom_utf8_sig_ok(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert len(c.compraventas) == 1

    def test_trailing_comma_no_crash(self, detalles_xrp_buy):
        c = ClasificadorBitget(detalles_xrp_buy).clasificar()
        assert len(c.desconocidas) == 0

    def test_tab_en_order_id_ignorado(self, transacciones_mixto):
        c = ClasificadorBitget(transacciones_mixto).clasificar()
        assert c.tipo_export == "transacciones"


# ── TESTS CON ARCHIVOS REALES (CSV original de la fase 1) ────────────────────

@pytest.mark.skipif(not _REAL_DISPONIBLE, reason="Archivos CSV reales de Bitget (fase 1) no disponibles en ~/Downloads/")
class TestArchivosRealesFase1:

    def test_detalles_real_no_crash(self):
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        assert c.tipo_export == "detalles"
        assert len(c.compraventas) > 0

    def test_detalles_real_33_fills(self):
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

    def test_historial_real_error_descriptivo(self):
        with pytest.raises(ValueError) as exc_info:
            ClasificadorBitget(_HISTORIAL_REAL).clasificar()
        assert "detalles" in str(exc_info.value).lower()

    def test_detalles_real_multifill_xrp(self):
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        xrp_17jun = [
            op for op in c.compraventas
            if op.activo == "XRP" and op.fecha.startswith("2025-06-17 22:15:27")
        ]
        assert len(xrp_17jun) == 3

    def test_detalles_real_multifill_pi(self):
        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        pi_15mar = [
            op for op in c.compraventas
            if op.activo == "PI" and op.fecha.startswith("2025-03-15 20:14:47")
        ]
        assert len(pi_15mar) == 6

    def test_pipeline_real_detalles_fifo(self):
        from fiscal_app_export.motor_fifo import MotorFIFO

        c = ClasificadorBitget(_DETALLES_REAL).clasificar()
        motor = MotorFIFO()
        for op in sorted(c.compraventas, key=lambda x: x.fecha):
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

        assert len(motor.resultados) > 0
        assert all(r.activo for r in motor.resultados)


# ── TESTS CON CSV REAL DEL USUARIO (octubre 2024 – mayo 2026) ────────────────

@pytest.mark.skipif(not _USUARIO_REAL_DISPONIBLE, reason="CSV real de usuario no disponible en ~/Downloads/")
class TestArchivosRealesUsuario:

    def test_tipo_detectado_como_transacciones(self):
        assert detect_bitget_file_type(_USUARIO_REAL) == "transacciones"

    def test_no_crash(self):
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        assert c.tipo_export == "transacciones"

    def test_70_compraventas(self):
        """El CSV tiene 70 pares Buy/Sell → 70 operaciones FIFO."""
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        assert len(c.compraventas) == 70

    def test_compras_y_ventas_presentes(self):
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        tipos = {op.tipo for op in c.compraventas}
        assert "COMPRA" in tipos
        assert "VENTA" in tipos

    def test_67_rendimientos_interest(self):
        """El CSV tiene 67 filas de Interest en XPL."""
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        assert len(c.rendimientos) == 67

    def test_rendimientos_en_xpl(self):
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        activos_rend = {r.activo for r in c.rendimientos}
        assert activos_rend == {"XPL"}

    def test_2_swaps_internos(self):
        """BTC→BGB (Exchange) + AITECH→ACN (Exchange rate) = 2 swaps."""
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        assert len(c.swaps) == 2

    def test_swap_btc_bgb(self):
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        btc_bgb = [s for s in c.swaps if s.activo_entregado == "BTC"]
        assert len(btc_bgb) == 1
        assert btc_bgb[0].activo_recibido == "BGB"

    def test_swap_aitech_acn(self):
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        aitech_acn = [s for s in c.swaps if s.activo_entregado == "AITECH"]
        assert len(aitech_acn) == 1
        assert aitech_acn[0].activo_recibido == "ACN"

    def test_sin_desconocidas(self):
        """Todos los tipos del CSV están clasificados: 0 desconocidas."""
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        assert len(c.desconocidas) == 0

    def test_advertencia_duplicidad_primera(self):
        """La primera advertencia avisa de posible duplicidad con CSV de detalles."""
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        assert len(c.advertencias) > 0
        primera = c.advertencias[0]
        assert "duplicar" in primera.lower() or "ledger" in primera.lower()

    def test_advertencia_rendimientos_xpl(self):
        """Hay advertencia sobre rendimientos en XPL con referencia LIRPF."""
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        assert any("xpl" in a.lower() for a in c.advertencias)

    def test_advertencia_swaps(self):
        """Hay advertencia sobre los 2 swaps que requieren valoración manual."""
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        assert any("swap" in a.lower() or "conversión" in a.lower()
                   for a in c.advertencias)

    def test_pipeline_fifo_sin_crash(self):
        """Pipeline completo con el CSV real del usuario no debe crashear."""
        from fiscal_app_export.motor_fifo import MotorFIFO

        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        motor = MotorFIFO()
        for op in sorted(c.compraventas, key=lambda x: x.fecha):
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

        # Debe haber resultados de ventas sin crash
        assert len(motor.resultados) > 0

    def test_compraventas_son_xrp_link_hbar_etc(self):
        """Los activos FIFO son los esperados (no USDT como activo base)."""
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        activos = {op.activo for op in c.compraventas}
        # USDT no debe aparecer como activo base (nunca como "cripto comprada/vendida")
        assert "USDT" not in activos

    def test_contraparte_siempre_usdt(self):
        """Todas las compraventas tienen USDT como contraparte."""
        c = ClasificadorBitget(_USUARIO_REAL).clasificar()
        contrapartes = {op.contraparte for op in c.compraventas}
        assert contrapartes.issubset({"USDT", "USDC", "BUSD", "FDUSD", "DAI"})


# ── REGRESIÓN: AttributeError 'NoneType' has no attribute 'strip' (fingerprint ed927121) ──

class TestNoneValuesRegression:
    """
    Regresión para el bug ed927121.

    csv.DictReader rellena con None los campos faltantes en filas cortas (restval=None).
    El parser debe sobrevivir a cualquier combinación de None en columnas del CSV.
    """

    def _csv_raw(self, headers: list, lines: list) -> str:
        """Crea un CSV temporal a partir de líneas en crudo (sin escapado automático)."""
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(",".join(headers) + "\n")
            for line in lines:
                f.write(line + "\n")
        return path

    def test_type_none_no_crash(self):
        """Fila con Type=None (fila más corta que el header) no lanza AttributeError."""
        # Fila incompleta: solo tiene la columna 'order', el resto queda None en DictReader
        path = self._csv_raw(
            TRANSACCIONES_HEADERS,
            ["ORD001"],  # solo 1 campo; Type, Amount, Fee, Available → None
        )
        try:
            c = ClasificadorBitget(path).clasificar()
            # No debe lanzar; la fila acaba en desconocidas o ignorada
            assert isinstance(c, ClasificadorBitget)
        except AttributeError as e:
            pytest.fail(f"AttributeError inesperado con Type=None: {e}")
        finally:
            os.unlink(path)

    def test_date_none_no_crash(self):
        """Fila con Date=None no lanza AttributeError."""
        path = self._csv_raw(
            TRANSACCIONES_HEADERS,
            # Tiene Type pero no Date (primera columna ausente → order ocupa Date, etc.)
            # Simulamos fila corta dejando solo 2 columnas de 7
            ["ORD001,"],
        )
        try:
            c = ClasificadorBitget(path).clasificar()
            assert isinstance(c, ClasificadorBitget)
        except AttributeError as e:
            pytest.fail(f"AttributeError inesperado con Date=None: {e}")
        finally:
            os.unlink(path)

    def test_fila_incompleta_queda_como_desconocida_o_ignorada(self):
        """Fila con menos columnas que el header termina en desconocidas o ignorada, sin crash."""
        # Una fila completa válida + una fila incompleta
        rows_valida = [["ORD1", "2025-01-01 10:00:00", "XRP", "Deposit", "100", "0", "100"]]
        path_valida = _csv_tmp(TRANSACCIONES_HEADERS, rows_valida)

        # Añadir fila incompleta al final
        with open(path_valida, "a", encoding="utf-8-sig") as f:
            f.write("ORD2\n")  # solo 1 campo

        try:
            c = ClasificadorBitget(path_valida).clasificar()
            # La fila válida debe haberse procesado
            assert len(c.movimientos) >= 1
            # No debe haber crash
            assert isinstance(c, ClasificadorBitget)
        except AttributeError as e:
            pytest.fail(f"AttributeError en fila incompleta: {e}")
        finally:
            os.unlink(path_valida)

    def test_pipeline_none_values_no_attributeerror(self):
        """Pipeline completo con filas None no genera 'NoneType has no attribute strip'."""
        # CSV con mezcla de filas válidas e incompletas
        rows = [
            ["ORD1", "2025-03-01 09:00:00", "BTC", "Deposit", "0.5", "0", "0.5"],
            ["ORD2", "2025-03-01 09:01:00", "USDT", "Interest", "1.5", "0", "1.5"],
        ]
        path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
        with open(path, "a", encoding="utf-8-sig") as f:
            f.write("ORD3\n")  # fila incompleta al final

        try:
            from fiscal_app_export.clasificador_bitget import ClasificadorBitget as CB
            c = CB(path).clasificar()
            assert isinstance(c, CB)
        except AttributeError as e:
            if "NoneType" in str(e) and "strip" in str(e):
                pytest.fail(f"Regresión ed927121 no corregida: {e}")
            raise
        finally:
            os.unlink(path)

    def test_csv_produccion_simulado(self):
        """
        Simula el CSV de producción del usuario (10 filas, 735 bytes, transacciones spot).
        Reproduce las condiciones del fingerprint ed927121.
        Resultado esperado: clasificación correcta o advertencia, nunca AttributeError.
        """
        # 10 filas variadas como las que produciría Bitget en un export pequeño
        rows = [
            ["6978809769001", "2026-01-15 10:00:00", "USDT",  "Deposit",            "500",  "0",   "500"],
            ["6978809769002", "2026-01-15 10:01:00", "BGB",   "Transaction fee deduct", "0", "-0.1", "10"],
            ["6978809769003", "2026-02-10 11:00:00", "USDT",  "Buy",                "100",  "-1",  "400"],
            ["6978809769004", "2026-02-10 11:00:00", "XRP",   "Sell",               "-50",  "0",   "350"],
            ["6978809769005", "2026-03-01 09:30:00", "XRP",   "Interest",           "0.5",  "0",   "50"],
            ["6978809769006", "2026-03-15 14:00:00", "USDT",  "Ordinary Withdrawal","-200", "0",   "150"],
            ["6978809769007", "2026-04-01 08:00:00", "XRP",   "Financial",          "-10",  "0",   "40"],
            ["6978809769008", "2026-04-01 08:01:00", "XRP",   "Redemption",         "10",   "0",   "50"],
            ["6978809769009", "2026-05-01 12:00:00", "USDT",  "Fiat",               "100",  "0",   "250"],
            ["6978809769010", "2026-05-10 16:00:00", "USDT",  "Transfer out",       "-50",  "0",   "200"],
        ]
        path = _csv_tmp(TRANSACCIONES_HEADERS, rows)
        try:
            c = ClasificadorBitget(path).clasificar()
            # No debe producir AttributeError; el resultado es informativo
            assert isinstance(c, ClasificadorBitget)
            # Hay al menos movimientos o rendimientos
            total = (len(c.movimientos) + len(c.rendimientos) +
                     len(c.compraventas) + len(c.desconocidas))
            assert total > 0, "El CSV tiene 10 filas pero el clasificador no produjo nada"
        except AttributeError as e:
            pytest.fail(f"Regresión ed927121 en CSV simulado de producción: {e}")
        finally:
            os.unlink(path)
