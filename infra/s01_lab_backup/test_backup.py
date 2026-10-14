"""Offline synthetic security contracts for private S01 logical backup runner."""
from __future__ import annotations

from io import StringIO
from contextlib import redirect_stderr
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

import backup as b


def fake_env():
    return {
        "RAILWAY_PROJECT_ID": b.PROJECT,
        "RAILWAY_ENVIRONMENT_ID": b.ENVIRONMENT,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": b.SERVICE,
        "RAILWAY_PRIVATE_DOMAIN": b.PRIVATE_DOMAIN,
        "DATABASE_URL": "postgresql://fake-user:FAKE-CI-PASSWORD@"
                        "postgres.railway.internal:5432/railway",
        "BACKUP_ENDPOINT": b.S3_ENDPOINT,
        "BACKUP_BUCKET": b.S3_BUCKET,
        "BACKUP_REGION": b.S3_REGION,
        "BACKUP_ACCESS_KEY_ID": "SYNTHETICKEY",
        "BACKUP_SECRET_ACCESS_KEY": "SYNTHETIC-SECRET-VALUE",
    }


class BackupGuard(unittest.TestCase):
    def reject(self, changes, reason):
        values = fake_env()
        values.update(changes)
        with self.assertRaises(b.StopBackup) as caught:
            b.checked_environment(values)
        self.assertEqual(caught.exception.reason, reason)

    def test_exact_fake_lab_identity_accepted_without_network(self):
        pg = b.checked_environment(fake_env())
        self.assertEqual(pg["PGHOST"], "postgres.railway.internal")
        self.assertEqual(pg["PGDATABASE"], "railway")
        self.assertEqual(pg["PGSSLMODE"], "require")
        self.assertIn("default_transaction_read_only=on", pg["PGOPTIONS"])

    def test_project_environment_service_domain_pinned(self):
        for key in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
                    "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID",
                    "RAILWAY_PRIVATE_DOMAIN"):
            with self.subTest(key=key):
                self.reject({key: "wrong"}, "WRONG_LAB_IDENTITY")

    def test_public_exposure_markers_denied(self):
        for key in b.PUBLIC_MARKERS:
            with self.subTest(key=key):
                self.reject({key: "enabled"}, "PUBLIC_EXPOSURE_MARKER")

    def test_payment_email_and_web_secrets_denied(self):
        for key in b.UNSAFE_PROVIDER_MARKERS:
            with self.subTest(key=key):
                self.reject({key: "test-secret"}, "PROVIDER_SECRET_IN_BACKUP_SERVICE")

    def test_injected_headless_port_is_safe_only_if_numeric(self):
        for port in ("1", "3000", "8080", "65535"):
            env = fake_env()
            env["PORT"] = port
            b.checked_environment(env)

    def test_invalid_runtime_ports_refused(self):
        for port in ("0", "65536", "xyz", "-1", "٠٨٠٨", "8080 ", "123456789"):
            with self.subTest(port=port):
                self.reject({"PORT": port}, "INVALID_PORT")

    def test_outside_pg_hostname_denied(self):
        for hostname in ("postgres-zzky.railway.internal", "localhost",
                         "external.example", "postgres.railway.internal.evil.test"):
            self.reject({"DATABASE_URL": f"postgresql://u:p@{hostname}:5432/railway"},
                        "WRONG_DATABASE_DESTINATION")

    def test_database_query_port_and_schema_denied(self):
        for suffix in ("/production", "/postgres",
                       "/railway?sslmode=disable", ":5433/railway"):
            if suffix.startswith(":"):
                url = "postgresql://u:p@postgres.railway.internal" + suffix
            else:
                url = "postgresql://u:p@postgres.railway.internal:5432" + suffix
            with self.subTest(suffix=suffix):
                self.reject({"DATABASE_URL": url}, "WRONG_DATABASE_DESTINATION")

    def test_bucket_endpoint_name_region_and_keys_pinned(self):
        for key in ("BACKUP_ENDPOINT", "BACKUP_BUCKET", "BACKUP_REGION",
                    "BACKUP_ACCESS_KEY_ID", "BACKUP_SECRET_ACCESS_KEY"):
            with self.subTest(key=key):
                self.reject({key: ""}, "WRONG_BUCKET_DESTINATION")

    def test_pg_cli_allowlist(self):
        with self.assertRaises(b.StopBackup) as caught:
            b.run_pg(["alembic", "upgrade", "head"], {}, timeout=1)
        self.assertEqual(caught.exception.reason, "COMMAND_DENIED")

    def test_psql_catalog_passes_only_pristine_matching_cluster(self):
        row = f"railway|180006|on|{b.CLUSTER}|0|0|0|0|0|0"
        with patch.object(b, "run_pg", return_value=row):
            b.assert_pristine_database({})

    def test_psql_catalog_wrong_fingerprint_rejected(self):
        row = "railway|180006|on|1234|0|0|0|0|0|0"
        with patch.object(b, "run_pg", return_value=row):
            with self.assertRaises(b.StopBackup) as caught:
                b.assert_pristine_database({})
        self.assertEqual(caught.exception.reason, "CLUSTER_MISMATCH")

    def test_psql_catalog_unexpected_objects_rejected(self):
        for i in range(4, 10):
            cols = ["railway", "180006", "on", b.CLUSTER] + ["0"] * 6
            cols[i] = "1"
            with self.subTest(column=i), patch.object(b, "run_pg", return_value="|".join(cols)):
                with self.assertRaises(b.StopBackup) as caught:
                    b.assert_pristine_database({})
            self.assertEqual(caught.exception.reason, "DB_NOT_PRISTINE")

    def test_real_backup_refuses_invalid_railway_before_psql_and_s3(self):
        with patch.object(b, "run_pg") as pg, patch.object(b, "s3_client") as s3:
            with self.assertRaises(b.StopBackup):
                b.create_backup({"RAILWAY_SERVICE_ID": "outside"})
            pg.assert_not_called()
            s3.assert_not_called()

    def test_backup_object_key_single_and_source_pinned(self):
        self.assertIn(b.CLUSTER, b.S3_KEY)
        self.assertNotIn("..", b.S3_KEY)
        self.assertLess(len(b.S3_KEY), 256)

    def test_hash_detects_tampered_bytes(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "dummy"
            p.write_bytes(b"PGDMP" + b"synthetic")
            a = b.sha256_file(p)
            p.write_bytes(b"PGDMP" + b"tampered")
            self.assertNotEqual(a, b.sha256_file(p))

    def test_main_hides_DSN_on_driver_error(self):
        err = StringIO()
        with patch.object(b, "create_backup", side_effect=RuntimeError("dsn PASS=SECRET")):
            with redirect_stderr(err), self.assertRaises(SystemExit) as e:
                b.main()
        self.assertEqual(e.exception.code, 1)
        self.assertIn("UNEXPECTED_ERROR", err.getvalue())
        self.assertNotIn("PASS=SECRET", err.getvalue())


if __name__ == "__main__":
    unittest.main()
