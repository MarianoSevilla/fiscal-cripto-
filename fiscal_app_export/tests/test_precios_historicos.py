"""
Tests para precios_historicos.py — Fase 3B.1.

Todos los tests mockean las llamadas HTTP (CoinGecko y BCE).
No se realizan peticiones reales a internet.
"""

import sys
import os
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

# Asegurar que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import precios_historicos as ph
from precios_historicos import (
    FUENTE_COINGECKO,
    FUENTE_ESTIMADO_BCE,
    FUENTE_NO_DISPONIBLE,
    FUENTE_FECHA_FUTURA,
    PrecioHistorico,
    obtener_precio_historico,
    obtener_precios_historicos,
    enriquecer_721_con_precios,
    _bce_eurusd_historico,
    _coingecko_precio_eur,
    _precio_cache,
)


# ── FIXTURE: limpiar caché entre tests ────────────────────────────────────────

@pytest.fixture(autouse=True)
def limpiar_cache():
    """Limpia la caché global antes de cada test."""
    _precio_cache.clear()
    yield
    _precio_cache.clear()


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _mock_cg_response(precio_eur: float) -> MagicMock:
    """Crea un mock de respuesta HTTP de CoinGecko con el precio indicado."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "id": "bitcoin",
        "market_data": {
            "current_price": {"eur": precio_eur, "usd": precio_eur * 1.08}
        }
    }
    return mock


def _mock_cg_no_market_data() -> MagicMock:
    """CoinGecko responde 200 pero sin market_data (moneda antigua/delisted)."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {"id": "some-coin"}
    return mock


def _mock_cg_rate_limit() -> MagicMock:
    """CoinGecko responde 429 rate limit."""
    mock = MagicMock()
    mock.status_code = 429
    return mock


