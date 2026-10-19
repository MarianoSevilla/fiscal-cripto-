"""Same-exchange CSV consolidation with conservative fiscal integrity guards.

Native transaction identifiers deduplicate exact overlaps; they do NOT prove
ownership. Ambiguous ordering is rejected rather than guessing FIFO lots.
"""
import csv
from datetime import datetime, timezone
from pathlib import Path

ID_COLUMNS = {"bitvavo": "Transaction ID", "coinbase": "ID",
              "kraken": "txid", "uphold": "Id"}
MAX_FILES = 8
MAX_ROWS = 100_000
MAX_RAW_ROWS = 800_000
MAX_COLUMNS = 80
MAX_COINBASE_PREAMBLE = 20


class MultiCsvUserError(ValueError):
    """User-correctable import ambiguity; do not emit a fiscal report."""


def _bitvavo_header(header):
    # Reuse the actual per-exchange parser's accepted column aliases.
    from clasificador_bitvavo import _COL_ALIASES, _COLS_OBLIGATORIAS
    aliases = {variant: canonical for canonical, values in _COL_ALIASES.items()
               for variant in values}
    normalized = [aliases.get(col, col) for col in header]
    if not set(_COLS_OBLIGATORIAS).issubset(normalized):
        return None
    return normalized


def _open_format(path: str, exchange: str):
    """Select only known Bitvavo variants; otherwise preserve the CSV contract."""
    if exchange != "bitvavo":
        return "utf-8-sig", ","
    for encoding in ("utf-8-sig", "latin1"):
        # Verify the entire file in constant memory; the parser supports Latin-1.
        try:
            with open(path, encoding=encoding, errors="strict") as f:
                for chunk in iter(lambda: f.read(64 * 1024), ""):
                    pass
        except UnicodeError:
            continue
        for delimiter in (",", ";", "\t"):
            try:
                with open(path, encoding=encoding, newline="") as f:
                    header = [x.strip() for x in next(csv.reader(f, delimiter=delimiter))]
                if _bitvavo_header(header) is not None and "Transaction ID" in header:
                    return encoding, delimiter
            except (StopIteration, UnicodeError, csv.Error):
                continue
    raise MultiCsvUserError(
        "No se reconoce el formato Bitvavo o falta la columna Transaction ID. "
        "Comprueba la exportación antes de combinar archivos."
    )


def _read_csv(path: str, exchange: str):
    """Return a context-managed streaming reader and canonical header."""
    encoding, delimiter = _open_format(path, exchange)
    stream = open(path, "r", encoding=encoding, newline="")
    try:
        reader = csv.reader(stream, delimiter=delimiter, strict=True)
        if exchange == "coinbase":
            header = None
            for index, row in enumerate(reader):
                candidate = [col.strip() for col in row]
                if {"ID", "Timestamp", "Transaction Type", "Asset", "Quantity Transacted"}.issubset(candidate):
                    header = candidate
                    break
                if index + 1 >= MAX_COINBASE_PREAMBLE:
                    break
            if header is None:
                raise MultiCsvUserError("No se reconoce la cabecera del historial Coinbase.")
        else:
            try:
                header = [col.strip() for col in next(reader)]
            except StopIteration:
                raise MultiCsvUserError("Uno de los CSV está vacío.") from None
        if exchange == "bitvavo":
            header = _bitvavo_header(header)
            if header is None:
                raise MultiCsvUserError("El CSV Bitvavo carece de columnas obligatorias.")
        if (not header or len(header) > MAX_COLUMNS or len(set(header)) != len(header)
                or any(not col for col in header)):
            raise MultiCsvUserError("Cabeceras vacías, duplicadas o demasiado extensas.")
        if ID_COLUMNS[exchange] not in header:
            raise MultiCsvUserError(
                f"Para combinar archivos de {exchange} se necesita la columna '{ID_COLUMNS[exchange]}'."
            )
        return stream, header, reader
    except Exception:
        stream.close()
        raise


