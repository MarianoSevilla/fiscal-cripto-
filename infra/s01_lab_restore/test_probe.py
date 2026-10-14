"""S01 B10N offline tests; fake psql responses, no database access."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import probe


def env():
    return {
        "RAILWAY_PROJECT_ID": probe.PROJECT,
        "RAILWAY_ENVIRONMENT_ID": probe.ENVIRONMENT,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": probe.RUNNER_SERVICE,
        "RAILWAY_PRIVATE_DOMAIN": probe.RUNNER_DOMAIN,
        "TARGET_DATABASE_URL":
            "postgresql://ci-only:fake@postgres-im3h.railway.internal:5432/railway",
    }


def row(cluster=probe.EXPECTED_TARGET_CLUSTER, counts=None):
    return "|".join(
        ["railway", "180006", "on", cluster] + (counts or ["0"] * 6)
    ) + "\n"


class TestReadOnlyRecoveryTarget(unittest.TestCase):
    def test_pinned_railway_identity(self):
        for key in ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
                    "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_SERVICE_ID",
                    "RAILWAY_PRIVATE_DOMAIN"):
            with self.subTest(key=key), self.assertRaises(probe.ProbeDenied):
                probe.validate_environment({**env(), key: "wrong"})

    def test_reject_source_db_secrets(self):
        for key in ("DATABASE_URL", "SOURCE_DATABASE_URL", "PGPASSWORD",
                    "PGHOST", "PGSERVICE", "PGPASSFILE"):
            with self.subTest(key=key), self.assertRaises(probe.ProbeDenied):
                probe.validate_environment({**env(), key: "secret"})

    def test_reject_public_markers(self):
        for key in probe.BLOCKED_PUBLIC:
            with self.subTest(key=key), self.assertRaises(probe.ProbeDenied):
                probe.validate_environment({**env(), key: "public"})

    def test_reject_payment_and_mail_secrets(self):
        for key in probe.BLOCKED_PROVIDERS:
            with self.subTest(key=key), self.assertRaises(probe.ProbeDenied):
                probe.validate_environment({**env(), key: "secret"})

    def test_allow_only_valid_railway_ports(self):
        for value in ("1", "8080", "65535"):
            probe.validate_environment({**env(), "PORT": value})
        for value in ("0", "65536", "abc", "٠٨٠٨", "-1", " 8080 "):
            with self.subTest(value=value), self.assertRaises(probe.ProbeDenied):
                probe.validate_environment({**env(), "PORT": value})

    def test_reject_non_target_hostname(self):
        for host in ("postgres.railway.internal", "evil.example", "127.0.0.1"):
            with self.subTest(host=host), self.assertRaises(probe.ProbeDenied):
                probe.validate_environment({
                    **env(),
                    "TARGET_DATABASE_URL":
                        f"postgresql://fake:fake@{host}:5432/railway",
                })

    def test_denied_identity_never_spawns_psql(self):
        run = Mock()
        with self.assertRaises(probe.ProbeDenied):
            probe.probe({**env(), "RAILWAY_SERVICE_ID": "wrong"}, runner=run)
        run.assert_not_called()

    def test_positive_uses_readonly_and_expected_private_host(self):
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout=row()))
        self.assertEqual(probe.probe(env(), runner=run),
                         probe.EXPECTED_TARGET_CLUSTER)
        argv, kw = run.call_args
        self.assertEqual(argv[0][0], "psql")
        self.assertTrue(argv[0][-1].lstrip().startswith("SELECT"))
        self.assertEqual(kw["env"]["PGHOST"], probe.TARGET_HOST)
        self.assertEqual(kw["env"]["PGSSLMODE"], "require")
        self.assertIn("default_transaction_read_only=on",
                      kw["env"]["PGOPTIONS"])

    def test_reject_original_cluster(self):
        with self.assertRaises(probe.ProbeDenied) as ctx:
            probe.validate_catalog(row(probe.ORIGINAL_CLUSTER))
        self.assertEqual(ctx.exception.reason, "SOURCE_CLUSTER_AS_TARGET")

    def test_reject_other_new_cluster(self):
        with self.assertRaises(probe.ProbeDenied) as ctx:
            probe.validate_catalog(row("8888888888888888888"))
        self.assertEqual(ctx.exception.reason, "UNEXPECTED_TARGET_CLUSTER")

    def test_accept_exact_target_cluster(self):
        self.assertEqual(probe.validate_catalog(row()),
                         "7696517018472497211")

    def test_reject_any_object_category(self):
        for i in range(6):
            counts = ["0"] * 6
            counts[i] = "1"
            with self.subTest(i=i), self.assertRaises(probe.ProbeDenied):
                probe.validate_catalog(row(counts=counts))

    def test_reject_wrong_version_or_read_write(self):
        for prefix in ("railway|170009|on", "railway|180006|off"):
            with self.assertRaises(probe.ProbeDenied):
                probe.validate_catalog(
                    prefix + "|" + probe.EXPECTED_TARGET_CLUSTER
                    + "|0|0|0|0|0|0\n"
                )

    def test_driver_error_never_logs_secrets(self):
        run = Mock(return_value=SimpleNamespace(
            returncode=1, stdout="secret DSN info"
        ))
        with self.assertRaises(probe.ProbeDenied) as ctx:
            probe.probe(env(), runner=run)
        self.assertEqual(ctx.exception.reason, "READONLY_QUERY_FAILED")


if __name__ == "__main__":
    unittest.main()
