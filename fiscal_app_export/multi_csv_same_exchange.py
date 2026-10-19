"""Conservative consolidation of identifiable same-exchange CSV exports.

No taxpayer ownership validation or cross-exchange FIFO. Existing fiscal parsers
continue to calculate the result from the one consolidated temporary file.
"""
import csv

# Native *operation* identifiers. Do not confuse with exchange account IDs.
ID_COLUMNS = {
    "bitvavo": "Transaction ID",
    "coinbase": "ID",
    "kraken": "txid",
    "uphold": "Id",
}
MAX_FILES = 8
MAX_COINBASE_PREAMBLE = 20


class MultiCsvUserError(ValueError):
    """User-correctable ambiguity: never silently change a FIFO result."""


def _read_csv(path: str, exchange: str):
    with open(path, "r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        if exchange == "coinbase":
            header = None
            for index, row in enumerate(reader):
                fields = [name.strip() for name in row]
                if {"ID", "Timestamp", "Transaction Type", "Asset", "Quantity Transacted"}.issubset(fields):
                    header = fields
                    break
                if index + 1 >= MAX_COINBASE_PREAMBLE:
                    break
            if header is None:
                raise MultiCsvUserError("No se reconoce la cabecera del historial Coinbase.")
        else:
            try:
                header = [name.strip() for name in next(reader)]
            except StopIteration:
                raise MultiCsvUserError("Uno de los CSV está vacío.") from None
        if not header or len(set(header)) != len(header) or any(not col for col in header):
            raise MultiCsvUserError("Cabeceras duplicadas o vacías en uno de los CSV.")
        key = ID_COLUMNS[exchange]
        if key not in header:
            raise MultiCsvUserError(
                f"Para combinar archivos de {exchange} se necesita la columna '{key}'. "
                "Utiliza una exportación que la incluya o procesa los CSV individualmente."
            )
        rows = []
        for row in reader:
            if not row or all(not value for value in row):
                continue
            if len(row) != len(header):
                raise MultiCsvUserError("Una fila del CSV no coincide con sus cabeceras.")
            rows.append(row)
        return header, rows


def merge_csv_same_exchange(paths: list[str], exchange: str, destination: str) -> dict:
    """Deduplicate exact native transactions and reject conflicting repeats.

    No fuzzy comparison or amount/date-based deduplication: identical-value
    independent trades can be valid. KuCoin/Bitget use specialized pipelines.
    """
    if exchange not in ID_COLUMNS:
        raise MultiCsvUserError("La combinación de varios CSV aún no está disponible para este exchange.")
    if not 2 <= len(paths) <= MAX_FILES:
        raise MultiCsvUserError(f"Selecciona entre 2 y {MAX_FILES} archivos CSV.")
    canonical_header = None
    seen: dict[str, tuple[str, ...]] = {}
    rows_out: list[tuple[str, ...]] = []
    discarded = 0
    for path in paths:
        header, rows = _read_csv(path, exchange)
        if canonical_header is None:
            canonical_header = header
        elif len(header) != len(canonical_header) or set(header) != set(canonical_header):
            raise MultiCsvUserError(
                "Los CSV tienen versiones de cabecera distintas. "
                "Exporta todos con el mismo formato para evitar un FIFO incorrecto."
            )
        order = [header.index(col) for col in canonical_header]
        id_index = canonical_header.index(ID_COLUMNS[exchange])
        for original in rows:
            ordered = tuple(original[index] for index in order)
            native_id = ordered[id_index].strip()
            if not native_id:
                raise MultiCsvUserError(
                    "Hay operaciones sin identificador. No es seguro deduplicarlas automáticamente."
                )
            old = seen.get(native_id)
            if old is not None:
                if old != ordered:
                    raise MultiCsvUserError(
                        "El mismo identificador de operación aparece con datos diferentes. "
                        "Revisa los CSV y utiliza exportaciones coherentes."
                    )
                discarded += 1
                continue
            seen[native_id] = ordered
            rows_out.append(ordered)
    if not rows_out:
        raise MultiCsvUserError("Los archivos no contienen operaciones combinables.")
    # Write only after complete validation; never leave partial output on error.
    with open(destination, "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(canonical_header)
        writer.writerows(rows_out)
    return {"files": len(paths), "rows": len(rows_out), "duplicates_removed": discarded}
