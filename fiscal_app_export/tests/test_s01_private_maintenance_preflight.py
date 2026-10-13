"""STG-B10A offline tests: synthetic identities, fake DB, zero external I/O."""
from __future__ import annotations

from dataclasses import replace
from io import StringIO
import contextlib
import unittest
from unittest.mock import Mock, patch

import private_maintenance_preflight as guard


SYNTHETIC_SERVICE = "11111111-2222-4333-8444-555555555555"
SYNTHETIC_ID = replace(guard.PINNED_IDENTITY, service_id=SYNTHETIC_SERVICE)


def valid_env():
    return {
        "RAILWAY_PROJECT_ID": SYNTHETIC_ID.project_id,
        "RAILWAY_ENVIRONMENT_ID": SYNTHETIC_ID.environment_id,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": SYNTHETIC_SERVICE,
        "RAILWAY_PRIVATE_DOMAIN": SYNTHETIC_ID.service_domain,
        "FLASK_ENV": "staging",
        "DATABASE_URL": (
            "postgresql://synthetic:CI_ONLY_PASSWORD@"
            "postgres.railway.internal:5432/railway"
        ),
        "PAYPAL_ENVIRONMENT": "sandbox",
    }


class Cursor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, statement):
        self.statements.append(statement)
        assert statement == "SET TRANSACTION READ ONLY" or statement.startswith("SELECT ")

    def fetchone(self):
        return next(self.responses)


class Connection:
    def __init__(self, *, responses=None):
        self.cursor_instance = Cursor(responses if responses is not None else [
            ("railway", "180006", "on"), (1,), (0,), (0,),
            (0,), (0,), (0,), (0,),
        ])
        self.session_calls = []
        self.rollbacks = 0
        self.closes = 0

    def set_session(self, **kwargs):
        self.session_calls.append(kwargs)

    def cursor(self):
        return self.cursor_instance

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closes += 1


