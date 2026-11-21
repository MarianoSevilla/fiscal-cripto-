"""Conciliación Convert vs ledger: únicamente fixtures sintéticos."""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import csv
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_convert_ledger_evidence import (
    BinanceConvertLedgerError, audit_convert_ledger,
)
from clasificador_binance_multi import ClasificadorBinanceMulti


def native(at="2025-01-03 12:00:01", given="XRP", received="USDC",
           give="2.12345678", recv="5.87654321"):
    return SimpleNamespace(
        source="Convert", local_time=at,
        given_asset=given, received_asset=received,
        given_amount=Decimal(give), received_amount=Decimal(recv),
    )


def row(at, asset, qty, operation="Binance Convert"):
    return {
        "operación": operation, "tiempo": at, "cuenta": "Spot",
        "moneda": asset, "cambio": qty,
    }


def test_exact_legs_with_split_accounting_second_are_matched():
    audit = audit_convert_ledger([native()], [
        row("2025-01-03 12:00:02", "XRP", "-2.12345678"),
        row("2025-01-03 12:00:01", "USDC", "5.87654321"),
    ])
    assert audit.native_swaps == audit.matched == 1
    assert audit.split_seconds == 1
    assert audit.legs_at_created_second == 1
    assert audit.legs_one_second_later == 1
    assert audit.reconciled_where_ledger_exists
    assert not audit.fiscal_ready
    assert not audit.matches[0].execution_time_accredited


def test_missing_leg_on_same_ledger_day_is_blocker():
    audit = audit_convert_ledger([native()], [
        row("2025-01-03 12:00:01", "XRP", "-2.12345678"),
    ])
    assert audit.missing_on_ledger_day == 1
    assert not audit.reconciled_where_ledger_exists


def test_when_ledger_does_not_cover_that_day_no_false_block():
    audit = audit_convert_ledger([native()], [
        row("2024-12-09 12:00:01", "XRP", "-2.12345678"),
    ])
    assert audit.no_ledger_day == 1
    assert audit.reconciled_where_ledger_exists


def test_ambiguous_duplicate_legs_never_reused_or_silently_dropped():
    audit = audit_convert_ledger([native()], [
        row("2025-01-03 12:00:02", "XRP", "-2.12345678"),
        row("2025-01-03 12:00:02", "XRP", "-2.12345678"),
        row("2025-01-03 12:00:02", "USDC", "5.87654321"),
    ])
    assert audit.ambiguous == 1
    assert not audit.reconciled_where_ledger_exists


def test_identical_native_orders_cannot_reuse_single_ledger_pair():
    audit = audit_convert_ledger([native(), native()], [
        row("2025-01-03 12:00:02", "XRP", "-2.12345678"),
        row("2025-01-03 12:00:02", "USDC", "5.87654321"),
    ])
    assert audit.ambiguous == 2
    assert audit.matched == 0


def test_quantity_or_instant_outside_window_does_not_match():
    audit = audit_convert_ledger([native()], [
        row("2025-01-03 12:00:05", "XRP", "-2.12345678"),
        row("2025-01-03 12:00:02", "USDC", "5.87654320"),
    ])
    assert audit.missing_on_ledger_day == 1
    assert not audit.reconciled_where_ledger_exists


@pytest.mark.parametrize("qty", ["NaN", "Infinity", "0", "", 0.1])
def test_bad_decimal_is_refused(qty):
    with pytest.raises(BinanceConvertLedgerError):
        audit_convert_ledger([native()], [
            row("2025-01-03 12:00:02", "XRP", qty)
        ])


def _csv(tmp_path, filename, columns, rows):
    p = tmp_path / filename
    with p.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        writer.writerows(rows)
    return str(p)


def test_multisource_convert_reconciliation_exact_split_and_no_second_swap(tmp_path):
    convert = _csv(tmp_path, "convert.csv",
       ["Tiempo", "Billetera", "Par", "Tipo", "Vender", "Comprar",
        "Precio", "Precio inverso", "Fecha actualizada", "Estado"],
       [["2025-01-03 12:00:01", "SPOT", "XRPUSDC", "Instant",
         "2.12345678 XRP", "5.87654321 USDC", "", "",
         "2025-01-03 12:00:02", "Successful"]])
    ledger = _csv(tmp_path, "tx.csv",
       ["ID de usuario","Tiempo","Cuenta","Operación","Moneda","Cambio","Observación"],
       [["synthetic", "2025-01-03 12:00:02", "Spot", "Binance Convert",
         "XRP", "-2.12345678", ""],
        ["synthetic", "2025-01-03 12:00:01", "Spot", "Binance Convert",
         "USDC", "5.87654321", ""]])
    c = ClasificadorBinanceMulti([convert,ledger]).clasificar()
    assert c.convert_ledger_reconciliation.matched == 1
    assert c.convert_ledger_reconciliation.split_seconds == 1
    assert c.convert_ledger_reconciliation.reconciled_where_ledger_exists
    assert len(c.swaps) == 1
    assert not c.convert_ledger_reconciliation.fiscal_ready
