"""Pure security contract tests, no DB connections or app import."""
from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
import inspect
import os
import unittest
from unittest.mock import patch

import private_maintenance_rehearsal as rehearsal


def synthetic_env():
    return {"GITHUB_ACTIONS": "true", "CI": "true", "RUNNER_OS": "Linux"}


class B10CContract(unittest.TestCase):
    def test_synthetic_ci_fixture_is_only_accepted_target(self):
        rehearsal.require_synthetic_ci(synthetic_env(), rehearsal.CI_DSN)

    def test_runtime_cli_fails_closed_unconditionally(self):
        out = StringIO()
        with redirect_stderr(out):
            with self.assertRaises(SystemExit) as exc:
                rehearsal.main()
        self.assertEqual(exc.exception.code, 1)
        self.assertIn("RUNTIME_EXECUTION_NOT_AUTHORIZED", out.getvalue())

    def test_railway_identity_always_forbidden(self):
        for marker in ("RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID",
                       "RAILWAY_ENVIRONMENT_ID", "RAILWAY_PRIVATE_DOMAIN"):
            env = synthetic_env()
            env[marker] = "dummy"
            with self.subTest(marker=marker), self.assertRaises(rehearsal.RehearsalDenied):
                rehearsal.require_synthetic_ci(env, rehearsal.CI_DSN)

    def test_railway_database_url_always_forbidden(self):
        env = synthetic_env()
        env["DATABASE_URL"] = "postgresql://secret@postgres.railway.internal/railway"
        with self.assertRaises(rehearsal.RehearsalDenied):
            rehearsal.require_synthetic_ci(env, rehearsal.CI_DSN)

    def test_alternate_destinations_always_denied(self):
        urls = (
            "postgresql://postgres:ci-only-test-password@localhost:5432/railway",
            "postgresql://postgres:ci-only-test-password@127.0.0.1:5433/railway",
            "postgresql://postgres:ci-only-test-password@127.0.0.1:5432/production",
            "postgresql://postgres:ci-only-test-password@postgres.railway.internal:5432/railway",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(rehearsal.RehearsalDenied):
                rehearsal.require_synthetic_ci(synthetic_env(), url)

    def test_false_ci_flags_denied(self):
        for key in ("CI", "GITHUB_ACTIONS", "RUNNER_OS"):
            env = synthetic_env()
            del env[key]
            with self.subTest(key=key), self.assertRaises(rehearsal.RehearsalDenied):
                rehearsal.require_synthetic_ci(env, rehearsal.CI_DSN)

    def test_precheck_happens_before_database_connect(self):
        with patch.object(rehearsal, "require_synthetic_ci",
                          side_effect=rehearsal.RehearsalDenied("DENIED")):
            with self.assertRaises(rehearsal.RehearsalDenied):
                rehearsal.rehearse_once(synthetic_env())

    def test_ddl_is_not_reached_when_graph_check_fails(self):
        with patch.object(rehearsal, "assert_graph_head",
                          side_effect=rehearsal.RehearsalDenied("MIGRATION_GRAPH")):
            with self.assertRaises(rehearsal.RehearsalDenied):
                rehearsal.rehearse_once(synthetic_env())

    def test_web_app_never_imported_in_migration_context(self):
        source = inspect.getsource(rehearsal)
        self.assertNotIn("from app import", source)
        self.assertNotIn("import app\n", source)
        self.assertNotIn("bootstrap_db.main", source)
        self.assertNotIn("os.getenv('ALLOW_DDL')", source)

    def test_runner_cli_never_invokes_rehearsal(self):
        source = inspect.getsource(rehearsal.main)
        self.assertNotIn("rehearse_once(", source)
        self.assertNotIn("db.create_all", source)

    def test_no_automatic_drop_or_truncate(self):
        src = inspect.getsource(rehearsal)
        for forbidden in ("DROP DATABASE", "DROP SCHEMA", "TRUNCATE ",
                          "delete_all(", "connection.commit("):
            self.assertNotIn(forbidden, src)

    def test_advisory_lock_is_fixed(self):
        self.assertEqual(rehearsal.LOCK_KEYS, (2026, 1010))


if __name__ == "__main__":
    unittest.main()
