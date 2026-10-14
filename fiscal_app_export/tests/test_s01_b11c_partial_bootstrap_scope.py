"""Unit-only B11C safety tests: never connect to any database."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import qa_s01_b11c_partial_bootstrap_denial_pg18 as b
from private_maintenance_rehearsal import RehearsalDenied


class TestB11CScope(TestCase):
    def test_every_fixture_has_reversible_synthetic_ddl(self):
        self.assertEqual(len(b.FIXTURES), 4)
        for name, create, cleanup, evidence in b.FIXTURES:
            with self.subTest(name=name):
                self.assertTrue(create.startswith("CREATE"))
                self.assertTrue(cleanup.startswith("DROP"))
                self.assertTrue(evidence.startswith("SELECT"))
                self.assertNotIn("DROP DATABASE", cleanup)

    def test_only_synthetic_admin_loopback_dsn(self):
        self.assertEqual(
            b.ADMIN_DSN,
            "postgresql://postgres:ci-only-test-password@127.0.0.1:5432/postgres",
        )
        self.assertNotIn("railway.internal", b.ADMIN_DSN)

    def test_reject_non_ci_before_database_creation(self):
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "false", "CI": "false"},
                        clear=True):
            with patch.object(b, "create_empty_ci_database") as create:
                with self.assertRaises(RehearsalDenied):
                    b.run()
                create.assert_not_called()

    def test_reject_real_cluster_ids(self):
        self.assertEqual(
            b.FORBIDDEN_REAL_CLUSTERS,
            frozenset(("7696213098351943739", "7696517018472497211")),
        )

    def test_refusal_does_not_swallow_unexpected_errors(self):
        class Unexpected(Exception):
            pass
        with patch.object(b, "rehearse_once", side_effect=Unexpected):
            with self.assertRaises(Unexpected):
                b.expect_refusal({}, "NOT_PRISTINE")

    def test_preflight_refuses_noop_bootstrap(self):
        with patch.object(b, "rehearse_once", return_value="PASS"):
            with self.assertRaises(RehearsalDenied) as ex:
                b.expect_refusal({}, "NOT_PRISTINE")
            self.assertEqual(ex.exception.code, "UNSAFE_BOOTSTRAP_ACCEPTED")

    def test_no_runtime_ddl_entrypoint_in_new_script(self):
        text = Path(b.__file__).read_text()
        self.assertNotIn("from app import", text)
        self.assertNotIn("from bootstrap_db import", text)
        self.assertNotIn("railway.internal", text)
        self.assertNotIn("psql -h", text)


if __name__ == "__main__":
    import unittest
    unittest.main()
