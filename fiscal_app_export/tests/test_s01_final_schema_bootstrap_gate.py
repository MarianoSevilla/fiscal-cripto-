"""Release contract for S01 schema writer. ALL tests synthetic/no DB traffic."""
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import schema_preflight as pg
import schema_bootstrap_one_shot as live


def fake_lab(approval=None):
    result = {
        "RAILWAY_PROJECT_ID": pg.PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": pg.ENVIRONMENT_ID,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": pg.SERVICE_ID,
        "RAILWAY_PRIVATE_DOMAIN": pg.SERVICE_PRIVATE_DOMAIN,
        "TARGET_DATABASE_URL": (
            "postgresql://postgres:fake-ci-only-password@"
            "postgres-im3h.railway.internal:5432/railway"
        ),
    }
    if approval is not None:
        result[live.APPROVAL_KEY] = approval
    return result


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.last_query = ""
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def execute(self, statement, args=None):
        self.last_query = statement
        self.connection.queries.append((statement, args))
    def fetchone(self):
        if "current_database()" in self.last_query:
            return ("railway", pg.TARGET_PG_VERSION, pg.TARGET_CLUSTER)
        if "pg_try_advisory_lock" in self.last_query:
            return (self.connection.lock_granted,)
        if "pg_advisory_unlock" in self.last_query:
            return (True,)
        raise AssertionError("Unexpected mock SQL")


class FakeConnection:
    def __init__(self, lock_granted=True):
        self.lock_granted = lock_granted
        self.queries = []
        self.closed = False
        self.autocommit = False
    def cursor(self):
        return FakeCursor(self)
    def close(self):
        self.closed = True


