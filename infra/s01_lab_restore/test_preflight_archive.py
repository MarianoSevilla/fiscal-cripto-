"""B10Q: all data and calls are synthetic; no Railway or S3 connections."""
from contextlib import redirect_stderr
import hashlib
from io import BytesIO, StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import probe
import preflight_archive as q


def env():
    return {
        "RAILWAY_PROJECT_ID": probe.PROJECT,
        "RAILWAY_ENVIRONMENT_ID": probe.ENVIRONMENT,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": probe.RUNNER_SERVICE,
        "RAILWAY_PRIVATE_DOMAIN": probe.RUNNER_DOMAIN,
        "TARGET_DATABASE_URL": "postgresql://ci-only:ci-fake-secret@"
                               "postgres-im3h.railway.internal:5432/railway",
        "RESTORE_ENDPOINT": q.ENDPOINT,
        "RESTORE_BUCKET": q.BUCKET,
        "RESTORE_REGION": q.REGION,
        "RESTORE_ACCESS_KEY_ID": "CI-FAKE-ACCESS",
        "RESTORE_SECRET_ACCESS_KEY": "CI-FAKE-SECRET",
    }


class StubBucket:
    def __init__(self, data):
        self.data = data
        self.calls = []
        self.metadata = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "cluster": q.SOURCE_CLUSTER,
            "database": "railway",
            "pgmajor": "18",
        }

    def head_object(self, **kwargs):
        self.calls.append(("head", kwargs))
        return {"Metadata": self.metadata.copy(),
                "ContentLength": len(self.data)}

    def get_object(self, **kwargs):
        self.calls.append(("get", kwargs))
        return {"ContentLength": len(self.data), "Body": BytesIO(self.data)}

    def put_object(self, **kwargs):
        raise AssertionError("NO S3 write allowed")


