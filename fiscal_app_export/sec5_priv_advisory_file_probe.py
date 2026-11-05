"""SEC5-PRIV: explicit read-only, count-only inventory of advisory upload metadata.

This command does NOT look up file names, paths, content, or users; it does NOT
prove physical files exist or that none exist. Never import it into Flask.
Execute only after an operator explicitly opts in to a metadata-only check.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import text
from sec5_priv_role_preflight import inspect_runtime_role

# One aggregate row only; no user identifiers, free text, filenames or paths.
METADATA_QUERY = """
SELECT
    COUNT(*)::bigint AS metadata_rows,
    COUNT(DISTINCT f.request_id)::bigint AS linked_requests,
    COUNT(DISTINCT f.user_id)::bigint AS linked_users,
    COUNT(*) FILTER (WHERE r.id IS NULL)::bigint AS missing_requests,
    COUNT(*) FILTER (WHERE u.id IS NULL)::bigint AS missing_users,
    COUNT(*) FILTER (WHERE r.id IS NOT NULL AND r.user_id IS NULL)::bigint
        AS unlinked_request_owners,
    COUNT(*) FILTER (
        WHERE r.id IS NOT NULL AND r.user_id IS NOT NULL
          AND r.user_id <> f.user_id
    )::bigint AS ownership_mismatches
FROM public.fiscal_advisory_files AS f
LEFT JOIN public.fiscal_advisory_requests AS r ON r.id = f.request_id
LEFT JOIN public.users AS u ON u.id = f.user_id
"""

COUNT_FIELDS = (
    "metadata_rows", "linked_requests", "linked_users",
    "missing_requests", "missing_users", "unlinked_request_owners",
    "ownership_mismatches",
)


def inspect_advisory_file_metadata(engine) -> dict:
    """Count historical rows using the limited runtime login, without PII."""
    if engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL required")

    # Reuses the audited, read-only metadata check; a privileged login fails.
    role = inspect_runtime_role(engine)
    if role["status"] != "CANDIDATE_ONLY" or role["risk_flags"]:
        raise RuntimeError("Limited runtime login required")

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            if connection.exec_driver_sql(
                "SHOW transaction_read_only"
            ).scalar_one() != "on":
                raise RuntimeError("Read-only transaction not confirmed")
            record = connection.execute(text(METADATA_QUERY)).mappings().one()
        finally:
            transaction.rollback()

    counts = {key: record[key] for key in COUNT_FIELDS}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise RuntimeError("Unreliable aggregate counts")
    if any(counts[key] > counts["metadata_rows"] for key in COUNT_FIELDS[1:]):
        raise RuntimeError("Inconsistent aggregate counts")

    return {
        "status": (
            "REVIEW_REQUIRED" if counts["metadata_rows"]
            else "NO_METADATA_ROWS"
        ),
        **counts,
        "physical_files_verified": False,
        "complete_inventory_proven": False,
        "data_erasure_authorized": False,
    }


def main() -> int:
    if os.environ.get("SEC5_PRIV_ADVISORY_FILE_PROBE") != "EXPLICIT_READONLY":
        print("SEC5_ADVISORY_FILES: OPT_IN_REQUIRED", file=sys.stderr)
        return 2
    try:
        from app import app, db
        with app.app_context():
            result = inspect_advisory_file_metadata(db.engine)
    except Exception:
        # No errors/DSNs/identities are printed to logs or external services.
        print("SEC5_ADVISORY_FILES: INDETERMINATE", file=sys.stderr)
        return 2

    print("SEC5_ADVISORY_FILES: " + result["status"])
    for key in COUNT_FIELDS:
        print("SEC5_ADVISORY_FILES_" + key.upper() + ": " + str(result[key]))
    print("SEC5_ADVISORY_FILES_PHYSICAL_FILES_VERIFIED: false")
    print("SEC5_ADVISORY_FILES_COMPLETE_INVENTORY_PROVEN: false")
    return 1 if result["metadata_rows"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
