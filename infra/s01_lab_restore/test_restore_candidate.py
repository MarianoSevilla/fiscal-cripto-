"""B10O synthetic candidate: positive flow and hard denials. NO Railway I/O."""
from __future__ import annotations

from contextlib import redirect_stderr
import hashlib
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import probe
import restore_candidate as r


def fake_env():
    return {
        "RAILWAY_PROJECT_ID": probe.PROJECT,
        "RAILWAY_ENVIRONMENT_ID": probe.ENVIRONMENT,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": probe.RUNNER_SERVICE,
        "RAILWAY_PRIVATE_DOMAIN": probe.RUNNER_DOMAIN,
        "TARGET_DATABASE_URL":
            "postgresql://fake-ci:fake-only-secret@"
            "postgres-im3h.railway.internal:5432/railway",
        "RESTORE_ENDPOINT": r.S3_ENDPOINT,
        "RESTORE_BUCKET": r.S3_BUCKET,
        "RESTORE_REGION": r.S3_REGION,
        "RESTORE_ACCESS_KEY_ID": "CI-ONLY",
        "RESTORE_SECRET_ACCESS_KEY": "NOT-A-REAL-KEY",
    }


class FakeBucket:
    def __init__(self, data):
        self.data = data
        self.calls = []
        self.claimed = False
        self.metadata = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "cluster": probe.ORIGINAL_CLUSTER,
            "database": "railway",
            "pgmajor": "18",
        }

    def head_object(self, **kwargs):
        self.calls.append("head")
        return {"Metadata": dict(self.metadata), "ContentLength": len(self.data)}

    def get_object(self, **kwargs):
        self.calls.append("get")
        return {"ContentLength": len(self.data), "Body": BytesIO(self.data)}

    def put_object(self, **kwargs):
        self.calls.append("intent")
        if self.claimed:
            raise RuntimeError("The intent key already exists")
        if kwargs.get("Key") != r.RESTORE_INTENT_KEY or kwargs.get("IfNoneMatch") != "*":
            raise RuntimeError("A non-atomic marker attempt")
        self.claimed = True
        return {"ETag": '"ci-only"'}


