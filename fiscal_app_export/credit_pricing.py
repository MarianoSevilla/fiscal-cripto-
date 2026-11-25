"""Hypothetical, disabled-by-default pricing for the FIFO credits pilot.

Rows estimate the volume component. The separate file-count component is a
small operational complexity proxy, not a fiscal or CPU guarantee. Prices and
credits remain pilot configuration and must not be enabled in production
without an explicit approval.
"""
from dataclasses import dataclass


PACKAGES = {
    "basic": {"label": "Básico", "price_cents": 1590, "credits": 110},
    "standard": {"label": "Estándar", "price_cents": 2990, "credits": 230},
    "advanced": {"label": "Avanzado", "price_cents": 4990, "credits": 460},
}


@dataclass(frozen=True)
class CreditQuote:
    row_credits: int
    complexity_credits: int
    max_credits: int
    rows: int
    files: int


def quote_analysis(*, rows: int, files: int) -> CreditQuote:
    """Quote a maximum from validated row/file counts, without FIFO execution.

    The row bands are anchored to the supplied production percentiles
    (P50=442, P75=2,292, P90=6,298, P99=33,519). Files beyond the first add
    a capped multi-file handling allowance. Inputs above current support
    limits are refused instead of silently underquoting.
    """
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
        raise ValueError("Número de filas inválido")
    if isinstance(files, bool) or not isinstance(files, int) or files < 1:
        raise ValueError("Número de archivos inválido")
    if rows > 35_000:
        raise ValueError("El volumen supera el máximo de cotización del piloto")
    row_credits = 50 if rows <= 1_000 else 100 if rows <= 3_000 else 200 if rows <= 10_000 else 400
    complexity_credits = min(60, (files - 1) * 10)
    return CreditQuote(row_credits, complexity_credits,
                       row_credits + complexity_credits, rows, files)
