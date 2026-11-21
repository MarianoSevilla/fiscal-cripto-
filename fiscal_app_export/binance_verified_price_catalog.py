"""Binance: catálogo de cotizaciones públicas verificadas, pequeño y sin red.

El constructor *offline* valida el origen público Binance Vision, ZIP, SHA256
y cada trade. El proceso Flask no descarga cotizaciones ni acepta registros
aportados por el usuario para el precio fiscal: solo lee este catálogo
administrado por el operador y fijado con SHA256 en el entorno.

Una prueba de checksum no acredita por sí sola el precio de la permuta:
se conserva timestamp, trade ID y SHA256 del ZIP de origen; el libro exige
cotización ANTERIOR y suficientemente próxima para AMBOS activos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import os
import re
import stat

from binance_eur_valuation import (
    BinanceHistoricalEURPrices, BinancePriceEvidenceError, TradePriceEvidence,
)

MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 4096
_MAX_AGE_SECONDS = 60


class BinanceCatalogError(BinancePriceEvidenceError):
    """El catálogo local no cumple su integridad/política de precios."""


def _utc_string(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise BinanceCatalogError("La cotización requiere un instante UTC")
    at = value.astimezone(timezone.utc)
    return at.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _pairs_no_duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise BinanceCatalogError("Catálogo con claves JSON duplicadas")
        obj[key] = value
    return obj


def _parse_no_constants(value):
    raise BinanceCatalogError("Número no finito en catálogo")


def serialize_verified_catalog(records, *, max_age_seconds=60):
    """Exportación determinista: solo trades públicos, nunca importes privados."""
    if not isinstance(max_age_seconds, int) or not 1 <= max_age_seconds <= _MAX_AGE_SECONDS:
        raise BinanceCatalogError("Antigüedad histórica fuera de política")
    normalized = {}
    for item in records:
        if not isinstance(item, TradePriceEvidence):
            raise BinanceCatalogError("La evidencia no es un trade público validado")
        key = (item.base, item.quote, item.public_trade_id)
        existing = normalized.get(key)
        if existing is not None and existing != item:
            raise BinanceCatalogError("Mismo trade público con evidencia diferente")
        normalized[key] = item
        if len(normalized) > MAX_RECORDS:
            raise BinanceCatalogError("Catálogo demasiado grande")
    if not normalized:
        raise BinanceCatalogError("Catálogo sin operaciones públicas")
    rows = []
    for row in sorted(normalized.values(), key=lambda x: (
        x.base, x.quote, x.observed_at, x.public_trade_id,
    )):
        rows.append({
            "base": row.base,
            "quote": row.quote,
            "price": str(row.price),
            "observed_at_utc": _utc_string(row.observed_at),
            "public_trade_id": row.public_trade_id,
            "archive_sha256": row.archive_sha256,
        })
    payload = {
        "schema_version": 1,
        "max_age_seconds": max_age_seconds,
        "trades": rows,
    }
    raw = (json.dumps(payload, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > MAX_CATALOG_BYTES:
        raise BinanceCatalogError("Catálogo supera el tamaño permitido")
    return raw


def _decode_catalog(raw):
    try:
        payload = json.loads(
            raw, object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_parse_no_constants,
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise BinanceCatalogError("Catálogo JSON inválido") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "max_age_seconds", "trades"
    } or type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise BinanceCatalogError("Versión de catálogo no compatible")
    age = payload["max_age_seconds"]
    if type(age) is not int or not 1 <= age <= _MAX_AGE_SECONDS:
        raise BinanceCatalogError("Antigüedad histórica fuera de política")
    rows = payload["trades"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_RECORDS:
        raise BinanceCatalogError("Cantidad de cotizaciones no admitida")
    evidence = []
    for raw_row in rows:
        if not isinstance(raw_row, dict) or set(raw_row) != {
            "base", "quote", "price", "observed_at_utc",
            "public_trade_id", "archive_sha256"
        }:
            raise BinanceCatalogError("Campos de cotización inválidos")
        stamp = raw_row["observed_at_utc"]
        if not isinstance(stamp, str) or not stamp.endswith("Z"):
            raise BinanceCatalogError("Cotización sin instante UTC explícito")
        try:
            when = datetime.fromisoformat(stamp[:-1] + "+00:00")
        except (ValueError, OverflowError) as exc:
            raise BinanceCatalogError("Instante de cotización inválido") from exc
        if when.year < 2017 or when.year > 2100:
            raise BinanceCatalogError("Cotización fuera del intervalo histórico")
        try:
            evidence.append(TradePriceEvidence(
                base=raw_row["base"], quote=raw_row["quote"],
                price=Decimal(str(raw_row["price"])),
                observed_at=when,
                public_trade_id=raw_row["public_trade_id"],
                archive_sha256=raw_row["archive_sha256"],
            ))
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise BinanceCatalogError("Cotización histórica no verificable") from exc
    return BinanceHistoricalEURPrices(evidence, max_age_seconds=age)


def load_pinned_verified_catalog(path, *, expected_sha256):
    """Lee una sola vez un fichero regular del servidor, fijado por SHA256.

    Ni una ruta enviada por el usuario ni una URL. Un cambio de contenido sin
    actualización explícita del hash fijado impide iniciar el servicio.
    """
    if not isinstance(path, (str, Path)) or not Path(path).is_absolute():
        raise BinanceCatalogError("La ruta de mercado debe ser absoluta y local")
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise BinanceCatalogError("Falta hash SHA256 de catálogo fijado por el operador")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                raise BinanceCatalogError("El catálogo no es un fichero regular")
            raw = fh.read(MAX_CATALOG_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise BinanceCatalogError("No se puede leer el catálogo de mercado local") from exc
    if not raw or len(raw) > MAX_CATALOG_BYTES:
        raise BinanceCatalogError("Catálogo local vacío o excesivo")
    digest = sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise BinanceCatalogError("El catálogo ha cambiado respecto a su SHA256 fijado")
    return _decode_catalog(raw)
