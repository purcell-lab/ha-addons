"""The Status page against its preview server (tests/ui_preview.py): no image.

Every element the script looks up exists, the collapsible sections are named
so the browser can remember them, nothing needs an inline style (the page CSP
is style-src 'self'), and each preview scenario serves the page and its API.
"""
import json
from pathlib import Path
import re
import sys
import unittest
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ui_preview  # noqa: E402

WWW = ui_preview.WWW


class StatusPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (WWW / "index.html").read_text()
        cls.js = (WWW / "app.js").read_text()

    def test_every_looked_up_id_exists(self):
        ids = set(re.findall(r'id="([^"]+)"', self.html))
        used = set(re.findall(r'\$\("([^"]+)"\)', self.js))
        self.assertTrue(used)
        self.assertEqual(sorted(used - ids), [])
        self.assertEqual(len(re.findall(r'id="([^"]+)"', self.html)), len(ids), "duplicate id")

    def test_layout_station_left_ev_right_raw_data_folded(self):
        station = self.html.index('class="col station"')
        ev = self.html.index('class="col ev"')
        self.assertLess(station, ev)
        # Live power comes before the folded sections in the station column.
        self.assertLess(self.html.index('id="powervalue"'), self.html.index('<details'))
        folds = re.findall(r'<details class="card fold"( id="[^"]+")?', self.html)
        self.assertGreaterEqual(len(folds), 6)
        self.assertTrue(all(folds), "every folded section needs an id")
        for raw in ("txjson", "diagjson", "evsends", "needsmsgs", "dermsgs", "pricing"):
            self.assertLess(self.html.rindex("<details", 0, self.html.index(f'id="{raw}"')),
                            self.html.index(f'id="{raw}"'), raw)

    def test_no_inline_styles_or_scripts(self):
        self.assertNotIn(" style=", self.html)
        self.assertNotIn("<style", self.html)
        self.assertEqual(re.findall(r"<script(?! src=)", self.html), [])


class PreviewServerTest(unittest.TestCase):
    def setUp(self):
        self.server = ui_preview.serve(0)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=3) as r:
            return r.status, r.read()

    def test_scenarios(self):
        self.assertEqual(self.get("/")[0], 200)
        self.assertEqual(self.get("/style.css")[0], 200)
        for scenario in ui_preview.SCENARIOS:
            status = json.loads(self.get("/api/status?scenario=" + scenario)[1])
            profiles = json.loads(self.get("/api/profiles?scenario=" + scenario)[1])
            power = status["evse"]["powermeter"]["value"]["power_W"]["total"]
            self.assertEqual(power > 0, scenario == "charging", scenario)
            self.assertEqual(power < 0, scenario == "discharging", scenario)
            self.assertIn("charging_needs", profiles)

    def test_needs_are_kept(self):
        req = urllib.request.Request(self.base + "/api/ev/needs", method="POST",
                                     data=json.dumps({"mode": "charge_by", "ready_by": 1}).encode())
        with urllib.request.urlopen(req, timeout=3) as r:
            self.assertEqual(json.loads(r.read())["needs"]["mode"], "charge_by")
        self.assertEqual(json.loads(self.get("/api/status")[1])["ev"]["needs"]["mode"], "charge_by")


if __name__ == "__main__":
    unittest.main()
