"""S01-R02: offline, aggregate-only review of PayPal Activity Download CSV.

This tool never connects to PayPal, Railway, Stripe or a database. It only reads
a privately held local merchant report and prints fixed counters; never rows,
identifiers, buyer details, money amounts, locations, or untrusted CSV values.

It is NOT a reconciliation by itself and does NOT certify report completeness,
settlement, refunds, disputes, PayPal account identity or absence of payments.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 50_000
REQUIRED = frozenset({
    "Date", "Time", "TimeZone", "Type", "Status", "Currency",
    "Gross", "Fee", "Net", "Transaction ID", "Reference Txn ID",
    "Balance Impact", "Transaction Event Code",
})


class PrivateReportError(RuntimeError):
    pass


def checked_report(path: Path) -> None:
    """Prevent a private report from being read through links or repository files."""
    if not path.is_absolute() or path.is_symlink():
        raise PrivateReportError("Archivo CSV: ruta absoluta sin enlaces simbólicos")
    try:
        meta = path.stat()
    except OSError:
        raise PrivateReportError("No se encuentra el informe CSV local") from None
    if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
            or meta.st_mode & 0o077):
        raise PrivateReportError("El informe debe ser propio y privado (0600)")
    if not 0 < meta.st_size <= MAX_BYTES:
        raise PrivateReportError("Archivo vacío o demasiado grande")
    if path.resolve().is_relative_to(ROOT):
        raise PrivateReportError("Nunca almacenar informes PayPal dentro del repositorio")


def summarize_report(path: Path) -> dict[str, int]:
    """Parse rows privately; retain IDs only in memory to count repeated references."""
    checked_report(path)
    counts = Counter()
    observed = set()
    duplicates = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            csv.field_size_limit(32768)
            reader = csv.DictReader(stream, dialect="excel", strict=True)
            if reader.fieldnames is None:
                raise PrivateReportError("Cabecera ausente")
            fields = reader.fieldnames
            if any(not isinstance(v, str) or not v.strip() for v in fields):
                raise PrivateReportError("Cabecera no válida")
            if len(fields) != len(set(fields)) or not REQUIRED.issubset(set(fields)):
                raise PrivateReportError("Columnas PayPal obligatorias ausentes o repetidas")
            for row in reader:
                counts["filas"] += 1
                if counts["filas"] > MAX_ROWS:
                    raise PrivateReportError("Más de 50.000 filas: procesar informe por partes")
                if None in row or any(value is None for value in row.values()):
                    raise PrivateReportError("Fila CSV incompleta o con columnas extra")
                # Do not print, log or serialize any untrusted field.
                ident = row["Transaction ID"].strip()
                if ident:
                    if ident in observed:
                        duplicates.add(ident)
                    observed.add(ident)
                else:
                    counts["sin_id_transaccion"] += 1

                state = row["Status"].strip().casefold()
                if state == "completed":
                    counts["estado_completed"] += 1
                elif state in {"pending", "processing", "created", "active"}:
                    counts["estado_pendiente_o_procesando"] += 1
                elif state in {"refunded", "partially refunded", "reversed",
                               "denied", "voided", "canceled", "expired"}:
                    counts["estado_reversado_reembolsado_u_otro_cierre"] += 1
                else:
                    counts["estado_otros"] += 1

                impact = row["Balance Impact"].strip().casefold()
                if impact in {"credit", "debit"}:
                    counts["impacto_saldo_credito_debito"] += 1
                elif impact == "memo":
                    counts["impacto_saldo_memo"] += 1
                else:
                    counts["impacto_saldo_no_identificado"] += 1

                currency = row["Currency"].strip().upper()
                if currency == "EUR":
                    counts["divisa_eur"] += 1
                else:
                    counts["divisa_otra_o_ausente"] += 1

                code = row["Transaction Event Code"].strip()
                if len(code) == 5 and code.startswith("T") and code[1:].isdigit():
                    counts["tcode_formato_reconocido"] += 1
                else:
                    counts["tcode_ausente_o_no_reconocido"] += 1

                if row["Reference Txn ID"].strip():
                    counts["con_referencia_relacionada"] += 1
    except (UnicodeError, csv.Error):
        raise PrivateReportError("Error de formato/UTF-8 CSV: informe denegado") from None
    counts["ids_transaccion_distintos"] = len(observed)
    counts["grupos_id_repetido"] = len(duplicates)
    # Keep fixed integer-only result to prevent exfiltration of original rows.
    names = (
        "filas", "ids_transaccion_distintos", "sin_id_transaccion",
        "grupos_id_repetido", "estado_completed",
        "estado_pendiente_o_procesando",
        "estado_reversado_reembolsado_u_otro_cierre", "estado_otros",
        "impacto_saldo_credito_debito", "impacto_saldo_memo",
        "impacto_saldo_no_identificado", "divisa_eur",
        "divisa_otra_o_ausente", "tcode_formato_reconocido",
        "tcode_ausente_o_no_reconocido", "con_referencia_relacionada",
    )
    result = {key: int(counts[key]) for key in names}
    total = result["filas"]
    if any(v < 0 or v > total for v in result.values()):
        raise PrivateReportError("Recuentos inconsistentes")
    for group in (
        ("estado_completed", "estado_pendiente_o_procesando",
         "estado_reversado_reembolsado_u_otro_cierre", "estado_otros"),
        ("impacto_saldo_credito_debito", "impacto_saldo_memo",
         "impacto_saldo_no_identificado"),
        ("divisa_eur", "divisa_otra_o_ausente"),
        ("tcode_formato_reconocido", "tcode_ausente_o_no_reconocido"),
    ):
        if sum(result[k] for k in group) != total:
            raise PrivateReportError("Recuentos inconsistentes")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0 or os.environ.get("GITHUB_ACTIONS") == "true":
        raise PrivateReportError("No ejecutar como root ni dentro de CI")
    result = summarize_report(args.csv)
    print("S01 G05 PAYPAL CSV: informe local procesado; solo recuentos", flush=True)
    for name, value in result.items():
        print(f"S01 G05 {name}: {value}", flush=True)
    print(
        "S01 G05: PASS LECTURA LOCAL; alcance/periodo/cuenta NO VERIFICADOS; "
        "ninguna fila se atribuye automáticamente a S01; G05 ABIERTO",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except PrivateReportError as exc:
        print(f"S01 G05: NO-GO ({exc})", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # File paths / business rows / CSV contents can leak via exception text.
        print("S01 G05: NO-GO (error interno " + type(exc).__name__
              + "; detalles protegidos)", file=sys.stderr)
        sys.exit(1)
