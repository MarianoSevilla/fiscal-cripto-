"""B10R immutable source denial: no runtime route to real Railway DDL."""
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import real_restore_entrypoint as entry

ROOT = Path(__file__).resolve().parent

class TestFinalEntryPointDenied(unittest.TestCase):
    def test_literal_disabled_gate(self):
        self.assertIs(entry.LIVE_RESTORE_AUTHORIZED_IN_SOURCE, False)

    def test_default_call_refuses_even_with_dummy_worker(self):
        worker = Mock()
        with self.assertRaises(entry.EntryDenied) as exc:
            entry.entrypoint(env={}, worker=worker)
        self.assertEqual(exc.exception.code, "AWAITING_SEPARATE_RESTORE_AUTHORIZATION")
        worker.assert_not_called()

    def test_no_environment_override(self):
        for k in ("APPROVE_REAL_RESTORE", "LIVE_RESTORE_ALLOWED", "GO", "B10R_RUN", "RAILWAY_ENVIRONMENT_ID"):
            with self.subTest(k=k), self.assertRaises(entry.EntryDenied):
                entry.entrypoint(env={k: "true"}, worker=Mock())

    def test_manually_changing_flag_to_true_is_not_authorization(self):
        with patch.object(entry, "LIVE_RESTORE_AUTHORIZED_IN_SOURCE", True):
            worker = Mock()
            with self.assertRaises(entry.EntryDenied) as ex:
                entry.entrypoint(env={"APPROVE_REAL_RESTORE": "true"}, worker=worker)
            self.assertEqual(ex.exception.code, "SOURCE_GATE_TAMPERED")
            worker.assert_not_called()

    def test_none_or_string_override_also_denied(self):
        for value in (None, "true", 1, ""):
            with self.subTest(value=value), patch.object(entry, "LIVE_RESTORE_AUTHORIZED_IN_SOURCE", value):
                with self.assertRaises(entry.EntryDenied):
                    entry.entrypoint(worker=Mock())

    def test_main_always_exits_nonzero_without_worker(self):
        buf = StringIO()
        with patch.object(entry, "entrypoint", side_effect=entry.EntryDenied("AWAITING_SEPARATE_RESTORE_AUTHORIZATION")):
            with redirect_stderr(buf), self.assertRaises(SystemExit) as out:
                entry.main()
        self.assertEqual(out.exception.code, 1)
        self.assertIn("NO-GO", buf.getvalue())

    def test_current_railway_image_includes_no_writer(self):
        d = (ROOT / "Dockerfile.readonly-archive").read_text()
        self.assertIn("COPY preflight_archive.py", d)
        self.assertNotIn("COPY restore_candidate.py", d)
        self.assertNotIn("COPY real_restore_entrypoint.py", d)

    def test_b10r_image_contains_disabled_entrypoint(self):
        d = (ROOT / "Dockerfile.real-restore-disabled").read_text()
        self.assertIn("COPY real_restore_entrypoint.py", d)
        self.assertIn("ENTRYPOINT", d)
        self.assertIn("/app/real_restore_entrypoint.py", d)
        self.assertNotIn("ENTRYPOINT [\"/opt/s01-restore-venv/bin/python\", \"/app/restore_candidate.py\"]", d)

if __name__ == "__main__":
    unittest.main()
