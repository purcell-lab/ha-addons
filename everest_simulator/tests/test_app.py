"""Unit tests for option validation, identity binding, generated EVerest and
device-model configuration, log parsing, log filtering and the UI service.
No EVerest binaries are needed."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "rootfs/opt/ha-everest"
sys.path.insert(0, str(APP))
import configure  # noqa: E402
import ocpp_log  # noqa: E402

CONFIG_TEXT = (ROOT / "config.yaml").read_text()
GOOD = {"csms_url": "ws://192.0.2.10:9300/ocpp", "charge_point_id": "SIM-EV-EVEREST-01",
        "ocpp_version": "2.1", "phases": "1", "max_current_a": 32,
        "acknowledge_test_isolation": True}


def component_fixture(directory):
    """Minimal standardized device-model files with the properties we edit."""
    def doc(*props):
        return {"properties": {p: {"attributes": [{"type": "Actual", "value": None}]} for p in props}}
    std = directory / "standardized"
    std.mkdir(parents=True)
    files = {
        "InternalCtrlr": doc("ChargePointId", "NetworkConnectionProfiles", "SupportedOcppVersions",
                             "ChargePointVendor", "ChargePointModel", "ChargeBoxSerialNumber",
                             "LogMessagesFormat", "LogRotation", "LogRotationMaximumFileSize",
                             "LogRotationMaximumFileCount"),
        "SecurityCtrlr": doc("SecurityCtrlrIdentity", "BasicAuthPassword", "SecurityProfile"),
        "SmartChargingCtrlr": doc("CompositeScheduleDefaultLimitAmps", "CompositeScheduleDefaultLimitWatts",
                                  "CompositeScheduleDefaultNumberPhases"),
        "SampledDataCtrlr": doc("SampledDataTxUpdatedInterval"),
        "OCPPCommCtrlr": doc("HeartbeatInterval"),
        "ChargingStation": doc("ChargingStationSupplyPhases"),
    }
    for name, content in files.items():
        (std / f"{name}.json").write_text(json.dumps(content))
    return directory


def value(directory, name, prop):
    doc = json.loads((directory / "standardized" / f"{name}.json").read_text())
    return doc["properties"][prop]["attributes"][0]["value"]


class ManifestTest(unittest.TestCase):
    def test_safe_defaults(self):
        for line in ("boot: manual", "ingress: true", "ingress_port: 8099", 'csms_url: ""',
                     'ocpp_version: "2.1"', "acknowledge_test_isolation: false",
                     "charge_point_id: SIM-EV-EVEREST-01", "ocpp_version: list(2.1|2.0.1)",
                     "charge_point_id: match(^SIM-EV-[A-Za-z0-9_-]{1,36}$)"):
            self.assertIn(line, CONFIG_TEXT)
        for forbidden in ("ports:", "host_network", "privileged", "full_access", "devices:",
                          "homeassistant_api", "hassio_api", "docker_api", "map:"):
            self.assertNotIn(forbidden, CONFIG_TEXT)


class ValidateTest(unittest.TestCase):
    def test_defaults_are_disconnected_and_2_1(self):
        settings = configure.validate({})
        self.assertEqual(settings["csms_url"], "")
        self.assertEqual(settings["ocpp_version"], "2.1")
        self.assertEqual(configure.VERSIONS["2.1"], "ocpp2.1,ocpp2.0.1")
        self.assertEqual(configure.VERSIONS["2.0.1"], "ocpp2.0.1")

    def test_ha_string_phases(self):
        self.assertEqual(configure.validate(dict(GOOD, phases="3"))["phases"], 3)
        self.assertEqual(configure.validate(dict(GOOD, phases=1))["phases"], 1)

    def test_rejections(self):
        bad = [
            {"charge_point_id": "REAL-CHARGER"}, {"charge_point_id": "SIM-EV-"},
            {"ocpp_version": "1.6"}, {"ocpp_version": 2.1}, {"phases": 2}, {"phases": True},
            {"max_current_a": 5}, {"max_current_a": 33}, {"max_current_a": True},
            {"csms_url": "wss://host:443"}, {"csms_url": "http://host:80"},
            {"csms_url": "ws://host"}, {"csms_url": "ws://user:pw@host:80"},
            {"csms_url": "ws://host:80/?a=b"}, {"csms_url": "ws://host:80/%2e"},
            {"csms_url": "ws://127.0.0.1:9"}, {"csms_url": "ws://h:80/" + "x" * 200},
            {"csms_url": "ws://host:80/SIM-EV-EVEREST-01"},
            {"acknowledge_test_isolation": False},
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                configure.validate(dict(GOOD, **change))

    def test_disconnected_needs_no_acknowledgement(self):
        configure.validate({"csms_url": "", "acknowledge_test_isolation": False})


class BindingTest(unittest.TestCase):
    def test_bind_once_and_refuse_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            settings = configure.validate(GOOD)
            configure.bind(data, settings)
            configure.bind(data, settings)
            with self.assertRaisesRegex(ValueError, "archive"):
                configure.bind(data, dict(settings, charge_point_id="SIM-EV-OTHER"))
            configure.bind(data, dict(settings, csms_url=""))  # disconnected start keeps binding
            self.assertEqual(json.loads((data / "test-identity.json").read_text())["csms_url"],
                             GOOD["csms_url"])

    def test_unbound_state_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "everest/ocpp201").mkdir(parents=True)
            (data / "everest/ocpp201/cp.db").write_text("x")
            with self.assertRaises(ValueError):
                configure.bind(data, configure.validate(GOOD))

    def test_archive_moves_not_deletes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "everest").mkdir()
            (data / "everest/marker").write_text("keep")
            (data / "test-identity.json").write_text("{}")
            archive = configure.archive_if_requested(data, {"archive_and_rebind": True})
            self.assertEqual((archive / "everest/marker").read_text(), "keep")
            self.assertFalse((data / "test-identity.json").exists())
            self.assertIsNone(configure.archive_if_requested(data, {}))

    def test_password_generated_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            first = configure.basic_auth_password(data)
            self.assertRegex(first, r"^[0-9a-f]{32}$")
            self.assertEqual(first, configure.basic_auth_password(data))
            self.assertEqual((data / "basic-auth-password").stat().st_mode & 0o777, 0o600)


class GeneratedConfigTest(unittest.TestCase):
    def build(self, options):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        source = component_fixture(Path(tmp.name) / "source")
        target = Path(tmp.name) / "target"
        settings = configure.validate(options)
        configure.component_config(source, target, settings, "a" * 32)
        return settings, target

    def test_offers_2_1_with_fallback(self):
        settings, target = self.build(GOOD)
        self.assertEqual(value(target, "InternalCtrlr", "SupportedOcppVersions"), "ocpp2.1,ocpp2.0.1")
        profile = json.loads(value(target, "InternalCtrlr", "NetworkConnectionProfiles"))[0]
        self.assertEqual(profile["connectionData"]["ocppCsmsUrl"], GOOD["csms_url"])
        self.assertEqual(profile["connectionData"]["securityProfile"], 1)
        self.assertEqual(value(target, "SecurityCtrlr", "SecurityCtrlrIdentity"), "SIM-EV-EVEREST-01")
        self.assertEqual(value(target, "SmartChargingCtrlr", "CompositeScheduleDefaultLimitWatts"), 7360)
        # Regression: a supply-phases override made libocpp ignore all profiles.
        self.assertIsNone(value(target, "ChargingStation", "ChargingStationSupplyPhases"))

    def test_pinned_2_0_1(self):
        _, target = self.build(dict(GOOD, ocpp_version="2.0.1"))
        self.assertEqual(value(target, "InternalCtrlr", "SupportedOcppVersions"), "ocpp2.0.1")

    def test_disconnected_url_is_closed_loopback(self):
        _, target = self.build({"csms_url": ""})
        profile = json.loads(value(target, "InternalCtrlr", "NetworkConnectionProfiles"))[0]
        self.assertEqual(profile["connectionData"]["ocppCsmsUrl"], "ws://127.0.0.1:9")

    def test_everest_config_scope(self):
        settings = configure.validate(dict(GOOD, phases="3", max_current_a=16))
        config = configure.everest_config(settings, Path("/data"))
        self.assertEqual(config["settings"]["mqtt_broker_host"], "127.0.0.1")
        self.assertFalse(config["settings"]["telemetry_enabled"])
        modules = {m["module"] for m in config["active_modules"].values()}
        self.assertNotIn("EvseV2G", modules)
        self.assertNotIn("PyEvJosev", modules)
        evse = config["active_modules"]["evse_manager_1"]["config_module"]
        self.assertFalse(evse["ac_hlc_enabled"])
        self.assertEqual(evse["max_current_export_A"], 0)
        self.assertEqual(evse["max_current_import_A"], 16)
        ev = config["active_modules"]["ev_manager_1"]["config_module"]
        self.assertTrue(ev["three_phases"])
        self.assertIn("draw_power_regulated 16,3", ev["auto_exec_commands"])
        for path in json.dumps(config).split('"'):
            if path.startswith("/") and "everest" in path and not path.startswith("/data"):
                self.fail(f"state outside /data: {path}")


LOG = """2026-10-10T07:13:33.909Z: CentralSystem>ChargePoint  SetChargingProfile
[
  2,
  "csms-2",
  "SetChargingProfile",
  {"evseId": 1, "chargingProfile": {"id": 160601, "chargingProfilePurpose": "TxProfile",
   "chargingSchedule": [{"id": 1, "chargingRateUnit": "W", "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 4000.0}]}]}}
]
2026-10-10T07:13:34.007Z: ChargePoint>CentralSystem SetChargingProfileResponse
[
  3,
  "csms-2",
  {"status": "Accepted"}
]
2026-10-10T07:13:40.000Z: CentralSystem>ChargePoint  SetChargingProfile
[2, "csms-3", "SetChargingProfile", {"evseId": 1, "chargingProfile": {"id": 9, "chargingProfilePurpose": "TxDefaultProfile"}}]
2026-10-10T07:13:40.100Z: ChargePoint>CentralSystem SetChargingProfileResponse
[3, "csms-3", {"status": "Rejected", "statusInfo": {"reasonCode": "InvalidSchedule"}}]
2026-10-10T07:13:41.000Z: CentralSystem>ChargePoint  ClearChargingProfile
[2, "csms-4", "ClearChargingProfile", {"chargingProfileCriteria": {"chargingProfilePurpose": "TxProfile"}}]
2026-10-10T07:13:42.000Z: ChargePoint>CentralSystem Heartbeat
[2, "x", "Heartbeat", {}]
2026-10-10T07:13:43.000Z: CentralSystem>ChargePoint  SetChargingProfile
[ truncated
"""


class OcppLogTest(unittest.TestCase):
    def test_pairs_requests_and_replies(self):
        events = ocpp_log.profile_events(LOG)
        self.assertEqual([e["message_id"] for e in events], ["csms-4", "csms-3", "csms-2"])
        self.assertIsNone(events[0]["status"])
        self.assertEqual(events[1]["status"], "Rejected")
        self.assertEqual(events[1]["status_info"]["reasonCode"], "InvalidSchedule")
        tx = ocpp_log.latest_tx_profile(events)
        self.assertEqual(tx["message_id"], "csms-2")
        self.assertEqual(tx["status"], "Accepted")
        self.assertEqual(tx["received"], "2026-10-10T07:13:33.909Z")
        self.assertEqual(tx["payload"]["chargingProfile"]["id"], 160601)

    def test_oversized_payload_withheld(self):
        big = {"chargingProfile": {"chargingProfilePurpose": "TxProfile", "pad": "x" * 9000}}
        text = "2026-10-10T00:00:00.000Z: CentralSystem>ChargePoint  SetChargingProfile\n" + \
            json.dumps([2, "b", "SetChargingProfile", big])
        event = ocpp_log.profile_events(text)[0]
        self.assertIsNone(event["payload"])
        self.assertGreater(event["payload_bytes"], 8192)

    def test_rotated_files_read_oldest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "libocpp_201.log.1").write_text("old\n")
            (d / "libocpp_201.log").write_text("new\n")
            import os
            os.utime(d / "libocpp_201.log.1", (1, 1))
            self.assertEqual(ocpp_log.read_logs(d).split(), ["old", "new"])


class LogFilterTest(unittest.TestCase):
    def test_drops_schedule_noise_only(self):
        import app
        lines = [
            "2026-10-10 07:27:41.098538 [INFO] ocpp:OCPP201   : {",
            '    "chargingRateUnit": "W",',
            "}",
            "2026-10-10 07:27:41.099454 [INFO] api:API        : Received OCPP charging schedule update: {}",
            "2026-10-10 07:27:42.000000 [INFO] ocpp:OCPP201   : OCPP client successfully connected to server with version: ocpp2.1",
            "2026-10-10 07:27:43.000000 [ERRO] evse_manager_1_: fault",
            "continuation of a kept message",
            "libgcov profiling error:/tmp/gcov/x.gcda:overwriting an existing profile",
            "2026-10-10 07:40:16.797956 [INFO] ocpp:OCPP201   : About to publish composite charging schedules: ",
        ]
        log_filter = app.LogFilter()
        kept = [line for line in lines if log_filter.keep(line)]
        self.assertEqual(kept, lines[4:7])


class FakeBus:
    def __init__(self):
        self.sent = []
        self.last_command = None

    def snapshot(self):
        return {"session_info": {"value": {"state": "Unplugged"}, "age_s": 1.0}}

    def send(self, name, state):
        self.sent.append((name, state.get("max_current_a")))
        return True


class UiServerTest(unittest.TestCase):
    def setUp(self):
        import ui_server
        from http.server import ThreadingHTTPServer
        self.tmp = tempfile.TemporaryDirectory()
        run = Path(self.tmp.name)
        (run / "state.json").write_text(json.dumps({"max_current_a": 20, "phases": 1}))
        ui_server.RUN = run
        ui_server.LOGS = run / "logs"
        self.bus = FakeBus()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.make_handler(self.bus))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ui = ui_server

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, method="GET", headers=None, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}{path}",
                                     method=method, headers=headers or {}, data=body)
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            result = error.code, error.read()
            error.close()
            return result

    def test_static_and_status(self):
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/app.js")[0], 200)
        self.assertEqual(self.request("/../configure.py")[0], 404)
        self.assertEqual(self.request("/configure.py")[0], 404)
        code, body = self.request("/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["evse"]["session_info"]["value"]["state"], "Unplugged")
        code, body = self.request("/api/profiles")
        self.assertEqual(code, 200)
        self.assertIsNone(json.loads(body)["latest_tx_profile"])

    def test_commands_need_header_and_no_body(self):
        self.assertEqual(self.request("/api/ev/plugin", "POST")[0], 403)
        self.assertEqual(self.request("/api/ev/plugin", "POST", {"X-HA-EVerest": "1"}, b"x")[0], 400)
        self.assertEqual(self.request("/api/ev/launch", "POST", {"X-HA-EVerest": "1"})[0], 404)
        self.assertEqual(self.request("/api/ev/plugin", "POST", {"X-HA-EVerest": "1"})[0], 200)
        self.assertEqual(self.bus.sent, [("plugin", 20)])

    def test_command_strings(self):
        commands = self.ui.ev_commands({"max_current_a": 16, "phases": 3})
        self.assertEqual(commands["unplug"], ("modify_charging_session", "unplug"))
        self.assertIn("draw_power_regulated 16,3", commands["plugin"][1])
        self.assertTrue(commands["pause"][1].startswith("pause"))


class PublishWorkflowTest(unittest.TestCase):
    """Publication stays an explicit, gated, non-overwriting operator action."""

    def setUp(self):
        workflows = ROOT.parent / ".github/workflows"
        self.publish = (workflows / "everest-publish.yml").read_text()
        self.ci = (workflows / "everest.yml").read_text()

    def test_image_name_matches_workflow(self):
        self.assertIn("image: ghcr.io/purcell-lab/{arch}-everest-simulator", CONFIG_TEXT)
        self.assertIn('IMAGE=ghcr.io/purcell-lab/${{ matrix.arch }}-everest-simulator', self.publish)

    def test_only_tags_trigger_publication(self):
        trigger = self.publish.split("\non:", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn('"everest_simulator-v*"', trigger)
        for forbidden in ("pull_request", "branches", "workflow_dispatch", "schedule"):
            self.assertNotIn(forbidden, trigger)
        self.assertNotIn("packages: write", self.ci)

    def test_gate_before_push_and_no_overwrite_or_latest(self):
        order = [self.publish.index(step) for step in (
            "Tag must match the App version", "Refuse to overwrite a published version",
            "ci_image_checks.sh", 'docker push "$IMAGE:$VERSION"')]
        self.assertEqual(order, sorted(order))
        self.assertEqual(self.publish.count("docker push"), 1)
        self.assertNotIn(":latest", self.publish)
        self.assertIn("ci_image_checks.sh", self.ci)

    def test_merge_gate_checks_public_pull(self):
        self.assertIn("published-image:", self.ci)
        gate = self.ci.split("published-image:", 1)[1]
        self.assertIn("docker manifest inspect", gate)
        self.assertNotIn("docker login", gate)


if __name__ == "__main__":
    unittest.main()
