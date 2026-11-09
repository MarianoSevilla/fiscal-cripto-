"""Valuación histórica EUR de permutas Binance basada en evidencias de mercado.

Módulo puro y opt-in: NO consulta proveedores, no añade paridades, no modifica
MotorFIFO y NO habilita PDFs. La descarga autenticada del dataset público
y su procedencia deben acreditarse por separado; un checksum verifica
integridad de bytes, pero no por sí solo autenticidad de origen.

Una cotización representa una ejecución pública Spot realizada ANTES o en
el instante del hecho económico. Si no hay precios recientes suficientes
para los DOS activos de una permuta, se rechaza la valoración.
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Iterable


class BinancePriceEvidenceError(ValueError):
    """La cotización histórica no es verificable para el hecho declarado."""


def _positive_decimal(value: str | Decimal, *, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BinancePriceEvidenceError(f"{name} no es un decimal válido") from exc
    if not result.is_finite() or result <= 0:
        raise BinancePriceEvidenceError(f"{name} debe ser positivo y finito")
    return result


def _utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise BinancePriceEvidenceError(f"{field} requiere fecha UTC consciente de zona")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class TradePriceEvidence:
    base: str
    quote: str
    price: Decimal
    observed_at: datetime
    public_trade_id: int
    archive_sha256: str

    def __post_init__(self):
        for field in ("base", "quote"):
            value = getattr(self, field)
            if not isinstance(value, str) or not re.fullmatch(r"[A-Z0-9]{2,20}", value):
                raise BinancePriceEvidenceError("Activo de cotización no válido")
        if self.base == self.quote:
            raise BinancePriceEvidenceError("Una cotización debe enlazar dos activos")
        object.__setattr__(self, "price", _positive_decimal(self.price, name="price"))
        object.__setattr__(self, "observed_at", _utc(self.observed_at, field="observed_at"))
        if not isinstance(self.public_trade_id, int) or self.public_trade_id < 0:
            raise BinancePriceEvidenceError("Identificador público de operación inválido")
        if not re.fullmatch(r"[0-9a-f]{64}", str(self.archive_sha256)):
            raise BinancePriceEvidenceError("SHA256 de archivo histórico inválido")


def _timestamp_utc(raw: str) -> datetime:
    """Binance Spot publica milisegundos antes de 2025 y microsegundos desde 2025."""
    try:
        number = int(raw)
        unit = 1_000_000 if number >= 10**15 else 1_000
        seconds, remainder = divmod(number, unit)
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc) + timedelta(
            microseconds=remainder if unit == 1_000_000 else remainder * 1_000
        )
    except (ValueError, OverflowError, OSError) as exc:
        raise BinancePriceEvidenceError("Timestamp Spot público inválido") from exc
    if dt.year < 2017 or dt.year > 2100:
        raise BinancePriceEvidenceError("Timestamp Spot fuera de intervalo")
    return dt


def parse_verified_binance_trade_zip(
    archive: bytes, checksum: str, *, archive_name: str, symbol: str,
    base: str, quote: str, max_archive_bytes: int = 50 * 1024 * 1024,
    max_uncompressed_bytes: int = 150 * 1024 * 1024,
    max_trades: int = 1_000_000,
) -> list[TradePriceEvidence]:
    """Carga un ZIP public-trades cuyo SHA256 concuerda con su .CHECKSUM.

    La fuente/red de la que se obtuvieron archive y checksum DEBE verificarse
    externamente. El formato sin cabecera es el publicado por Binance Vision.
    No se admite ningún archivo ZIP adicional ni miembros con rutas.
    """
    if not isinstance(archive, bytes) or not archive or len(archive) > max_archive_bytes:
        raise BinancePriceEvidenceError("ZIP histórico vacío o excesivo")
    symbol = str(symbol).upper()
    base, quote = str(base).upper(), str(quote).upper()
    if symbol != base + quote:
        raise BinancePriceEvidenceError("El símbolo no coincide con base/quote")
    if not re.fullmatch(r"[A-Z0-9]{4,40}-trades-\d{4}-\d{2}(?:-\d{2})?\.zip", archive_name):
        raise BinancePriceEvidenceError("Nombre de archivo de operaciones no reconocido")
    if not archive_name.startswith(f"{symbol}-trades-"):
        raise BinancePriceEvidenceError("ZIP histórico de símbolo distinto")
    match = re.fullmatch(
        r"\s*([a-fA-F0-9]{64})(?:[ \t]+[*]?([^\r\n]+))?\s*",
        str(checksum), re.ASCII,
    )
    if not match:
        raise BinancePriceEvidenceError("Formato .CHECKSUM inválido")
    expected_name = match.group(2)
    if expected_name and PurePosixPath(expected_name.strip()).name != archive_name:
        raise BinancePriceEvidenceError("El .CHECKSUM corresponde a otro archivo")
    digest = hashlib.sha256(archive).hexdigest()
    if digest != match.group(1).lower():
        raise BinancePriceEvidenceError("ZIP histórico no coincide con checksum")

    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            if len(members) != 1:
                raise BinancePriceEvidenceError("ZIP histórico debe contener un único CSV")
            member = members[0]
            name = PurePosixPath(member.filename.replace("\\", "/"))
            if (
                name.is_absolute() or len(name.parts) != 1
                or name.name != archive_name[:-4] + ".csv"
                or name.suffix.lower() != ".csv" or ".." in name.parts
                or member.file_size > max_uncompressed_bytes
                or member.file_size <= 0
            ):
                raise BinancePriceEvidenceError("Miembro ZIP histórico no seguro")
            if member.file_size > 1024 * 1024 and (
                member.file_size / max(member.compress_size, 1) > 200
            ):
                raise BinancePriceEvidenceError("Compresión histórica anómala")
            result: list[TradePriceEvidence] = []
            with zf.open(member) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text_stream:
                    reader = csv.reader(text_stream)
                    for idx, row in enumerate(reader):
                        if idx == 0 and row and row[0].strip().lower() in {"id", "trade id"}:
                            continue
                        if len(row) != 7:
                            raise BinancePriceEvidenceError("Registro trade histórico incompleto")
                        try:
                            trade_id = int(row[0])
                        except ValueError as exc:
                            raise BinancePriceEvidenceError("Trade ID histórico inválido") from exc
                        if len(result) >= max_trades:
                            raise BinancePriceEvidenceError("Límite de operaciones históricas superado")
                        result.append(TradePriceEvidence(
                            base=base, quote=quote,
                            price=_positive_decimal(row[1], name="precio histórico"),
                            observed_at=_timestamp_utc(row[4].strip()),
                            public_trade_id=trade_id, archive_sha256=digest,
                        ))
            if not result:
                raise BinancePriceEvidenceError("Archivo sin trades válidos")
            return result
    except (zipfile.BadZipFile, UnicodeError, OSError) as exc:
        raise BinancePriceEvidenceError("ZIP histórico ilegible") from exc


@dataclass(frozen=True)
class AssetEURPrice:
    asset: str
    unit_price_eur: Decimal
    path: tuple[TradePriceEvidence, ...]

    def __post_init__(self):
        object.__setattr__(
            self, "unit_price_eur",
            _positive_decimal(self.unit_price_eur, name="precio unitario EUR"),
        )


@dataclass(frozen=True)
class SwapEURValuation:
    given: AssetEURPrice
    received: AssetEURPrice
    given_amount: Decimal
    received_amount: Decimal
    given_value_eur: Decimal
    received_value_eur: Decimal
    fiscal_value_eur: Decimal


class BinanceHistoricalEURPrices:
    """Libro de cotizaciones públicas recientes, sin llamadas de red ni paridades."""

    DEFAULT_BRIDGES = ("USDT", "USDC", "BTC", "ETH")

    def __init__(self, evidence: Iterable[TradePriceEvidence], *, max_age_seconds: int = 60):
        if not isinstance(max_age_seconds, int) or not (1 <= max_age_seconds <= 300):
            raise ValueError("max_age_seconds fuera del intervalo 1..300")
        self.max_age_seconds = max_age_seconds
        grouped: dict[tuple[str, str], list[TradePriceEvidence]] = {}
        by_public_trade_id: dict[tuple[str, str, int], TradePriceEvidence] = {}
        for entry in evidence:
            if not isinstance(entry, TradePriceEvidence):
                raise BinancePriceEvidenceError("Evidencia de precio no válida")
            key = (entry.base, entry.quote, entry.public_trade_id)
            if key in by_public_trade_id:
                prev = by_public_trade_id[key]
                if prev.price != entry.price or prev.observed_at != entry.observed_at:
                    raise BinancePriceEvidenceError(
                        "Conflicto entre cotizaciones para el mismo trade ID público"
                    )
                continue
            by_public_trade_id[key] = entry
            grouped.setdefault((entry.base, entry.quote), []).append(entry)
        self._prices = {
            pair: sorted(rows, key=lambda e: (e.observed_at, e.public_trade_id))
            for pair, rows in grouped.items()
        }
        self._times = {
            pair: [entry.observed_at for entry in rows]
            for pair, rows in self._prices.items()
        }

    def _last_trade(self, base: str, quote: str, at: datetime) -> TradePriceEvidence | None:
        pair = (base, quote)
        timestamps = self._times.get(pair)
        if not timestamps:
            return None
        idx = bisect.bisect_right(timestamps, at) - 1
        if idx < 0:
            return None
        obs = self._prices[pair][idx]
        if at - obs.observed_at > timedelta(seconds=self.max_age_seconds):
            return None
        return obs

    def _pair_rate(
        self, base: str, quote: str, at: datetime
    ) -> tuple[Decimal, tuple[TradePriceEvidence, ...]] | None:
        if base == quote:
            return Decimal("1"), ()
        obs = self._last_trade(base, quote, at)
        if obs is not None:
            return obs.price, (obs,)
        inverse = self._last_trade(quote, base, at)
        if inverse is not None:
            return Decimal("1") / inverse.price, (inverse,)
        return None

    def price_eur(self, asset: str, at: datetime) -> AssetEURPrice:
        at = _utc(at, field="fecha de valoración")
        asset = asset.strip().upper()
        if asset == "EUR":
            return AssetEURPrice("EUR", Decimal("1"), ())
        direct = self._pair_rate(asset, "EUR", at)
        if direct is not None:
            return AssetEURPrice(asset, direct[0], direct[1])
        for bridge in self.DEFAULT_BRIDGES:
            if bridge == asset:
                continue
            left = self._pair_rate(asset, bridge, at)
            right = self._pair_rate(bridge, "EUR", at)
            if left is not None and right is not None:
                return AssetEURPrice(asset, left[0] * right[0], left[1] + right[1])
        raise BinancePriceEvidenceError(
            f"No existe evidencia reciente de precio EUR de {asset}. "
            "No se presupone paridad ni cotización."
        )

    def value_swap(
        self, *, timestamp: datetime, given_asset: str, given_amount: Decimal,
        received_asset: str, received_amount: Decimal,
    ) -> SwapEURValuation:
        at = _utc(timestamp, field="fecha de permuta")
        if given_asset.upper() == received_asset.upper():
            raise BinancePriceEvidenceError("Una transferencia del mismo activo no es permuta")
        give_qty = _positive_decimal(given_amount, name="cantidad entregada")
        recv_qty = _positive_decimal(received_amount, name="cantidad recibida")
        given = self.price_eur(given_asset, at)
        received = self.price_eur(received_asset, at)
        given_value = give_qty * given.unit_price_eur
        received_value = recv_qty * received.unit_price_eur
        return SwapEURValuation(
            given=given, received=received,
            given_amount=give_qty, received_amount=recv_qty,
            given_value_eur=given_value, received_value_eur=received_value,
            fiscal_value_eur=max(given_value, received_value),
        )
