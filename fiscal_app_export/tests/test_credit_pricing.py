import pytest

from credit_pricing import PACKAGES, quote_analysis


def test_packages_keep_approved_prices_and_credits_cover_the_top_volume_band():
    assert {k: v["price_cents"] for k, v in PACKAGES.items()} == {
        "basic": 1590, "standard": 2990, "advanced": 4990,
    }
    assert PACKAGES["advanced"]["credits"] >= 400 + 60


@pytest.mark.parametrize("rows,expected", [
    (442, 50), (2292, 100), (6298, 200), (33519, 400),
])
def test_rows_percentiles_map_to_documented_bands(rows, expected):
    assert quote_analysis(rows=rows, files=1).row_credits == expected


def test_complexity_is_a_separate_capped_multifile_allowance():
    quote = quote_analysis(rows=33519, files=10)
    assert quote.row_credits == 400
    assert quote.complexity_credits == 60
    assert quote.max_credits == PACKAGES["advanced"]["credits"]


@pytest.mark.parametrize("rows,files", [(-1, 1), (1, 0), (35001, 1), (True, 1), (1, True)])
def test_invalid_or_unpriced_quotes_fail_closed(rows, files):
    with pytest.raises(ValueError):
        quote_analysis(rows=rows, files=files)
