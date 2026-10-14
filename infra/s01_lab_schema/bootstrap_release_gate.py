"""STG-B11E: schema-bootstrap release contract — unconditionally INACTIVE.

This module deliberately CANNOT bootstrap a database. It contains NO
Flask/SQLAlchemy/Alembic imports, NO PostgreSQL connection and NO DDL.
All tests use synthetic env. The Railway B11B source-attachment block must
be resolved legitimately before any prospective bootstrap runner is reviewed.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import sys

from preflight import (
    SchemaPreflightDenied,
    checked_pg_environment,
    TARGET_CLUSTER,
    FORBIDDEN_ORIGINAL_CLUSTER,
    SERVICE_ID,
    TARGET_HOST,
)

APPROVAL_KEY = "S01_SCHEMA_BOOTSTRAP_APPROVAL"
APPROVAL_INTENT = (
    "ONE-SCHEMA-BOOTSTRAP:POSTGRES-IM3H:"
    "7696517018472497211:z9a0b1c2d3e4"
)
MIGRATION_HEAD = "z9a0b1c2d3e4"
MIGRATION_BASELINE = "m6n7o8p9q0r1"
# This value cannot become true through Railway environment variables.
SOURCE_RELEASED = False


class SchemaReleaseDenied(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ImmutableReview:
    destination: str
    destination_cluster: str
    service_id: str
    head_revision: str
    baseline_revision: str
    approved_intent_present: bool


def validate_review_parameters(env: dict[str, str]) -> ImmutableReview:
    """Pure data validation for a FUTURE manual approval, no sockets/DDL.

    Authorization intent alone is never an execution credential. Even a
    fully valid return value cannot lift SOURCE_RELEASED=False.
    """
    try:
        pg_env = checked_pg_environment(env)
    except SchemaPreflightDenied as exc:
        raise SchemaReleaseDenied("PIN_" + exc.code) from None
    if pg_env["PGHOST"] != TARGET_HOST or TARGET_CLUSTER == FORBIDDEN_ORIGINAL_CLUSTER:
        raise SchemaReleaseDenied("TARGET_ISOLATION")
    if env.get("S01_RECOVERY_WRITE_APPROVAL"):
        raise SchemaReleaseDenied("STALE_RESTORE_APPROVAL")
    if env.get("S01_SCHEMA_BOOTSTRAP_APPROVAL") not in ("", None, APPROVAL_INTENT):
        raise SchemaReleaseDenied("UNEXPECTED_SCHEMA_APPROVAL")
    return ImmutableReview(
        destination=TARGET_HOST,
        destination_cluster=TARGET_CLUSTER,
        service_id=SERVICE_ID,
        head_revision=MIGRATION_HEAD,
        baseline_revision=MIGRATION_BASELINE,
        approved_intent_present=env.get(APPROVAL_KEY) == APPROVAL_INTENT,
    )


def release_gate(env: dict[str, str] | None = None, *, worker=None) -> None:
    """ALWAYS fail before parsing DSNs, importing clients or invoking worker."""
    if SOURCE_RELEASED is not False:
        # A later source edit that simply flips the flag still cannot run DDL.
        raise SchemaReleaseDenied("UNREVIEWED_SOURCE_CHANGE")
    raise SchemaReleaseDenied("DDL_NOT_AUTHORIZED")


def main() -> None:
    try:
        release_gate(dict(os.environ))
    except SchemaReleaseDenied as exc:
        print("S01 STG-B11E: NO-GO (" + exc.code + ")",
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    print("S01 STG-B11E: NO-GO (FAIL_CLOSED)",
          file=sys.stderr, flush=True)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