class TestSchemaBootstrapRelease(TestCase):
    def test_without_approval_no_import_or_connection(self):
        connector = Mock()
        with self.assertRaises(live.BootstrapDenied) as ex:
            live.bootstrap_once(fake_lab(), connect_fn=connector)
        self.assertEqual(ex.exception.code, "EXACT_OWNER_APPROVAL_ABSENT")
        connector.assert_not_called()

    def test_generic_procede_not_authorized(self):
        for flag in ("procede", "autorizo", "true", "1", ""):
            with self.subTest(flag=flag), self.assertRaises(live.BootstrapDenied):
                live.validate_release(fake_lab(flag))

    def test_origin_dsn_is_never_valid(self):
        data = fake_lab(live.APPROVAL_INTENT)
        data["TARGET_DATABASE_URL"] = (
            "postgresql://u:p@postgres.railway.internal:5432/railway"
        )
        with self.assertRaisesRegex(live.BootstrapDenied, "WRONG_LAB_WRONG_TARGET"):
            live.validate_release(data)

    def test_wrong_railway_service_or_environment_fails(self):
        for k in ("RAILWAY_SERVICE_ID", "RAILWAY_PROJECT_ID",
                  "RAILWAY_ENVIRONMENT_ID", "RAILWAY_ENVIRONMENT_NAME"):
            with self.subTest(k=k), self.assertRaises(live.BootstrapDenied):
                live.validate_release({
                    **fake_lab(live.APPROVAL_INTENT), k: "not-lab"
                })

    def test_deny_additional_payment_keys_and_source_url(self):
        for k in ("DATABASE_URL", "STRIPE_SECRET_KEY", "PAYPAL_CLIENT_SECRET"):
            with self.subTest(k=k), self.assertRaises(live.BootstrapDenied):
                live.validate_release({
                    **fake_lab(live.APPROVAL_INTENT), k: "fake-only"
                })

    def test_old_restore_approval_cross_contamination_denied(self):
        with self.assertRaisesRegex(live.BootstrapDenied, "RESTORE_APPROVAL"):
            live.validate_release({
                **fake_lab(live.APPROVAL_INTENT),
                "S01_RECOVERY_WRITE_APPROVAL": "anything",
            })

    def test_synthetic_success_uses_double_readonly_and_one_writer(self):
        env = fake_lab(live.APPROVAL_INTENT)
        conn = FakeConnection()
        preflight = Mock(return_value=pg.TARGET_CLUSTER)
        writer = Mock()
        postcheck = Mock()
        connect = Mock(return_value=conn)
        result = live.bootstrap_once(
            env, preflight_fn=preflight,
            connect_fn=connect, migrate_fn=writer, postcheck_fn=postcheck,
        )
        self.assertEqual(result, live.PASS)
        self.assertEqual(preflight.call_count, 2)
        writer.assert_called_once_with(env["TARGET_DATABASE_URL"])
        postcheck.assert_called_once_with(env["TARGET_DATABASE_URL"])
        self.assertTrue(conn.closed)
        self.assertTrue(any("pg_try_advisory_lock" in q for q, _ in conn.queries))
        self.assertTrue(any("pg_advisory_unlock" in q for q, _ in conn.queries))

    def test_conflicting_advisory_lock_denies_and_never_calls_ddl(self):
        conn = FakeConnection(lock_granted=False)
        writer = Mock()
        postcheck = Mock()
        with self.assertRaisesRegex(live.BootstrapDenied, "CONCURRENT_BOOTSTRAP"):
            live.bootstrap_once(
                fake_lab(live.APPROVAL_INTENT),
                preflight_fn=Mock(return_value=pg.TARGET_CLUSTER),
                connect_fn=Mock(return_value=conn),
                migrate_fn=writer,
                postcheck_fn=postcheck,
            )
        writer.assert_not_called()
        postcheck.assert_not_called()
        self.assertTrue(conn.closed)

    def test_second_readonly_probe_detects_dirty_target_before_ddl(self):
        conn = FakeConnection()
        probe = Mock(side_effect=[
            pg.TARGET_CLUSTER,
            pg.SchemaPreflightDenied("SCHEMA_NOT_PRISTINE"),
        ])
        writer = Mock()
        with self.assertRaises(pg.SchemaPreflightDenied):
            live.bootstrap_once(
                fake_lab(live.APPROVAL_INTENT),
                preflight_fn=probe, connect_fn=Mock(return_value=conn),
                migrate_fn=writer,
            )
        writer.assert_not_called()
        self.assertTrue(conn.closed)
        self.assertTrue(any("pg_advisory_unlock" in q for q, _ in conn.queries))

    def test_ddl_error_leaves_partial_schema_and_never_retries(self):
        conn = FakeConnection()
        writer = Mock(side_effect=RuntimeError("synthetic DDL stop"))
        postcheck = Mock()
        with self.assertRaisesRegex(RuntimeError, "synthetic DDL stop"):
            live.bootstrap_once(
                fake_lab(live.APPROVAL_INTENT),
                preflight_fn=Mock(return_value=pg.TARGET_CLUSTER),
                connect_fn=Mock(return_value=conn),
                migrate_fn=writer,
                postcheck_fn=postcheck,
            )
        writer.assert_called_once()
        postcheck.assert_not_called()
        self.assertTrue(conn.closed)

    def test_writer_database_version_and_cluster_checked(self):
        conn = FakeConnection()
        conn.cursor = lambda: BadCursor(conn)
        writer = Mock()
        with self.assertRaisesRegex(live.BootstrapDenied, "WRITER_CLUSTER_IDENTITY"):
            live.bootstrap_once(
                fake_lab(live.APPROVAL_INTENT),
                preflight_fn=Mock(return_value=pg.TARGET_CLUSTER),
                connect_fn=Mock(return_value=conn),
                migrate_fn=writer,
            )
        writer.assert_not_called()
        self.assertTrue(conn.closed)

    def test_dockerfile_does_not_import_web_app_or_include_providers(self):
        root = Path(__file__).resolve().parent.parent
        docker = (root / "Dockerfile.schema-one-shot").read_text()
        self.assertIn("COPY migrations/", docker)
        self.assertIn("COPY models.py", docker)
        self.assertIn("COPY schema_bootstrap_one_shot.py", docker)
        for bad in ("COPY app.py", "COPY bootstrap_db.py", "COPY payments",
                    "COPY . /app", "ENTRYPOINT [\"gunicorn"):
            self.assertNotIn(bad, docker)
        for bad in ("stripe", "resend", "paypal"):
            self.assertNotIn(bad, (root / "requirements.schema-bootstrap.txt").read_text().lower())

    def test_b11b_preflight_is_exact_copy(self):
        root = Path(__file__).resolve().parent.parent.parent
        original = (root / "infra/s01_lab_schema/preflight.py").read_bytes()
        bundled = (root / "fiscal_app_export/schema_preflight.py").read_bytes()
        self.assertEqual(original, bundled)


class BadCursor(FakeCursor):
    def fetchone(self):
        if "current_database()" in self.last_query:
            return ("railway", pg.TARGET_PG_VERSION,
                    pg.FORBIDDEN_ORIGINAL_CLUSTER)
        return super().fetchone()


if __name__ == "__main__":
    import unittest
    unittest.main()
