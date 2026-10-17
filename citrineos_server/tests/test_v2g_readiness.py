import unittest
from v2g_trial import discovery_ready, evaluate_steps


class ReadinessTest(unittest.TestCase):
    def test_pending_failed_or_malformed_is_not_ready(self):
        for value in (None, {}, {"selftest":None}, {"selftest":{}},
                      {"selftest":{"pass":False}}, {"selftest":{"pass":"true"}},
                      {"selftest":[]}, {"selftest":{"pass":1}}):
            with self.subTest(value=value):
                self.assertFalse(discovery_ready(value))

    def test_explicit_pass_is_ready(self):
        self.assertTrue(discovery_ready({"selftest":{"pass":True}}))


def samples_for(means, step=30):
    return [{"relative_s": i*step + offset, "power_w": watts}
            for i, watts in enumerate(means) for offset in range(8, step-2)]


class StepEvaluationTest(unittest.TestCase):
    targets = [6000, -5000, 3000, 0]

    def test_zero_watt_step_is_tracked_like_any_other(self):
        steps, failures, known = evaluate_steps(self.targets, samples_for([6000, -5000, 3000, 0]), 30)
        self.assertEqual((failures, known), ([], []))
        self.assertEqual([s["passed"] for s in steps], [True, True, True, True])

    def test_zero_watt_hold_fails(self):
        _, failures, known = evaluate_steps(self.targets, samples_for([6000, -5000, 3000, 3000]), 30)
        self.assertEqual(known, [])
        self.assertEqual(len(failures), 1)
        self.assertIn("at 0 W", failures[0])

    def test_other_steps_still_fail(self):
        _, failures, _ = evaluate_steps(self.targets, samples_for([11000, -5000, 3000, 0]), 30)
        self.assertEqual(len(failures), 1)
        self.assertIn("6000 W", failures[0])
        _, failures, _ = evaluate_steps(self.targets, samples_for([6000, -1111.11, 3000, 0]), 30)
        self.assertIn("-5000 W", failures[0])

    def test_a_known_defect_allowance_fails_once_the_step_passes(self):
        import v2g_trial
        v2g_trial.KNOWN_DEFECT_SETPOINTS[0] = "held"
        try:
            _, failures, known = evaluate_steps(self.targets, samples_for([6000, -5000, 3000, 0]), 30)
            self.assertEqual(known, [])
            self.assertIn("remove its known-defect allowance", failures[0])
            _, failures, known = evaluate_steps(self.targets, samples_for([6000, -5000, 3000, 3000]), 30)
            self.assertEqual(failures, [])
            self.assertEqual(len(known), 1)
        finally:
            v2g_trial.KNOWN_DEFECT_SETPOINTS.clear()