class TestRestoreCandidate(TestCase):
    def setUp(self):
        self.data = b"PGDMP" + b"synthetic-archive-content-only"
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.pin = patch.object(r, "EXPECTED_SHA256", self.digest)
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def run_synthetic(self, bucket=None, fn=None, cli=None, env=None):
        b = bucket or FakeBucket(self.data)
        probe_mock = fn or Mock(return_value=probe.EXPECTED_TARGET_CLUSTER)
        runner = cli or Mock(side_effect=lambda argv, **kw:
            SimpleNamespace(
                returncode=0,
                stdout="; synthetic pg_restore archive\n" if "--list" in argv else ""
            ))
        value = r.restore_once(env or fake_env(), client=b,
                               probe_fn=probe_mock, cli_runner=runner)
        return value, b, probe_mock, runner

    def test_exact_configuration_accepted_without_socket(self):
        pg = r.validate_configuration(fake_env())
        self.assertEqual(pg["PGHOST"], probe.TARGET_HOST)
        self.assertEqual(pg["PGDATABASE"], "railway")
        self.assertEqual(pg["PGSSLMODE"], "require")
        self.assertIn("default_transaction_read_only=on", pg["PGOPTIONS"])

    def test_wrong_project_denied(self):
        with self.assertRaisesRegex(r.RestoreDenied, "TARGET_WRONG_RAILWAY_IDENTITY"):
            r.validate_configuration({**fake_env(), "RAILWAY_PROJECT_ID": "prod"})

    def test_source_dsn_injected_denied(self):
        for name in ("DATABASE_URL", "SOURCE_DATABASE_URL", "PGHOST"):
            with self.subTest(name=name), self.assertRaisesRegex(
                r.RestoreDenied, "TARGET_UNEXPECTED_DATABASE_SOURCE"
            ):
                r.validate_configuration({**fake_env(), name: "source"})

    def test_original_host_denied(self):
        values = fake_env()
        values["TARGET_DATABASE_URL"] = (
            "postgresql://u:p@postgres.railway.internal:5432/railway"
        )
        with self.assertRaisesRegex(r.RestoreDenied, "TARGET_WRONG_TARGET_DATABASE"):
            r.validate_configuration(values)

    def test_public_marker_denied(self):
        with self.assertRaisesRegex(r.RestoreDenied, "TARGET_PUBLIC_MARKER"):
            r.validate_configuration({**fake_env(), "RAILWAY_PUBLIC_DOMAIN": "evil"})

    def test_missing_storage_key_denied(self):
        for key in ("RESTORE_SECRET_ACCESS_KEY", "RESTORE_ACCESS_KEY_ID"):
            with self.subTest(key=key), self.assertRaises(r.RestoreDenied):
                r.validate_configuration({**fake_env(), key: ""})

    def test_wrong_bucket_endpoint_or_name_denied(self):
        for key in ("RESTORE_ENDPOINT", "RESTORE_BUCKET", "RESTORE_REGION"):
            with self.subTest(key=key), self.assertRaisesRegex(
                r.RestoreDenied, "STORAGE_REFERENCE"
            ):
                r.validate_configuration({**fake_env(), key: "foreign"})

    def test_positive_flow_pins_hash_and_calls_once(self):
        val, bucket, probe_mock, runner = self.run_synthetic()
        self.assertEqual(val, "RESTORE_VERIFIED_INDEPENDENT_RECOVERY_CLUSTER")
        self.assertEqual(bucket.calls, ["head", "get", "intent"])
        self.assertTrue(bucket.claimed)
        self.assertEqual(probe_mock.call_count, 3)
        args = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(len(args), 2)
        self.assertEqual(args[0][0:2], ["pg_restore", "--list"])
        self.assertEqual(args[1][0:4], [
            "pg_restore", "--exit-on-error", "--single-transaction",
            "--no-owner",
        ])
        self.assertNotIn("--clean", args[1])
        self.assertNotIn("--create", args[1])
        self.assertEqual(args[1].count("--single-transaction"), 1)
        self.assertTrue(args[1][-1].endswith("/verified.pgcustom"))
        env = runner.call_args_list[-1].kwargs["env"]
        self.assertEqual(env["PGHOST"], probe.TARGET_HOST)
        self.assertNotIn("default_transaction_read_only=on", env["PGOPTIONS"])
        self.assertEqual(env["PGSSLMODE"], "require")

    def test_wrong_preflight_cluster_denied_before_bucket(self):
        bucket = FakeBucket(self.data)
        client_fn = Mock()
        with self.assertRaisesRegex(r.RestoreDenied, "PRECHECK_TARGET_MISMATCH"):
            r.restore_once(fake_env(), client=bucket,
                           probe_fn=Mock(return_value="someone-else"),
                           cli_runner=client_fn)
        self.assertFalse(bucket.calls)
        client_fn.assert_not_called()

    def test_probe_denial_before_bucket_denied(self):
        bucket = FakeBucket(self.data)
        with self.assertRaisesRegex(r.RestoreDenied, "PRECHECK_TARGET_NOT_PRISTINE"):
            r.restore_once(fake_env(), client=bucket,
                           probe_fn=Mock(side_effect=probe.ProbeDenied(
                               "TARGET_NOT_PRISTINE"
                           )))
        self.assertFalse(bucket.calls)

    def test_wrong_archive_metadata_denied(self):
        bucket = FakeBucket(self.data)
        bucket.metadata["cluster"] = probe.EXPECTED_TARGET_CLUSTER
        with self.assertRaisesRegex(r.RestoreDenied, "ARCHIVE_METADATA"):
            r.restore_once(fake_env(), client=bucket,
                           probe_fn=Mock(return_value=probe.EXPECTED_TARGET_CLUSTER))
        self.assertEqual(bucket.calls, ["head"])

    def test_wrong_s3_digest_denied(self):
        bucket = FakeBucket(self.data)
        bucket.metadata["sha256"] = "0" * 64
        with self.assertRaisesRegex(r.RestoreDenied, "ARCHIVE_METADATA"):
            r.restore_once(fake_env(), client=bucket,
                           probe_fn=Mock(return_value=probe.EXPECTED_TARGET_CLUSTER))

    def test_truncated_download_denied_before_intent(self):
        bucket = FakeBucket(self.data)
        bucket.get_object = lambda **kwargs: {
            "ContentLength": len(bucket.data),
            "Body": BytesIO(bucket.data[:-1]),
        }
        with self.assertRaisesRegex(r.RestoreDenied, "ARCHIVE_SHA256|ARCHIVE_LENGTH"):
            r.restore_once(fake_env(), client=bucket,
                           probe_fn=Mock(return_value=probe.EXPECTED_TARGET_CLUSTER))
        self.assertFalse(bucket.claimed)

    def test_archive_larger_than_limit_denied(self):
        bucket = FakeBucket(self.data)
        bucket.head_object = lambda **kwargs: {
            "Metadata": bucket.metadata, "ContentLength": r.MAX_ARCHIVE_BYTES+1,
        }
        with self.assertRaisesRegex(r.RestoreDenied, "ARCHIVE_SIZE"):
            r.restore_once(fake_env(), client=bucket,
                           probe_fn=Mock(return_value=probe.EXPECTED_TARGET_CLUSTER))
        self.assertFalse(bucket.claimed)

    def test_wrong_archive_magic_denied(self):
        b = FakeBucket(b"WRONG" + self.data[5:])
        with patch.object(r, "EXPECTED_SHA256", hashlib.sha256(b.data).hexdigest()):
            with self.assertRaisesRegex(r.RestoreDenied, "ARCHIVE_FORMAT"):
                r.restore_once(fake_env(), client=b,
                               probe_fn=Mock(return_value=probe.EXPECTED_TARGET_CLUSTER))
        self.assertFalse(b.claimed)

    def test_invalid_toc_denied_before_marker(self):
        bucket = FakeBucket(self.data)
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout="BAD TOC"))
        with self.assertRaisesRegex(r.RestoreDenied, "ARCHIVE_TOC"):
            r.restore_once(fake_env(), client=bucket,
                           probe_fn=Mock(return_value=probe.EXPECTED_TARGET_CLUSTER),
                           cli_runner=runner)
        self.assertFalse(bucket.claimed)

    def test_changed_destination_on_second_preflight_denied(self):
        bucket = FakeBucket(self.data)
        probe_fn = Mock(side_effect=[
            probe.EXPECTED_TARGET_CLUSTER, probe.ORIGINAL_CLUSTER
        ])
        with self.assertRaisesRegex(r.RestoreDenied, "SECOND_PRECHECK_TARGET_MISMATCH"):
            r.restore_once(fake_env(), client=bucket,
                           probe_fn=probe_fn,
                           cli_runner=Mock(return_value=SimpleNamespace(
                               returncode=0, stdout="; toc"
                           )))
        self.assertFalse(bucket.claimed)

    def test_marker_failure_blocks_any_pg_restore_write(self):
        bucket = FakeBucket(self.data)
        bucket.claimed = True
        calls = []
        def cli(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout="; toc")
        with self.assertRaisesRegex(r.RestoreDenied, "RESTORE_INTENT_ALREADY_EXISTS"):
            r.restore_once(fake_env(), client=bucket,
                           probe_fn=Mock(return_value=probe.EXPECTED_TARGET_CLUSTER),
                           cli_runner=cli)
        self.assertEqual(len(calls), 1)
        self.assertIn("--list", calls[0])

    def test_second_execution_replay_rejected(self):
        b = FakeBucket(self.data)
        self.run_synthetic(bucket=b)
        with self.assertRaisesRegex(r.RestoreDenied, "RESTORE_INTENT_ALREADY_EXISTS"):
            self.run_synthetic(bucket=b)

    def test_failed_pg_restore_cannot_auto_retry(self):
        b = FakeBucket(self.data)
        runner = Mock(side_effect=[
            SimpleNamespace(returncode=0, stdout="; toc"),
            SimpleNamespace(returncode=1, stdout="secret data in error"),
        ])
        with self.assertRaisesRegex(r.RestoreDenied, "RESTORE_CLI_FAILED"):
            r.restore_once(fake_env(), client=b,
                           probe_fn=Mock(return_value=probe.EXPECTED_TARGET_CLUSTER),
                           cli_runner=runner)
        self.assertTrue(b.claimed)
        self.assertEqual(runner.call_count, 2)

    def test_postflight_denial_never_clears_marker(self):
        b = FakeBucket(self.data)
        probe_fn = Mock(side_effect=[
            probe.EXPECTED_TARGET_CLUSTER, probe.EXPECTED_TARGET_CLUSTER,
            probe.ProbeDenied("TARGET_NOT_PRISTINE"),
        ])
        with self.assertRaisesRegex(r.RestoreDenied, "POSTCHECK_TARGET_NOT_PRISTINE"):
            r.restore_once(fake_env(), client=b, probe_fn=probe_fn,
                           cli_runner=Mock(side_effect=lambda argv, **kw:
                               SimpleNamespace(returncode=0, stdout="; toc")))
        self.assertTrue(b.claimed)

    def test_main_always_no_go_without_importing_sdk(self):
        log = StringIO()
        with patch.object(r, "restore_once") as execute:
            with redirect_stderr(log), self.assertRaises(SystemExit) as err:
                r.main()
        self.assertEqual(err.exception.code, 1)
        self.assertIn("LIVE_RESTORE_NOT_AUTHORIZED", log.getvalue())
        execute.assert_not_called()


if __name__ == "__main__":
    import unittest
    unittest.main()
