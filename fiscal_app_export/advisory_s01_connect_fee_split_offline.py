"""S01 · Stripe Connect direct-charge fee-sharing arithmetic (OFFLINE ONLY).

Pure deterministic cent accounting. This module neither imports nor calls Stripe
and deliberately does not create an invoice, Checkout Session, application fee
refund, transfer, payment, account or bank payout.

The actual Stripe fee must first be verified against the successful direct
charge's settled balance transaction on Rafa's connected account. The caller
must then reconcile an application-fee refund idempotently in its own approved
financial workflow. THIS MODULE IS NOT THAT WORKFLOW.

No taxes on the service or 30% intermediary fee are determined here. The base
honoraria and fee treatment require the parties' and fiscal adviser's approval.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PLATFORM_PROCESSING_SHARE_BPS = 5000
BPS = 10_000
MAX_AMOUNT_CENTS = 99_999_999


class ConnectSplitBlocked(ValueError):
    """No financial adjustment can be computed from these inputs."""


@dataclass(frozen=True, slots=True)
class DirectChargeFeeSplit:
    customer_total_cents: int
    rafa_honoraria_cents: int
    platform_gross_commission_cents: int
    actual_processing_fee_cents: int
    platform_fee_share_cents: int
    rafa_fee_share_cents: int
    checkout_application_fee_cents: int
    application_fee_refund_to_rafa_cents: int
    platform_net_before_other_costs_cents: int
    rafa_net_before_other_costs_cents: int

    @property
    def must_refund_part_of_application_fee(self) -> bool:
        return self.application_fee_refund_to_rafa_cents > 0


def calculate_direct_charge_fee_split(
    *, rafa_honoraria_cents: int,
    platform_gross_commission_cents: int,
    actual_processing_fee_cents: int,
    platform_processing_share_bps: int = DEFAULT_PLATFORM_PROCESSING_SHARE_BPS,
) -> DirectChargeFeeSplit:
    """Calculate agreed 50/50 *economic* processing-fee sharing.

    The connected account initially bears the Stripe processing fee. The
    platform initially receives its full gross application fee, then refunds
    only its half of the VERIFIED actual processing fee back to the connected
    account via a *partial application-fee refund*, subject to independent
    authorization, balance and idempotency checks. This is NOT a refund to the
    end customer.

    Odd cents are allocated to the platform: processing 415c -> platform
    208c, Rafa 207c. Other share ratios are mathematically representable,
    but NONE is contractually approved merely by calling this function.
    """
    values = {
        "rafa_honoraria_cents": rafa_honoraria_cents,
        "platform_gross_commission_cents": platform_gross_commission_cents,
        "actual_processing_fee_cents": actual_processing_fee_cents,
        "platform_processing_share_bps": platform_processing_share_bps,
    }
    if any(type(v) is not int for v in values.values()):
        raise ConnectSplitBlocked("All amounts and ratios must be exact integers")
    if (rafa_honoraria_cents < 100
            or platform_gross_commission_cents <= 0
            or not 0 <= actual_processing_fee_cents <= MAX_AMOUNT_CENTS
            or not 0 <= platform_processing_share_bps <= BPS):
        raise ConnectSplitBlocked("Negative, unsupported or zero-price inputs")

    # S01 provisional business rule: gross platform compensation is 30% of
    # Rafa's declared honoraria, rounded HALF_UP once in eurocents.
    expected_commission = (rafa_honoraria_cents * 30 + 50) // 100
    if platform_gross_commission_cents != expected_commission:
        raise ConnectSplitBlocked("The provisional S01 30 percent split differs")
    total = rafa_honoraria_cents + platform_gross_commission_cents
    if total > MAX_AMOUNT_CENTS or actual_processing_fee_cents > total:
        raise ConnectSplitBlocked("Total or processing fee outside supported range")

    # Fraction nearest cent, HALF_UP. Odd cents on an exact 50/50 split go to
    # the platform. This prevents any fractional-cent debt being tracked.
    platform_share = (
        actual_processing_fee_cents * platform_processing_share_bps + BPS // 2
    ) // BPS
    rafa_share = actual_processing_fee_cents - platform_share

    # A partial application fee refund cannot exceed the fee already taken.
    # Never silently cap the refund: fail closed and require case review.
    if platform_share > platform_gross_commission_cents:
        raise ConnectSplitBlocked("Platform commission cannot fund its fee share")

    platform_net = platform_gross_commission_cents - platform_share
    rafa_net = rafa_honoraria_cents - rafa_share
    if rafa_net < 0:
        raise ConnectSplitBlocked("Rafa honoraria cannot fund their fee share")
    if platform_net + rafa_net + actual_processing_fee_cents != total:
        raise ConnectSplitBlocked("Conservation of cents violated")

    return DirectChargeFeeSplit(
        customer_total_cents=total,
        rafa_honoraria_cents=rafa_honoraria_cents,
        platform_gross_commission_cents=platform_gross_commission_cents,
        actual_processing_fee_cents=actual_processing_fee_cents,
        platform_fee_share_cents=platform_share,
        rafa_fee_share_cents=rafa_share,
        checkout_application_fee_cents=platform_gross_commission_cents,
        application_fee_refund_to_rafa_cents=platform_share,
        platform_net_before_other_costs_cents=platform_net,
        rafa_net_before_other_costs_cents=rafa_net,
    )