class TestQPreflight(unittest.TestCase):
    def setUp(self):
        self.archive = b"PGDMP" + b"SYNTHETIC ONLY NOT A REAL ARCHIVE"
        self.b = StubBucket(self.archive)
        self.pin = patch.object(
            q, "EXPECTED_SHA256", hashlib.sha256(self.archive).hexdigest()
        )
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.probe_fn = Mock(return_value=q.TARGET_CLUSTER)
        self.runner = Mock(return_value=SimpleNamespace(
            returncode=0, stdout="; TOC of synthetic CI archive\n"
        ))

    def inspect(self, values=None):
        return q.inspect(
            env() if values is None else values,
            client=self.b,
            probe_fn=self.probe_fn,
            list_runner=self.runner,
        )

    def assert_denied(self, reason, values):
        with self.assertRaises(q.AuditDenied) as err:
            self.inspect(values)
        self.assertEqual(err.exception.code, reason)

    def test_valid_configuration_only_pins_recovery_db(self):
        pg = q.validate_env(env())
        self.assertEqual(pg["PGHOST"], probe.TARGET_HOST)
        self.assertEqual(pg["PGSSLMODE"], "require")
        self.assertIn("default_transaction_read_only=on", pg["PGOPTIONS"])

    def test_target_db_source_injection_refused(self):
        for name in ("DATABASE_URL", "SOURCE_DATABASE_URL", "PGHOST"):
            with self.subTest(name=name):
                self.assert_denied(
                    "TARGET_UNEXPECTED_DATABASE_SOURCE",
                    {**env(), name: "postgresql://secret"},
                )
        self.probe_fn.assert_not_called()

    def test_nonlab_railway_identity_refused(self):
        self.assert_denied(
            "TARGET_WRONG_RAILWAY_IDENTITY",
            {**env(), "RAILWAY_SERVICE_ID": "other"},
        )

    def test_wrong_destination_private_host_refused(self):
        self.assert_denied(
            "TARGET_WRONG_TARGET_DATABASE",
            {**env(), "TARGET_DATABASE_URL":
                "postgresql://u:p@postgres.railway.internal:5432/railway"},
        )

    def test_public_domain_refused(self):
        self.assert_denied(
            "TARGET_PUBLIC_MARKER",
            {**env(), "RAILWAY_PUBLIC_DOMAIN": "unapproved"},
        )

    def test_unexpected_s3_endpoint_and_bucket_refused(self):
        for name in ("RESTORE_ENDPOINT", "RESTORE_BUCKET", "RESTORE_REGION"):
            with self.subTest(name=name):
                self.assert_denied("STORAGE_REFERENCE_" + name,
                    {**env(), name: "fake-different"})
        self.probe_fn.assert_not_called()

    def test_missing_s3_secret_refused_without_showing_value(self):
        for name in ("RESTORE_ACCESS_KEY_ID", "RESTORE_SECRET_ACCESS_KEY"):
            with self.subTest(name=name):
                self.assert_denied("STORAGE_CREDENTIAL_" + name,
                    {**env(), name: ""})

    def test_happy_path_only_readonly_probe_get_head_and_list(self):
        result = self.inspect()
        self.assertEqual(result, hashlib.sha256(self.archive).hexdigest())
        self.assertEqual([name for name, _ in self.b.calls], ["head", "get"])
        self.assertEqual(self.probe_fn.call_count, 2)
        argv = self.runner.call_args.args[0]
        self.assertEqual(argv[0:2], ["pg_restore", "--list"])
        self.assertNotIn("--dbname", argv)
        self.assertNotIn("--clean", argv)
        self.assertNotIn("--create", argv)
        self.assertNotIn("pg_restore", self.probe_fn.call_args.args[0])

    def test_original_cluster_denied_before_bucket(self):
        self.probe_fn.return_value = q.SOURCE_CLUSTER
        with self.assertRaisesRegex(q.AuditDenied, "FIRST_PROBE_WRONG_CLUSTER"):
            self.inspect()
        self.assertEqual(self.b.calls, [])

    def test_unexpected_cluster_denied_before_bucket(self):
        self.probe_fn.return_value = "8888888888888888888"
        with self.assertRaisesRegex(q.AuditDenied, "FIRST_PROBE_WRONG_CLUSTER"):
            self.inspect()
        self.assertEqual(self.b.calls, [])

    def test_head_wrong_archive_metadata_refused(self):
        self.b.metadata["cluster"] = q.TARGET_CLUSTER
        with self.assertRaisesRegex(q.AuditDenied, "ARCHIVE_METADATA"):
            self.inspect()
        self.assertEqual([name for name, _ in self.b.calls], ["head"])

    def test_head_bad_sha_metadata_refused(self):
        self.b.metadata["sha256"] = "0" * 64
        with self.assertRaisesRegex(q.AuditDenied, "ARCHIVE_METADATA"):
            self.inspect()

    def test_modified_archive_payload_rejected(self):
        self.b.data = b"PGDMP" + b"MODIFIED PAYLOAD OF THE SAME LENGTH"
        self.b.data = self.b.data.ljust(len(self.archive), b"!")
        self.b.data = self.b.data[:len(self.archive)]
        with self.assertRaisesRegex(q.AuditDenied, "ARCHIVE_SHA256"):
            self.inspect()

    def test_truncated_stream_rejected(self):
        self.b.get_object = lambda **kw: {
            "ContentLength": len(self.archive),
            "Body": BytesIO(self.archive[:-1]),
        }
        with self.assertRaisesRegex(q.AuditDenied, "ARCHIVE_SHA256"):
            self.inspect()

    def test_wrong_magic_rejected(self):
        self.b.data = b"BADXX" + self.archive[5:]
        digest = hashlib.sha256(self.b.data).hexdigest()
        self.b.metadata["sha256"] = digest
        with patch.object(q, "EXPECTED_SHA256", digest):
            with self.assertRaisesRegex(q.AuditDenied, "ARCHIVE_MAGIC"):
                self.inspect()

    def test_archive_list_error_rejected(self):
        self.runner.return_value = SimpleNamespace(returncode=1, stdout="")
        with self.assertRaisesRegex(q.AuditDenied, "PG_RESTORE_LIST_FAILED"):
            self.inspect()

    def test_post_probe_changing_cluster_rejected(self):
        self.probe_fn.side_effect = [q.TARGET_CLUSTER, q.SOURCE_CLUSTER]
        with self.assertRaisesRegex(q.AuditDenied, "SECOND_PROBE_WRONG_CLUSTER"):
            self.inspect()
        self.assertEqual([name for name, _ in self.b.calls], ["head", "get"])

    def test_run_error_sanitized_and_no_secret_log(self):
        buf = StringIO()
        with patch.object(q, "inspect", side_effect=RuntimeError(
            "postgresql://ci-only:SUPERSECRET@example")):
            with redirect_stderr(buf), self.assertRaises(SystemExit) as out:
                q.main()
        self.assertEqual(out.exception.code, 1)
        self.assertIn("REDACTED_FAILURE", buf.getvalue())
        self.assertNotIn("SUPERSECRET", buf.getvalue())

    def test_archive_limit_fails(self):
        self.b.head_object = lambda **kw: {
            "ContentLength": q.MAX_BYTES + 1, "Metadata": self.b.metadata
        }
        with self.assertRaisesRegex(q.AuditDenied, "ARCHIVE_SIZE"):
            self.inspect()

    def test_no_s3_put_delete_write_functions_in_module(self):
        source = Path(q.__file__).read_text()
        self.assertNotIn("client.put_object(", source)
        self.assertNotIn("client.delete_object(", source)
        self.assertNotIn("pg_restore\", \"--dbname", source)


if __name__ == "__main__":
    unittest.main()
