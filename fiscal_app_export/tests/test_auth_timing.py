"""Phase durations and exceptions without logging credential/request content."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('auth_timing_unit',Path(__file__).resolve().parents[1]/'auth_timing.py')
timing=importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing)

class LoginTimingTests(unittest.TestCase):
    def test_phase_duration_and_total(self):
        with patch.object(timing,'perf_counter',side_effect=[0,0,1.25,1.5]), patch.object(timing.logger,'info') as log:
            with timing.LoginTiming() as t:
                with t.phase('account_lookup'):
                    pass
            calls=log.call_args_list
            self.assertEqual(calls[-2].args[-1],1250)
            self.assertEqual(calls[-1].args[-2:],(1500,False))
            self.assertTrue(all(c.args[1]==t.trace for c in calls))

    def test_exception_propagates_but_its_content_is_not_logged(self):
        secret='private@example.invalid password-reset-token'
        with patch.object(timing.logger,'info') as log:
            with self.assertRaisesRegex(RuntimeError,'private'):
                with timing.LoginTiming() as t:
                    with t.phase('last_login_commit'):
                        raise RuntimeError(secret)
            self.assertNotIn(secret,str(log.call_args_list))
            self.assertTrue(log.call_args_list[-1].args[-1])

    def test_unknown_phase_cannot_log_arbitrary_input(self):
        with patch.object(timing.logger,'info') as log:
            with self.assertRaises(ValueError):
                with timing.LoginTiming() as t:
                    with t.phase('private@example.invalid'):
                        pass
            self.assertNotIn('private@example.invalid',str(log.call_args_list))

if __name__=='__main__':
    unittest.main()
