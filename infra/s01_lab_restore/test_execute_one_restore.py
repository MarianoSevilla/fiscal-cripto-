"""B10S release gate contracts; exclusively fake env and mocked worker."""
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import execute_one_restore as live
import probe
import restore_candidate as candidate


def fake_config():
    return {
        "RAILWAY_PROJECT_ID": probe.PROJECT,
        "RAILWAY_ENVIRONMENT_ID": probe.ENVIRONMENT,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": probe.RUNNER_SERVICE,
        "RAILWAY_PRIVATE_DOMAIN": probe.RUNNER_DOMAIN,
        "TARGET_DATABASE_URL": "postgresql://fake:fake-only-ci-secret@"
                               "postgres-im3h.railway.internal:5432/railway",
        "RESTORE_ENDPOINT": candidate.S3_ENDPOINT,
        "RESTORE_BUCKET": candidate.S3_BUCKET,
        "RESTORE_REGION": candidate.S3_REGION,
        "RESTORE_ACCESS_KEY_ID": "FAKE-CI-ONLY",
        "RESTORE_SECRET_ACCESS_KEY": "FAKE-CI-ONLY",
    }


class TestRealEntryApproval(TestCase):
    def test_without_explicit_gate_refuses_before_any_worker(self):
        worker = Mock()
        with self.assertRaises(live.ReleaseDenied) as caught:
            live.execute_approved(fake_config(), restore_fn=worker)
        self.assertEqual(caught.exception.code, "EXPLICIT_ONE_RESTORE_APPROVAL_MISSING")
        worker.assert_not_called()

    def test_generic_approval_false(self):
        worker = Mock()
        for value in ("true", "1", "procede", "approved", "", None):
            env = {**fake_config(), live.APPROVAL_KEY: value}
            with self.subTest(value=value), self.assertRaises(live.ReleaseDenied):
                live.execute_approved(env, restore_fn=worker)
        worker.assert_not_called()

    def test_unexpected_project_refused_after_approval(self):
        env = {**fake_config(), live.APPROVAL_KEY: live.APPROVAL_INTENT,
               "RAILWAY_PROJECT_ID": "production"}
        worker = Mock()
        with self.assertRaisesRegex(live.ReleaseDenied, "INVALID_PINNED_LAB"):
            live.execute_approved(env, restore_fn=worker)
        worker.assert_not_called()

    def test_source_database_url_refused_after_approval(self):
        env = {**fake_config(), live.APPROVAL_KEY: live.APPROVAL_INTENT,
               "DATABASE_URL": "postgresql://source-secret@postgres.railway.internal:5432/railway"}
        worker = Mock()
        with self.assertRaisesRegex(live.ReleaseDenied, "INVALID_PINNED_LAB"):
            live.execute_approved(env, restore_fn=worker)
        worker.assert_not_called()

    def test_wrong_target_hostname_refused(self):
        env = {**fake_config(), live.APPROVAL_KEY: live.APPROVAL_INTENT,
               "TARGET_DATABASE_URL": "postgresql://fake:fake@postgres.railway.internal:5432/railway"}
        worker = Mock()
        with self.assertRaisesRegex(live.ReleaseDenied, "INVALID_PINNED_LAB"):
            live.execute_approved(env, restore_fn=worker)
        worker.assert_not_called()

    def test_wrong_bucket_or_secret_refused(self):
        worker = Mock()
        for field, value in (("RESTORE_BUCKET", "wrong"), ("RESTORE_SECRET_ACCESS_KEY", "")):
            with self.subTest(field=field), self.assertRaises(live.ReleaseDenied):
                live.execute_approved({
                    **fake_config(), live.APPROVAL_KEY: live.APPROVAL_INTENT,
                    field: value,
                }, restore_fn=worker)
        worker.assert_not_called()

    def test_valid_synthetic_approved_path_calls_exactly_once(self):
        worker = Mock(return_value="RESTORE_VERIFIED_INDEPENDENT_RECOVERY_CLUSTER")
        env = {**fake_config(), live.APPROVAL_KEY: live.APPROVAL_INTENT}
        result = live.execute_approved(env, restore_fn=worker)
        self.assertEqual(result, "RESTORE_VERIFIED_INDEPENDENT_RECOVERY_CLUSTER")
        worker.assert_called_once_with(env)

    def test_main_default_without_var_never_runs_restore(self):
        buf = StringIO()
        with patch.object(live, "execute_approved",
                          side_effect=live.ReleaseDenied(
                              "EXPLICIT_ONE_RESTORE_APPROVAL_MISSING"
                          )), redirect_stderr(buf), self.assertRaises(SystemExit) as caught:
            live.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("NO-GO", buf.getvalue())

    def test_real_driver_errors_are_redacted(self):
        buf = StringIO()
        with patch.object(live, "execute_approved",
                          side_effect=RuntimeError(
                              "postgresql://PRODUCTION-SHOULD-NOT-PRINT"
                          )), redirect_stderr(buf), self.assertRaises(SystemExit):
            live.main()
        self.assertNotIn("PRODUCTION-SHOULD-NOT-PRINT", buf.getvalue())
        self.assertIn("REDACTED_ERROR", buf.getvalue())

    def test_active_image_differs_from_railway_configured_readonly_image(self):
        root = Path(__file__).resolve().parent
        active = (root / "Dockerfile.real-restore-guarded").read_text()
        readonly = (root / "Dockerfile.readonly-archive").read_text()
        self.assertIn("COPY execute_one_restore.py", active)
        self.assertIn("/app/execute_one_restore.py", active)
        self.assertNotIn("COPY execute_one_restore.py", readonly)
        self.assertNotIn("COPY restore_candidate.py", readonly)


if __name__ == "__main__":
    import unittest
    unittest.main()
