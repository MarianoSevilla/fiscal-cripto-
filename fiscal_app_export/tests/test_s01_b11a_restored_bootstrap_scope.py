"""STG-B11A: deny any non-disposable/real PostgreSQL execution."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qa_s01_b11a_restored_bootstrap_pg18 as b
from private_maintenance_rehearsal import RehearsalDenied


def fixture():
    return {
        "GITHUB_ACTIONS": "true",
        "CI": "true",
        "RUNNER_OS": "Linux",
    }


class TestRestoredBootstrapScope(unittest.TestCase):
    def test_only_approved_ci_scope(self):
        b.require_fixture_scope(fixture())

    def test_reject_missing_ci_identity(self):
        for name in ("GITHUB_ACTIONS", "CI", "RUNNER_OS"):
            with self.subTest(name=name), self.assertRaises(RehearsalDenied):
                b.require_fixture_scope({**fixture(), name: "no"})

    def test_reject_railway_service_marker(self):
        for name in ("RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID"):
            with self.subTest(name=name), self.assertRaises(RehearsalDenied):
                b.require_fixture_scope({**fixture(), name: "any-value"})

    def test_reject_database_source_variables(self):
        for name in (
            "DATABASE_URL", "TARGET_DATABASE_URL", "SOURCE_DATABASE_URL",
            "PGHOST", "PGSERVICE", "PGPASSWORD", "PGPASSFILE",
        ):
            with self.subTest(name=name), self.assertRaises(RehearsalDenied):
                b.require_fixture_scope({**fixture(), name: "unsafe"})

    def test_reject_real_restore_approval(self):
        for name in (
            "S01_RECOVERY_WRITE_APPROVAL", "B11A_RESTORE_REAL_BACKUP",
        ):
            with self.subTest(name=name), self.assertRaises(RehearsalDenied):
                b.require_fixture_scope({**fixture(), name: "true"})

    def test_only_loopback_synthetic_pg_ports(self):
        self.assertIn("@127.0.0.1:5432/railway", b.dsn(b.DESTINATION_PORT))
        self.assertIn("@127.0.0.1:55433/postgres", b.dsn(b.SOURCE_PORT, "postgres"))
        for value in (22, 5433, 11111, -1, 0):
            with self.subTest(value=value), self.assertRaises(RehearsalDenied):
                b.dsn(value)

    def test_database_allowlist(self):
        for value in ("production", "railway-public", "other"):
            with self.subTest(value=value), self.assertRaises(RehearsalDenied):
                b.dsn(b.DESTINATION_PORT, value)

    def test_real_cluster_id_denied_even_if_distinct(self):
        for value in b.FORBIDDEN_REAL_CLUSTERS:
            with self.subTest(value=value):
                with self.assertRaises(RehearsalDenied):
                    b.assert_disposable_clusters(value, "7777777777777777777")
                with self.assertRaises(RehearsalDenied):
                    b.assert_disposable_clusters("7777777777777777777", value)

    def test_matching_or_malformed_cluster_ids_denied(self):
        for source, target in (
            ("7777777777777777777", "7777777777777777777"),
            ("bad-host", "7777777777777777777"),
            ("7777777777777777777", "not-a-cluster"),
        ):
            with self.subTest(source=source, target=target):
                with self.assertRaises(RehearsalDenied):
                    b.assert_disposable_clusters(source, target)

    def test_distinct_valid_synthetic_cluster_ids(self):
        b.assert_disposable_clusters(
            "7777777777777777777", "8888888888888888888"
        )

    def test_script_does_not_import_web_entrypoint(self):
        code = Path(b.__file__).read_text()
        self.assertNotIn("from app import", code)
        self.assertNotIn("from bootstrap_db import", code)
        self.assertNotIn("railway.internal", code)
        self.assertNotIn("main()", code.split("def run():")[0])

    def test_no_database_access_when_scope_invalid(self):
        with patch.object(b, "create_empty_ci_database") as create:
            with patch.dict(os.environ, {"DATABASE_URL": "do-not-connect"}):
                with self.assertRaises(RehearsalDenied):
                    b.run()
            create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
