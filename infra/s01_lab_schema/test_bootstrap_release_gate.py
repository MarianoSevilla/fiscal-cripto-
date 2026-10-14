"""B11E: contract tests are pure, do not contact Railway or PostgreSQL."""
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import preflight
import bootstrap_release_gate as gate


def fake_lab():
    return {
        "RAILWAY_PROJECT_ID": preflight.PROJECT_ID,
        "RAILWAY_ENVIRONMENT_ID": preflight.ENVIRONMENT_ID,
        "RAILWAY_ENVIRONMENT_NAME": "lab",
        "RAILWAY_SERVICE_ID": preflight.SERVICE_ID,
        "RAILWAY_PRIVATE_DOMAIN": preflight.SERVICE_PRIVATE_DOMAIN,
        "TARGET_DATABASE_URL":
            "postgresql://fake-user:CI-ONLY-secret@"
            "postgres-im3h.railway.internal:5432/railway",
    }


class TestB11EHardDenials(unittest.TestCase):
    def test_source_release_literal_false(self):
        self.assertIs(gate.SOURCE_RELEASED, False)

    def test_release_always_denies_without_external_actions(self):
        fn = Mock()
        with self.assertRaises(gate.SchemaReleaseDenied) as ex:
            gate.release_gate(fake_lab(), worker=fn)
        self.assertEqual(ex.exception.code, "DDL_NOT_AUTHORIZED")
        fn.assert_not_called()

    def test_approval_intent_not_sufficient_for_execution(self):
        fn = Mock()
        env = {**fake_lab(), gate.APPROVAL_KEY: gate.APPROVAL_INTENT}
        with self.assertRaisesRegex(gate.SchemaReleaseDenied, "DDL_NOT_AUTHORIZED"):
            gate.release_gate(env, worker=fn)
        fn.assert_not_called()

    def test_boolean_override_still_denied(self):
        for val in (True, None, "true", 1):
            with self.subTest(val=val), patch.object(gate, "SOURCE_RELEASED", val):
                fn = Mock()
                with self.assertRaisesRegex(
                    gate.SchemaReleaseDenied, "UNREVIEWED_SOURCE_CHANGE"
                ):
                    gate.release_gate({gate.APPROVAL_KEY: gate.APPROVAL_INTENT}, worker=fn)
                fn.assert_not_called()

    def test_approval_is_not_accepted_as_generic_word(self):
        for word in ("procede", "autorizo", "true", "1", "approved"):
            with self.subTest(word=word), self.assertRaisesRegex(
                gate.SchemaReleaseDenied, "UNEXPECTED_SCHEMA_APPROVAL"
            ):
                gate.validate_review_parameters({**fake_lab(), gate.APPROVAL_KEY: word})

    def test_review_without_approval_is_non_executable(self):
        summary = gate.validate_review_parameters(fake_lab())
        self.assertFalse(summary.approved_intent_present)
        self.assertEqual(summary.destination_cluster, preflight.TARGET_CLUSTER)
        self.assertEqual(summary.service_id, preflight.SERVICE_ID)
        self.assertEqual(summary.head_revision, "z9a0b1c2d3e4")

    def test_review_with_exact_approval_still_only_pure_summary(self):
        summary = gate.validate_review_parameters({
            **fake_lab(), gate.APPROVAL_KEY: gate.APPROVAL_INTENT
        })
        self.assertTrue(summary.approved_intent_present)
        self.assertEqual(summary.destination, "postgres-im3h.railway.internal")
        self.assertFalse(hasattr(summary, "password"))

    def test_wrong_project_or_service_denied(self):
        for field in ("RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_ENVIRONMENT_ID"):
            with self.subTest(field=field), self.assertRaisesRegex(
                gate.SchemaReleaseDenied, "PIN_RAILWAY_IDENTITY"
            ):
                gate.validate_review_parameters({**fake_lab(), field: "not-authorized"})

    def test_original_pg_url_denied(self):
        with self.assertRaisesRegex(gate.SchemaReleaseDenied, "PIN_WRONG_TARGET"):
            gate.validate_review_parameters({
                **fake_lab(), "TARGET_DATABASE_URL":
                "postgresql://u:p@postgres.railway.internal:5432/railway"
            })

    def test_restore_approval_conflict_denied(self):
        with self.assertRaisesRegex(gate.SchemaReleaseDenied, "STALE_RESTORE_APPROVAL"):
            gate.validate_review_parameters({
                **fake_lab(), "S01_RECOVERY_WRITE_APPROVAL": "even-revoked"
            })

    def test_additional_web_secrets_denied(self):
        for key in ("DATABASE_URL", "STRIPE_SECRET_KEY", "RESEND_API_KEY"):
            with self.subTest(key=key), self.assertRaisesRegex(
                gate.SchemaReleaseDenied, "PIN_UNAPPROVED_SECRETS"
            ):
                gate.validate_review_parameters({**fake_lab(), key: "fictitious"})

    def test_source_has_no_schema_writer_or_network_client(self):
        text = Path(gate.__file__).read_text()
        for forbidden in ("import psycopg2", "import sqlalchemy", "import flask",
                          "import app", "from models import", "db.create_all(",
                          "stamp(", "upgrade(", "subprocess.run(", "connect("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_cli_always_prints_no_go_without_secret(self):
        out = StringIO()
        with redirect_stderr(out), self.assertRaises(SystemExit) as ex:
            gate.main()
        self.assertEqual(ex.exception.code, 1)
        self.assertIn("DDL_NOT_AUTHORIZED", out.getvalue())
        self.assertNotIn("postgresql://", out.getvalue())

    def test_current_readonly_dockerfile_remains_writer_free(self):
        df = (Path(gate.__file__).parent / "Dockerfile").read_text()
        self.assertIn("COPY preflight.py", df)
        self.assertNotIn("COPY bootstrap_release_gate.py", df)
        self.assertNotIn("COPY bootstrap_executor.py", df)


if __name__ == "__main__":
    unittest.main()
