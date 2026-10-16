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
              "password":"a"*40,"charge_point_id":"SIM-CITRINE-LAB-01"}
        self.assertEqual(app.validate(good)[1],"SIM-CITRINE-LAB-01")
        for change in ({"charge_point_id":"REAL"},{"backend_url":"ws://physical:9000"},{"password":""}):
            with self.assertRaises(ValueError):app.validate({**good,**change})

    def test_disconnected_default(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(app.configure(Path(d),{}))

    def test_trial_requires_connected_safe_identifier(self):
        for options in ({"bounded_trial_id":"trial"}, {"bounded_trial_id":"../bad"}):
            with self.assertRaises(ValueError):app.validate(options)

    def test_archive_and_rebind_moves_state_aside(self):
        good={"backend_url":"ws://lab-server:8081","acknowledge_test_isolation":True,
              "password":"a"*40,"charge_point_id":"SIM-CITRINE-LAB-01"}
        with tempfile.TemporaryDirectory() as d:
            data=Path(d)
            app.configure(data,good)
            (data/"mo_store"/"tx201-1-1-0.json").write_text("{}")
            moved={**good,"backend_url":"ws://31ac84d3-citrineos-server:8081"}
            with self.assertRaises(ValueError):app.configure(data,moved)
            app.configure(data,{**moved,"archive_and_rebind":True})
            archive=next(data.glob("archive-*"))
            self.assertTrue((archive/"mo_store"/"tx201-1-1-0.json").exists())
            self.assertIn("lab-server",(archive/"test-identity.json").read_text())
            self.assertIn("31ac84d3",(data/"test-identity.json").read_text())
        with self.assertRaises(ValueError):app.validate({"archive_and_rebind":"yes"})

    def test_lab_dns_url(self):
        self.assertEqual(app.lab_dns_url("nameserver fd00::1\nnameserver 172.30.32.3\n"),"udp://172.30.32.3:53")
        self.assertIsNone(app.lab_dns_url(""))
