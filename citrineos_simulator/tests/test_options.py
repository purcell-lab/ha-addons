import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location("app",Path(__file__).resolve().parents[1]/"app.py")
app=importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

class DedicatedOptions(unittest.TestCase):
    def test_reject_wrong_identity_endpoint_and_missing_password(self):
        good={"backend_url":"ws://lab-server:8081","acknowledge_test_isolation":True,
              "password":"a"*64,"charge_point_id":"SIM-CITRINE-LAB-01"}
        self.assertEqual(app.validate(good)[1],"SIM-CITRINE-LAB-01")
        for change in ({"charge_point_id":"REAL"},{"backend_url":"ws://physical:9000"},{"password":""}):
            with self.assertRaises(ValueError):app.validate({**good,**change})

    def test_disconnected_default(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(app.configure(Path(d),{}))
