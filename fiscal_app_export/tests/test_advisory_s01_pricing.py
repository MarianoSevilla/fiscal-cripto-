"""S01 — contrato económico independiente de Stripe y de bases de datos."""
from decimal import Decimal

import pytest

from advisory_s01_pricing import (
    COMMISSION_RATE_BPS,
    QuotePricingError,
    calculate_s01_quote,
)


@pytest.mark.parametrize(
    "input_value, rafa, commission, total",
    [
        ("200", 20_000, 6_000, 26_000),
        ("200,00", 20_000, 6_000, 26_000),
        (Decimal("200.00"), 20_000, 6_000, 26_000),
        (200.0, 20_000, 6_000, 26_000),
        ("1.05", 105, 32, 137),  # 31,5 céntimos -> 32 (HALF_UP)
        ("1.04", 104, 31, 135),
        ("149.99", 14_999, 4_500, 19_499),
        ("79.90", 7_990, 2_397, 10_387),
    ],
)
def test_exact_fee_commission_and_total(input_value, rafa, commission, total):
    quote = calculate_s01_quote(input_value)
    assert quote.rafa_fee_cents == rafa
    assert quote.commission_cents == commission
    assert quote.total_cents == total
    assert quote.commission_rate_bps == COMMISSION_RATE_BPS == 3000


@pytest.mark.parametrize(
    "invalid",
    [
        None, True, False, "", " ", "-1", "0", "0.99", 0,
        "12.001", "1e3", "NaN", "Infinity", "1 000",
        "1.234,56", "1,234.56", "0002.00", {}, [],
        float("nan"), float("inf"), 1.001,
        "999999.99",
    ],
)
def test_unsafe_input_rejected(invalid):
    with pytest.raises(QuotePricingError):
        calculate_s01_quote(invalid)


def test_inputs_are_pure_and_repeatable():
    a = calculate_s01_quote("330,33")
    b = calculate_s01_quote("330.33")
    assert a == b
    assert a.total_cents == a.rafa_fee_cents + a.commission_cents


def test_boundary_one_euro():
    quote = calculate_s01_quote("1.00")
    assert (quote.rafa_fee_cents, quote.commission_cents, quote.total_cents) == (100, 30, 130)
