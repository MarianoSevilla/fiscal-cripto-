"""STG-B10J: offline evidence checklist for a future S01 LAB restore drill.

It does NOT connect to databases, fetch secrets, inspect Railway resources,
restore backups, authorize DDL, or execute any subprocess. Evidence fields are
claims until independently corroborated with live provider/DB observations.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
import sys

LAB_PROJECT = "5f26aa6e-2e6d-46ef-bb5f-bca4ece07d5e"
LAB_ENVIRONMENT = "3f9758ef-4e26-4e8d-9dd4-7b9286d81ea8"
LAB_SOURCE_DB_SERVICE = "f680f3fc-4581-44ff-8bc1-d034840f2c7e"
LAB_SOURCE_VOLUME = "c35d178f-7473-4d0b-adb9-1faae815b7af"
LAB_CLUSTER = "7696213098351943739"
CHECK_NAMES = (
    "archive_sha256_valid",
    "archive_readable_by_pg_restore",
    "source_catalog_readonly",
    "target_was_empty",
    "alembic_head_equal",
    "relations_equal",
    "row_counts_equal",
    "constraints_equal",
    "indexes_equal",
    "seed_equal",
    "no_public_network_on_restore_runner",
    "backups_held_in_restricted_location",
)
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z"
)


class EvidenceDenied(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def verify_documented_evidence(record: Mapping[str, object]) -> str:
    """Check structure/coherence only, never independently attest authenticity.

    A passing return value must NEVER be treated as permission to run DDL.
    A new, separately signed human approval and independent live corroboration
    remain mandatory for any real Railway restore/bootstrap.
    """
    if not isinstance(record, Mapping):
        raise EvidenceDenied("FORMAT")

    source, backup, target, validation = (
        record.get("source"),
        record.get("backup"),
        record.get("target"),
        record.get("validation"),
    )
    if any(not isinstance(x, Mapping)
           for x in (source, backup, target, validation)):
        raise EvidenceDenied("MISSING_SECTIONS")

    if (
        source.get("project_id") != LAB_PROJECT
        or source.get("environment_id") != LAB_ENVIRONMENT
        or source.get("service_id") != LAB_SOURCE_DB_SERVICE
        or source.get("volume_id") != LAB_SOURCE_VOLUME
        or str(source.get("cluster_id")) != LAB_CLUSTER
        or source.get("database") != "railway"
        or type(source.get("pg_major")) is not int
        or source.get("pg_major") != 18
    ):
        raise EvidenceDenied("SOURCE_IDENTITY")

    digest = backup.get("sha256")
    if not isinstance(digest, str) or SHA256.fullmatch(digest) is None:
        raise EvidenceDenied("BACKUP_DIGEST")
    if (
        backup.get("type") != "pg_dump_custom"
        or backup.get("source_service_id") != LAB_SOURCE_DB_SERVICE
        or str(backup.get("source_cluster_id")) != LAB_CLUSTER
        or backup.get("sha256_restored") != digest
    ):
        raise EvidenceDenied("BACKUP_BINDING")

    if (
        target.get("project_id") != LAB_PROJECT
        or target.get("environment_id") != LAB_ENVIRONMENT
        or target.get("service_id") == LAB_SOURCE_DB_SERVICE
        or target.get("volume_id") == LAB_SOURCE_VOLUME
        or not isinstance(target.get("service_id"), str)
        or UUID.fullmatch(target.get("service_id")) is None
        or not isinstance(target.get("volume_id"), str)
        or UUID.fullmatch(target.get("volume_id")) is None
        or str(target.get("cluster_id")) == LAB_CLUSTER
        or str(target.get("cluster_id")) == ""
        or str(target.get("cluster_id")) == "None"
        or type(target.get("pg_major")) is not int
        or target.get("pg_major") != 18
        or target.get("database") != "railway"
    ):
        raise EvidenceDenied("TARGET_ISOLATION")

    if type(validation.get("pg_restore_exit_code")) is not int:
        raise EvidenceDenied("RESTORE_EXIT")
    if validation["pg_restore_exit_code"] != 0:
        raise EvidenceDenied("RESTORE_EXIT")

    for name in CHECK_NAMES:
        if validation.get(name) is not True:
            raise EvidenceDenied("INCOMPLETE_VALIDATION")

    return "EVIDENCE_FORMAT_COMPLETE_NOT_AUTHORIZATION"


def main() -> None:
    print("S01 STG-B10J: NO-GO (NO_REAL_RESTORE_OR_DDL_EXECUTOR)",
          file=sys.stderr, flush=True)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