class MaintenanceTest(unittest.TestCase):
    def assert_denied(self, env, expected, *, identity=SYNTHETIC_ID):
        with self.assertRaises(guard.PreflightDenied) as ctx:
            guard.validate_identity(env, identity=identity)
        self.assertEqual(ctx.exception.code, expected)

    def test_real_id_pinned_and_synthetic_service_denied(self):
        self.assertEqual(
            guard.PINNED_IDENTITY.service_id,
            "9728d19b-7d17-4acb-8be1-c4b0847179df",
        )
        self.assert_denied(valid_env(), "RAILWAY_IDENTITY",
                           identity=guard.PINNED_IDENTITY)

    def test_actual_service_identity_only_passes_pure_validation(self):
        env = valid_env()
        env["RAILWAY_SERVICE_ID"] = guard.PINNED_IDENTITY.service_id
        # This validates only an offline synthetic mapping, NOT a real Railway
        # endpoint or the private Postgres database.
        guard.validate_identity(env)

    def test_synthetic_identity_accepts_only_test_injected_pin(self):
        guard.validate_identity(valid_env(), identity=SYNTHETIC_ID)

    def test_each_identity_marker_must_match(self):
        for field in (
            "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
            "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID",
            "RAILWAY_PRIVATE_DOMAIN", "FLASK_ENV",
        ):
            with self.subTest(field=field):
                env = valid_env()
                env[field] = "wrong"
                self.assert_denied(env, "RAILWAY_IDENTITY")
                del env[field]
                self.assert_denied(env, "RAILWAY_IDENTITY")

    def test_production_and_old_staging_database_rejected(self):
        for host in (
            "postgres-zzky.railway.internal", "prod.railway.internal",
            "localhost", "example.com", "postgres.railway.internal.evil.test",
        ):
            with self.subTest(host=host):
                env = valid_env()
                env["DATABASE_URL"] = (
                    "postgresql://user:pass@" + host + ":5432/railway"
                )
                self.assert_denied(env, "DATABASE_TARGET")

    def test_wrong_database_dsn_shapes_rejected(self):
        base = "postgresql://user:pass@postgres.railway.internal:5432/railway"
        variants = (
            "", "postgres://user:pass@postgres.railway.internal:5432/railway",
            base.replace("/railway", "/postgres"),
            base.replace(":5432/", ":5433/"), base + "?sslmode=disable",
            base + "#fragment",
            "postgresql://user@postgres.railway.internal:5432/railway",
            "postgresql://:pass@postgres.railway.internal:5432/railway",
        )
        for dsn in variants:
            with self.subTest(dsn=dsn[:28]):
                env = valid_env()
                env["DATABASE_URL"] = dsn
                self.assert_denied(env, "DATABASE_TARGET")

    def test_explicit_psycopg2_scheme_is_permitted(self):
        env = valid_env()
        env["DATABASE_URL"] = env["DATABASE_URL"].replace(
            "postgresql://", "postgresql+psycopg2://", 1
        )
        guard.validate_identity(env, identity=SYNTHETIC_ID)

    def test_no_public_network_or_web_port(self):
        for field in guard.FORBIDDEN_NETWORK_SETTINGS:
            with self.subTest(field=field):
                env = valid_env()
                env[field] = "present"
                self.assert_denied(env, "PUBLIC_NETWORK")

    def test_all_provider_secrets_forbidden(self):
        for field in guard.FORBIDDEN_CREDENTIALS:
            with self.subTest(field=field):
                env = valid_env()
                env[field] = "secret-should-never-print"
                self.assert_denied(env, "EXTERNAL_CREDENTIALS")

    def test_all_feature_flags_fail_when_enabled(self):
        for field in guard.DISABLED_FEATURES:
            with self.subTest(field=field):
                env = valid_env()
                env[field] = "true"
                self.assert_denied(env, "ACTIVE_FEATURE")
                env[field] = "false"
                guard.validate_identity(env, identity=SYNTHETIC_ID)

    def test_live_paypal_flag_denied(self):
        env = valid_env()
        env["PAYPAL_ENVIRONMENT"] = "live"
        self.assert_denied(env, "PAYMENT_ENVIRONMENT")

    def test_lab_bypass_flags_never_authorize(self):
        env = valid_env()
        env["S01_LAB_MODE"] = "true"
        env["S01_SYNTHETIC_LAB_MODE"] = "true"
        self.assert_denied(env, "RAILWAY_IDENTITY",
                           identity=guard.PINNED_IDENTITY)

    def test_identity_fails_before_any_connection_attempt(self):
        connect = Mock(side_effect=AssertionError("must not connect"))
        with self.assertRaises(guard.PreflightDenied):
            guard.run_preflight(valid_env(), connect)
        connect.assert_not_called()

    def test_empty_pg18_readonly_success_and_cleanup(self):
        conn = Connection()
        connect = Mock(return_value=conn)
        report = guard.run_preflight(
            valid_env(), connect, identity=SYNTHETIC_ID
        )
        self.assertEqual(report.database, "railway")
        self.assertEqual(report.postgres_version, 180006)
        self.assertEqual(report.public_relations, 0)
        self.assertEqual(conn.session_calls, [
            {"readonly": True, "autocommit": False},
        ])
        self.assertEqual(conn.cursor_instance.statements[0],
                         "SET TRANSACTION READ ONLY")
        self.assertEqual(len(conn.cursor_instance.statements), 9)
        self.assertEqual(conn.rollbacks, 1)
        self.assertEqual(conn.closes, 1)
        args, kwargs = connect.call_args
        self.assertNotIn("psycopg2", args[0])
        self.assertEqual(kwargs["sslmode"], "require")
        self.assertIn("default_transaction_read_only=on", kwargs["options"])

    def test_normalization_for_explicit_psycopg2_driver(self):
        env = valid_env()
        env["DATABASE_URL"] = env["DATABASE_URL"].replace(
            "postgresql://", "postgresql+psycopg2://", 1
        )
        connect = Mock(return_value=Connection())
        guard.run_preflight(env, connect, identity=SYNTHETIC_ID)
        self.assertTrue(connect.call_args.args[0].startswith("postgresql://"))

    def test_db_version_and_name_and_readonly_rejected(self):
        for identity, code in (
            (("postgres", "180006", "on"), "DATABASE_IDENTITY"),
            (("railway", "170009", "on"), "DATABASE_IDENTITY"),
            (("railway", "garbage", "on"), "DATABASE_IDENTITY"),
            (("railway", "180006", "off"), "TRANSACTION_NOT_READONLY"),
        ):
            with self.subTest(identity=identity):
                conn = Connection(responses=[identity])
                with self.assertRaises(guard.PreflightDenied) as ctx:
                    guard.run_preflight(
                        valid_env(), Mock(return_value=conn),
                        identity=SYNTHETIC_ID,
                    )
                self.assertEqual(ctx.exception.code, code)
                self.assertEqual(conn.rollbacks, 1)
                self.assertEqual(conn.closes, 1)

    def test_any_nonempty_catalog_object_refused(self):
        counts = [1, 0, 0, 0, 0, 0, 0]
        for pos in range(1, len(counts)):
            with self.subTest(index=pos):
                bad = counts.copy()
                bad[pos] = 1
                conn = Connection(responses=[
                    ("railway", "180006", "on"), *((v,) for v in bad)
                ])
                with self.assertRaises(guard.PreflightDenied) as ctx:
                    guard.run_preflight(
                        valid_env(), Mock(return_value=conn),
                        identity=SYNTHETIC_ID,
                    )
                self.assertEqual(ctx.exception.code, "NOT_PRISTINE")
                self.assertEqual(conn.rollbacks, 1)
                self.assertEqual(conn.closes, 1)

    def test_missing_public_schema_rejected(self):
        conn = Connection(responses=[
            ("railway", "180006", "on"), (0,), *((0,) for _ in range(6))
        ])
        with self.assertRaises(guard.PreflightDenied) as ctx:
            guard.run_preflight(
                valid_env(), Mock(return_value=conn),
                identity=SYNTHETIC_ID,
            )
        self.assertEqual(ctx.exception.code, "NOT_PRISTINE")

    def test_no_commit_ddl_app_or_bootstrap_reference(self):
        import inspect
        source = inspect.getsource(guard)
        self.assertNotIn("from app import", source)
        self.assertNotIn("db.create_all(", source)
        self.assertNotIn("upgrade(", source)
        self.assertNotIn("connection.commit(", source)
        for statement in guard._SQL:
            self.assertTrue(statement.startswith("SELECT "))

    def test_real_main_no_network_no_secret_leak(self):
        stderr = StringIO()
        with patch.dict(guard.os.environ, valid_env(), clear=True):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as ctx:
                    guard.main()
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("RAILWAY_IDENTITY", stderr.getvalue())
        self.assertNotIn("CI_ONLY_PASSWORD", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
