"""STG-B11B: fake-env tests; every actual database operation is mocked."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import preflight as b


def env():
    return {
        "RAILWAY_PROJECT_ID": b.PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": b.ENVIRONMENT_ID,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": b.SERVICE_ID,
        "RAILWAY_PRIVATE_DOMAIN": b.SERVICE_PRIVATE_DOMAIN,
        "TARGET_DATABASE_URL":
            "postgresql://ci-user:fake-password@"
            "postgres-im3h.railway.internal:5432/railway",
    }


def catalog(cluster=b.TARGET_CLUSTER, counts=None):
    return "|".join(
        ["railway", "180006", "on", cluster] + (
            ["0"] * 6 if counts is None else counts
        )
    ) + "\n"


class TestSchemaTargetReadonly(unittest.TestCase):
    def test_valid_pins_only_dest(self):
        pg_env = b.checked_pg_environment(env())
        self.assertEqual(pg_env["PGHOST"], b.TARGET_HOST)
        self.assertEqual(pg_env["PGSSLMODE"], "require")
        self.assertIn("default_transaction_read_only=on", pg_env["PGOPTIONS"])

    def test_each_wrong_railway_identity_denied(self):
        for key in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
                    "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID",
                    "RAILWAY_PRIVATE_DOMAIN"):
            with self.subTest(key=key), self.assertRaises(b.SchemaPreflightDenied):
                b.checked_pg_environment({**env(), key: "wrong"})

    def test_source_database_never_allowed(self):
        for key in ("DATABASE_URL", "SOURCE_DATABASE_URL", "PGHOST"):
            with self.subTest(key=key), self.assertRaises(b.SchemaPreflightDenied):
                b.checked_pg_environment({**env(), key: "fake-source"})

    def test_no_payment_or_email_secrets(self):
        for key in ("STRIPE_SECRET_KEY", "PAYPAL_CLIENT_SECRET",
                    "RESEND_API_KEY", "SECRET_KEY"):
            with self.subTest(key=key), self.assertRaises(b.SchemaPreflightDenied):
                b.checked_pg_environment({**env(), key: "fake-credential"})

    def test_no_public_domain(self):
        for key in b.PUBLIC_MARKERS:
            with self.subTest(key=key), self.assertRaises(b.SchemaPreflightDenied):
                b.checked_pg_environment({**env(), key: "public"})

    def test_original_postgres_hostname_forbidden(self):
        bad = {
            **env(), "TARGET_DATABASE_URL":
                "postgresql://u:p@postgres.railway.internal:5432/railway"
        }
        with self.assertRaises(b.SchemaPreflightDenied) as ex:
            b.checked_pg_environment(bad)
        self.assertEqual(ex.exception.code, "WRONG_TARGET")

    def test_wrong_port_or_db_denied(self):
        for suffix in (":55433/railway", ":5432/postgres"):
            with self.subTest(suffix=suffix), self.assertRaises(b.SchemaPreflightDenied):
                b.checked_pg_environment({
                    **env(), "TARGET_DATABASE_URL":
                        "postgresql://u:p@postgres-im3h.railway.internal" + suffix
                })

    def test_exact_target_cluster_and_empty_schema(self):
        self.assertEqual(b.checked_readonly_catalog(catalog()), b.TARGET_CLUSTER)

    def test_original_cluster_rejected(self):
        with self.assertRaises(b.SchemaPreflightDenied) as ex:
            b.checked_readonly_catalog(catalog(b.FORBIDDEN_ORIGINAL_CLUSTER))
        self.assertEqual(ex.exception.code, "ORIGINAL_CLUSTER_FORBIDDEN")

    def test_unknown_cluster_rejected(self):
        with self.assertRaises(b.SchemaPreflightDenied):
            b.checked_readonly_catalog(catalog("7777777777777777777"))

    def test_any_catalog_object_denied(self):
        for index in range(6):
            counts = ["0"] * 6
            counts[index] = "1"
            with self.subTest(index=index), self.assertRaises(b.SchemaPreflightDenied):
                b.checked_readonly_catalog(catalog(counts=counts))

    def test_version_and_readonly_mandatory(self):
        for data in (
            catalog().replace("180006", "170009"),
            catalog().replace("|on|", "|off|"),
            catalog() + "second row",
        ):
            with self.subTest(data=data), self.assertRaises(b.SchemaPreflightDenied):
                b.checked_readonly_catalog(data)

    def test_query_uses_only_readonly_catalog_and_private_host(self):
        run = Mock(return_value=SimpleNamespace(
            returncode=0, stdout=catalog(),
        ))
        self.assertEqual(b.preflight(env(), runner=run), b.TARGET_CLUSTER)
        argv, kwargs = run.call_args
        self.assertEqual(argv[0][0], "psql")
        self.assertTrue(argv[0][-1].strip().startswith("SELECT"))
        self.assertNotIn("INSERT ", argv[0][-1])
        self.assertNotIn("CREATE ", argv[0][-1])
        self.assertEqual(kwargs["env"]["PGHOST"], b.TARGET_HOST)
        self.assertEqual(kwargs["env"]["PGSSLMODE"], "require")

    def test_no_connection_after_bad_identity(self):
        run = Mock()
        with self.assertRaises(b.SchemaPreflightDenied):
            b.preflight({**env(), "RAILWAY_SERVICE_ID": "bad"}, runner=run)
        run.assert_not_called()

    def test_query_error_never_leaks_driver_text(self):
        run = Mock(return_value=SimpleNamespace(
            returncode=1, stdout="postgresql://secret@example",
        ))
        with self.assertRaises(b.SchemaPreflightDenied) as ex:
            b.preflight(env(), runner=run)
        self.assertEqual(ex.exception.code, "READONLY_QUERY_FAILED")


if __name__ == "__main__":
    unittest.main()
