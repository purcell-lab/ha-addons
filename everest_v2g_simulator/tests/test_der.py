"""OCPP 2.1 DER control: the App's grid_support module (HaGridSupport), the
Status page summary, the DER message log and the core-database upgrade.
No EVerest binaries are needed."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/ha-everest"))
import configure  # noqa: E402
import ocpp_log  # noqa: E402

MODULE = ROOT / "rootfs/opt/everest/libexec/everest/modules/HaGridSupport/module.py"
spec = importlib.util.spec_from_file_location("ha_grid_support", MODULE)
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)  # main() needs everest.framework; the helpers do not

# An active directive set as OCPPmulti pushes it (types/grid_support.yaml).
ACTIVE = {"evse_id": 1, "directives": [
    {"id": "ha-der-1", "directive_type": "LimitMaxDischarge", "priority": 1, "is_default": False,
     "source": "ocpp", "received_at": "2026-10-25T00:00:00Z", "start_time": "2026-10-25T00:00:00Z",
     "duration_s": 600, "limit_max_discharge": {"pct_max_discharge_power": 50.0}},
    {"id": "ha-der-default", "directive_type": "FixedPFInject", "priority": 2, "is_default": True,
     "source": "ocpp", "received_at": "2026-10-25T00:00:00Z",
     "fixed_pf": {"displacement": 0.95, "excitation": False}},
    {"id": "vv", "directive_type": "VoltVar", "priority": 3, "is_default": False, "source": "ocpp",
     "received_at": "2026-10-25T00:00:00Z",
     "curve": {"y_unit": "PctMaxVar", "curve_data": [{"x": 95, "y": 30}, {"x": 105, "y": -30}]}},
]}


class CapabilityTest(unittest.TestCase):
    def test_dc_capability_from_config(self):
        config = {"evse_id": 1, "supported_types": ",".join(configure.DER_CONTROL_TYPES),
                  "rated_power_W": 25000.0, "nominal_voltage_V": 380.0}
        value = grid.capability(config)
        self.assertEqual(value["evse_id"], 1)
        cap = value["capability"]
        self.assertEqual(cap["supported_types"], list(configure.DER_CONTROL_TYPES))
        self.assertEqual(cap["nameplate"], {"max_w_W": 25000.0, "max_va_VA": 25000.0, "v_nom_V": 380.0,
                                            "max_charge_w_W": 25000.0, "max_discharge_w_W": 25000.0})
        # DC: OCPPmulti enables DCDERCtrlr (the EVSE is DC); never AC here.
        self.assertIn("dc", cap)
        self.assertNotIn("ac", cap)
        # additionalProperties: false in the type schema.
        self.assertEqual(set(cap), {"supported_types", "nameplate", "dc"})
        self.assertEqual(set(cap["dc"]["device_info"]), {"manufacturer", "model", "sw_version"})

    def test_types_are_ocpp_der_control_names(self):
        # libocpp's ModesSupported valuesList (ocpp_module_common definitions).
        values = ("EnterService,FreqDroop,FreqWatt,FixedPFAbsorb,FixedPFInject,FixedVar,Gradients,"
                  "HFMustTrip,HFMayTrip,HVMustTrip,HVMomCess,HVMayTrip,LimitMaxDischarge,LFMustTrip,"
                  "LVMustTrip,LVMomCess,LVMayTrip,PowerMonitoringMustTrip,VoltVar,VoltWatt,WattPF,WattVar")
        self.assertEqual(list(configure.DER_CONTROL_TYPES), values.split(","))
        self.assertEqual(grid.capability({"supported_types": " LimitMaxDischarge, ,VoltVar"})
                         ["capability"]["supported_types"], ["LimitMaxDischarge", "VoltVar"])


class DerStateTest(unittest.TestCase):
    def test_written_atomically_after_each_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run" / "der.json"
            ticks = iter(range(100, 200))
            state = grid.DerState(path, clock=lambda: next(ticks))
            state.update(relay="connected")
            self.assertEqual(json.loads(path.read_text())["relay"], "connected")
            state.set_capability({"evse_id": 1})
            state.set_active(ACTIVE)
            state.set_active({"evse_id": 1, "directives": []})
            data = json.loads(path.read_text())
            self.assertEqual(data["updates"], 2)
            self.assertEqual(data["active"], {"evse_id": 1, "directives": []})
            self.assertEqual(data["capability_at"], 100)
            for i in range(grid.ALARMS_KEPT + 3):
                state.add_alarm({"fault": "OverVoltage", "alarm_ended": bool(i % 2), "timestamp": "t"})
            self.assertEqual(len(json.loads(path.read_text())["alarms"]), grid.ALARMS_KEPT)
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["der.json"])

    def test_unwritable_path_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("")
            grid.DerState(blocker / "der.json").set_active(ACTIVE)  # parent is a file


class StatusTest(unittest.TestCase):
    def setUp(self):
        import ui_server
        self.ui = ui_server

    def test_summary_of_recorded_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "der.json"
            self.assertIsNone(self.ui.der_status(path))
            path.write_text("not json")
            self.assertIsNone(self.ui.der_status(path))
            state = grid.DerState(path, clock=lambda: 5.0)
            state.set_capability(grid.capability({"supported_types": "LimitMaxDischarge,FixedPFInject,VoltVar"}))
            state.set_active(ACTIVE)
            der = self.ui.der_status(path)
        self.assertEqual(der["control_types"], ["LimitMaxDischarge", "FixedPFInject", "VoltVar"])
        self.assertEqual([d["detail"] for d in der["active"]],
                         ["50 % of rated discharge power", "power factor 0.95", "curve, 2 points"])
        self.assertEqual(der["active"][0], {"id": "ha-der-1", "type": "LimitMaxDischarge", "priority": 1,
                                            "is_default": False, "start_time": "2026-10-25T00:00:00Z",
                                            "duration_s": 600, "detail": "50 % of rated discharge power"})
        self.assertTrue(der["active"][1]["is_default"])
        self.assertEqual((der["updates"], der["active_at"]), (1, 5.0))

    def test_status_reads_the_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            saved = self.ui.RUN
            self.ui.RUN = Path(tmp)
            try:
                grid.DerState(Path(tmp) / configure.DER_STATE).set_active(ACTIVE)
                bus = type("Bus", (), {"snapshot": lambda self: {}, "last_command": None})()
                self.assertEqual(len(self.ui.status(bus)["der"]["active"]), 3)
            finally:
                self.ui.RUN = saved


LOG = """2026-10-25T00:00:01.000Z: CentralSystem>ChargePoint  SetDERControl
[2, "a", "SetDERControl", {"isDefault": false, "controlId": "ha-der-1", "controlType": "LimitMaxDischarge", "limitMaxDischarge": {"priority": 1, "pctMaxDischargePower": 50.0}}]
2026-10-25T00:00:01.100Z: ChargePoint>CentralSystem  SetDERControlResponse
[3, "a", {"status": "Accepted"}]
2026-10-25T00:00:02.000Z: CentralSystem>ChargePoint  SetDERControl
[2, "b", "SetDERControl", {"isDefault": false, "controlId": "x", "controlType": "LimitMaxDischarge", "fixedVar": {"priority": 1, "setpoint": 1, "unit": "PctMaxVar"}}]
2026-10-25T00:00:02.100Z: ChargePoint>CentralSystem  SetDERControlResponse
[3, "b", {"status": "Rejected", "statusInfo": {"reasonCode": "InvalidValue", "additionalInfo": "ControlFieldMismatch"}}]
2026-10-25T00:00:03.000Z: CentralSystem>ChargePoint  GetDERControl
[2, "c", "GetDERControl", {"requestId": 42}]
2026-10-25T00:00:03.100Z: ChargePoint>CentralSystem  GetDERControlResponse
[3, "c", {"status": "Accepted"}]
2026-10-25T00:00:03.200Z: ChargePoint>CentralSystem  ReportDERControl
[2, "d", "ReportDERControl", {"requestId": 42}]
2026-10-25T00:00:04.000Z: CentralSystem>ChargePoint  ClearDERControl
[2, "e", "ClearDERControl", {"isDefault": true}]
2026-10-25T00:00:04.100Z: ChargePoint>CentralSystem  ClearDERControlResponse
[3, "e", {"status": "Accepted"}]
"""


class DerLogTest(unittest.TestCase):
    def test_der_requests_and_replies(self):
        events = ocpp_log.der_events(LOG)
        self.assertEqual([(e["action"], e["status"]) for e in events],
                         [("ClearDERControl", "Accepted"), ("GetDERControl", "Accepted"),
                          ("SetDERControl", "Rejected"), ("SetDERControl", "Accepted")])
        self.assertEqual(events[1 + 1]["status_info"]["additionalInfo"], "ControlFieldMismatch")
        # Kept apart from charging profiles and pricing.
        self.assertEqual(ocpp_log.profile_events(LOG), [])
        self.assertEqual(ocpp_log.pricing_events(LOG), [])


def core_db(path, version):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE T (x)")
    connection.execute(f"PRAGMA user_version = {version}")
    connection.commit()
    connection.close()


class CoreDatabaseTest(unittest.TestCase):
    def test_copy_before_migration_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "everest"
            (store / "ocpp201").mkdir(parents=True)
            self.assertIsNone(configure.preserve_core_db(store))  # fresh install
            db = store / "ocpp201" / configure.CORE_DB
            core_db(db, 6)  # EVerest 2025.10.0 (App 0.1.13)
            backup = configure.preserve_core_db(store)
            self.assertEqual(backup.name, "cp-schema6.db.bak")
            self.assertEqual(configure.core_schema(backup), 6)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            backup.write_bytes(b"kept")
            self.assertIsNone(configure.preserve_core_db(store))  # never overwritten
            self.assertEqual(backup.read_bytes(), b"kept")
            # Not a *.db file: the identity binding's state check ignores it.
            self.assertEqual(sorted(p.name for p in (store / "ocpp201").glob("*.db")), ["cp.db"])

    def test_current_schema_and_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "everest"
            (store / "ocpp201").mkdir(parents=True)
            db = store / "ocpp201" / configure.CORE_DB
            core_db(db, configure.CORE_SCHEMA)
            self.assertIsNone(configure.preserve_core_db(store))
            db.write_bytes(b"not a database")
            self.assertIsNone(configure.preserve_core_db(store))  # libocpp decides
            self.assertEqual(sorted(p.name for p in db.parent.iterdir()), ["cp.db"])

    def test_target_schema_matches_shipped_migrations(self):
        # 7_up-der_controls_db.sql is the newest core migration at 2026.10.0-rc1.
        self.assertEqual(configure.CORE_SCHEMA, 7)


if __name__ == "__main__":
    unittest.main()
