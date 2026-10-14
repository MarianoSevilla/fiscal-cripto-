"""B11F unit-only boundary tests: no database, Docker or Railway connections."""
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import preflight
import qa_b11f_real_pg18_readonly as b


def ci_env():
    return {"GITHUB_ACTIONS": "true", "CI": "true", "RUNNER_OS": "Linux"}


class TestB11FSyntheticBoundaries(unittest.TestCase):
    def test_exact_ci_scope_only(self):
        b.require_disposable_ci(ci_env())

    def test_missing_or_malformed_ci_flags_blocked(self):
        for key in ("GITHUB_ACTIONS", "CI", "RUNNER_OS"):
            with self.subTest(key=key), self.assertRaises(b.CiDenied):
                b.require_disposable_ci({**ci_env(), key: "invalid"})

    def test_injected_railway_identity_rejected(self):
        for key in ("RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID", "RAILWAY_PRIVATE_DOMAIN"):
            with self.subTest(key=key), self.assertRaises(b.CiDenied):
                b.require_disposable_ci({**ci_env(), key: "inject"})

    def test_database_and_approval_secrets_rejected(self):
        for key in ("DATABASE_URL", "TARGET_DATABASE_URL", "PGPASSWORD",
                    "PGHOST", "SOURCE_DATABASE_URL", "S01_SCHEMA_BOOTSTRAP_APPROVAL"):
            with self.subTest(key=key), self.assertRaises(b.CiDenied):
                b.require_disposable_ci({**ci_env(), key: "inject"})

    def test_synthetic_mapping_checks_real_service_constants(self):
        env = b.fake_identity()
        checked = preflight.checked_pg_environment(env)
        self.assertEqual(checked["PGHOST"], "postgres-im3h.railway.internal")
        self.assertEqual(env["RAILWAY_SERVICE_ID"], preflight.SERVICE_ID)

    def test_test_runner_rejects_sql_mutation(self):
        safe = preflight.checked_pg_environment(b.fake_identity())
        with self.assertRaisesRegex(b.CiDenied, "UNAPPROVED_SQL_QUERY"):
            b.readonly_runner(
                ["psql", "-c", "DROP TABLE public.x"],
                env=safe, text=True, capture_output=True, check=False, timeout=20,
            )

    def test_test_runner_rejects_wrong_private_target(self):
        safe = {**preflight.checked_pg_environment(b.fake_identity()), "PGHOST": "postgres.railway.internal"}
        with self.assertRaisesRegex(b.CiDenied, "PROBE_DID_NOT_PIN_TARGET_HOST"):
            b.readonly_runner(
                ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                 "-c", preflight.SQL],
                env=safe, text=True, capture_output=True, check=False, timeout=20,
            )

    def test_test_runner_checks_readonly_session(self):
        pg_env = preflight.checked_pg_environment(b.fake_identity())
        pg_env["PGOPTIONS"] = "-c statement_timeout=10000"
        with self.assertRaisesRegex(b.CiDenied, "PROBE_DID_NOT_REQUIRE_READONLY"):
            b.readonly_runner(
                ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                 "-c", preflight.SQL],
                env=pg_env, text=True, capture_output=True, check=False, timeout=20,
            )

    def test_test_runner_positive_is_mocked(self):
        fake = Mock(return_value="mocked readonly output")
        env = preflight.checked_pg_environment(b.fake_identity())
        with patch.object(b, "disposable_psql", fake):
            report = b.readonly_runner(
                ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1",
                 "-c", preflight.SQL],
                env=env, text=True, capture_output=True, check=False, timeout=20,
            )
        self.assertEqual(report.stdout, "mocked readonly output\n")
        fake.assert_called_once_with(preflight.SQL, readonly=True)

    def test_bad_ci_env_does_not_touch_database(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}, clear=True):
            with patch.object(b, "disposable_psql") as runner:
                with self.assertRaisesRegex(b.CiDenied, "NOT_GITHUB_CI"):
                    b.run()
                runner.assert_not_called()

    def test_real_cluster_ids_explicitly_forbidden(self):
        self.assertEqual(b.FORBIDDEN_CLUSTER_IDS, frozenset({
            "7696213098351943739",
            "7696517018472497211",
        }))

    def test_no_drop_database_or_production_connection(self):
        src = Path(b.__file__).read_text()
        self.assertNotIn("DROP DATABASE", src)
        self.assertNotIn("railway.com", src)
        self.assertNotIn("from app import", src)
        self.assertNotIn("connect_service_source", src)


if __name__ == "__main__":
    unittest.main()
