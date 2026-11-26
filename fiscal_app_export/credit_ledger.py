"""Transactional credit ledger primitives for the disabled FIFO pilot.

Callers must wrap payment mutations in a verified Stripe event handler and
analysis mutations in a request that already owns a pre-analysis reservation.
This module does not call Stripe and never grants a purchase from a browser
redirect.
"""
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from models import (
    db, CreditWallet, CreditLedgerEntry, CreditPurchase, CreditAnalysis,
    CreditStripeEventReceipt, CreditReportArtifact,
)
from credit_pricing import PACKAGES
from credit_execution import AnalysisExecutionLock


class CreditError(ValueError):
    pass


def _wallet_for_update(user_id: int) -> CreditWallet:
    wallet = db.session.execute(
        select(CreditWallet).where(CreditWallet.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if wallet is None:
        try:
            with db.session.begin_nested():
                db.session.add(CreditWallet(user_id=user_id))
                db.session.flush()
        except IntegrityError:
            pass  # another transaction created it; the following locked read wins
        wallet = db.session.execute(
            select(CreditWallet).where(CreditWallet.user_id == user_id).with_for_update()
        ).scalar_one()
    if wallet.frozen:
        raise CreditError("El saldo está temporalmente bloqueado para revisión.")
    return wallet


def _append(user_id, kind, available_delta, reserved_delta, key, reference_id=None):
    if CreditLedgerEntry.query.filter_by(idempotency_key=key).first():
        return False
    db.session.add(CreditLedgerEntry(
        user_id=user_id, entry_type=kind, available_delta=available_delta,
        reserved_delta=reserved_delta, idempotency_key=key,
        reference_id=reference_id,
    ))
    return True


def balance(user_id: int) -> dict:
    wallet = CreditWallet.query.filter_by(user_id=user_id).one_or_none()
    return {"available": wallet.available_credits if wallet else 0,
            "reserved": wallet.reserved_credits if wallet else 0,
            "frozen": bool(wallet.frozen) if wallet else False}


def create_purchase(*, user_id: int, package_key: str, purchase_id: str | None = None,
                    idempotency_key: str | None = None) -> CreditPurchase:
    package = PACKAGES.get(package_key)
    if not package:
        raise CreditError("Paquete no válido.")
    idem = idempotency_key or ("purchase:" + (purchase_id or str(uuid4())))
    existing = CreditPurchase.query.filter_by(user_id=user_id, idempotency_key=idem).first()
    if existing:
        if existing.package_key != package_key:
            raise CreditError("La clave de reintento ya se usó para otro paquete.")
        return existing
    purchase = CreditPurchase(
        id=purchase_id or str(uuid4()), user_id=user_id,
        package_key=package_key, amount_cents=package["price_cents"],
        credits=package["credits"], status="pending", idempotency_key=idem,
    )
    try:
        db.session.add(purchase)
        db.session.commit()
        return purchase
    except IntegrityError:
        db.session.rollback()
        existing = CreditPurchase.query.filter_by(user_id=user_id, idempotency_key=idem).first()
        if existing and existing.package_key == package_key:
            return existing
        raise


def attach_checkout_session(*, purchase_id: str, session_id: str) -> CreditPurchase:
    if not session_id.startswith("cs_test_"):
        raise CreditError("Solo se admite una sesión Checkout de prueba.")
    purchase = db.session.execute(
        select(CreditPurchase).where(CreditPurchase.id == purchase_id).with_for_update()
    ).scalar_one_or_none()
    if not purchase or purchase.status != "pending":
        raise CreditError("La compra no está pendiente.")
    if purchase.checkout_session_id not in (None, session_id):
        raise CreditError("La compra ya está vinculada a otra sesión.")
    purchase.checkout_session_id = session_id
    db.session.commit()
    return purchase


def confirm_test_payment(*, purchase_id: str, event_id: str, session_id: str,
                         payment_intent_id: str, amount_cents: int,
                         currency: str, livemode: bool) -> bool:
    """Grant once for a caller-verified test-mode checkout.session.completed."""
    if livemode is not False:
        raise CreditError("Este piloto solo admite eventos de Stripe en modo test.")
    purchase = db.session.execute(
        select(CreditPurchase).where(CreditPurchase.id == purchase_id).with_for_update()
    ).scalar_one_or_none()
    if purchase is None:
        raise CreditError("Compra no encontrada.")
    if purchase.status == "paid":
        return False
    if (purchase.status != "pending" or amount_cents != purchase.amount_cents
            or currency != purchase.currency or not session_id.startswith("cs_test_")
            or purchase.checkout_session_id != session_id
            or not payment_intent_id.startswith("pi_") or not event_id.startswith("evt_")):
        raise CreditError("El pago no coincide con la compra esperada.")
    wallet = _wallet_for_update(purchase.user_id)
    purchase.status = "paid"
    purchase.checkout_session_id = session_id
    purchase.payment_intent_id = payment_intent_id
    purchase.stripe_event_id = event_id
    purchase.paid_at = datetime.utcnow()
    wallet.available_credits += purchase.credits
    _append(purchase.user_id, "purchase", purchase.credits, 0,
            "purchase:" + purchase.id, purchase.id)
    db.session.add(CreditStripeEventReceipt(
        stripe_event_id=event_id, purchase_id=purchase.id,
        event_type="checkout.session.completed",
    ))
    db.session.commit()
    return True


def flag_refund_for_review(*, event_id: str, payment_intent_id: str,
                           event_type: str = "charge.refunded") -> bool:
    """Freeze spending on a refunded purchase; never guess a clawback amount."""
    if not event_id.startswith("evt_") or not payment_intent_id.startswith("pi_"):
        raise CreditError("Evento de reembolso incompleto.")
    if CreditStripeEventReceipt.query.filter_by(stripe_event_id=event_id).first():
        return False
    purchase = db.session.execute(
        select(CreditPurchase).where(CreditPurchase.payment_intent_id == payment_intent_id)
        .with_for_update()
    ).scalar_one_or_none()
    if not purchase or purchase.status not in {"paid", "refund_review"}:
        raise CreditError("Compra reembolsada no identificada.")
    wallet = _wallet_for_update(purchase.user_id)
    wallet.frozen = True
    purchase.status = "refund_review"
    db.session.add(CreditStripeEventReceipt(
        stripe_event_id=event_id, purchase_id=purchase.id,
        event_type=event_type[:100],
    ))
    db.session.commit()
    return True


def reserve_analysis(*, user_id: int, analysis_id: str | None = None,
                     idempotency_key: str, exchange: str, fiscal_years: str,
                     csv_rows: int, file_count: int, file_fingerprint: str,
                     max_credits: int,
                     correction_of_id: str | None = None) -> CreditAnalysis:
    if not (1 <= len(idempotency_key) <= 100) or max_credits < 0:
        raise CreditError("Reserva inválida.")
    prior = CreditAnalysis.query.filter_by(user_id=user_id, idempotency_key=idempotency_key).first()
    if prior:
        if (prior.exchange != exchange[:40] or prior.fiscal_years != fiscal_years[:50]
                or prior.csv_rows != csv_rows or prior.file_count != file_count
                or prior.file_fingerprint != file_fingerprint):
            raise CreditError("La clave de reintento ya está vinculada a otro análisis.")
        return prior
    wallet = _wallet_for_update(user_id)
    # Re-read under the wallet lock so simultaneous retries with one
    # idempotency key converge on the reservation created by the first request.
    prior = CreditAnalysis.query.filter_by(user_id=user_id, idempotency_key=idempotency_key).first()
    if prior:
        if (prior.exchange != exchange[:40] or prior.fiscal_years != fiscal_years[:50]
                or prior.csv_rows != csv_rows or prior.file_count != file_count
                or prior.file_fingerprint != file_fingerprint):
            raise CreditError("La clave de reintento ya está vinculada a otro análisis.")
        return prior
    # Wallet serialization also prevents two tabs with different idempotency
    # keys from reserving the same unchanged file set concurrently.
    duplicate_query = CreditAnalysis.query.filter_by(
        user_id=user_id, exchange=exchange[:40], fiscal_years=fiscal_years[:50],
        file_fingerprint=file_fingerprint,
    ).filter(CreditAnalysis.status.in_(
        ("reserved", "processing", "consumed", "execution_unknown", "settlement_unknown")
    ))
    if duplicate_query.filter(CreditAnalysis.status.in_(
            ("reserved", "processing", "execution_unknown", "settlement_unknown")
    )).first():
        raise CreditError("Ya existe un análisis idéntico en curso. Espera a que termine antes de repetirlo.")
    acquired_duplicate = (duplicate_query.filter_by(status="consumed")
                          .join(CreditReportArtifact,
                                CreditReportArtifact.analysis_id == CreditAnalysis.id)
                          .filter(CreditReportArtifact.expires_at > datetime.utcnow())
                          .first())
    if acquired_duplicate:
        raise CreditError("Este análisis ya está adquirido y su documento sigue disponible para descarga gratuita.")
    if correction_of_id:
        parent = CreditAnalysis.query.filter_by(id=correction_of_id, user_id=user_id).with_for_update().first()
        if (not parent or parent.correction_of_id is not None
                or parent.status != "consumed" or not parent.correction_expires_at
                or parent.correction_expires_at < datetime.utcnow()):
            raise CreditError("La ventana de corrección ha caducado o el expediente no existe.")
        # Pilot policy: one fee-free correction for each acquired analysis.
        if CreditAnalysis.query.filter_by(correction_of_id=parent.id).first():
            raise CreditError("La corrección gratuita de este informe ya se ha utilizado.")
        max_credits = 0
    if wallet.available_credits < max_credits:
        raise CreditError("Saldo de créditos insuficiente.")
    analysis = CreditAnalysis(
        id=analysis_id or str(uuid4()), user_id=user_id,
        idempotency_key=idempotency_key, exchange=exchange[:40],
        fiscal_years=fiscal_years[:50], csv_rows=csv_rows, file_count=file_count,
        file_fingerprint=file_fingerprint,
        reserved_credits=max_credits, status="reserved",
        correction_of_id=correction_of_id,
        correction_expires_at=datetime.utcnow() + timedelta(days=30),
    )
    wallet.available_credits -= max_credits
    wallet.reserved_credits += max_credits
    db.session.add(analysis)
    if max_credits:
        _append(user_id, "reserve", -max_credits, max_credits,
                "reserve:" + analysis.id, analysis.id)
    db.session.commit()
    return analysis


def begin_analysis(*, analysis_id: str, user_id: int,
                   execution_lock: AnalysisExecutionLock) -> CreditAnalysis:
    """Atomically move an unstarted reservation into an execution claim."""
    if not execution_lock.matches(user_id=user_id, analysis_id=analysis_id):
        raise CreditError("No se posee el bloqueo de ejecución del análisis.")
    analysis = db.session.execute(
        select(CreditAnalysis).where(CreditAnalysis.id == analysis_id,
                                    CreditAnalysis.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if not analysis or analysis.status != "reserved":
        raise CreditError("La reserva ya no está disponible para iniciar.")
    analysis.status = "processing"
    analysis.execution_started_at = datetime.utcnow()
    db.session.commit()
    return analysis


def settle_analysis(*, analysis_id: str, user_id: int,
                    execution_lock: AnalysisExecutionLock, result_type: str,
                    actual_credits: int | None = None) -> CreditAnalysis:
    if not execution_lock.matches(user_id=user_id, analysis_id=analysis_id):
        raise CreditError("No se posee el bloqueo de ejecución del análisis.")
    if result_type not in {"definitive", "provisional"}:
        raise CreditError("Solo un análisis completado puede consumir créditos.")
    analysis = db.session.execute(
        select(CreditAnalysis).where(CreditAnalysis.id == analysis_id,
                                    CreditAnalysis.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if not analysis:
        raise CreditError("Reserva no encontrada.")
    if analysis.status == "consumed":
        return analysis
    if analysis.status != "processing":
        raise CreditError("La reserva no está activa.")
    charge = (0 if analysis.correction_of_id else analysis.reserved_credits) if actual_credits is None else actual_credits
    if isinstance(charge, bool) or not isinstance(charge, int) or charge < 0 or charge > analysis.reserved_credits:
        raise CreditError("Consumo fuera de la reserva autorizada.")
    wallet = _wallet_for_update(user_id)
    if wallet.reserved_credits < analysis.reserved_credits:
        raise CreditError("Saldo reservado inconsistente.")
    released = analysis.reserved_credits - charge
    wallet.reserved_credits -= analysis.reserved_credits
    wallet.available_credits += released
    analysis.charged_credits = charge
    analysis.result_type = result_type
    analysis.status = "consumed"
    if analysis.reserved_credits:
        _append(user_id, "settle", released, -analysis.reserved_credits,
                "settle:" + analysis.id, analysis.id)
    db.session.commit()
    return analysis


def _release_analysis_row(analysis: CreditAnalysis, *, user_id: int) -> CreditAnalysis:
    wallet = _wallet_for_update(user_id)
    if wallet.reserved_credits < analysis.reserved_credits:
        raise CreditError("Saldo reservado inconsistente.")
    wallet.reserved_credits -= analysis.reserved_credits
    wallet.available_credits += analysis.reserved_credits
    analysis.status = "released"
    analysis.charged_credits = 0
    # A result artifact is never downloadable unless the analysis is consumed.
    # Remove any partial artifact from a failed settlement in the same commit.
    db.session.query(CreditReportArtifact).filter_by(
        analysis_id=analysis.id
    ).delete(synchronize_session=False)
    if analysis.reserved_credits:
        _append(user_id, "release", analysis.reserved_credits,
                -analysis.reserved_credits, "release:" + analysis.id, analysis.id)
    db.session.commit()
    return analysis


def release_analysis(*, analysis_id: str, user_id: int) -> CreditAnalysis:
    """Release only an analysis that never claimed execution."""
    analysis = db.session.execute(
        select(CreditAnalysis).where(CreditAnalysis.id == analysis_id,
                                    CreditAnalysis.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if not analysis:
        raise CreditError("Reserva no encontrada.")
    if analysis.status == "released":
        return analysis
    if analysis.status != "reserved":
        raise CreditError("Solo puede liberarse automáticamente una reserva no iniciada.")
    return _release_analysis_row(analysis, user_id=user_id)


def release_processing_analysis(*, analysis_id: str, user_id: int,
                                execution_lock: AnalysisExecutionLock) -> CreditAnalysis:
    """Release a known failed execution while its request still owns the lock."""
    if not execution_lock.matches(user_id=user_id, analysis_id=analysis_id):
        raise CreditError("No se posee el bloqueo de ejecución del análisis.")
    analysis = db.session.execute(
        select(CreditAnalysis).where(CreditAnalysis.id == analysis_id,
                                    CreditAnalysis.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if not analysis:
        raise CreditError("Reserva no encontrada.")
    if analysis.status == "released":
        return analysis
    if analysis.status != "processing":
        raise CreditError("La ejecución no puede liberarse en este estado.")
    return _release_analysis_row(analysis, user_id=user_id)


def recover_analysis(*, analysis_id: str, user_id: int,
                     execution_lock: AnalysisExecutionLock) -> CreditAnalysis:
    """Recover unstarted work or quarantine an interrupted execution.

    The advisory lock proves no request for this analysis is currently active.
    An execution already marked `processing` is never released automatically;
    it becomes `execution_unknown` and the wallet is frozen for reconciliation.
    """
    if not execution_lock.matches(user_id=user_id, analysis_id=analysis_id):
        raise CreditError("No se posee el bloqueo de ejecución del análisis.")
    analysis = db.session.execute(
        select(CreditAnalysis).where(CreditAnalysis.id == analysis_id,
                                    CreditAnalysis.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if not analysis:
        raise CreditError("Análisis no encontrado.")
    if analysis.status == "reserved":
        return _release_analysis_row(analysis, user_id=user_id)
    if analysis.status == "processing":
        wallet = db.session.execute(
            select(CreditWallet).where(CreditWallet.user_id == user_id).with_for_update()
        ).scalar_one_or_none()
        if wallet is None:
            raise CreditError("Monedero no encontrado durante la recuperación.")
        analysis.status = "execution_unknown"
        wallet.frozen = True
        db.session.commit()
        return analysis
    return analysis


def quarantine_unknown_analysis(*, analysis_id: str, user_id: int) -> bool:
    """Freeze a wallet when a failed settlement cannot be read back safely."""
    analysis = db.session.execute(
        select(CreditAnalysis).where(CreditAnalysis.id == analysis_id,
                                    CreditAnalysis.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if not analysis or analysis.status not in {"reserved", "processing"}:
        return False
    wallet = db.session.execute(
        select(CreditWallet).where(CreditWallet.user_id == user_id).with_for_update()
    ).scalar_one_or_none()
    if not wallet:
        raise CreditError("Monedero no encontrado durante la conciliación.")
    analysis.status = "settlement_unknown"
    wallet.frozen = True
    db.session.commit()
    return True
