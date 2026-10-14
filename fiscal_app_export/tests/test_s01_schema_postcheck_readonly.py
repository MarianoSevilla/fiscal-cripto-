"""Postbootstrap parking image contracts; synthetic responses only."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import schema_postcheck_readonly as pc
import schema_preflight as pg


def fake_env():
    return {
        "RAILWAY_PROJECT_ID": pg.PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": pg.ENVIRONMENT_ID,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": pg.SERVICE_ID,
        "RAILWAY_PRIVATE_DOMAIN": pg.SERVICE_PRIVATE_DOMAIN,
        "TARGET_DATABASE_URL":
            "postgresql://user:fake-ci-password@"
            "postgres-im3h.railway.internal:5432/railway",
    }


def success():
    return "|".join([
        "railway", pg.TARGET_PG_VERSION, "on", pg.TARGET_CLUSTER,
        "6", "1", pc.HEAD, "1", "7", "2",
    ]) + "\n"


class TestPostBootstrapReadOnly(unittest.TestCase):
    def test_expected_schema_accepted_only_when_complete(self):
        self.assertEqual(pc.validate_output(success()), pg.TARGET_CLUSTER)

    def test_wrong_cluster_rejected(self):
        with self.assertRaisesRegex(pc.PostcheckDenied, "WRONG_RECOVERED_CLUSTER"):
            pc.validate_output(success().replace(pg.TARGET_CLUSTER, pg.FORBIDDEN_ORIGINAL_CLUSTER))

    def test_partial_schema_or_seed_rejected(self):
        cols = success().strip().split("|")
        for idx in range(4, 10):
            if idx == 6:
                value = "m6n7o8p9q0r1"
            else:
                value = "0"
            dirty = cols.copy()
            dirty[idx] = value
            with self.subTest(idx=idx), self.assertRaises(pc.PostcheckDenied):
                pc.validate_output("|".join(dirty) + "\n")

    def test_not_readonly_rejected(self):
        with self.assertRaisesRegex(pc.PostcheckDenied, "DATABASE_VERSION_OR_READONLY"):
            pc.validate_output(success().replace("|on|", "|off|"))

    def test_no_additional_rows_accepted(self):
        with self.assertRaisesRegex(pc.PostcheckDenied, "RESULT_SHAPE"):
            pc.validate_output(success() + success())

    def test_psql_query_is_select_and_pg_env_readonly(self):
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=success()))
        self.assertEqual(pc.probe_completed_schema(fake_env(), runner=runner), pg.TARGET_CLUSTER)
        argv, kwargs = runner.call_args
        self.assertEqual(argv[0][0], "psql")
        self.assertTrue(argv[0][-1].strip().startswith("SELECT"))
        self.assertIn("default_transaction_read_only=on", kwargs["env"]["PGOPTIONS"])
        self.assertEqual(kwargs["env"]["PGHOST"], "postgres-im3h.railway.internal")

    def test_no_unapproved_host_ever_contacts_psql(self):
        runner = Mock()
        with self.assertRaises(pg.SchemaPreflightDenied):
            pc.probe_completed_schema({
                **fake_env(), "TARGET_DATABASE_URL":
                "postgresql://x:y@postgres.railway.internal:5432/railway"
            }, runner=runner)
        runner.assert_not_called()

    def test_writer_excluded_from_parking_dockerfile(self):
        docker = (Path(pc.__file__).parent / "Dockerfile.schema-postcheck-readonly").read_text()
        self.assertIn("COPY schema_postcheck_readonly.py", docker)
        self.assertNotIn("COPY schema_bootstrap_one_shot.py", docker)
        self.assertNotIn("COPY models.py", docker)
        self.assertNotIn("COPY migrations", docker)


if __name__ == "__main__":
    unittest.main()
