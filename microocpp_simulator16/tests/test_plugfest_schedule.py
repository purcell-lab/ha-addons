import unittest

from plugfest_schedule import WINDOWS, expected_wh, schedule


class PlugfestFixtureTests(unittest.TestCase):
    def test_five_minute_fixture_and_acceleration(self):
        normal, fast = schedule(), schedule(4)
        self.assertEqual(normal["duration"], 2100)
        self.assertEqual(fast["duration"], 28)
        self.assertEqual([p["limit"] for p in normal["chargingSchedulePeriod"]],
                         [11000, 7000, 11000, 3000, 0, 11000, 0])
        self.assertEqual([p["startPeriod"] for p in normal["chargingSchedulePeriod"]],
                         list(range(0, 2100, 300)))
        energy = expected_wh(normal["chargingSchedulePeriod"], 0, 2100, 2100)
        self.assertAlmostEqual(energy, 3583.333333333333)
        self.assertAlmostEqual(
            expected_wh(fast["chargingSchedulePeriod"], 0, 28, 28), energy / 75)

    def test_energy_uses_interval_not_whole_schedule(self):
        s = schedule(4)
        self.assertAlmostEqual(expected_wh(s["chargingSchedulePeriod"], 3, 5, 28), 5)
        self.assertEqual(expected_wh(s["chargingSchedulePeriod"], 16, 20, 28), 0)
        with self.assertRaises(ValueError):
            expected_wh(s["chargingSchedulePeriod"], 0, 29, 28)

    def test_reject_v2g_and_inconsistent_fixture(self):
        with self.assertRaises(ValueError):
            schedule(windows=(("V2G", -2000, 13000, 0, -2000),))
        with self.assertRaises(ValueError):
            schedule(windows=(("wrong headroom", 11000, 9000, 2000, 9000),))
        for seconds in (0, -1, 0.5):
            with self.assertRaises(ValueError):
                schedule(seconds)
        self.assertEqual(len(WINDOWS), 7)
