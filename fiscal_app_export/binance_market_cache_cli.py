"""Generador EXCLUSIVAMENTE offline de un catálogo Binance Vision verificable.

Ejecutar por un operador con conexión HTTPS fuera del servidor Flask.
Entrada: manifiesto PRIVADO con instantes UTC y los dos activos (sin montos).
Salida: pruebas de trades públicos, precios y SHA256 de un JSON compacto.
NO SUBIR al repositorio el manifiesto de transacciones del usuario ni el
catálogo derivado sin revisión (los instantes pueden revelar actividad).
No altera DB, PR, despliegues ni cuentas.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from binance_eur_valuation import BinanceHistoricalEURPrices, BinancePriceEvidenceError
from binance_public_price_source import fetch_official_spot_trades
from binance_verified_price_catalog import (
    BinanceCatalogError, serialize_verified_catalog, load_pinned_verified_catalog,
)

MAX_EVENTS = 200
MAX_ARCHIVE_ATTEMPTS = 160
BRIDGES = ("USDT", "USDC", "BTC", "ETH")
_ASSET = re.compile(r"[A-Z0-9]{2,20}")


def parse_private_manifest(raw: bytes):
    """Devuelve eventos UTC sin importes; falla cerrado con tipos/formato extraños."""
    if not isinstance(raw, bytes) or not raw or len(raw) > 64 * 1024:
        raise BinanceCatalogError("Manifiesto vacío o excesivo")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise BinanceCatalogError("Manifiesto no es JSON válido") from exc
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or not isinstance(data.get("events"), list)
            or not 1 <= len(data["events"]) <= MAX_EVENTS):
        raise BinanceCatalogError("Manifiesto de hechos no reconocido")
    results = []
    for item in data["events"]:
        if not isinstance(item, dict) or set(item) != {
            "timestamp_utc", "given_asset", "received_asset"
        }:
            raise BinanceCatalogError("Campos de hecho económico no reconocidos")
        raw_time = item["timestamp_utc"]
        if not isinstance(raw_time, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", raw_time
        ):
            raise BinanceCatalogError("Hecho económico sin instante UTC exacto")
        try:
            at = datetime.strptime(raw_time, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError as exc:
            raise BinanceCatalogError("Fecha del manifiesto inexistente") from exc
        given, received = item["given_asset"], item["received_asset"]
        if any(not isinstance(x, str) or not _ASSET.fullmatch(x)
               for x in (given, received)) or given == received or "EUR" in (given, received):
            raise BinanceCatalogError("Permuta del manifiesto no es cripto-cripto válida")
        results.append((at, given, received))
    return tuple(sorted(results))


def build_public_price_catalog(events, *, fetcher=fetch_official_spot_trades,
                               max_age_seconds=60):
    """Intenta pares directos EUR y puentes con cotización EUR verdadera.

    Solo se aceptan evidencias validadas. Un ZIP mensual enorme, par no
    listado, día sin trades o mercado obsoleto impide cerrar un swap.
    Nunca usa precio supuesto, paridad de stablecoin ni trading posterior.
    """
    events = tuple(events)
    if not 1 <= len(events) <= MAX_EVENTS:
        raise BinanceCatalogError("Número de permutas fuera de intervalo")
    days = defaultdict(set)
    assets_by_day = defaultdict(set)
    all_targets = defaultdict(lambda: defaultdict(set))
    for at, given, received in events:
        if at.tzinfo is None or at.utcoffset() is None:
            raise BinanceCatalogError("Permuta sin instante UTC")
        at = at.astimezone(timezone.utc)
        day = at.date().isoformat()
        days[day].add(at)
        for asset in (given, received):
            assets_by_day[day].add(asset)
            all_targets[(day,asset)][asset].add(at)
    attempts = {}
    evidence = []
    errors = {}

    def _try(base, quote, day):
        if base == quote:
            return
        key = (base, quote, day)
        if key not in attempts:
            if len(attempts) >= MAX_ARCHIVE_ATTEMPTS:
                raise BinanceCatalogError("Se superó el máximo de archivos públicos a consultar")
            try:
                result = fetcher(
                    symbol=base + quote, base=base, quote=quote,
                    period=day, target_times=sorted(days[day]),
                    max_age_seconds=max_age_seconds,
                )
                if not result:
                    raise BinancePriceEvidenceError("No hay trades públicos recientes")
                attempts[key] = tuple(result)
                evidence.extend(result)
            except BinancePriceEvidenceError as exc:
                attempts[key] = ()
                errors[key] = type(exc).__name__
        return attempts[key]

    def _pair(a, b, day):
        _try(a, b, day)
        _try(b, a, day)

    def _has_all(asset, times):
        try:
            book = BinanceHistoricalEURPrices(
                evidence, max_age_seconds=max_age_seconds
            )
            for at in times:
                book.price_eur(asset, at)
            return True
        except BinancePriceEvidenceError:
            return False

    unresolved = []
    for day in sorted(days):
        for asset in sorted(assets_by_day[day]):
            at_times = tuple(sorted(all_targets[(day, asset)][asset]))
            if asset == "EUR":
                continue
            _pair(asset, "EUR", day)
            if _has_all(asset, at_times):
                continue
            for bridge in BRIDGES:
                if bridge == asset:
                    continue
                _pair(asset, bridge, day)
                _pair(bridge, "EUR", day)
                if _has_all(asset, at_times):
                    break
            if not _has_all(asset, at_times):
                unresolved.append((day, asset))
    if unresolved:
        # No crear catálogo parcial de apariencia completa.
        raise BinanceCatalogError(
            f"No se acreditaron {len(unresolved)} combinaciones activo/día "
            f"con trades públicos anteriores y recientes. "
            f"Archivos públicos consultados: {len(attempts)}."
        )
    book = BinanceHistoricalEURPrices(evidence, max_age_seconds=max_age_seconds)
    for at, given, received in events:
        book.value_swap(
            timestamp=at, given_asset=given, given_amount=1,
            received_asset=received, received_amount=1,
        )
    return serialize_verified_catalog(evidence, max_age_seconds=max_age_seconds), {
        "events": len(events), "unique_asset_days": sum(len(v) for v in assets_by_day.values()),
        "archive_attempts": len(attempts),
        "archive_matched": sum(bool(v) for v in attempts.values()),
        "market_records": len(evidence),
        "archive_unavailable": len(errors),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.manifest.resolve() == args.output.resolve():
        parser.error("No sobrescribir el manifiesto privado")
    events = parse_private_manifest(args.manifest.read_bytes())
    raw, result = build_public_price_catalog(events)
    # Escribir el catálogo solo tras verificar TODAS las cotizaciones.
    # No sobrescribir pruebas anteriores sin revisión del operador.
    with args.output.open("xb") as fh:
        fh.write(raw)
    digest = sha256(raw).hexdigest()
    # Comprobar lectura reproducible con el mismo hash que se fijaría.
    loaded = load_pinned_verified_catalog(args.output.resolve(), expected_sha256=digest)
    assert isinstance(loaded, BinanceHistoricalEURPrices)
    print(f"CATALOGO_PUBLICO_OK SHA256={digest}")
    print("ALCANCE " + json.dumps(result, sort_keys=True))
    print("NOTA: el catálogo requiere revisión y configuración por un operador; "
          "NO se ha modificado la aplicación ni habilitado un PDF real.")


if __name__ == "__main__":
    main()
