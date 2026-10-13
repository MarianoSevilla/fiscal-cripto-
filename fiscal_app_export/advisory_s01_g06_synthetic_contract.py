"""S01 G06 — pure, SYNTHETIC-ONLY contract for a versioned service offer.

NO routes, DB writes, Stripe, PayPal, MERU, personal data, invoice generation,
network, emails, tax advice or implied legal sign-off. This prototype must NOT
be wired into the production quote/Checkout flow. Commercial/legal decisions
are outstanding and cannot be supplied by defaults.

This is a deterministic *integrity digest*, NOT an electronic signature, proof
of identity, durable-storage receipt, or complete evidence of a legal contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import re

SCHEMA = "s01-g06-synthetic-offer-v1"
MAX_TOTAL = 99_999_999
_MAX_TEXT = 12_000
_REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z")
_SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_PENDING = re.compile(
    r"\b(?:pendiente|por\s+definir|sin\s+determinar|tbd|todo|"
    r"placeholder|lorem\s+ipsum|no\s+aprobado|no\s+decidido)\b",
    re.IGNORECASE,
)


class S01G06Unapproved(ValueError):
    """The G06 offer/consent is not sufficiently defined for this test."""


@dataclass(frozen=True, slots=True)
class S01G06SyntheticOffer:
    """All customer-visible legal inputs must be supplied, never inferred."""

    advisory_id: int
    offer_reference: str
    issued_at_ts: int
    expires_at_ts: int
    rafa_fee_cents: int
    platform_supplement_cents: int
    taxes_cents: int
    total_payable_cents: int
    currency: str
    service_scope: str
    contracting_party_identity: str
    service_provider_identity: str
    invoicing_responsibility: str
    tax_treatment: str
    general_terms_version: str
    general_terms_text: str
    withdrawal_information_text: str
    cancellations_refunds_text: str
    legal_approval_reference: str
    business_approval_reference: str
    language: str = "es-ES"
    schema: str = SCHEMA


@dataclass(frozen=True, slots=True)
class S01G06SyntheticAcceptance:
    offer_digest: str
    offer_reference: str
    accepted_at_ts: int
    accepted_total_cents: int
    accepted_currency: str
    accepted_terms_version: str
    explicit_acceptance: bool
    acknowledges_payment_obligation: bool
    actor_verification_reference: str
    # Separate optional expression for starting a service within withdrawal
    # period; never interpret merely accepting a quote as waiving withdrawal.
    asks_for_early_service: bool = False
    acknowledges_withdrawal_consequence: bool = False


def _positive_integer(name: str, value: object, *, zero_allowed: bool = False) -> None:
    if type(value) is not int or value < (0 if zero_allowed else 1):
        raise S01G06Unapproved("Invalid integer contract field: " + name)


def _required_ref(name: str, value: object) -> None:
    if not isinstance(value, str) or not _REF_PATTERN.fullmatch(value):
        raise S01G06Unapproved("Missing explicit review reference: " + name)


def _approved_text(name: str, value: object, *, min_length: int = 12) -> None:
    if (not isinstance(value, str) or len(value) > _MAX_TEXT
            or len(value.strip()) < min_length or _PENDING.search(value)
            or any(ord(c) < 32 and c not in "\n\r\t" for c in value)):
        raise S01G06Unapproved("Incomplete commercial/legal field: " + name)


def validate_synthetic_offer(offer: S01G06SyntheticOffer) -> None:
    if type(offer) is not S01G06SyntheticOffer or offer.schema != SCHEMA:
        raise S01G06Unapproved("Wrong offer schema or object type")
    if offer.language != "es-ES" or offer.currency != "EUR":
        raise S01G06Unapproved("Unexpected locale or currency")
    for name in ("advisory_id", "issued_at_ts", "expires_at_ts", "rafa_fee_cents",
                 "platform_supplement_cents", "taxes_cents", "total_payable_cents"):
        _positive_integer(
            name, getattr(offer, name),
            zero_allowed=name in ("platform_supplement_cents", "taxes_cents"),
        )
    if offer.expires_at_ts <= offer.issued_at_ts:
        raise S01G06Unapproved("Offer expires before it can be accepted")
    fee = offer.rafa_fee_cents
    supplement = (fee * 30 + 50) // 100
    if (offer.platform_supplement_cents != supplement
            or offer.total_payable_cents != fee + supplement + offer.taxes_cents
            or offer.total_payable_cents > MAX_TOTAL):
        raise S01G06Unapproved("Money or approved 30% formula does not reconcile")
    for name in ("offer_reference", "legal_approval_reference",
                 "business_approval_reference"):
        _required_ref(name, getattr(offer, name))
    if offer.legal_approval_reference == offer.business_approval_reference:
        raise S01G06Unapproved("Legal and business approvals must be distinct")
    for name in (
        "service_scope", "contracting_party_identity",
        "service_provider_identity", "invoicing_responsibility",
        "tax_treatment", "general_terms_text",
        "withdrawal_information_text", "cancellations_refunds_text",
    ):
        _approved_text(name, getattr(offer, name))
    _required_ref("general_terms_version", offer.general_terms_version)
    # Explicitly validating nonempty values is not a legal opinion. Even a
    # valid object requires human approval before any production use.


def synthetic_offer_digest(offer: S01G06SyntheticOffer) -> str:
    """Canonical SHA-256 with domain separation; no tokens, email or IP."""
    from dataclasses import asdict

    validate_synthetic_offer(offer)
    raw = json.dumps(
        asdict(offer), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return sha256(b"marianosevilla:s01:g06:synthetic:v1\x00" + raw).hexdigest()


def verify_synthetic_acceptance(
    offer: S01G06SyntheticOffer,
    evidence: S01G06SyntheticAcceptance,
) -> str:
    """Fail closed on price/terms/timing/subject changes, return offer digest.

    The caller must separately verify actor identity and collect this evidence
    into durable, append-only storage; those mechanisms are NOT implemented.
    """
    if type(evidence) is not S01G06SyntheticAcceptance:
        raise S01G06Unapproved("Missing acceptance evidence")
    fingerprint = synthetic_offer_digest(offer)
    if (not isinstance(evidence.offer_digest, str)
            or not _SHA_PATTERN.fullmatch(evidence.offer_digest)
            or not hmac.compare_digest(fingerprint, evidence.offer_digest)):
        raise S01G06Unapproved("Offer content differs from accepted terms")
    if (evidence.offer_reference != offer.offer_reference
            or evidence.accepted_terms_version != offer.general_terms_version
            or evidence.accepted_currency != offer.currency
            or type(evidence.accepted_total_cents) is not int
            or evidence.accepted_total_cents != offer.total_payable_cents):
        raise S01G06Unapproved("Accepted terms, identity of offer or total changed")
    if (type(evidence.accepted_at_ts) is not int
            or not offer.issued_at_ts <= evidence.accepted_at_ts <= offer.expires_at_ts):
        raise S01G06Unapproved("Acceptance occurred outside quote validity")
    if (evidence.explicit_acceptance is not True
            or evidence.acknowledges_payment_obligation is not True):
        raise S01G06Unapproved("Explicit consent and payment acknowledgement required")
    _required_ref("actor_verification_reference", evidence.actor_verification_reference)
    if (type(evidence.asks_for_early_service) is not bool
            or type(evidence.acknowledges_withdrawal_consequence) is not bool):
        raise S01G06Unapproved("Withdrawal selection is not unambiguous")
    if (evidence.asks_for_early_service
            and not evidence.acknowledges_withdrawal_consequence):
        raise S01G06Unapproved("Separate withdrawal acknowledgement missing")
    if (not evidence.asks_for_early_service
            and evidence.acknowledges_withdrawal_consequence):
        raise S01G06Unapproved("Contradictory withdrawal selections")
    return fingerprint
