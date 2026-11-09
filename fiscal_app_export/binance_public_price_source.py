"""Descarga explícita, acotada y verificable de cotizaciones Spot públicas.

NO participa en peticiones Flask y no se llama al procesar CSV de usuarios.
Requiere TLS del sistema, host fijo, cero redirecciones y CHECKSUM publicado
junto al ZIP. No persiste datos ni maneja credenciales. Una fuente externa debe
usarse para símbolos/pares disponibles; no se inventan pares ni paridades.

Referencias de formato:
https://github.com/binance/binance-public-data
https://github.com/binance/binance-public-data/blob/master/python/download-trade.py
"""
from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Literal

from binance_eur_valuation import (
    BinancePriceEvidenceError, TradePriceEvidence, parse_verified_binance_trade_zip,
)


ORIGIN = "https://data.binance.vision"
ZIP_LIMIT = 50 * 1024 * 1024
CHECKSUM_LIMIT = 2048
TIMEOUT_SECONDS = 15


class BinanceMarketDownloadError(BinancePriceEvidenceError):
    """No se pudo obtener una fuente de mercado suficientemente verificable."""


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_official_https(url: str, *, limit: int) -> bytes:
    """Abre únicamente Binance Vision, sin redirecciones, con lectura limitada."""
    target = urllib.parse.urlsplit(url)
    if (
        target.scheme != "https" or target.netloc != "data.binance.vision"
        or not target.path.startswith("/data/spot/")
        or target.query or target.fragment
    ):
        raise BinanceMarketDownloadError("Destino histórico ajeno al origen Binance permitido")
    request = urllib.request.Request(
        url, headers={"Accept-Encoding": "identity", "User-Agent": "marianosevilla-offline-price-audit/1"},
        method="GET",
    )
    try:
        opener = urllib.request.build_opener(_NoRedirects())
        with opener.open(request, timeout=TIMEOUT_SECONDS) as resp:
            if getattr(resp, "status", None) != 200:
                raise BinanceMarketDownloadError("Descarga pública sin HTTP 200")
            content_length = resp.headers.get("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except (TypeError, ValueError) as exc:
                    raise BinanceMarketDownloadError("Content-Length público inválido") from exc
                if declared_length < 1 or declared_length > limit:
                    raise BinanceMarketDownloadError("Archivo histórico supera límite autorizado")
            raw = resp.read(limit + 1)
            if not raw or len(raw) > limit:
                raise BinanceMarketDownloadError("Archivo histórico vacío o demasiado grande")
            if content_length is not None and len(raw) != declared_length:
                raise BinanceMarketDownloadError("Lectura histórica incompleta")
            return raw
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, TimeoutError) as exc:
        raise BinanceMarketDownloadError(
            "La fuente histórica Binance no está disponible en el origen autorizado"
        ) from exc


def fetch_official_spot_trades(
    *, symbol: str, base: str, quote: str, period: str,
    granularity: Literal["daily", "monthly"] = "daily",
) -> list[TradePriceEvidence]:
    """Descarga ZIP y CHECKSUM con URL construida internamente y verifica trades.

    La operación es explícita, offline y acotada. En el endpoint público está
    prohibido realizar estas descargas por solicitud. No supone que el par esté
    listado, que haya trades suficientes ni que un precio sea fiscalmente válido.
    """
    symbol = str(symbol).upper()
    base = str(base).upper()
    quote = str(quote).upper()
    if not re.fullmatch(r"[A-Z0-9]{4,40}", symbol):
        raise BinanceMarketDownloadError("Símbolo Binance no admitido")
    if not re.fullmatch(r"[A-Z0-9]{2,20}", base) or not re.fullmatch(r"[A-Z0-9]{2,20}", quote):
        raise BinanceMarketDownloadError("Activos históricos inválidos")
    if symbol != base + quote:
        raise BinanceMarketDownloadError("Par histórico no coincide con activos")
    if granularity not in ("daily", "monthly"):
        raise BinanceMarketDownloadError("Granularidad histórica inválida")
    expected_pattern = r"\d{4}-\d{2}-\d{2}" if granularity == "daily" else r"\d{4}-\d{2}"
    if not re.fullmatch(expected_pattern, period):
        raise BinanceMarketDownloadError("Periodo histórico inválido")
    try:
        date.fromisoformat(period + ("-01" if granularity == "monthly" else ""))
    except ValueError as exc:
        raise BinanceMarketDownloadError("Fecha histórica inexistente") from exc

    filename = f"{symbol}-trades-{period}.zip"
    base_url = f"{ORIGIN}/data/spot/{granularity}/trades/{symbol}/{filename}"
    archive = _read_official_https(base_url, limit=ZIP_LIMIT)
    checksum_bytes = _read_official_https(base_url + ".CHECKSUM", limit=CHECKSUM_LIMIT)
    try:
        checksum = checksum_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise BinanceMarketDownloadError("CHECKSUM público no es ASCII") from exc
    return parse_verified_binance_trade_zip(
        archive, checksum, archive_name=filename,
        symbol=symbol, base=base, quote=quote,
        max_archive_bytes=ZIP_LIMIT,
    )
