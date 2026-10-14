"""Offline NO-GO release policy for B10P candidate image."""
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch
import release_gate as g


HERE = Path(__file__).resolve().parent


class TestRestoreReleaseGate(unittest.TestCase):
    def test_compiled_release_gate_is_literal_false(self):
        self.assertIs(g.LIVE_RESTORE_RELEASED, False)

    def test_release_unconditionally_denied(self):
        with self.assertRaises(g.ReleaseDenied) as ctx:
            g.restore_release({})
        self.assertEqual(str(ctx.exception), "REAL_RESTORE_NOT_AUTHORIZED")

    def test_tampering_flag_cannot_enable_restoration(self):
        with patch.object(g, "LIVE_RESTORE_RELEASED", True):
            with self.assertRaises(g.ReleaseDenied) as ctx:
                g.restore_release({})
        self.assertEqual(str(ctx.exception), "INVALID_RELEASE_GATE")

    def test_no_environment_flag_can_authorize_it(self):
        for key in ("RESTORE_ALLOWED", "GO", "AUTHORIZED",
                    "RAILWAY_ENVIRONMENT_ID", "B10P_ALLOW_REAL"):
            with self.subTest(key=key):
                with self.assertRaises(g.ReleaseDenied):
                    g.restore_release({key: "true"})

    def test_main_fails_closed_and_logs_no_sensitive_values(self):
        buf = StringIO()
        with redirect_stderr(buf), self.assertRaises(SystemExit) as exc:
            g.main()
        self.assertEqual(exc.exception.code, 1)
        self.assertIn("NO-GO (REAL_RESTORE_NOT_AUTHORIZED)", buf.getvalue())
        self.assertNotIn("postgresql://", buf.getvalue())

    def test_current_railway_dockerfile_excludes_candidate_and_gate(self):
        docker = (HERE / "Dockerfile").read_text()
        self.assertIn("COPY probe.py", docker)
        self.assertNotIn("COPY restore_candidate.py", docker)
        self.assertNotIn("COPY release_gate.py", docker)
        self.assertIn("/app/probe.py", docker)

    def test_proposed_image_uses_only_denied_release_gate(self):
        docker = (HERE / "Dockerfile.candidate-disabled").read_text()
        self.assertIn("COPY restore_candidate.py", docker)
        self.assertIn("COPY release_gate.py", docker)
        self.assertIn("/app/release_gate.py", docker)
        self.assertNotIn("ENTRYPOINT [\"python3\", \"/app/restore_candidate.py\"]", docker)

    def test_restorer_candidate_main_remains_denied(self):
        import restore_candidate as candidate
        with patch.object(candidate, "restore_once") as fn:
            with redirect_stderr(StringIO()) as _, self.assertRaises(SystemExit):
                candidate.main()
        fn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