def _timestamp(exchange: str, header: list[str], row: tuple[str, ...]) -> datetime:
    data = dict(zip(header, row))
    try:
        if exchange == "bitvavo":
            zone = (data.get("Timezone") or "UTC").upper()
            if zone not in ("UTC", "GMT"):
                raise ValueError("timezone not supported")
            text = data["Date"].strip() + " " + data["Time"].strip()
            dt = datetime.fromisoformat(text)
        elif exchange == "coinbase":
            dt = datetime.fromisoformat(data["Timestamp"].strip().replace("Z", "+00:00"))
        elif exchange == "kraken":
            dt = datetime.fromisoformat(data["time"].strip().replace("Z", "+00:00"))
        else:
            text = data["Date"].strip()
            dt = datetime.strptime(text, "%a %b %d %Y %H:%M:%S GMT%z")
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except (ValueError, TypeError, KeyError):
        raise MultiCsvUserError(
            "No se puede establecer el orden cronológico de los movimientos. "
            "Revisa los formatos y zonas horarias de las exportaciones."
        ) from None


def _tie_identity(exchange: str, header: list[str], row: tuple[str, ...]):
    data = dict(zip(header, row))
    if exchange == "bitvavo":
        return data.get("Currency", "")
    if exchange == "coinbase":
        return data.get("Asset", "")
    if exchange == "uphold":
        return (data.get("Destination Currency") if data.get("Type") == "in"
                else data.get("Origin Currency")) or ""
    # Kraken has two legs under the same refid; compare different refs only.
    return data.get("asset", "")


def merge_csv_same_exchange(paths: list[str], exchange: str, destination: str) -> dict:
    if exchange not in ID_COLUMNS:
        raise MultiCsvUserError("La combinación de varios CSV aún no está disponible para este exchange.")
    if not 2 <= len(paths) <= MAX_FILES:
        raise MultiCsvUserError(f"Selecciona entre 2 y {MAX_FILES} archivos CSV.")

    header0 = None
    seen = {}
    records = []
    raw_count = 0
    discarded = 0
    for path in paths:
        stream, header, reader = _read_csv(path, exchange)
        try:
            if header0 is None:
                header0 = header
            elif len(header) != len(header0) or set(header) != set(header0):
                raise MultiCsvUserError(
                    "Los CSV tienen versiones de cabecera distintas. "
                    "Exporta todos con el mismo formato."
                )
            columns = {name: i for i, name in enumerate(header)}
            order = [columns[name] for name in header0]
            id_index = header0.index(ID_COLUMNS[exchange])
            for original in reader:
                if not original or all(not cell for cell in original):
                    continue
                raw_count += 1
                if raw_count > MAX_RAW_ROWS:
                    raise MultiCsvUserError("Demasiadas filas para combinar en una petición.")
                if len(original) != len(header):
                    raise MultiCsvUserError("Una fila del CSV no coincide con sus cabeceras.")
                row = tuple(original[i] for i in order)
                native_id = row[id_index].strip()
                if not native_id:
                    raise MultiCsvUserError(
                        "Hay operaciones sin identificador. No es seguro deduplicarlas automáticamente."
                    )
                old = seen.get(native_id)
                if old is not None:
                    if old != row:
                        raise MultiCsvUserError(
                            "El mismo identificador de operación aparece con datos diferentes. "
                            "Revisa los CSV y utiliza exportaciones coherentes."
                        )
                    discarded += 1
                    continue
                if len(records) >= MAX_ROWS:
                    raise MultiCsvUserError(
                        f"El historial combinado supera el máximo de {MAX_ROWS:,} operaciones."
                    )
                dt = _timestamp(exchange, header0, row)
                seen[native_id] = row
                records.append((dt, native_id, row))
        finally:
            stream.close()
    if not records:
        raise MultiCsvUserError("Los archivos no contienen operaciones combinables.")

    # Never let the order in which files were selected choose FIFO lots.
    records.sort(key=lambda record: record[0])
    # Fiscal ambiguity is assessed after each exchange parser has reconstructed
    # purchases, disposals and BOTH sides of swaps. Raw rows cannot express
    # those dependencies reliably. The same check covers single-CSV input.

    with open(destination, "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header0)
        writer.writerows(row for _, _, row in records)
    return {"files": len(paths), "rows": len(records), "duplicates_removed": discarded,
            "rows_read": raw_count}
