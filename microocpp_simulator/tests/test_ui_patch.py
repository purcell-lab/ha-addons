"""Focused fail-closed regression for the pinned upstream UI adaptation."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "prepare_source", Path(__file__).resolve().parents[1] / "prepare_source.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CONTEXT = (
    "{evPlugged:e,evReady:n,evseReady:r};"
    "{evPlugged:$,evReady:z,evseReady:q};"
    "t.evPlugged===O&&t.evReady===x&&t.evseReady===E;"
    "DateFormatter.fullDate(new Date);"
    '{class:"status-badge",onClick:function(){M("Charging")}}'
    'case"Charging":;case"Charging":;case"Charging":;'
)


class UiPatchTest(unittest.TestCase):
    def test_both_forms_match_both_cable_ends_and_actual_submitted_state(self):
        result = module.fix_ui_power_controls(CONTEXT)
        self.assertIn("evPlugged:e,evsePlugged:e,", result)
        self.assertIn("evPlugged:$,evsePlugged:$,", result)
        self.assertIn("t.evPlugged===e&&t.evsePlugged===e&&t.evReady===n", result)
        self.assertNotIn("DateFormatter", result)
        self.assertNotIn('M("Charging")', result)
        self.assertEqual(result.count('case"Occupied":'), 3)

    def test_changed_upstream_and_double_application_fail_closed(self):
        with self.assertRaises(ValueError):
            module.fix_ui_power_controls(CONTEXT.replace("evPlugged:$,", "changed:$,"))
        with self.assertRaises(ValueError):
            module.fix_ui_power_controls(module.fix_ui_power_controls(CONTEXT))
