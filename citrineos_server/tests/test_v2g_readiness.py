import unittest
from v2g_trial import discovery_ready


class ReadinessTest(unittest.TestCase):
    def test_pending_failed_or_malformed_is_not_ready(self):
        for value in (None, {}, {"selftest":None}, {"selftest":{}},
                      {"selftest":{"pass":False}}, {"selftest":{"pass":"true"}},
                      {"selftest":[]}, {"selftest":{"pass":1}}):
            with self.subTest(value=value):
                self.assertFalse(discovery_ready(value))

    def test_explicit_pass_is_ready(self):
        self.assertTrue(discovery_ready({"selftest":{"pass":True}}))
