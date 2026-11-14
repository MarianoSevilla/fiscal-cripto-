"""Offline-only extraction of a PRIVATE Binance crypto-swap market manifest.

Usage:
  python binance_market_manifest_cli.py --source /local/export-2025.zip \
      [--source /local/spot.csv ...] --output /private/manifest.json

The manifest contains UTC seconds and asset symbols ONLY: no quantities,
prices, account IDs, ledger rows, file names, or user information. Its times
remain sensitive and must never be committed or logged. This is a preparatory
step for binance_market_cache_cli.py; it does NOT verify EUR values or permit
a tax PDF. It never downloads prices or accesses a live account.
"""
from __future__ import annotations

import argparse
from datetime import timezone
import json
import os
from pathlib import Path

from binance_eur_valuation import BinancePriceEvidenceError, binance_export_time_to_utc
from binance_market_cache_cli import MAX_EVENTS, parse_private_manifest
from binance_verified_price_catalog import BinanceCatalogError

_NATIVE_SWAP_SOURCES = frozenset({"Spot BUY", "Spot SELL", "Convert"})


def build_private_market_manifest(classifier):
    """Create a bounded, deterministic source manifest without private amounts.

    Only recognized native Spot/Convert crypto-to-crypto exchanges participate.
    Unrecognized non-EUR exchanges cannot be silently omitted, because doing
    so would imply that a generated catalogue covers all native exchanges.
    The logical filenames must carry an explicit UTC offset. Every event must
    have a valid local second and two distinct crypto assets.
    """
    seen = set()
    native_swap_count = 0
    for event in getattr(classifier, "intercambios_nativos", ()):
        given, received = event.given_asset, event.received_asset
        if given == "EUR" or received == "EUR":
            continue
        if event.source not in _NATIVE_SWAP_SOURCES:
            raise BinanceCatalogError(
                "Existe un intercambio no EUR fuera de Spot/Convert; "
                "el manifiesto nativo sería incompleto."
            )
        try:
            when = binance_export_time_to_utc(event.local_time, event.filename)
        except BinancePriceEvidenceError as exc:
            raise BinanceCatalogError(
                "Una permuta no tiene fecha o zona horaria verificable."
            ) from exc
        # Separate fills may legitimately share second and assets. A single
        # public price at that second can support both; dedup ONLY the request
        # for market evidence, never the economic facts themselves.
        key = (
            when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            given, received,
        )
        seen.add(key)
        native_swap_count += 1
        if len(seen) > MAX_EVENTS:
            raise BinanceCatalogError(
                "Demasiadas marcas de mercado para el catálogo acotado; "
                "se requiere un lote de análisis más pequeño."
            )
    if not seen:
        raise BinanceCatalogError(
            "Los archivos aportados no contienen permutas Spot/Convert "
            "cripto-cripto que necesiten un manifiesto de cotizaciones."
        )
    events = [
        {"timestamp_utc": at, "given_asset": given, "received_asset": received}
        for at, given, received in sorted(seen)
    ]
    manifest = {"schema_version": 1, "events": events}
    raw = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    # The verifier used by the offline market tool is the single source of
    # truth for schema, symbols, dates and maximum size.
    parse_private_manifest(raw)
    return raw, {
        "native_swaps": native_swap_count,
        "market_events": len(events),
    }


def extract_manifest_from_files(source_paths):
    """Use exactly the same ZIP/CSV secure import boundary as the website."""
    from werkzeug.datastructures import FileStorage
    from binance_uploads import save_binance_uploads
    from clasificador_binance_multi import ClasificadorBinanceMulti

    paths = tuple(Path(s) for s in source_paths)
    if not paths:
        raise BinanceCatalogError("Faltan ZIP/CSV originales de Binance.")
    open_streams = []
    extracted = []
    try:
        uploads = []
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in {".zip", ".csv"}:
                raise BinanceCatalogError("Cada fuente debe ser ZIP o CSV local.")
            source = path.open("rb")
            open_streams.append(source)
            uploads.append(FileStorage(stream=source, filename=path.name))
        extracted, names = save_binance_uploads(uploads, prefix="binance_manifest_")
        classifier = ClasificadorBinanceMulti(extracted, names).clasificar()
        return build_private_market_manifest(classifier)
    finally:
        for source in open_streams:
            source.close()
        for path in extracted:
            try:
                os.unlink(path)
            except OSError:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, action="append",
                        help="ZIP o CSV original de Binance; repetible")
    parser.add_argument("--output", type=Path, required=True,
                        help="JSON privado, nuevo; no se sobrescribirá")
    args = parser.parse_args(argv)
    raw, summary = extract_manifest_from_files(args.source)
    target = args.output
    if not target.is_absolute():
        parser.error("La ruta de salida privada debe ser absoluta.")
    # Exclusive create, private permissions; never overwrite a prior manifest
    # and never follow an existing symlink at the output path.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(target, flags, 0o600), "wb") as out:
        out.write(raw)
    print("MANIFIESTO_PRIVADO_OK " + json.dumps(summary, sort_keys=True))
    print("No se han descargado precios ni validado el FIFO fiscal.")


if __name__ == "__main__":
    main()
