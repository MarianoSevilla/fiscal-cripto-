"""STG-B10J offline recovery attestation syntax tests; no PostgreSQL I/O."""
from __future__ import annotations

from contextlib import redirect_stderr
from copy import deepcopy
from io import StringIO
import unittest

import private_restore_evidence_gate as gate


def fake_record():
    """Entirely fictional metadata: never evidence of a real backup."""
    return {
        "source": {
            "project_id": gate.LAB_PROJECT,
            "environment_id": gate.LAB_ENVIRONMENT,
            "service_id": gate.LAB_SOURCE_DB_SERVICE,
            "volume_id": gate.LAB_SOURCE_VOLUME,
            "cluster_id": gate.LAB_CLUSTER,
            "database": "railway",
            "pg_major": 18,
        },
        "backup": {
            "type": "pg_dump_custom",
            "source_service_id": gate.LAB_SOURCE_DB_SERVICE,
            "source_cluster_id": gate.LAB_CLUSTER,
            "sha256": "a" * 64,
            "sha256_restored": "a" * 64,
        },
        "target": {
            "project_id": gate.LAB_PROJECT,
            "environment_id": gate.LAB_ENVIRONMENT,
            "service_id": "aa000000-0000-4000-8000-000000000001",
            "volume_id": "aa000000-0000-4000-8000-000000000002",
            "cluster_id": "7777777777777777777",
            "database": "railway",
            "pg_major": 18,
        },
        "validation": {
            "pg_restore_exit_code": 0,
            **{key: True for key in gate.CHECK_NAMES},
        },
    }


class RestoreEvidenceContract(unittest.TestCase):
    def assert_refuses(self, record, code):
        with self.assertRaises(gate.EvidenceDenied) as caught:
            gate.verify_documented_evidence(record)
        self.assertEqual(caught.exception.code, code)

    def test_explicit_positive_is_only_format_not_execution_authority(self):
        self.assertEqual(
            gate.verify_documented_evidence(fake_record()),
            "EVIDENCE_FORMAT_COMPLETE_NOT_AUTHORIZATION",
        )

    def test_absent_or_bad_sections_rejected(self):
        self.assert_refuses(None, "FORMAT")
        for key in ("source", "backup", "target", "validation"):
            record = fake_record()
            record.pop(key)
            with self.subTest(section=key):
                self.assert_refuses(record, "MISSING_SECTIONS")

    def test_wrong_source_project_rejected(self):
        record = fake_record()
        record["source"]["project_id"] = "production"
        self.assert_refuses(record, "SOURCE_IDENTITY")

    def test_wrong_source_environment_rejected(self):
        record = fake_record()
        record["source"]["environment_id"] = "staging"
        self.assert_refuses(record, "SOURCE_IDENTITY")

    def test_wrong_source_service_or_volume_rejected(self):
        for key in ("service_id", "volume_id", "cluster_id"):
            record = fake_record()
            record["source"][key] = "wrong"
            with self.subTest(key=key):
                self.assert_refuses(record, "SOURCE_IDENTITY")

    def test_wrong_source_database_pg_major_rejected(self):
        for key, value in (("database", "postgres"), ("pg_major", 17),
                           ("pg_major", True)):
            record = fake_record()
            record["source"][key] = value
            with self.subTest(key=key, value=value):
                self.assert_refuses(record, "SOURCE_IDENTITY")

    def test_backup_digest_format_rejected(self):
        for digest in ("abc", "A" * 64, "x" * 64, "", None):
            record = fake_record()
            record["backup"]["sha256"] = digest
            with self.subTest(digest=str(digest)[:8]):
                self.assert_refuses(record, "BACKUP_DIGEST")

    def test_backup_digest_must_match_restored_digest(self):
        record = fake_record()
        record["backup"]["sha256_restored"] = "b" * 64
        self.assert_refuses(record, "BACKUP_BINDING")

    def test_backup_must_be_bound_to_correct_source(self):
        for key in ("type", "source_service_id", "source_cluster_id"):
            record = fake_record()
            record["backup"][key] = "wrong"
            with self.subTest(key=key):
                self.assert_refuses(record, "BACKUP_BINDING")

    def test_original_db_must_never_be_restore_target(self):
        for key, value in (
            ("service_id", gate.LAB_SOURCE_DB_SERVICE),
            ("volume_id", gate.LAB_SOURCE_VOLUME),
            ("cluster_id", gate.LAB_CLUSTER),
        ):
            record = fake_record()
            record["target"][key] = value
            with self.subTest(key=key):
                self.assert_refuses(record, "TARGET_ISOLATION")

    def test_target_must_be_distinct_valid_lab_pg18(self):
        for key, value in (
            ("project_id", "production"),
            ("environment_id", "production"),
            ("service_id", "not-uuid"),
            ("volume_id", "not-uuid"),
            ("pg_major", 17),
            ("database", "prod"),
            ("cluster_id", None),
        ):
            record = fake_record()
            record["target"][key] = value
            with self.subTest(key=key):
                self.assert_refuses(record, "TARGET_ISOLATION")

    def test_restore_error_rejected_including_bool(self):
        for code in (1, -1, None, True, "0"):
            record = fake_record()
            record["validation"]["pg_restore_exit_code"] = code
            with self.subTest(code=code):
                self.assert_refuses(record, "RESTORE_EXIT")

    def test_every_integrity_check_mandatory(self):
        for name in gate.CHECK_NAMES:
            record = fake_record()
            record["validation"][name] = False
            with self.subTest(name=name):
                self.assert_refuses(record, "INCOMPLETE_VALIDATION")

    def test_no_missing_or_implicit_validation_truthy(self):
        for name in gate.CHECK_NAMES:
            for value in ("true", 1, None):
                record = fake_record()
                record["validation"][name] = value
                with self.subTest(name=name, value=value):
                    self.assert_refuses(record, "INCOMPLETE_VALIDATION")

    def test_runtime_command_always_denied(self):
        buffer = StringIO()
        with redirect_stderr(buffer), self.assertRaises(SystemExit) as caught:
            gate.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("NO_REAL_RESTORE_OR_DDL_EXECUTOR", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
