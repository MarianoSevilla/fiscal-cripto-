"""SEC5-PRIV experimental scope probe. TESTS ONLY; not imported by the Flask app.

Read-only, count-only map for a verified *active* synthetic user's footprint.
Counts for repeated email values are CANDIDATES, not ownership proof.
No delete/update/commit/flush, no PII in the result, no production API/CLI.
"""
from sqlalchemy import func, select
from models import (
    User, FifoReport, ProcessingError, Incident, Contacto,
    FiscalAdvisoryRequest, S01StripeCheckoutAttempt, S01StripeEventReceipt,
    S01StripeNotificationOutbox, FiscalAdvisoryFile, FiscalAdvisoryStatusHistory,
    AdvisoryInternalNote, AdvisoryAuditLog, CommunicationCampaign,
    CommunicationDelivery, Resource, ResourceRequest,
)

MODELS = (
    User, FifoReport, ProcessingError, Incident, Contacto,
    FiscalAdvisoryRequest, S01StripeCheckoutAttempt, S01StripeEventReceipt,
    S01StripeNotificationOutbox, FiscalAdvisoryFile, FiscalAdvisoryStatusHistory,
    AdvisoryInternalNote, AdvisoryAuditLog, CommunicationCampaign,
    CommunicationDelivery, Resource, ResourceRequest,
)

# References tied to subject by a verified user ID.
SUBJECT_FIELDS = {
    FifoReport: ("user_id",),
    ProcessingError: ("user_id",),
    FiscalAdvisoryRequest: ("user_id",),
    FiscalAdvisoryFile: ("user_id",),
    CommunicationDelivery: ("user_id",),
}

# References to the user AS an actor/employee; never claim these are
# records to delete on the same basis as a customer's own activity.
ACTOR_FIELDS = {
    FiscalAdvisoryRequest: ("quoted_by_user_id", "assigned_to"),
    FiscalAdvisoryStatusHistory: ("changed_by",),
    AdvisoryInternalNote: ("author_id",),
    AdvisoryAuditLog: ("admin_id",),
    CommunicationCampaign: ("created_by_id",),
}

# A historical email copied into a table is NOT automatically a record
# belonging to the holder of the account. Every hit requires manual review.
EMAIL_CANDIDATES = {
    ProcessingError: ("email",),
    Contacto: ("email",),
    FiscalAdvisoryRequest: ("email",),
    CommunicationCampaign: ("individual_email",),
    CommunicationDelivery: ("email",),
    ResourceRequest: ("email",),
}

# No FK directly connects the incident aggregate or published resources
# to a user. Free-text fields and external providers require separate review.
UNLINKED = frozenset({"incidents", "resources"})


def _count(session, model, condition):
    return int(session.execute(
        select(func.count()).select_from(model).where(condition)
    ).scalar_one())


def inventory_verified_user_synthetic(session, *, user_id, original_email):
    """Return counts, never row data; fail closed when identity is ambiguous.

    The function is intentionally available ONLY from the test directory.
    It is neither a GDPR erasure engine nor evidence of legal blocking.
    """
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("A valid positive verified user ID is required")
    if not isinstance(original_email, str) or not original_email.strip():
        raise ValueError("Original verified email is required before deactivation")

    with session.no_autoflush:
        # Enforce account/email correspondence. After deactivation the
        # old email is lost; returning guesses would risk third-party data.
        match = session.execute(
            select(User.email, User.is_active).where(User.id == user_id)
        ).one_or_none()
        if (match is None or not match.is_active
                or match.email.lower() != original_email.strip().lower()):
            raise ValueError("Verified active account/email pairing is required")

        result = {
            "verified_subject_refs": {},
            "staff_actor_refs": {},
            "copied_email_candidates": {},
            "indirect_case_refs": {},
            "no_direct_fk": tuple(sorted(UNLINKED)),
            "tables_modeled": len(MODELS),
            "delete_permitted": False,
            "blocking_proven": False,
            "external_systems_checked": False,
        }
        for model, fields in SUBJECT_FIELDS.items():
            for field in fields:
                result["verified_subject_refs"][f"{model.__tablename__}.{field}"] = (
                    _count(session, model, getattr(model, field) == user_id)
                )
        for model, fields in ACTOR_FIELDS.items():
            for field in fields:
                result["staff_actor_refs"][f"{model.__tablename__}.{field}"] = (
                    _count(session, model, getattr(model, field) == user_id)
                )
        lowered = original_email.strip().lower()
        for model, fields in EMAIL_CANDIDATES.items():
            for field in fields:
                result["copied_email_candidates"][f"{model.__tablename__}.{field}"] = (
                    _count(session, model, func.lower(getattr(model, field)) == lowered)
                )

        # Follow financial references ONLY from cases linked by user_id.
        # A coincident email alone must never drive this chain.
        case_ids = select(FiscalAdvisoryRequest.id).where(
            FiscalAdvisoryRequest.user_id == user_id
        )
        attempt_ids = select(S01StripeCheckoutAttempt.id).where(
            S01StripeCheckoutAttempt.advisory_id.in_(case_ids)
        )
        descendant_conditions = (
            (S01StripeCheckoutAttempt, S01StripeCheckoutAttempt.advisory_id.in_(case_ids)),
            (S01StripeEventReceipt, S01StripeEventReceipt.attempt_id.in_(attempt_ids)),
            (S01StripeNotificationOutbox, S01StripeNotificationOutbox.attempt_id.in_(attempt_ids)),
            (FiscalAdvisoryFile, FiscalAdvisoryFile.request_id.in_(case_ids)),
            (FiscalAdvisoryStatusHistory, FiscalAdvisoryStatusHistory.request_id.in_(case_ids)),
            (AdvisoryInternalNote, AdvisoryInternalNote.request_id.in_(case_ids)),
            (AdvisoryAuditLog, AdvisoryAuditLog.request_id.in_(case_ids)),  # No FK, candidate only
        )
        for model, condition in descendant_conditions:
            result["indirect_case_refs"][model.__tablename__] = (
                _count(session, model, condition)
            )
        return result
