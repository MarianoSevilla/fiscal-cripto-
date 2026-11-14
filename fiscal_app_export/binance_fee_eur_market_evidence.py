"""Cotización pública de referencia para comisiones BNB de compras Spot/EUR.

Entrada: auditor de adquisiciones EUR + catálogo privado de trades públicos
Binance Vision. Sin API, sin datos de usuario persistidos y sin alterar MotorFIFO.
Solo se valoran muestras con archivo comprobado contra CHECKSUM oficial;
un precio de mercado no acredita coste de adquisición ni resultado fiscal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re


class BinanceFeeMarketError(ValueError):
    """Entrada de cotizaciones o fechas no fiable."""


@dataclass(frozen=True)
class BinanceFeeMarketEvidence:
    native_ordinal: int
    fee_quantity: Decimal
    timestamp_utc: str
    observed_at_utc: str | None
    public_trade_id: int | None
    archive_sha256: str | None
    price_bnb_eur: Decimal | None
    market_value_eur: Decimal | None
    reason: str

    @property
    def fiscal_ready(self) -> bool:
        return False


@dataclass(frozen=True)
class BinanceFeeMarketAudit:
    candidates: tuple[BinanceFeeMarketEvidence, ...]
    market_reference_count: int
    pending_market_reference_count: int

    @property
    def fiscal_ready(self) -> bool:
        return False


def _positive_decimal(value):
    if type(value) not in (str, int, Decimal):
        raise BinanceFeeMarketError("Cotización o cantidad inválida")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise BinanceFeeMarketError("Cotización o cantidad inválida") from exc
    if not number.is_finite() or number <= 0:
        raise BinanceFeeMarketError("Cotización o cantidad inválida")
    return number


def _utc_trade_stamp(raw):
    if not isinstance(raw, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", raw
    ):
        raise BinanceFeeMarketError("Marca temporal de mercado inválida")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BinanceFeeMarketError("Marca temporal de mercado inválida") from exc


def auditar_precio_eur_comisiones_bnb(
    acquisition_evidence, market_catalog, *, export_utc_offset_minutes,
    independently_verified_archive_sha256,
) -> BinanceFeeMarketAudit:
    """Coteja el último trade BNBEUR público anterior a cada comisión.

    El huso es el offset FIJO expresado en el export de Binance, no el del
    ordenador ni un supuesto horario de verano. Máximo desfase: 60 segundos.
    Los SHA se reciben del verificador externo de CHECKSUM; este módulo
    jamás considera auténtico un hash por estar escrito en un JSON.
    """
    if (type(export_utc_offset_minutes) is not int
            or not -12 * 60 <= export_utc_offset_minutes <= 14 * 60):
        raise BinanceFeeMarketError("Zona horaria de Binance no verificada")
    if (not isinstance(market_catalog, dict)
            or market_catalog.get("schema_version") != 1
            or type(market_catalog.get("max_age_seconds")) is not int
            or not 1 <= market_catalog["max_age_seconds"] <= 60
            or not isinstance(market_catalog.get("trades"), list)):
        raise BinanceFeeMarketError("Catálogo de mercado no verificable")
    if not isinstance(independently_verified_archive_sha256, (set, frozenset)):
        raise BinanceFeeMarketError("Checksums públicos no verificados")
    sha_pattern = re.compile(r"[0-9a-f]{64}")
    if not all(
        isinstance(h, str) and sha_pattern.fullmatch(h)
        for h in independently_verified_archive_sha256
    ):
        raise BinanceFeeMarketError("Checksums públicos no verificados")

    # Solo trades BNBEUR con procedencia completa: nunca BNBUSDT ~= BNBEUR.
    all_trades = []
    for item in market_catalog["trades"]:
        if not isinstance(item, dict):
            raise BinanceFeeMarketError("Fila de mercado no verificable")
        if item.get("base") != "BNB" or item.get("quote") != "EUR":
            continue
        sha = item.get("archive_sha256")
        trade_id = item.get("public_trade_id")
        if (not isinstance(sha, str)
                or not sha_pattern.fullmatch(sha)
                or type(trade_id) is not int or trade_id < 0):
            raise BinanceFeeMarketError("Procedencia de mercado incompleta")
        ts = _utc_trade_stamp(item.get("observed_at_utc"))
        price = _positive_decimal(item.get("price"))
        all_trades.append((ts, price, trade_id, sha))
    all_trades.sort(key=lambda t: t[0])
    records = []
    for candidate in getattr(acquisition_evidence, "candidates", ()):
        if getattr(candidate, "outstanding_reason", None) != (
            "comision_en_tercer_activo_sin_eur"
        ) or getattr(candidate, "fee_asset", None) != "BNB":
            continue
        stamp = getattr(candidate, "local_time", "")
        if not isinstance(stamp, str) or len(stamp) != 19:
            raise BinanceFeeMarketError("Segundo de comisión no acreditado")
        try:
            event_local = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise BinanceFeeMarketError("Segundo de comisión no acreditado") from exc
        event_utc = event_local.replace(tzinfo=timezone.utc) - timedelta(
            minutes=export_utc_offset_minutes
        )
        fee_qty = _positive_decimal(getattr(candidate, "fee_quantity", None))
        ordinal = getattr(candidate, "native_ordinal", None)
        if type(ordinal) is not int or ordinal < 0:
            raise BinanceFeeMarketError("Ordinal nativo no verificable")
        event_label = event_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        matching = [
            trade for trade in all_trades
            if timedelta(0) <= event_utc - trade[0]
            <= timedelta(seconds=market_catalog["max_age_seconds"])
        ]
        verified = [
            trade for trade in matching
            if trade[3] in independently_verified_archive_sha256
        ]
        best = None
        reason = "sin_cotizacion_en_ventana"
        if matching and not verified:
            reason = "archivo_publico_no_verificado"
        if verified:
            latest = max(t[0] for t in verified)
            choices = [t for t in verified if t[0] == latest]
            # No seleccionar arbitrariamente dos trades simultáneos
            # de precio diferente cuando el evento privado no tiene micros.
            if len({t[1] for t in choices}) == 1:
                best = min(choices, key=lambda t: t[2])
                reason = "referencia_mercado_verificada"
            else:
                reason = "trades_publicos_ambiguos"
        records.append(BinanceFeeMarketEvidence(
            native_ordinal=ordinal, fee_quantity=fee_qty,
            timestamp_utc=event_label,
            observed_at_utc=(best[0].isoformat().replace("+00:00", "Z")
                             if best else None),
            public_trade_id=best[2] if best else None,
            archive_sha256=best[3] if best else None,
            price_bnb_eur=best[1] if best else None,
            market_value_eur=(fee_qty * best[1] if best else None),
            reason=reason,
        ))
    priced = sum(1 for r in records if r.market_value_eur is not None)
    return BinanceFeeMarketAudit(
        candidates=tuple(records),
        market_reference_count=priced,
        pending_market_reference_count=len(records) - priced,
    )
