"""S01 STG-B10G: synthetic identity checks, no network and no database."""
from __future__ import annotations

import contextlib
from io import StringIO
import inspect
import sys
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import private_maintenance_identity as identity
from private_maintenance_preflight import PreflightDenied, PINNED_IDENTITY
from test_s01_private_maintenance_preflight import Connection, valid_env


def authorized_mapping():
    env = valid_env()
    env["RAILWAY_SERVICE_ID"] = PINNED_IDENTITY.service_id
    return env


class TestIdentity(TestCase):
    def test_owner_supplied_cluster_id_fixed(self):
        self.assertEqual(identity.EXPECTED_CLUSTER_ID, "7696213098351943739")

    def test_wrong_service_denies_before_connect(self):
        conn = Mock()
        with self.assertRaises(PreflightDenied):
            identity.probe(valid_env(), conn)
        conn.assert_not_called()

    def test_real_pinned_identity_accepted_by_validation(self):
        from private_maintenance_preflight import validate_identity
        validate_identity(authorized_mapping())

    def test_wrong_project_or_environment_denies_before_connect(self):
        for key in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID"):
            env = authorized_mapping()
            env[key] = "outside-s01"
            connect = Mock()
            with self.subTest(key=key), self.assertRaises(PreflightDenied):
                identity.probe(env, connect)
            connect.assert_not_called()

    def test_foreign_database_denies_before_connect(self):
        env = authorized_mapping()
        env["DATABASE_URL"] = "postgresql://u:p@postgres-zzky.railway.internal:5432/railway"
        conn = Mock()
        with self.assertRaises(PreflightDenied):
            identity.probe(env, conn)
        conn.assert_not_called()

    def test_readonly_sequence_same_connection_no_commit(self):
        c = Connection(responses=[
            ("railway", "180006", "on"),
            (1,), (0,), (0,), (0,), (0,), (0,), (0,),
            ("railway", "180006", "on", identity.EXPECTED_CLUSTER_ID)
        ])
        connect = Mock(return_value=c)
        result = identity.probe(authorized_mapping(), connect)
        self.assertEqual(result, identity.EXPECTED_CLUSTER_ID)
        connect.assert_called_once()
        self.assertEqual(c.rollbacks, 2)
        self.assertEqual(c.closes, 1)
        self.assertEqual(c.session_calls, [
            {"readonly": True, "autocommit": False},
            {"readonly": True, "autocommit": False},
        ])
        self.assertEqual(c.cursor_instance.statements.count("SET TRANSACTION READ ONLY"), 2)
        self.assertTrue(all(
            s == "SET TRANSACTION READ ONLY" or s.startswith("SELECT ")
            for s in c.cursor_instance.statements
        ))
        self.assertIn("default_transaction_read_only=on",
                      connect.call_args.kwargs["options"])
        self.assertEqual(connect.call_args.kwargs["sslmode"], "require")

    def test_bad_cluster_fingerprint_fails_closed(self):
        for cluster in ("7696213098351943738", "", "123", None):
            c = Connection(responses=[
                ("railway", "180006", "on"),
                (1,), (0,), (0,), (0,), (0,), (0,), (0,),
                ("railway", "180006", "on", cluster),
            ])
            with self.subTest(cluster=cluster), self.assertRaisesRegex(
                PreflightDenied, "CLUSTER_IDENTITY"
            ):
                identity.probe(authorized_mapping(), Mock(return_value=c))
            self.assertEqual(c.rollbacks, 2)
            self.assertEqual(c.closes, 1)

    def test_mismatch_readonly_version_database_denied(self):
        for data in (
            ("railway", "170009", "on", identity.EXPECTED_CLUSTER_ID),
            ("other", "180006", "on", identity.EXPECTED_CLUSTER_ID),
            ("railway", "180006", "off", identity.EXPECTED_CLUSTER_ID),
        ):
            c = Connection(responses=[
                ("railway", "180006", "on"),
                (1,), (0,), (0,), (0,), (0,), (0,), (0,), data,
            ])
            with self.subTest(data=data), self.assertRaises(PreflightDenied):
                identity.probe(authorized_mapping(), Mock(return_value=c))
            self.assertEqual(c.closes, 1)

    def test_catalog_nonempty_aborts_before_cluster_query(self):
        c = Connection(responses=[
            ("railway", "180006", "on"),
            (1,), (1,), (0,), (0,), (0,), (0,), (0,),
        ])
        with self.assertRaises(PreflightDenied):
            identity.probe(authorized_mapping(), Mock(return_value=c))
        self.assertEqual(c.rollbacks, 1)
        self.assertEqual(c.closes, 1)

    def test_sanitizes_connection_errors(self):
        stderr = StringIO()
        env = authorized_mapping()
        with patch.dict(identity.os.environ, env, clear=True):
            with patch.dict(sys.modules, {
                "psycopg2": SimpleNamespace(
                    connect=Mock(side_effect=RuntimeError(env["DATABASE_URL"]))
                )
            }):
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as caught:
                        identity.main()
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("PROBE_FAILED", stderr.getvalue())
        self.assertNotIn("CI_ONLY_PASSWORD", stderr.getvalue())

    def test_no_web_or_migration_imports_or_dml_in_entrypoint(self):
        source = inspect.getsource(identity)
        for prohibited in ("from app import", "import app\n", "import models\n",
                           "import bootstrap_db", "flask_migrate", "db.create_all(",
                           "alembic.command", "DROP TABLE ", "INSERT INTO ",
                           "UPDATE public.", "DELETE FROM "):
            self.assertNotIn(prohibited, source)
        self.assertTrue(identity.IDENTITY_SQL.startswith("SELECT "))


if __name__ == "__main__":
    import unittest
    unittest.main()
