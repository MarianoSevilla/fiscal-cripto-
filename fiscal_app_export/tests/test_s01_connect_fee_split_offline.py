"""Unit tests for S01 Connect design. No live services, bank data or Stripe SDK."""

from dataclasses import replace
from pathlib import Path

import pytest

from advisory_s01_connect_fee_split_offline import (
    ConnectSplitBlocked,
    calculate_direct_charge_fee_split,
)


def example(**updates):
    p = {
        "rafa_honoraria_cents": 20_000,
        "platform_gross_commission_cents": 6_000,
        "actual_processing_fee_cents": 415,
    }
    p.update(updates)
    return calculate_direct_charge_fee_split(**p)


@pytest.mark.parametrize(
    "actual,platform_part,rafa_part,platform_net,rafa_net",
    [
        (0, 0, 0, 6000, 20000),
        (1, 1, 0, 5999, 20000),
        (2, 1, 1, 5999, 19999),
        (3, 2, 1, 5998, 19999),
        (415, 208, 207, 5792, 19793),
        (675, 338, 337, 5662, 19663),
        (753, 377, 376, 5623, 19624),
        (844, 422, 422, 5578, 19578),
    ],
)
def test_direct_split_in_exact_eurocents(
    actual, platform_part, rafa_part, platform_net, rafa_net,
):
    value = example(actual_processing_fee_cents=actual)
    assert value.customer_total_cents == 26_000
    assert value.platform_fee_share_cents == platform_part
    assert value.rafa_fee_share_cents == rafa_part
    assert value.checkout_application_fee_cents == 6_000
    assert value.application_fee_refund_to_rafa_cents == platform_part
    assert value.platform_net_before_other_costs_cents == platform_net
    assert value.rafa_net_before_other_costs_cents == rafa_net
    assert value.must_refund_part_of_application_fee is (platform_part > 0)
    assert platform_net + rafa_net + actual == value.customer_total_cents
    assert platform_part + rafa_part == actual


@pytest.mark.parametrize("params", [
    {"rafa_honoraria_cents": 0},
    {"rafa_honoraria_cents": -20000},
    {"rafa_honoraria_cents": True},
    {"rafa_honoraria_cents": 200.0},
    {"platform_gross_commission_cents": 0},
    {"platform_gross_commission_cents": 6001},
    {"platform_gross_commission_cents": -6000},
    {"platform_gross_commission_cents": "6000"},
    {"actual_processing_fee_cents": -1},
    {"actual_processing_fee_cents": True},
    {"actual_processing_fee_cents": 4.15},
    {"actual_processing_fee_cents": "415"},
    {"actual_processing_fee_cents": 26001},
    {"rafa_honoraria_cents": 99_999_999},
    {"platform_processing_share_bps": True},
    {"platform_processing_share_bps": -1},
    {"platform_processing_share_bps": 10_001},
    {"platform_processing_share_bps": 50.00},
])
def test_invalid_or_unreconciled_inputs_block(params):
    with pytest.raises(ConnectSplitBlocked):
        example(**params)


def test_fee_higher_than_platform_commission_fails_not_silently_capped():
    with pytest.raises(ConnectSplitBlocked, match="cannot fund"):
        calculate_direct_charge_fee_split(
            rafa_honoraria_cents=100,
            platform_gross_commission_cents=30,
            actual_processing_fee_cents=100,
        )


def test_pure_arithmetic_does_not_mutate_provider_or_app():
    src = (Path(__file__).resolve().parents[1] /
           "advisory_s01_connect_fee_split_offline.py").read_text(encoding="utf-8")
    app_src = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    for forbidden in ("import stripe", "from stripe", "import requests",
                      "import flask", "from models", "db.session",
                      "checkout.Session.create", "api_key", "create_refund(",
                      "refund.create(", "os.environ", "http.client"):
        assert forbidden not in src
    assert "advisory_s01_connect_fee_split_offline" not in app_src


def test_illustrative_alternative_share_does_not_change_customer_price():
    # Not a negotiated rule; 50/50 is the *provisional* recommendation.
    x = example(platform_processing_share_bps=4000)
    assert x.platform_fee_share_cents == 166
    assert x.rafa_fee_share_cents == 249
    assert x.customer_total_cents == 26000
    assert x.platform_net_before_other_costs_cents == 5834
    assert x.rafa_net_before_other_costs_cents == 19751