def _mock_bce_response(usd_per_eur: float) -> MagicMock:
    """Crea un mock de respuesta BCE con el tipo de cambio indicado (USD por EUR)."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = {
        "dataSets": [{
            "series": {
                "0:0:0:0:0": {
                    "observations": {"0": [usd_per_eur]}
                }
            }
        }]
    }
    return mock


def _datos_721_simple(ticker="BTC", cantidad="0.5", ejercicio=2024) -> dict:
    """Crea un dict de datos 721 mínimo para tests de enriquecimiento."""
    return {
        "modelo": "721",
        "ejercicio": ejercicio,
        "fecha_referencia": f"31-12-{ejercicio}",
        "potencialmente_obligado": True,
        "informe_orientativo": True,
        "total_valor_eur": None,
        "exchanges": [{
            "exchange": "Binance",
            "exchange_key": "binance",
            "pais_custodio": "Islas Caimán",
            "codigo_pais_iso": None,
            "extranjero": True,
            "nif_custodio": None,
            "web_custodio": "https://www.binance.com",
            "requiere_revision": True,
            "activos": [{
                "activo": ticker,
                "denominacion": "Bitcoin",
                "siglas": ticker,
                "cantidad": cantidad,
                "valor_eur": None,
                "origen_valor": None,
                "coste_base_fifo": "12000.00",
                "clave": "T",
                "origen_moneda_virtual": "A",
                "fecha_referencia": f"31-12-{ejercicio}",
                "requiere_revision": True,
                "advertencias": [
                    f"Valor de mercado de {ticker} a 31/12/{ejercicio} no calculable "
                    "desde el historial de transacciones. Consultar precio oficial "
                    "(CoinMarketCap, CoinGecko, cotización en el exchange) y actualizar."
                ],
            }],
        }],
        "advertencias": [],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 1 — _coingecko_precio_eur
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoinGeckoPrecioEur:

    def test_01_precio_correcto(self):
        """CoinGecko devuelve precio EUR correctamente."""
        with patch("requests.get", return_value=_mock_cg_response(85432.12)):
            precio = _coingecko_precio_eur("bitcoin", "31-12-2024")
        assert precio == Decimal("85432.120000")

    def test_02_sin_market_data_devuelve_none(self):
        """Si no hay market_data, retorna None."""
        with patch("requests.get", return_value=_mock_cg_no_market_data()):
            precio = _coingecko_precio_eur("some-coin", "31-12-2024")
        assert precio is None

    def test_03_rate_limit_devuelve_none(self):
        """HTTP 429 retorna None sin lanzar excepción."""
        with patch("requests.get", return_value=_mock_cg_rate_limit()):
            precio = _coingecko_precio_eur("bitcoin", "31-12-2024")
        assert precio is None

    def test_04_http_error_devuelve_none(self):
        """HTTP 500 retorna None."""
        mock = MagicMock()
        mock.status_code = 500
        with patch("requests.get", return_value=mock):
            precio = _coingecko_precio_eur("bitcoin", "31-12-2024")
        assert precio is None

    def test_05_excepcion_red_devuelve_none(self):
        """Excepción de red retorna None."""
        with patch("requests.get", side_effect=ConnectionError("timeout")):
            precio = _coingecko_precio_eur("bitcoin", "31-12-2024")
        assert precio is None

    def test_06_precio_pequeno_precision(self):
        """Precio muy pequeño (ej. SHIB) con precisión correcta."""
        with patch("requests.get", return_value=_mock_cg_response(0.000012345678)):
            precio = _coingecko_precio_eur("shiba-inu", "31-12-2024")
        assert precio is not None
        assert precio > 0


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 2 — _bce_eurusd_historico
# ═══════════════════════════════════════════════════════════════════════════════

class TestBceEurUsd:

    def test_07_tipo_cambio_correcto(self):
        """BCE devuelve tipo de cambio y se invierte correctamente."""
        # 1 EUR = 1.10 USD  →  1 USD = 0.909090... EUR
        with patch("requests.get", return_value=_mock_bce_response(1.10)):
            eur_per_usd = _bce_eurusd_historico(2024)
        assert eur_per_usd is not None
        expected = (Decimal("1") / Decimal("1.10")).quantize(Decimal("0.000001"))
        assert eur_per_usd == expected

    def test_08_bce_falla_devuelve_none(self):
        """Si BCE falla en todos los reintentos, retorna None."""
        mock = MagicMock()
        mock.status_code = 503
        with patch("requests.get", return_value=mock):
            resultado = _bce_eurusd_historico(2024)
        assert resultado is None

    def test_09_bce_excepcion_red_devuelve_none(self):
        """Excepción de red retorna None."""
        with patch("requests.get", side_effect=ConnectionError("timeout")):
            resultado = _bce_eurusd_historico(2024)
        assert resultado is None

    def test_10_bce_sin_observaciones_devuelve_none(self):
        """Respuesta BCE sin observations retorna None."""
        mock = MagicMock()
        mock.status_code = 200
        mock.json.return_value = {"dataSets": [{"series": {}}]}
        with patch("requests.get", return_value=mock):
            resultado = _bce_eurusd_historico(2024)
        assert resultado is None


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 3 — obtener_precio_historico (un ticker)
# ═══════════════════════════════════════════════════════════════════════════════

class TestObtenerPrecioHistorico:

    def test_11_btc_coingecko(self):
        """BTC se resuelve via CoinGecko con precio correcto."""
        with patch("requests.get", return_value=_mock_cg_response(85000.0)):
            resultado = obtener_precio_historico("BTC", 2024)
        assert resultado.fuente    == FUENTE_COINGECKO
        assert resultado.precio_eur == Decimal("85000.000000")
        assert resultado.estimado  is False
        assert resultado.coingecko_id == "bitcoin"
        assert resultado.ticker    == "BTC"
        assert resultado.ejercicio == 2024
        assert resultado.fecha_corte == date(2024, 12, 31)

    def test_12_eth_coingecko(self):
        """ETH se resuelve via CoinGecko."""
        with patch("requests.get", return_value=_mock_cg_response(3200.0)):
            resultado = obtener_precio_historico("eth", 2024)
        assert resultado.ticker     == "ETH"
        assert resultado.fuente     == FUENTE_COINGECKO
        assert resultado.precio_eur == Decimal("3200.000000")

    def test_13_usdt_stablecoin_via_bce(self):
        """USDT (stablecoin USD) se resuelve via BCE, no CoinGecko."""
        with patch("requests.get", return_value=_mock_bce_response(1.08)):
            resultado = obtener_precio_historico("USDT", 2024)
        assert resultado.fuente    == FUENTE_ESTIMADO_BCE
        assert resultado.estimado  is True
        assert resultado.precio_eur is not None
        assert resultado.coingecko_id is None

    def test_14_usdc_stablecoin_via_bce(self):
        """USDC también se resuelve via BCE."""
        with patch("requests.get", return_value=_mock_bce_response(1.10)):
            resultado = obtener_precio_historico("USDC", 2024)
        assert resultado.fuente   == FUENTE_ESTIMADO_BCE
        assert resultado.estimado is True

    def test_15_ticker_desconocido_no_disponible(self):
        """Ticker sin CoinGecko ID → fuente no_disponible."""
        resultado = obtener_precio_historico("XYZUNKNOWN123", 2024)
        assert resultado.fuente     == FUENTE_NO_DISPONIBLE
        assert resultado.precio_eur is None
        assert resultado.estimado   is False

    def test_16_coingecko_falla_no_disponible(self):
        """Si CoinGecko falla → fuente no_disponible (ticker conocido)."""
        with patch("requests.get", side_effect=ConnectionError("timeout")):
            resultado = obtener_precio_historico("BTC", 2024)
        assert resultado.fuente     == FUENTE_NO_DISPONIBLE
        assert resultado.precio_eur is None
        assert resultado.coingecko_id == "bitcoin"

    def test_17_stablecoin_bce_falla_no_disponible(self):
        """Si BCE falla con stablecoin → fuente no_disponible."""
        mock = MagicMock()
        mock.status_code = 503
        with patch("requests.get", return_value=mock):
            resultado = obtener_precio_historico("USDT", 2024)
        assert resultado.fuente     == FUENTE_NO_DISPONIBLE
        assert resultado.precio_eur is None

    def test_18_fecha_futura_no_disponible(self):
        """Ejercicio futuro → fuente fecha_futura sin HTTP."""
        resultado = obtener_precio_historico("BTC", 2099)
        assert resultado.fuente     == FUENTE_FECHA_FUTURA
        assert resultado.precio_eur is None
        assert resultado.estimado   is False

    def test_19_ticker_minusculas_normalizado(self):
        """Tickers en minúsculas se normalizan a uppercase."""
        with patch("requests.get", return_value=_mock_cg_response(3200.0)):
            resultado = obtener_precio_historico("eth", 2024)
        assert resultado.ticker == "ETH"

    def test_20_cache_evita_segunda_peticion(self):
        """El resultado queda en caché; la segunda llamada no hace HTTP."""
        with patch("requests.get", return_value=_mock_cg_response(85000.0)) as mock_get:
            r1 = obtener_precio_historico("BTC", 2024)
            r2 = obtener_precio_historico("BTC", 2024)
        assert mock_get.call_count == 1
        assert r1.precio_eur == r2.precio_eur

    def test_21_cache_separada_por_ejercicio(self):
        """Cache diferencia el mismo ticker con diferentes ejercicios."""
        with patch("requests.get", side_effect=[
            _mock_cg_response(30000.0),  # 2022
            _mock_cg_response(40000.0),  # 2023
        ]):
            r1 = obtener_precio_historico("BTC", 2022)
            r2 = obtener_precio_historico("BTC", 2023)
        assert r1.precio_eur != r2.precio_eur
        assert r1.ejercicio  == 2022
        assert r2.ejercicio  == 2023

    def test_22_nota_contiene_informacion_trazabilidad(self):
        """La nota debe contener información de trazabilidad."""
        with patch("requests.get", return_value=_mock_cg_response(85000.0)):
            resultado = obtener_precio_historico("BTC", 2024)
        assert "CoinGecko" in resultado.nota
        assert "2024" in resultado.nota

    def test_23_nota_stablecoin_menciona_bce(self):
        """La nota de stablecoin debe mencionar BCE."""
        with patch("requests.get", return_value=_mock_bce_response(1.08)):
            resultado = obtener_precio_historico("USDT", 2024)
        assert "BCE" in resultado.nota or "bce" in resultado.nota.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 4 — obtener_precios_historicos (batch)
# ═══════════════════════════════════════════════════════════════════════════════

class TestObtenerPreciosHistoricos:

    def test_24_batch_varios_tickers(self):
        """Batch devuelve dict con todos los tickers solicitados."""
        responses = [
            _mock_cg_response(85000.0),   # BTC
            _mock_cg_response(3200.0),    # ETH
        ]
        with patch("requests.get", side_effect=responses):
            resultado = obtener_precios_historicos(["BTC", "ETH"], 2024)
        assert "BTC" in resultado
        assert "ETH" in resultado
        assert resultado["BTC"].precio_eur == Decimal("85000.000000")
        assert resultado["ETH"].precio_eur == Decimal("3200.000000")

    def test_25_batch_con_stablecoin_mixto(self):
        """Batch con crypto + stablecoin usa fuentes distintas."""
        bce_mock = _mock_bce_response(1.08)
        cg_mock  = _mock_cg_response(85000.0)
        # USDT va primero (stablecoin), luego BTC (CoinGecko)
        with patch("requests.get", side_effect=[bce_mock, cg_mock]):
            resultado = obtener_precios_historicos(["USDT", "BTC"], 2024)
        assert resultado["USDT"].fuente == FUENTE_ESTIMADO_BCE
        assert resultado["BTC"].fuente  == FUENTE_COINGECKO

    def test_26_batch_normaliza_tickers(self):
        """Batch normaliza tickers a uppercase en el resultado."""
        with patch("requests.get", return_value=_mock_cg_response(85000.0)):
            resultado = obtener_precios_historicos(["btc"], 2024)
        assert "BTC" in resultado

    def test_27_batch_tickers_desconocidos_no_disponible(self):
        """Tickers sin CoinGecko ID retornan no_disponible sin HTTP."""
        with patch("requests.get") as mock_get:
            resultado = obtener_precios_historicos(["XYZUNKNOWN"], 2024)
        mock_get.assert_not_called()
        assert resultado["XYZUNKNOWN"].fuente == FUENTE_NO_DISPONIBLE

    def test_28_batch_usa_cache_existente(self):
        """Si el ticker ya está en caché, no hace HTTP."""
        # Pre-poblar caché
        with patch("requests.get", return_value=_mock_cg_response(85000.0)):
            obtener_precio_historico("BTC", 2024)
        # Segunda llamada en batch no debe hacer HTTP adicional
        with patch("requests.get") as mock_get:
            resultado = obtener_precios_historicos(["BTC"], 2024)
        mock_get.assert_not_called()
        assert resultado["BTC"].precio_eur == Decimal("85000.000000")

    def test_29_batch_lista_vacia(self):
        """Lista vacía retorna dict vacío."""
        resultado = obtener_precios_historicos([], 2024)
        assert resultado == {}


# ═══════════════════════════════════════════════════════════════════════════════
# BLOQUE 5 — enriquecer_721_con_precios
# ═══════════════════════════════════════════════════════════════════════════════

def _precio_btc(ejercicio=2024, precio=85000.0) -> PrecioHistorico:
    return PrecioHistorico(
        ticker="BTC", ejercicio=ejercicio, fecha_corte=date(ejercicio, 12, 31),
        precio_eur=Decimal(str(precio)), fuente=FUENTE_COINGECKO,
        estimado=False, coingecko_id="bitcoin",
        nota=f"Precio CoinGecko a 31/12/{ejercicio}: {precio} EUR.",
    )


def _precio_usdt(ejercicio=2024, precio=0.92) -> PrecioHistorico:
    return PrecioHistorico(
        ticker="USDT", ejercicio=ejercicio, fecha_corte=date(ejercicio, 12, 31),
        precio_eur=Decimal(str(precio)), fuente=FUENTE_ESTIMADO_BCE,
        estimado=True, coingecko_id=None,
        nota=f"Stablecoin USD. Valor EUR estimado BCE a 31/12/{ejercicio}.",
    )


def _precio_no_disponible(ticker="XYZ", ejercicio=2024) -> PrecioHistorico:
    return PrecioHistorico(
        ticker=ticker, ejercicio=ejercicio, fecha_corte=date(ejercicio, 12, 31),
        precio_eur=None, fuente=FUENTE_NO_DISPONIBLE,
        estimado=False, coingecko_id=None,
        nota=f"'{ticker}' no disponible.",
    )


class TestEnriquecer721ConPrecios:

    def test_30_enriquece_valor_eur(self):
        """valor_eur se calcula correctamente: precio × cantidad."""
        datos = _datos_721_simple("BTC", "0.5", 2024)
        precios = {"BTC": _precio_btc(precio=85000.0)}
        enriquecido = enriquecer_721_con_precios(datos, precios)
        activo = enriquecido["exchanges"][0]["activos"][0]
        assert activo["valor_eur"]    == "42500.00"   # 85000 × 0.5
        assert activo["origen_valor"] == "O"

    def test_31_total_valor_eur_calculado(self):
        """total_valor_eur se calcula cuando todos los activos tienen precio."""
        datos = _datos_721_simple("BTC", "0.5", 2024)
        precios = {"BTC": _precio_btc(precio=85000.0)}
        enriquecido = enriquecer_721_con_precios(datos, precios)
        assert enriquecido["total_valor_eur"] == "42500.00"

    def test_32_sin_precio_valor_eur_sigue_none(self):
        """Si no hay precio, valor_eur permanece None."""
        datos = _datos_721_simple("XYZ", "100", 2024)
        precios = {"XYZ": _precio_no_disponible("XYZ")}
        enriquecido = enriquecer_721_con_precios(datos, precios)
        activo = enriquecido["exchanges"][0]["activos"][0]
        assert activo["valor_eur"] is None

    def test_33_total_eur_none_si_falta_algun_precio(self):
        """total_valor_eur es None si algún activo no tiene precio."""
        datos = _datos_721_simple("XYZ", "100", 2024)
        precios = {"XYZ": _precio_no_disponible("XYZ")}
        enriquecido = enriquecer_721_con_precios(datos, precios)
        assert enriquecido["total_valor_eur"] is None

    def test_34_advertencia_pendiente_se_reemplaza(self):
        """La advertencia genérica de precio-pendiente se sustituye por la nota de trazabilidad."""
        datos = _datos_721_simple("BTC", "0.5", 2024)
        precios = {"BTC": _precio_btc()}
        enriquecido = enriquecer_721_con_precios(datos, precios)
        activo = enriquecido["exchanges"][0]["activos"][0]
        advertencias = activo["advertencias"]
        # No deben quedar advertencias de precio-pendiente
        assert not any("no calculable" in a for a in advertencias)
        assert not any("Actualizar manualmente" in a for a in advertencias)
        # Sí debe haber la nota de trazabilidad
        assert any("CoinGecko" in a for a in advertencias)

    def test_35_stablecoin_advertencia_bce_reemplaza(self):
        """Advertencia de stablecoin se reemplaza por nota BCE."""
        datos = _datos_721_simple("USDT", "1000", 2024)
        # Añadir advertencia de stablecoin como la genera modelo721.py
        datos["exchanges"][0]["activos"][0]["advertencias"] = [
            "Stablecoin vinculada al USD. Valor EUR ≈ tipo de cambio EUR/USD "
            "oficial (BCE) a 31/12/2024. Actualizar manualmente."
        ]
        precios = {"USDT": _precio_usdt()}
        enriquecido = enriquecer_721_con_precios(datos, precios)
        activo = enriquecido["exchanges"][0]["activos"][0]
        advertencias = activo["advertencias"]
        assert not any("Actualizar manualmente" in a for a in advertencias)
        assert any("BCE" in a or "Stablecoin" in a or "bce" in a.lower() for a in advertencias)

    def test_36_no_muta_original(self):
        """enriquecer_721_con_precios no muta el dict original."""
        datos = _datos_721_simple("BTC", "0.5", 2024)
        precios = {"BTC": _precio_btc(precio=85000.0)}
        import copy
        datos_copia = copy.deepcopy(datos)
        enriquecer_721_con_precios(datos, precios)
        assert datos == datos_copia

    def test_37_multiples_activos_todos_con_precio(self):
        """Múltiples activos todos con precio → total_valor_eur es suma correcta."""
        datos = {
            "modelo": "721", "ejercicio": 2024, "fecha_referencia": "31-12-2024",
            "potencialmente_obligado": True, "informe_orientativo": True,
            "total_valor_eur": None,
            "exchanges": [{
                "exchange": "Binance", "exchange_key": "binance",
                "pais_custodio": None, "codigo_pais_iso": None, "extranjero": True,
                "nif_custodio": None, "web_custodio": None, "requiere_revision": True,
                "activos": [
                    {
                        "activo": "BTC", "denominacion": "Bitcoin", "siglas": "BTC",
                        "cantidad": "1.0", "valor_eur": None, "origen_valor": None,
                        "coste_base_fifo": "20000.00", "clave": "T",
                        "origen_moneda_virtual": "A", "fecha_referencia": "31-12-2024",
                        "requiere_revision": True, "advertencias": [
                            "Valor de mercado de BTC a 31/12/2024 no calculable desde el historial."
                        ],
                    },
                    {
                        "activo": "ETH", "denominacion": "Ethereum", "siglas": "ETH",
                        "cantidad": "10.0", "valor_eur": None, "origen_valor": None,
                        "coste_base_fifo": "15000.00", "clave": "T",
                        "origen_moneda_virtual": "A", "fecha_referencia": "31-12-2024",
                        "requiere_revision": True, "advertencias": [
                            "Valor de mercado de ETH a 31/12/2024 no calculable desde el historial."
                        ],
                    },
                ],
            }],
            "advertencias": [],
        }
        btc_precio = PrecioHistorico(
            ticker="BTC", ejercicio=2024, fecha_corte=date(2024, 12, 31),
            precio_eur=Decimal("85000.00"), fuente=FUENTE_COINGECKO,
            estimado=False, coingecko_id="bitcoin", nota="BTC ok",
        )
        eth_precio = PrecioHistorico(
            ticker="ETH", ejercicio=2024, fecha_corte=date(2024, 12, 31),
            precio_eur=Decimal("3200.00"), fuente=FUENTE_COINGECKO,
            estimado=False, coingecko_id="ethereum", nota="ETH ok",
        )
        enriquecido = enriquecer_721_con_precios(datos, {"BTC": btc_precio, "ETH": eth_precio})
        # BTC: 85000 × 1.0 = 85000.00
        # ETH: 3200 × 10.0 = 32000.00
        # Total: 117000.00
        assert enriquecido["exchanges"][0]["activos"][0]["valor_eur"] == "85000.00"
        assert enriquecido["exchanges"][0]["activos"][1]["valor_eur"] == "32000.00"
        assert enriquecido["total_valor_eur"] == "117000.00"

    def test_38_multiples_activos_uno_sin_precio(self):
        """Si un activo no tiene precio, total_valor_eur permanece None."""
        datos = _datos_721_simple("BTC", "1.0", 2024)
        datos["exchanges"][0]["activos"].append({
            "activo": "XYZUNK", "denominacion": "XYZUnknown", "siglas": "XYZUNK",
            "cantidad": "500", "valor_eur": None, "origen_valor": None,
            "coste_base_fifo": "0.00", "clave": "T",
            "origen_moneda_virtual": "A", "fecha_referencia": "31-12-2024",
            "requiere_revision": True, "advertencias": [],
        })
        precios = {
            "BTC": _precio_btc(precio=85000.0),
            "XYZUNK": _precio_no_disponible("XYZUNK"),
        }
        enriquecido = enriquecer_721_con_precios(datos, precios)
        assert enriquecido["exchanges"][0]["activos"][0]["valor_eur"] == "85000.00"
        assert enriquecido["exchanges"][0]["activos"][1]["valor_eur"] is None
        assert enriquecido["total_valor_eur"] is None

    def test_39_dict_precios_vacio_no_modifica(self):
        """Si el dict de precios está vacío, los datos quedan sin valor_eur."""
        datos = _datos_721_simple("BTC", "0.5", 2024)
        enriquecido = enriquecer_721_con_precios(datos, {})
        activo = enriquecido["exchanges"][0]["activos"][0]
        assert activo["valor_eur"] is None
        assert enriquecido["total_valor_eur"] is None

    def test_40_valor_eur_redondea_dos_decimales(self):
        """valor_eur se redondea a 2 decimales (centavos)."""
        datos = _datos_721_simple("BTC", "0.123456789", 2024)
        btc = PrecioHistorico(
            ticker="BTC", ejercicio=2024, fecha_corte=date(2024, 12, 31),
            precio_eur=Decimal("10000.123456"), fuente=FUENTE_COINGECKO,
            estimado=False, coingecko_id="bitcoin", nota="ok",
        )
        enriquecido = enriquecer_721_con_precios(datos, {"BTC": btc})
        activo = enriquecido["exchanges"][0]["activos"][0]
        # Resultado debe tener exactamente 2 decimales
        assert "." in activo["valor_eur"]
        decimales = activo["valor_eur"].split(".")[1]
        assert len(decimales) == 2
