"""
LOTE 1 — Tarea 3: no cachear fallos transitorios de CoinGecko/BCE.

Antes: un 429/timeout/error HTTP de CoinGecko (o del BCE para stablecoins)
se guardaba en _precio_cache como 'no_disponible' y bloqueaba la generación
del XML 721 hasta reiniciar el proceso.

Ahora:
  · éxito                → se cachea (sin segunda petición HTTP)
  · fallo transitorio    → NO se cachea (el siguiente intento reintenta)
  · miss de catálogo     → se cachea (resultado determinista, sin HTTP)
"""

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import precios_historicos as ph
from precios_historicos import (
    obtener_precio_historico,
    FUENTE_COINGECKO,
    FUENTE_ESTIMADO_BCE,
    FUENTE_NO_DISPONIBLE,
    _precio_cache,
)


@pytest.fixture(autouse=True)
def limpiar_cache():
    _precio_cache.clear()
    yield
    _precio_cache.clear()


def test_fallo_coingecko_no_se_cachea_y_reintenta(monkeypatch):
    """429/timeout → None la primera vez; el segundo intento debe reintentar
    la petición HTTP y poder resolver el precio."""
    llamadas = []

    def fake_cg(cg_id, fecha_cg):
        llamadas.append(cg_id)
        if len(llamadas) == 1:
            return None                       # fallo transitorio (429/timeout)
        return Decimal("40000.123456")        # reintento con éxito

    monkeypatch.setattr(ph, "_coingecko_precio_eur", fake_cg)

    r1 = obtener_precio_historico("BTC", 2024)
    assert r1.precio_eur is None
    assert r1.fuente == FUENTE_NO_DISPONIBLE
    assert ("BTC", 2024) not in _precio_cache, "el fallo transitorio NO debe cachearse"

    r2 = obtener_precio_historico("BTC", 2024)
    assert r2.precio_eur == Decimal("40000.123456")
    assert r2.fuente == FUENTE_COINGECKO
    assert len(llamadas) == 2, "el segundo intento debe llegar a CoinGecko"


def test_exito_coingecko_se_cachea(monkeypatch):
    """El éxito sí se cachea: una sola petición HTTP para dos llamadas."""
    llamadas = []

    def fake_cg(cg_id, fecha_cg):
        llamadas.append(cg_id)
        return Decimal("2500.50")

    monkeypatch.setattr(ph, "_coingecko_precio_eur", fake_cg)

    r1 = obtener_precio_historico("ETH", 2024)
    r2 = obtener_precio_historico("ETH", 2024)
    assert r1.precio_eur == r2.precio_eur == Decimal("2500.50")
    assert len(llamadas) == 1, "el éxito debe servirse de caché"
    assert ("ETH", 2024) in _precio_cache


def test_fallo_bce_no_se_cachea_y_reintenta(monkeypatch):
    """Stablecoin + BCE caído → no cachear; el reintento resuelve."""
    llamadas = []

    def fake_bce(ejercicio):
        llamadas.append(ejercicio)
        if len(llamadas) == 1:
            return None                       # BCE caído / timeout
        return Decimal("0.920100")

    monkeypatch.setattr(ph, "_bce_eurusd_historico", fake_bce)

    r1 = obtener_precio_historico("USDT", 2024)
    assert r1.precio_eur is None
    assert ("USDT", 2024) not in _precio_cache

    r2 = obtener_precio_historico("USDT", 2024)
    assert r2.precio_eur == Decimal("0.920100")
    assert r2.fuente == FUENTE_ESTIMADO_BCE
    assert len(llamadas) == 2


def test_exito_bce_se_cachea(monkeypatch):
    llamadas = []

    def fake_bce(ejercicio):
        llamadas.append(ejercicio)
        return Decimal("0.950000")

    monkeypatch.setattr(ph, "_bce_eurusd_historico", fake_bce)

    obtener_precio_historico("USDC", 2024)
    obtener_precio_historico("USDC", 2024)
    assert len(llamadas) == 1
    assert ("USDC", 2024) in _precio_cache


def test_miss_de_catalogo_si_se_cachea(monkeypatch):
    """Ticker sin CoinGecko ID: resultado determinista → debe cachearse
    (y nunca tocar HTTP)."""
    def fake_cg(cg_id, fecha_cg):
        raise AssertionError("no debe haber petición HTTP para ticker desconocido")

    monkeypatch.setattr(ph, "_coingecko_precio_eur", fake_cg)

    r1 = obtener_precio_historico("ZZZNOEXISTE", 2024)
    assert r1.fuente == FUENTE_NO_DISPONIBLE
    assert ("ZZZNOEXISTE", 2024) in _precio_cache

    r2 = obtener_precio_historico("ZZZNOEXISTE", 2024)
    assert r2 is r1, "debe servirse el objeto cacheado"
