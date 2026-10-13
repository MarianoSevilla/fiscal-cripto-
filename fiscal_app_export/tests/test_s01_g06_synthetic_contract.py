"""G06: no approved legal terms, merchant identity or VAT are assumed.

Entirely fictional contract inputs. Tests never access private information,
Flask, SQLAlchemy, Stripe/PayPal or any external provider.
"""
from dataclasses import replace
import re

import pytest

from advisory_s01_g06_synthetic_contract import (
    S01G06SyntheticOffer, S01G06SyntheticAcceptance,
    S01G06Unapproved, synthetic_offer_digest,
    validate_synthetic_offer, verify_synthetic_acceptance,
)

# Example only: fictitious labels below MUST NOT be published to customers.
def fictitious_offer(**changes):
    data = dict(
        advisory_id=77,
        offer_reference="S01-FAKE-OFFER-0077",
        issued_at_ts=1800000000,
        expires_at_ts=1800086400,
        rafa_fee_cents=20000,
        platform_supplement_cents=6000,
        # FICTITIOUS test amount; it is not a claim about Spanish tax rates.
        taxes_cents=2100,
        total_payable_cents=28100,
        currency="EUR",
        service_scope="Servicio fiscal ficticio para una prueba automatizada exclusivamente.",
        contracting_party_identity="Comerciante legal de ejemplo, no existe, TEST",
        service_provider_identity="Asesor profesional inventado para ensayos solamente",
        invoicing_responsibility="Emisor de factura de ejemplo, exclusivamente ficticio",
        tax_treatment="Hipótesis fiscal solo para test, no aplicable a clientes ni facturas",
        general_terms_version="G06-SYNTH-VERSION-001",
        general_terms_text="Condiciones generales simuladas exclusivamente para comprobar integridad de pruebas.",
        withdrawal_information_text="Explicación de desistimiento simulada: pendiente de revisión jurídica real no afirmada.",
        cancellations_refunds_text="Normas de cancelación simuladas que no representan una política comercial real.",
        legal_approval_reference="G06-LEGAL-FAKE-001",
        business_approval_reference="G06-BUSINESS-FAKE-001",
    )
    data.update(changes)
    return S01G06SyntheticOffer(**data)


def fictitious_consent(offer, **changes):
    args = dict(
        offer_digest=synthetic_offer_digest(offer),
        offer_reference=offer.offer_reference,
        accepted_at_ts=offer.issued_at_ts + 120,
        accepted_total_cents=offer.total_payable_cents,
        accepted_currency="EUR",
        accepted_terms_version=offer.general_terms_version,
        explicit_acceptance=True,
        acknowledges_payment_obligation=True,
        actor_verification_reference="G06-ACTOR-FAKE-0077",
    )
    args.update(changes)
    return S01G06SyntheticAcceptance(**args)


def test_deterministic_signed_scope_digest_without_any_network():
    offer = fictitious_offer(
        withdrawal_information_text="Explicación ficticia del derecho de desistimiento para casos sintéticos.",
    )
    assert synthetic_offer_digest(offer) == synthetic_offer_digest(replace(offer))
    assert re.fullmatch(r"[0-9a-f]{64}", synthetic_offer_digest(offer))
    assert verify_synthetic_acceptance(offer, fictitious_consent(offer)) == synthetic_offer_digest(offer)


