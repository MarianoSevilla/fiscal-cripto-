"""Conciliación histórica Binance del HISTORIAL GENERAL, sin calcular impuestos.

Lee ZIP originales uno a uno y una fila cada vez: memoria proporcional al
número de activos/cuentas, no al número de operaciones. El saldo del ledger
general NO equivale al inventario global Spot/Earn/Funding ni acredita lotes
FIFO, fechas de adquisición o valores EUR. No exporta datos de cliente.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Iterable


class BinanceHistoricalLedgerError(ValueError):
    """Error de la auditoría local; no contiene contenido privado."""


_EXPECTED = {
    "ID de usuario", "Tiempo", "Cuenta", "Operación",
    "Moneda", "Cambio", "Observación",
}
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,29}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_TZ = re.compile(r"\(UTC[+-]\d{1,2}\)")
_NO_DATA_SENTINEL = "no hay datos que se ajusten a los criterios"


@dataclass(frozen=True)
class BinanceHistoricalLedgerResult:
    registros: int
    archivos: int
    activos_distintos: int
    registros_por_ejercicio: tuple[tuple[int, int], ...]
    registros_por_operacion: tuple[tuple[str, int], ...]
    saldos_netos: tuple[tuple[str, Decimal], ...]
    netos_earn_flexible: tuple[tuple[str, Decimal], ...]
    saldos_por_cuenta: tuple[tuple[str, str, Decimal], ...]
    primeras_insuficiencias: tuple[tuple[str, str, Decimal], ...]

    @property
    def sin_saldos_negativos_globales(self) -> bool:
        return not self.primeras_insuficiencias

    @property
    def fifo_fiscal_acreditado(self) -> bool:
        # El libro general no suministra lotes de compras originales, EUR
        # histórico, rendimientos e inventario de todas las billeteras.
        return False


def inspeccionar_historial_binance(
    archivos: Iterable[str | Path], *,
    hasta_local: str | None = None,
    max_archivos: int = 12,
    max_registros: int = 500_000,
    max_csv_bytes: int = 16 * 1024 * 1024,
    max_total_bytes: int = 80 * 1024 * 1024,
) -> BinanceHistoricalLedgerResult:
    """Audita ZIP de Transaction History ordenados temporalmente.

    Este diagnóstico es local/solo lectura. NO usarlo como fuente de lotes
    fiscales ni para desactivar los bloqueos del endpoint FIFO.
    Los ZIP no se extraen al disco. El lector comprueba CRC al llegar al EOF.
    """
    # Corte en horario LOCAL del nombre original (UTC±H); no convertir una
    # fecha naive a UTC. Las filas posteriores siguen verificándose completas.
    cutoff = None
    if hasta_local is not None:
        if not isinstance(hasta_local, str) or not _DATE.fullmatch(hasta_local):
            raise BinanceHistoricalLedgerError("Instante de corte local inválido")
        try:
            cutoff = datetime.strptime(hasta_local, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise BinanceHistoricalLedgerError("Fecha de corte inexistente") from exc
    paths = list(archivos)
    if not paths or len(paths) > max_archivos or max_archivos < 1:
        raise BinanceHistoricalLedgerError("Cantidad de archivos fuera del límite")
    if max_registros < 1 or max_csv_bytes < 1 or max_total_bytes < 1:
        raise BinanceHistoricalLedgerError("Límites de lectura inválidos")

    counts: Counter[int] = Counter()
    operations: Counter[str] = Counter()
    balances: dict[str, Decimal] = defaultdict(Decimal)
    per_account: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    earn_net: dict[str, Decimal] = defaultdict(Decimal)
    first_negative: dict[str, tuple[str, Decimal]] = {}
    timezone: str | None = None
    last_time: datetime | None = None
    total_bytes = 0
    number_rows = 0
    scanned_rows = 0  # El límite de seguridad incluye filas posteriores al corte.

    # No se puede dar por positivo o negativo un movimiento dentro de
    # un segundo: Binance presenta varias patas de un mismo hecho con
    # la misma marca temporal. Acumularlas antes de comprobar los saldos.
    pending_time: datetime | None = None
    pending_changes: dict[str, Decimal] = defaultdict(Decimal)

    def settle() -> None:
        if pending_time is None:
            return
        for symbol, change in pending_changes.items():
            balances[symbol] += change
            if balances[symbol] < 0 and symbol not in first_negative:
                first_negative[symbol] = (
                    pending_time.isoformat(sep=" "),
                    balances[symbol],
                )
        pending_changes.clear()

    for path in paths:
        path = Path(path)
        matched_tz = _TZ.search(path.name)
        if not matched_tz:
            raise BinanceHistoricalLedgerError("Falta zona horaria explícita en un ZIP")
        if timezone is None:
            timezone = matched_tz.group(0)
        elif timezone != matched_tz.group(0):
            raise BinanceHistoricalLedgerError("Exportaciones con zonas horarias diferentes")

        try:
            with zipfile.ZipFile(path) as zf:
                members = [m for m in zf.infolist() if not m.is_dir()]
                if len(members) != 1:
                    raise BinanceHistoricalLedgerError(
                        "Cada ZIP debe contener exactamente un CSV de historial"
                    )
                member = members[0]
                member_name = PurePosixPath(member.filename.replace("\\", "/"))
                if (len(member_name.parts) != 1 or member_name.name != member.filename
                        or not member.filename.lower().endswith(".csv")):
                    raise BinanceHistoricalLedgerError("Nombre de CSV interno no seguro")
                if member.file_size > max_csv_bytes:
                    raise BinanceHistoricalLedgerError("CSV histórico demasiado grande")
                total_bytes += member.file_size
                if total_bytes > max_total_bytes:
                    raise BinanceHistoricalLedgerError("Conjunto histórico demasiado grande")
                if member.file_size > 1_048_576 and (
                    member.file_size / max(member.compress_size, 1) > 200
                ):
                    raise BinanceHistoricalLedgerError("Compresión ZIP anómala")

                first_in_file: datetime | None = None
                previous_in_file: datetime | None = None
                with zf.open(member) as stream:
                    with io.TextIOWrapper(
                        stream, encoding="utf-8-sig", errors="strict", newline=""
                    ) as text_stream:
                        reader = csv.DictReader(text_stream)
                        fieldnames = reader.fieldnames
                        if (not fieldnames or len(fieldnames) != len(_EXPECTED)
                                or set(fieldnames) != _EXPECTED):
                            raise BinanceHistoricalLedgerError(
                                "Las columnas no corresponden al historial general Binance"
                            )
                        for record in reader:
                            scanned_rows += 1
                            if scanned_rows > max_registros:
                                raise BinanceHistoricalLedgerError(
                                    "El historial supera el límite de filas"
                                )
                            # Exportación vacía nativa: frase en primera columna
                            # y resto de celdas vacías; no inventar una operación.
                            sentinel = str(record.get("ID de usuario") or "").strip().lower()
                            if sentinel.startswith(_NO_DATA_SENTINEL):
                                if all(
                                    value is None or str(value).strip() == ""
                                    for field, value in record.items()
                                    if field != "ID de usuario"
                                ):
                                    continue
                                raise BinanceHistoricalLedgerError(
                                    "Marcador de exportación vacía con otros datos"
                                )
                            if None in record or any(v is None for v in record.values()):
                                raise BinanceHistoricalLedgerError(
                                    "Fila histórica con columnas desalineadas"
                                )
                            stamp = record["Tiempo"].strip()
                            symbol = record["Moneda"].strip().upper()
                            if not _DATE.fullmatch(stamp) or not _SYMBOL.fullmatch(symbol):
                                raise BinanceHistoricalLedgerError(
                                    "Fecha o moneda inválidas en el historial"
                                )
                            try:
                                dt = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
                                amount = Decimal(record["Cambio"].strip())
                            except (ValueError, InvalidOperation) as exc:
                                raise BinanceHistoricalLedgerError(
                                    "Fecha o cantidad inválidas en el historial"
                                ) from exc
                            if not amount.is_finite():
                                raise BinanceHistoricalLedgerError(
                                    "Cantidad no finita en el historial"
                                )
                            if previous_in_file is not None and dt < previous_in_file:
                                raise BinanceHistoricalLedgerError(
                                    "Las operaciones del CSV no están en orden cronológico"
                                )
                            if first_in_file is None:
                                first_in_file = dt
                                if last_time is not None and first_in_file <= last_time:
                                    raise BinanceHistoricalLedgerError(
                                        "Los períodos históricos se solapan o están desordenados"
                                    )
                            previous_in_file = dt
                            if cutoff is not None and dt > cutoff:
                                continue
                            if pending_time is not None and dt > pending_time:
                                settle()
                            pending_time = dt
                            pending_changes[symbol] += amount
                            number_rows += 1
                            counts[dt.year] += 1
                            kind = record["Operación"].strip()
                            operations[kind] += 1
                            per_account[(record["Cuenta"].strip(), symbol)] += amount
                            if kind in (
                                "Simple Earn Flexible Subscription",
                                "Simple Earn Flexible Redemption",
                            ):
                                # Salida de Spot = entrada a Earn; redención inversa.
                                earn_net[symbol] -= amount

                if first_in_file is not None:
                    last_time = previous_in_file
        except (OSError, UnicodeDecodeError, zipfile.BadZipFile, RuntimeError) as exc:
            raise BinanceHistoricalLedgerError(
                "No se pudo leer íntegramente un ZIP histórico de Binance"
            ) from exc

    settle()
    return BinanceHistoricalLedgerResult(
        registros=number_rows,
        archivos=len(paths),
        activos_distintos=len(balances),
        registros_por_ejercicio=tuple(sorted(counts.items())),
        registros_por_operacion=tuple(sorted(operations.items())),
        saldos_netos=tuple(sorted(balances.items())),
        netos_earn_flexible=tuple(sorted(earn_net.items())),
        saldos_por_cuenta=tuple(sorted((acct, sym, q) for (acct, sym), q in per_account.items())),
        primeras_insuficiencias=tuple(sorted(
            (sym, day, amount) for sym, (day, amount) in first_negative.items()
        )),
    )
