"""Comparación adversarial de traslados Earn sin recompensas.

Nunca se utilizan movimientos de usuarios: todo es inventado.
"""
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from binance_earn_transfer_only import (
    BinancePrincipalOnlyAudit, validate_principal_only_motor,
)
from motor_fifo import MotorFIFO


def book_and_evidence():
    m = MotorFIFO()
    m.registrar_compra("2024-06-01 10:00:00", "XRP", 10, 20, "EUR", "EUR", 0)
    m.registrar_venta("2025-06-01 10:00:00", "XRP", 4, 12, "EUR", "EUR", 0)
    evidence = BinancePrincipalOnlyAudit(
        transfer_events=2, spot_trades=2, assets=("XRP",),
        sold=(("2025-06-01 10:00:00", "XRP", Decimal("4"), Decimal("8")),),
        remaining=(("XRP", Decimal("6"), Decimal("12")),),
    )
    return m, evidence


def test_decimal_book_matches_independent_fifo_motor():
    m, ev = book_and_evidence()
    validate_principal_only_motor(ev, m)


def test_wrong_fifo_cost_is_not_authorized():
    m, ev = book_and_evidence()
    altered = replace(ev, sold=((
        "2025-06-01 10:00:00", "XRP", Decimal("4"), Decimal("9")),))
    with pytest.raises(ValueError, match="coste FIFO"):
        validate_principal_only_motor(altered, m)


def test_wrong_disposition_units_and_order_are_not_authorized():
    m, ev = book_and_evidence()
    altered = replace(ev, sold=((
        "2025-06-01 10:00:00", "XRP", Decimal("5"), Decimal("8")),))
    with pytest.raises(ValueError, match="coste FIFO"):
        validate_principal_only_motor(altered, m)


def test_wrong_wallet_position_cost_is_not_authorized():
    m, ev = book_and_evidence()
    altered = replace(ev, remaining=((
        "XRP", Decimal("6"), Decimal("13")),))
    with pytest.raises(ValueError, match="saldo o coste"):
        validate_principal_only_motor(altered, m)


def test_wrong_wallet_quantity_is_not_authorized():
    m, ev = book_and_evidence()
    altered = replace(ev, remaining=((
        "XRP", Decimal("7"), Decimal("12")),))
    with pytest.raises(ValueError, match="saldo o coste"):
        validate_principal_only_motor(altered, m)
