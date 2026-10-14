"""B11D unit contracts — no database I/O (all synthetic)."""
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import qa_s01_b11d_interrupted_bootstrap_pg18 as b
from private_maintenance_rehearsal import RehearsalDenied


class TestB11DInterruptions(TestCase):
    def test_four_explicit_fault_stages(self):
        self.assertEqual(b.ALLOWED_CASES, frozenset((
            "after-models", "after-stamp", "mid-upgrade", "after-upgrade"
        )))

    def test_unknown_case_rejected_before_database_creation(self):
        env = {"GITHUB_ACTIONS": "true", "CI": "true", "RUNNER_OS": "Linux"}
        with patch.dict(os.environ, env, clear=True):
            with patch.object(b, "create_empty_ci_database") as db:
                with self.assertRaises(b.InterruptedRunDenied):
                    b.run("unsupported")
                db.assert_not_called()

    def test_no_ci_marker_rejected_before_database_creation(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(b, "create_empty_ci_database") as db:
                with self.assertRaises(RehearsalDenied):
                    b.run("after-models")
                db.assert_not_called()

    def test_railway_env_rejected_before_database_creation(self):
        env = {
            "GITHUB_ACTIONS": "true", "CI": "true", "RUNNER_OS": "Linux",
            "RAILWAY_PROJECT_ID": "not-allowed"
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(b, "create_empty_ci_database") as db:
                with self.assertRaises(RehearsalDenied):
                    b.run("after-stamp")
                db.assert_not_called()

    def test_real_database_url_rejected_before_database_creation(self):
        env = {
            "GITHUB_ACTIONS": "true", "CI": "true", "RUNNER_OS": "Linux",
            "DATABASE_URL": "postgresql://not-allowed"
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(b, "create_empty_ci_database") as db:
                with self.assertRaises(RehearsalDenied):
                    b.run("mid-upgrade")
                db.assert_not_called()

    def test_ci_dsn_is_local_not_railway(self):
        from private_maintenance_rehearsal import CI_DSN
        self.assertEqual(
            CI_DSN,
            "postgresql://postgres:ci-only-test-password@127.0.0.1:5432/railway",
        )

    def test_source_contains_no_drop_or_web_app_entrypoint(self):
        source = Path(b.__file__).read_text()
        self.assertNotIn("DROP DATABASE", source)
        self.assertNotIn("from app import", source)
        self.assertNotIn("from bootstrap_db import", source)
        self.assertNotIn("railway.internal", source)

    def test_unknown_case_never_injects_any_step(self):
        with self.assertRaises(b.InterruptedRunDenied):
            b.interrupt_case({}, "not-a-real-case")

    def test_after_models_fails_before_stamp(self):
        with patch.object(b.rehearsal, "rehearse_once",
                          side_effect=b.SyntheticInterruption("fixture")):
            with self.assertRaises(b.SyntheticInterruption):
                b.interrupt_case({}, "after-models")

    def test_after_stamp_fails_before_upgrade(self):
        with patch.object(b.rehearsal, "rehearse_once",
                          side_effect=b.SyntheticInterruption("fixture")):
            with self.assertRaises(b.SyntheticInterruption):
                b.interrupt_case({}, "after-stamp")


if __name__ == "__main__":
    import unittest
    unittest.main()
