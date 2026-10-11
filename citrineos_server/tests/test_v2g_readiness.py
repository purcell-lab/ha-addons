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

    def test_zero_watt_hold_is_a_known_defect_not_a_failure(self):
        steps, failures, known = evaluate_steps(self.targets, samples_for([6000, -5000, 3000, 3000]), 30)
        self.assertEqual(failures, [])
        self.assertEqual(len(known), 1)
        self.assertIn("3000", known[0])
        self.assertEqual([s["passed"] for s in steps], [True, True, True, False])

    def test_other_steps_still_fail(self):
        _, failures, _ = evaluate_steps(self.targets, samples_for([11000, -5000, 3000, 3000]), 30)
        self.assertEqual(len(failures), 1)
        self.assertIn("6000 W", failures[0])
        _, failures, _ = evaluate_steps(self.targets, samples_for([6000, -1111.11, 3000, 3000]), 30)
        self.assertIn("-5000 W", failures[0])

    def test_fixed_zero_step_fails_until_allowance_removed(self):
        _, failures, known = evaluate_steps(self.targets, samples_for([6000, -5000, 3000, 0]), 30)
        self.assertEqual(known, [])
        self.assertEqual(len(failures), 1)
        self.assertIn("remove its known-defect allowance", failures[0])