@pytest.mark.parametrize("change", [
    {"rafa_fee_cents": 20100},
    {"platform_supplement_cents": 5999},
    {"total_payable_cents": 28101},
    {"taxes_cents": 0},
    {"currency": "USD"},
    {"general_terms_version": "G06-SYNTH-VERSION-002"},
    {"service_scope": "Servicio fiscal simulado con otra descripción y alcance."},
    {"contracting_party_identity": "Otra entidad ficticia de la prueba técnica"},
    {"service_provider_identity": "Otro profesional ficticio para pruebas"},
    {"invoicing_responsibility": "Otro emisor de factura simulado en el test"},
    {"tax_treatment": "Tratamiento fiscal alternativo ficticio para comprobar cambios"},
    {"withdrawal_information_text": "Condiciones de desistimiento distintas en esta simulación."},
    {"cancellations_refunds_text": "Reembolso modificado exclusivamente para comprobar el hash."},
    {"legal_approval_reference": "G06-LEGAL-FAKE-002"},
])
def test_offer_changes_cannot_pass_previous_acceptance(change):
    original = fictitious_offer(
        withdrawal_information_text="Política de desistimiento ficticia de longitud suficiente para el test.",
    )
    proof = fictitious_consent(original)
    modified = replace(original, **change)
    with pytest.raises(S01G06Unapproved):
        verify_synthetic_acceptance(modified, proof)


@pytest.mark.parametrize("change", [
    {"legal_approval_reference": ""},
    {"business_approval_reference": "G06-LEGAL-FAKE-001"},
    {"contracting_party_identity": "Pendiente"},
    {"service_provider_identity": "POR DEFINIR"},
    {"invoicing_responsibility": "Sin determinar"},
    {"tax_treatment": "No decidido"},
    {"cancellations_refunds_text": "TODO"},
    {"service_scope": ""},
    {"general_terms_text": ""},
    {"withdrawal_information_text": ""},
    {"rafa_fee_cents": 0},
    {"rafa_fee_cents": True},
    {"platform_supplement_cents": True},
    {"taxes_cents": -1},
    {"taxes_cents": None},
    {"total_payable_cents": "28100"},
    {"issued_at_ts": 1800086400},
    {"expires_at_ts": 1800000000},
    {"language": "en-US"},
])
def test_g06_fails_closed_without_complete_commercial_approval(change):
    with pytest.raises(S01G06Unapproved):
        validate_synthetic_offer(fictitious_offer(**change))


@pytest.mark.parametrize("change", [
    {"offer_digest": "1" * 64},
    {"offer_digest": "not_a_hash"},
    {"offer_reference": "OTHER-REFERENCE-001"},
    {"accepted_terms_version": "G06-SYNTH-VERSION-002"},
    {"accepted_total_cents": 26000},
    {"accepted_total_cents": True},
    {"accepted_currency": "USD"},
    {"accepted_at_ts": 1799999999},
    {"accepted_at_ts": 1800086401},
    {"accepted_at_ts": True},
    {"explicit_acceptance": False},
    {"explicit_acceptance": 1},
    {"acknowledges_payment_obligation": False},
    {"actor_verification_reference": ""},
    {"asks_for_early_service": True},
    {"acknowledges_withdrawal_consequence": True},
    {"asks_for_early_service": "yes"},
])
def test_consent_fail_closed_on_time_terms_identity_price_or_withdrawal(change):
    offer = fictitious_offer(
        withdrawal_information_text="Desistimiento simulado para un ensayo técnico, sin valor contractual.",
    )
    with pytest.raises(S01G06Unapproved):
        verify_synthetic_acceptance(offer, fictitious_consent(offer, **change))


def test_early_service_requests_are_separate_and_only_valid_with_ack():
    offer = fictitious_offer(
        withdrawal_information_text="Desistimiento puramente ficticio, solo para pruebas automatizadas.",
    )
    p = fictitious_consent(
        offer, asks_for_early_service=True,
        acknowledges_withdrawal_consequence=True,
    )
    assert verify_synthetic_acceptance(offer, p) == synthetic_offer_digest(offer)
    assert fictitious_consent(offer).asks_for_early_service is False


def test_no_side_effectful_imports_and_no_public_routes():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    src = (root / "advisory_s01_g06_synthetic_contract.py").read_text(encoding="utf-8")
    app = (root / "app.py").read_text(encoding="utf-8")
    for forbidden in ("import stripe", "import requests", "import flask",
                      "db.session", "from models import", "create_all",
                      "http.client", "urllib.request", "smtp"):
        assert forbidden not in src.lower()
    assert "advisory_s01_g06_synthetic_contract" not in app
    assert "S01G06SyntheticOffer" not in app
