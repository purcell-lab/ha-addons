"""Unit tests for option validation, identity binding, generated EVerest and
device-model configuration, the test PKI, the private ISO 15118 link and
firewall, log parsing, log filtering and the UI service. No EVerest binaries
are needed (the PKI test needs openssl)."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "rootfs/opt/ha-everest"
sys.path.insert(0, str(APP))
import configure  # noqa: E402
import netguard  # noqa: E402
import ocpp_log  # noqa: E402
import pki  # noqa: E402

CONFIG_TEXT = (ROOT / "config.yaml").read_text()
DOCKERFILE = (ROOT / "Dockerfile").read_text()
GOOD = {"csms_url": "ws://192.0.2.10:9300/ocpp", "charge_point_id": "SIM-EV-EVEREST-V2G-01",
        "ocpp_version": "2.1", "max_power_kw": 11, "acknowledge_test_isolation": True}


def pricing_docs():
    """TariffCostCtrlr and CustomizationCtrlr shaped as in libocpp v0.30.3:
    Available[*] ReadOnly without a value, Enabled[Cost] false, Currency EUR."""
    def prop(name, instance=None, mutability="ReadWrite", **value):
        attribute = {"type": "Actual", "mutability": mutability}
        attribute.update(value)
        entry = {"variable_name": name, "attributes": [attribute]}
        if instance:
            entry["instance"] = instance
        return entry
    tariff = {"name": "TariffCostCtrlr", "properties": {
        "TariffCostCtrlrAvailableTariff": prop("Available", "Tariff", "ReadOnly"),
        "TariffCostCtrlrAvailableCost": prop("Available", "Cost", "ReadOnly"),
        "TariffCostCtrlrCurrency": prop("Currency", value="EUR"),
        "TariffCostCtrlrEnabledTariff": prop("Enabled", "Tariff"),
        "TariffCostCtrlrEnabledCost": prop("Enabled", "Cost", value=False),
        "TariffFallbackMessage": prop("TariffFallbackMessage", value=""),
        "TotalCostFallbackMessage": prop("TotalCostFallbackMessage", value=""),
        "NumberOfDecimalsForCostValues": prop("NumberOfDecimalsForCostValues"),
    }}
    custom = {"name": "CustomizationCtrlr", "properties": {
        "CustomImplementationEnabled": prop("CustomImplementationEnabled"),
        "CustomImplementationCaliforniaPricingEnabled": prop(
            "CustomImplementationEnabled", "org.openchargealliance.costmsg"),
        "CustomImplementationMultiLanguageEnabled": prop(
            "CustomImplementationEnabled", "org.openchargealliance.multilanguage"),
    }}
    return {"TariffCostCtrlr": tariff, "CustomizationCtrlr": custom}


def component_fixture(directory):
    """Minimal standardized device-model files with the properties we edit."""
    def doc(*props):
        return {"properties": {p: {"attributes": [{"type": "Actual", "value": None}]} for p in props}}
    std = directory / "standardized"
    std.mkdir(parents=True)
    # As in libocpp for EVerest 2026.10.0-rc1: InternalCtrlr has no
    # ChargePointId (SecurityCtrlr Identity is the station identity).
    files = {
        "InternalCtrlr": doc("NetworkConnectionProfiles", "SupportedOcppVersions",
                             "ChargePointVendor", "ChargePointModel", "ChargeBoxSerialNumber",
                             "LogMessagesFormat", "LogRotation", "LogRotationMaximumFileSize",
                             "LogRotationMaximumFileCount", "UseSslDefaultVerifyPaths",
                             "VerifyCsmsCommonName", "VerifyCsmsAllowWildcards"),
        "SecurityCtrlr": doc("SecurityCtrlrIdentity", "BasicAuthPassword", "SecurityProfile"),
        "SmartChargingCtrlr": doc("CompositeScheduleDefaultLimitAmps", "CompositeScheduleDefaultLimitWatts",
                                  "CompositeScheduleDefaultNumberPhases"),
        "SampledDataCtrlr": doc("SampledDataTxUpdatedInterval",
                               "SampledDataTxStartedMeasurands",
                               "SampledDataTxUpdatedMeasurands",
                               "SampledDataTxEndedMeasurands"),
        "OCPPCommCtrlr": doc("HeartbeatInterval"),
        "ISO15118Ctrlr": doc("PnCEnabled"),
        "ChargingStation": doc("ChargingStationSupplyPhases"),
    }
    for event in ("Started", "Updated", "Ended"):
        files["SampledDataCtrlr"]["properties"]["SampledDataTx" + event + "Measurands"]["attributes"][0]["value"] = "Energy.Active.Import.Register,Current.Import,Voltage"
    files.update(pricing_docs())
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
                     "charge_point_id: SIM-EV-EVEREST-V2G-01", "ocpp_version: list(2.1|2.0.1)",
                     "charge_point_id: match(^SIM-EV-[A-Za-z0-9_-]{1,36}$)",
                     "max_power_kw: int(3,25)", "slug: everest_v2g_simulator"):
            self.assertIn(line, CONFIG_TEXT)
        for forbidden in ("ports:", "host_network", "full_access", "devices:", "SYS_ADMIN",
                          "NET_RAW", "hassio_api", "hassio_role", "docker_api", "auth_api"):
            self.assertNotIn(forbidden, CONFIG_TEXT)
        # One mapped folder: /ssl, read-only, for csms_ca_certificate.
        self.assertEqual(CONFIG_TEXT.count("map:"), 1)
        self.assertIn("map:\n  - type: ssl\n    read_only: true\noptions:", CONFIG_TEXT)
        self.assertIn('  csms_ca_certificate: ""', CONFIG_TEXT)
        # Core API access only for the opt-in, outbound-only control bridge.
        self.assertIn("homeassistant_api: true", CONFIG_TEXT)
        self.assertIn("  ha_control: false", CONFIG_TEXT)
        self.assertIn("  ha_control: bool", CONFIG_TEXT)

    def test_only_net_admin(self):
        lines = CONFIG_TEXT.splitlines()
        index = lines.index("privileged:")
        self.assertEqual(lines[index + 1].strip(), "- NET_ADMIN")
        self.assertFalse(lines[index + 2].startswith("  -"))
        self.assertEqual(CONFIG_TEXT.count("privileged:"), 1)

    def test_no_keys_in_image(self):
        self.assertNotIn("certs", " ".join(l for l in DOCKERFILE.splitlines()
                                           if l.startswith(("COPY", "ADD"))))
        self.assertIn("--require-hashes", DOCKERFILE)

    def test_slim_java_runtime(self):
        final = DOCKERFILE.split("FROM ${DEBIAN_IMAGE}\n")[-1]
        self.assertNotIn("openjdk", final)
        self.assertIn("COPY --from=jre /stage/ /", final)
        self.assertIn("jlink --add-modules", DOCKERFILE)
        self.assertIn("-Xmx128m", DOCKERFILE)


class ValidateTest(unittest.TestCase):
    def test_provisioned_credential_is_validated_but_not_returned(self):
        secret = "a" * 32
        settings = configure.validate(dict(GOOD, csms_basic_auth_password=secret))
        self.assertNotIn("csms_basic_auth_password", settings)
        self.assertNotIn(secret, json.dumps(settings))
        for bad in (None, False, 12, "short", "A" * 32, "a" * 31):
            with self.assertRaises(ValueError) as caught:
                configure.validate(dict(GOOD, csms_basic_auth_password=bad))
            if isinstance(bad, str):
                self.assertNotIn(bad, str(caught.exception))

    def test_provisioned_password_does_not_replace_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            original = configure.basic_auth_password(data)
            supplied = "a" * 32
            self.assertEqual(configure.basic_auth_password(data, supplied), supplied)
            self.assertEqual(configure.basic_auth_password(data), original)
            self.assertEqual((data / "basic-auth-password").read_text(), original)

    def test_defaults_are_disconnected_and_2_1(self):
        settings = configure.validate({})
        self.assertEqual(settings["csms_url"], "")
        self.assertEqual(settings["ocpp_version"], "2.1")
        self.assertEqual(configure.VERSIONS["2.1"], "ocpp2.1,ocpp2.0.1")
        self.assertEqual(configure.VERSIONS["2.0.1"], "ocpp2.0.1")

    def test_power_rating(self):
        self.assertEqual(configure.validate({})["max_power_kw"], 25)
        rating = configure.ratings(configure.validate(dict(GOOD, max_power_kw=7)))
        self.assertEqual(rating, {"watts": 7000, "phase_amps": 31, "dc_amps": 19})
        # 25 kW: 109 A per phase is also the simulated board's limit
        # (YetiSimulator caps_max_current_A), and 66 A DC at 380 V is the
        # EV's discharge limit (patch_josev.py).
        rating = configure.ratings({"max_power_kw": 25})
        self.assertEqual(rating, {"watts": 25000, "phase_amps": 109, "dc_amps": 66})
        # One phase must carry the full rating (see configure.ratings).
        for kw in range(3, configure.MAX_POWER_KW + 1):
            rating = configure.ratings({"max_power_kw": kw})
            self.assertGreaterEqual(rating["phase_amps"] * configure.GRID_VOLTAGE, rating["watts"])

    def test_rejections(self):
        bad = [
            {"charge_point_id": "REAL-CHARGER"}, {"charge_point_id": "SIM-EV-"},
            {"ocpp_version": "1.6"}, {"ocpp_version": 2.1}, {"max_power_kw": 2},
            {"max_power_kw": 26}, {"max_power_kw": True}, {"max_power_kw": "11"},
            {"max_power_kw": 7.5},
            {"csms_url": "http://host:80"}, {"csms_url": "https://host"},
            {"csms_url": "ws://host"}, {"csms_url": "ws://user:pw@host:80"},
            {"csms_url": "ws://host:80/?a=b"}, {"csms_url": "ws://host:80/%2e"},
            {"csms_url": "ws://127.0.0.1:9"}, {"csms_url": "ws://h:80/" + "x" * 200},
            {"csms_url": "ws://host:80/SIM-EV-EVEREST-V2G-01"},
            {"acknowledge_test_isolation": False},
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                configure.validate(dict(GOOD, **change))

    def test_security_profile_follows_scheme(self):
        settings = configure.validate(GOOD)
        self.assertEqual((settings["security_profile"], settings["csms_ca_certificate"]), (1, ""))
        self.assertEqual(configure.validate({})["security_profile"], 1)
        for url in ("wss://csms.example.org", "wss://csms.example.org/", "wss://csms.example.org/ocpp",
                    "wss://csms.example.org:443/ocpp/", "wss://192.0.2.10:8443", "wss://[2001:db8::1]/ocpp"):
            with self.subTest(url=url):
                settings = configure.validate(dict(GOOD, csms_url=url))
                self.assertEqual(settings["security_profile"], 2)
                self.assertEqual(settings["csms_url"], url.rstrip("/"))

    def test_wss_keeps_every_other_url_rule(self):
        for url in ("wss://", "wss:///ocpp", "wss://host:", "wss://host:0", "wss://host:65536",
                    "wss://user:pw@host", "wss://host/?a=b", "wss://host/#x", "wss://host/%2e",
                    "wss://host/a b", "wss://host\\x", "WSS://host", "Ws://host:80",
                    "wss://localhost:9", "wss://host/ocpp/SIM-EV-EVEREST-V2G-01",
                    "wss://host/SIM-EV-EVEREST-V2G-01/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                configure.validate(dict(GOOD, csms_url=url))
        with self.assertRaises(ValueError):
            configure.validate(dict(GOOD, csms_url="wss://host", acknowledge_test_isolation=False))

    def test_csms_ca_option_rules(self):
        wss = dict(GOOD, csms_url="wss://csms.example.org/ocpp")
        for path in ("/ssl/ca.pem", "/ssl/test-csms/root_ca.crt", "/ssl/a.b.pem"):
            self.assertEqual(configure.validate(dict(wss, csms_ca_certificate=path))["csms_ca_certificate"], path)
        for bad in ("ca.pem", "/data/ca.pem", "/ssl/", "/ssl/ca.key", "/ssl/ca.pem.txt", "/ssl/../etc/ca.pem",
                    "/ssl/x/../ca.pem", "/ssl/.hidden.pem", "/ssl//ca.pem", "/ssl/c a.pem", "/ssl/ca%2e.pem",
                    "/ssl/" + "x" * 200 + ".pem", None, 1, True):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                configure.validate(dict(wss, csms_ca_certificate=bad))
        # Only meaningful with TLS: refused with ws://, ignored while disconnected.
        with self.assertRaises(ValueError):
            configure.validate(dict(GOOD, csms_ca_certificate="/ssl/ca.pem"))
        settings = configure.validate({"csms_url": "", "csms_ca_certificate": "/ssl/ca.pem"})
        self.assertEqual(settings["csms_ca_certificate"], "")

    def test_ha_control_is_boolean(self):
        self.assertFalse(configure.validate({})["ha_control"])
        self.assertTrue(configure.validate({"ha_control": True})["ha_control"])
        for bad in ("true", 1, None):
            with self.assertRaises(ValueError):
                configure.validate({"ha_control": bad})

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

    def test_disconnected_only_state_is_archived_on_first_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            settings = configure.validate(GOOD)
            configure.bind(data, dict(settings, csms_url=""))  # first start, disconnected
            self.assertTrue((data / configure.DISCONNECTED_ONLY).exists())
            (data / "everest/ocpp201").mkdir(parents=True)
            (data / "everest/ocpp201/cp.db").write_text("created while disconnected")
            configure.bind(data, dict(settings, csms_url=""))  # later disconnected start
            archived = configure.bind(data, settings)
            self.assertEqual((archived / "everest/ocpp201/cp.db").read_text(), "created while disconnected")
            self.assertFalse((data / "everest").exists())
            self.assertFalse((data / configure.DISCONNECTED_ONLY).exists())
            self.assertTrue((data / "test-identity.json").exists())

    def test_marker_never_written_for_bound_or_unmarked_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            settings = configure.validate(GOOD)
            configure.bind(data, settings)
            configure.bind(data, dict(settings, csms_url=""))  # disconnect after binding
            self.assertFalse((data / configure.DISCONNECTED_ONLY).exists())
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "everest/ocpp201").mkdir(parents=True)
            (data / "everest/ocpp201/cp.db").write_text("x")
            configure.bind(data, dict(configure.validate(GOOD), csms_url=""))
            self.assertFalse((data / configure.DISCONNECTED_ONLY).exists())
            with self.assertRaisesRegex(ValueError, "unbound"):
                configure.bind(data, configure.validate(GOOD))

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
        self.assertEqual(value(target, "SecurityCtrlr", "SecurityCtrlrIdentity"), "SIM-EV-EVEREST-V2G-01")
        self.assertEqual(value(target, "SmartChargingCtrlr", "CompositeScheduleDefaultLimitWatts"), 11000)
        self.assertEqual(value(target, "SmartChargingCtrlr", "CompositeScheduleDefaultNumberPhases"), 3)
        # Regression: a supply-phases override made libocpp ignore all profiles.
        self.assertIsNone(value(target, "ChargingStation", "ChargingStationSupplyPhases"))

    def test_transaction_sample_interval_option(self):
        _, target = self.build(GOOD)
        self.assertEqual(value(target, "SampledDataCtrlr", "SampledDataTxUpdatedInterval"), 5)
        _, target = self.build(dict(GOOD, tx_sample_interval_s=1))
        self.assertEqual(value(target, "SampledDataCtrlr", "SampledDataTxUpdatedInterval"), 1)
        for bad in (0, 61, True, "5"):
            with self.assertRaises(ValueError):
                configure.validate(dict(GOOD, tx_sample_interval_s=bad))

    def test_both_energy_registers_requested_for_whole_transaction(self):
        _, target = self.build(GOOD)
        for event in ("Started", "Updated", "Ended"):
            members = value(target, "SampledDataCtrlr",
                            "SampledDataTx" + event + "Measurands").split(",")
            self.assertEqual(members.count("Energy.Active.Import.Register"), 1)
            self.assertEqual(members.count("Energy.Active.Export.Register"), 1)
            self.assertIn("Power.Active.Import", members)
            self.assertIn("Current.Import", members)
            self.assertIn("Voltage", members)

    def test_ocpp_string_limits(self):
        # libocpp aborts on over-length CiString values (ChargePointModel <= 20).
        _, target = self.build(dict(GOOD, charge_point_id="SIM-EV-" + "x" * 36))
        self.assertLessEqual(len(value(target, "InternalCtrlr", "ChargePointModel")), 20)
        self.assertLessEqual(len(value(target, "InternalCtrlr", "ChargePointVendor")), 50)
        self.assertLessEqual(len(value(target, "InternalCtrlr", "ChargeBoxSerialNumber")), 25)

    def test_no_plug_and_charge(self):
        # OCPPmulti pushes PnCEnabled into EvseManager at start, overriding
        # payment_enable_contract, so both are off.
        _, target = self.build(GOOD)
        self.assertIs(value(target, "ISO15118Ctrlr", "PnCEnabled"), False)

    def test_pinned_2_0_1(self):
        _, target = self.build(dict(GOOD, ocpp_version="2.0.1"))
        self.assertEqual(value(target, "InternalCtrlr", "SupportedOcppVersions"), "ocpp2.0.1")

    def test_power_rating_reported_per_station(self):
        # EVerest builds EVSE 1 itself (board maxLimit, Actual only), so the
        # rating goes on ChargingStation Power: MaxSet and MinSet are stored
        # per station by CitrineOS.
        for kw in (3, 11, 25):
            _, target = self.build(dict(GOOD, max_power_kw=kw))
            doc = json.loads((target / "standardized/ChargingStation.json").read_text())
            power = doc["properties"]["ChargingStationPower"]
            self.assertEqual(power["variable_name"], "Power")
            self.assertNotIn("instance", power)
            self.assertEqual(power["characteristics"], {"unit": "W", "dataType": "decimal",
                             "minLimit": -kw * 1000, "maxLimit": kw * 1000, "supportsMonitoring": False})
            self.assertEqual({a["type"]: (a["value"], a["mutability"]) for a in power["attributes"]},
                             {"MaxSet": (kw * 1000, "ReadOnly"), "MinSet": (-kw * 1000, "ReadOnly")})
            # The upstream properties stay as they are.
            self.assertIsNone(value(target, "ChargingStation", "ChargingStationSupplyPhases"))
        self.assertFalse((target / "custom").exists())

    def test_power_rating_refuses_an_upstream_power_variable(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        source = component_fixture(Path(tmp.name) / "source")
        path = source / "standardized/ChargingStation.json"
        doc = json.loads(path.read_text())
        doc["properties"]["ChargingStationPower"] = {"attributes": []}
        path.write_text(json.dumps(doc))
        with self.assertRaises(ValueError):
            configure.component_config(source, Path(tmp.name) / "target", configure.validate(GOOD), "a" * 32)

    def test_no_ev_charging_needs_wiring(self):
        # Deliberate (DOCS.md, EV charging needs): CitrineOS v2.0.1 rejects
        # DC_BPT NotifyEVChargingNeeds and libocpp then stops the OCPP 2.1
        # transaction. Connecting the extensions would also need an EVSE mapping.
        active = configure.everest_config(configure.validate(GOOD), Path("/data"), "b" * 24)["active_modules"]
        self.assertNotIn("extensions_15118", active["ocpp"]["connections"])
        self.assertNotIn("mapping", active["iso15118_charger"])
        for module in active.values():
            for targets in module.get("connections", {}).values():
                self.assertNotIn("extensions", {t["implementation_id"] for t in targets})

    def test_der_control_wiring(self):
        # OCPP 2.1 DER: OCPPmulti -> the App's grid_support provider (EVSE 1
        # mapping, DC capability) -> Evse15118D20's grid_support (relay).
        config = configure.everest_config(configure.validate(dict(GOOD, max_power_kw=7)), Path("/data"),
                                          "b" * 24, Path("/run/test"))
        active = config["active_modules"]
        ocpp = active["ocpp"]
        self.assertEqual(ocpp["connections"]["grid_support"],
                         [{"module_id": "grid_support", "implementation_id": "main"}])
        self.assertEqual(ocpp["config_module"]["GridSupportHeartbeatS"], 60)
        provider = active["grid_support"]
        self.assertEqual(provider["module"], "HaGridSupport")
        self.assertEqual(provider["mapping"], {"module": {"evse": 1}})
        self.assertEqual(provider["connections"]["relay"],
                         [{"module_id": "iso15118_charger", "implementation_id": "grid_support"}])
        # V2XChargingCtrlr SupportedOperationModes: EVerest 2026.10 builds
        # ChargingOnly,Idle, and libocpp rejected CentralSetpoint profiles
        # (InvalidOperationMode) until the App wrote the list.
        self.assertEqual(provider["connections"]["ocpp"],
                         [{"module_id": "ocpp", "implementation_id": "ocpp_generic"}])
        self.assertEqual(provider["config_module"]["v2x_operation_modes"], "Idle,ChargingOnly,CentralSetpoint")
        cfg = provider["config_module"]
        self.assertEqual(cfg["state_file"], "/run/test/der.json")
        self.assertEqual(cfg["rated_power_W"], 7000.0)
        self.assertEqual(cfg["nominal_voltage_V"], 380.0)
        types = cfg["supported_types"].split(",")
        self.assertEqual(len(types), 22)
        self.assertEqual(len(set(types)), 22)
        self.assertIn("LimitMaxDischarge", types)
        # Only OCPP 2.1 DERControlEnum names (libocpp ModesSupported valuesList).
        self.assertNotIn("ZeroCurrent", types)
        # The relay has no mapping of its own: OCPPmulti routes by the provider's.
        self.assertNotIn("mapping", active["iso15118_charger"])
        manifest = yaml.safe_load((ROOT / "rootfs/opt/everest/libexec/everest/modules/HaGridSupport/manifest.yaml")
                                  .read_text())
        self.assertEqual(manifest["provides"]["main"]["interface"], "grid_support")
        self.assertEqual(manifest["requires"]["relay"], {"interface": "grid_support", "min_connections": 0,
                                                         "max_connections": 1})
        self.assertEqual(manifest["requires"]["ocpp"], {"interface": "ocpp", "min_connections": 0,
                                                        "max_connections": 1})
        self.assertEqual(set(cfg), set(manifest["config"]))

    def test_disconnected_url_is_closed_loopback(self):
        _, target = self.build({"csms_url": ""})
        profile = json.loads(value(target, "InternalCtrlr", "NetworkConnectionProfiles"))[0]
        self.assertEqual(profile["connectionData"]["ocppCsmsUrl"], "ws://127.0.0.1:9")
        self.assertEqual(profile["connectionData"]["securityProfile"], 1)
        self.assertEqual(value(target, "SecurityCtrlr", "SecurityProfile"), 1)

    def test_wss_is_security_profile_2_with_verified_server(self):
        url = "wss://csms.example.org/ocpp"
        _, target = self.build(dict(GOOD, csms_url=url))
        profile = json.loads(value(target, "InternalCtrlr", "NetworkConnectionProfiles"))[0]
        self.assertEqual(profile["connectionData"]["ocppCsmsUrl"], url)
        self.assertEqual(profile["connectionData"]["securityProfile"], 2)
        # Both places: libocpp drops profiles below SecurityCtrlr.SecurityProfile.
        self.assertEqual(value(target, "SecurityCtrlr", "SecurityProfile"), 2)
        self.assertEqual(value(target, "SecurityCtrlr", "BasicAuthPassword"), "a" * 32)
        # System CA store, hostname checked, whole-label wildcards allowed.
        self.assertIs(value(target, "InternalCtrlr", "UseSslDefaultVerifyPaths"), True)
        self.assertIs(value(target, "InternalCtrlr", "VerifyCsmsCommonName"), True)
        self.assertIs(value(target, "InternalCtrlr", "VerifyCsmsAllowWildcards"), True)
        _, target = self.build(GOOD)
        self.assertEqual(value(target, "SecurityCtrlr", "SecurityProfile"), 1)
        self.assertEqual(value(target, "SecurityCtrlr", "BasicAuthPassword"), "a" * 32)

    def test_csms_ca_replaces_the_system_store(self):
        options = dict(GOOD, csms_url="wss://csms.test:8443", csms_ca_certificate="/ssl/csms/ca.pem")
        _, target = self.build(options)
        self.assertIs(value(target, "InternalCtrlr", "UseSslDefaultVerifyPaths"), False)
        self.assertIs(value(target, "InternalCtrlr", "VerifyCsmsCommonName"), True)
        self.assertEqual(value(target, "SecurityCtrlr", "SecurityProfile"), 2)
        security = configure.everest_config(configure.validate(options), Path("/data"),
                                            "b" * 24)["active_modules"]["evse_security"]["config_module"]
        self.assertEqual(security, {"private_key_password": "b" * 24,
                                    "csms_ca_bundle": "/data/csms-ca/CSMS_ROOT_CA.pem"})
        # Without the option EvseSecurity keeps its default bundle.
        security = configure.everest_config(configure.validate(dict(options, csms_ca_certificate="")),
                                            Path("/data"), "b" * 24)["active_modules"]["evse_security"]
        self.assertEqual(security["config_module"], {"private_key_password": "b" * 24})

    def test_ev_charging_needs_is_opt_in(self):
        # NotifyEVChargingNeeds: a Rejected reply stops the OCPP 2.1
        # transaction, so the ISO 15118 extensions are wired only on request.
        modules = configure.everest_config(configure.validate(GOOD), Path("/data"), "b" * 24)["active_modules"]
        self.assertNotIn("extensions_15118", modules["ocpp"]["connections"])
        self.assertNotIn("mapping", modules["iso15118_charger"])
        settings = configure.validate(dict(GOOD, ev_charging_needs=True))
        modules = configure.everest_config(settings, Path("/data"), "b" * 24)["active_modules"]
        self.assertEqual(modules["ocpp"]["connections"]["extensions_15118"],
                         [{"module_id": "iso15118_charger", "implementation_id": "extensions"}])
        self.assertEqual(modules["iso15118_charger"]["mapping"], {"module": {"evse": 1}})
        with self.assertRaises(ValueError):
            configure.validate(dict(GOOD, ev_charging_needs="yes"))

    def test_everest_config_scope(self):
        settings = configure.validate(dict(GOOD, max_power_kw=7))
        config = configure.everest_config(settings, Path("/data"), "b" * 24)
        self.assertEqual(config["settings"]["mqtt_broker_host"], "127.0.0.1")
        self.assertFalse(config["settings"]["telemetry_enabled"])
        active = config["active_modules"]
        modules = {m["module"] for m in active.values()}
        for needed in ("Evse15118D20", "PyEvJosev", "DCSupplySimulator", "IMDSimulator", "SlacSimulator"):
            self.assertIn(needed, modules)
        self.assertNotIn("EvseV2G", modules)
        # Every EVerest module comes from the runtime, except the App's own.
        self.assertLessEqual(modules - {"HaGridSupport"},
                             set(DOCKERFILE.split("MODULES=")[1].split('"')[1].split()))
        self.assertTrue((ROOT / "rootfs/opt/everest/libexec/everest/modules/HaGridSupport/manifest.yaml").is_file())
        evse = active["evse_manager_1"]["config_module"]
        self.assertEqual(evse["charge_mode"], "DC")
        # EvseManager 2026.10 has no own current limits; the board's apply.
        self.assertNotIn("max_current_import_A", evse)
        self.assertNotIn("max_current_export_A", evse)
        self.assertEqual(active["yeti_driver_1"]["config_module"]["caps_max_current_A"], 31)
        # A 0 W setpoint must not end the ISO 15118 session (EvseManager
        # 2026.10 stopped it after 5 s, and the next steps were missed).
        self.assertEqual(evse["hlc_charge_loop_without_energy_timeout_s"], 86400)
        # EIM only: with Contract offered the EV chose PnC and the 2026.10
        # charger ended the session (CitrineOS native trial).
        self.assertFalse(evse["payment_enable_contract"])
        self.assertIn("iso_wait_for_stop 86400", configure.ev_session())
        self.assertFalse(evse["session_logging"])
        supply = next(m for m in active.values() if m["module"] == "DCSupplySimulator")
        self.assertTrue(supply["config_implementation"]["main"]["bidirectional"])
        self.assertEqual(supply["config_implementation"]["main"]["max_power"], 7000)
        # A 0 W target needs a 0 W supply minimum (VALIDATION.md).
        self.assertEqual(supply["config_implementation"]["main"]["min_current"], 0.0)
        # The supply's own 200 V minimum set the voltage while discharging.
        self.assertEqual(supply["config_implementation"]["main"]["min_voltage"], 380.0)
        ev = next(m for m in active.values() if m["module"] == "EvManager")["config_module"]
        self.assertEqual(ev["dc_target_voltage"], 380)
        # Issue #70: charging stays at the EV's 900 V maximum (EvManager
        # default). Equal charge and discharge voltages left power targets
        # unapplied (UPSTREAM.md, upstream behaviour 12).
        self.assertNotIn("dc_max_voltage_limit", ev)
        d20 = next(m for m in active.values() if m["module"] == "Evse15118D20")
        self.assertEqual(d20["config_module"]["device"], netguard.SECC_LINK)
        josev = next(m for m in active.values() if m["module"] == "PyEvJosev")["config_module"]
        self.assertEqual(josev["device"], netguard.EVCC_LINK)
        # Josev picks the first listed service: DC_BPT first or no export.
        self.assertEqual(josev["supported_d20_energy_services"], "DC_BPT,DC")
        self.assertTrue(josev["tls_active"])
        self.assertTrue(josev["enable_tls_1_3"])
        security = next(m for m in active.values() if m["module"] == "EvseSecurity")["config_module"]
        self.assertEqual(security["private_key_password"], "b" * 24)
        manager = next(m for m in active.values() if m["module"] == "EnergyManager")["config_module"]
        self.assertEqual(manager["switch_3ph1ph_while_charging_mode"], "Both")
        ocpp = next(m for m in active.values() if m["module"] == "OCPPmulti")
        self.assertNotIn("OCPP201", modules)
        self.assertEqual(ocpp["config_module"]["Mode"], "Only2")
        # The core database keeps its 0.1.x path, so an upgrade keeps it.
        self.assertEqual(ocpp["config_module"]["CoreDatabasePath"], "/data/everest/ocpp201")
        sinks = [c["module_id"] for c in ocpp["connections"]["evse_energy_sink"]]
        self.assertEqual(sinks, ["evse_manager_1_ocpp_sink"])
        # Issue #28: no EVSE 0 sink (it capped targets at a third); every
        # sink maps to EVSE 1, and the EVSE 0 warning is filtered (LogFilter).
        self.assertEqual(active["evse_manager_1_ocpp_sink"]["mapping"], {"module": {"evse": 1}})
        self.assertEqual(ocpp["config_module"]["CompositeScheduleIntervalS"], 10)
        for path in json.dumps(config).split('"'):
            # /run/ha-everest: the DER Status-page copy, rebuilt every start.
            if path.startswith("/") and "everest" in path and not path.startswith(
                    ("/data", "/opt/everest", "/run/ha-everest/")):
                self.fail(f"state outside /data: {path}")

    def test_ev_session_is_dc_bidirectional_ready(self):
        session = configure.ev_session()
        self.assertIn("iso_start_v2g_session DC", session)
        self.assertTrue(session.endswith("unplug"))


def openssl_cert(directory, name, *extra):
    """Self-signed P-256 certificate (and key) for the CSMS CA tests."""
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                    "-nodes", "-subj", f"/CN={name}", "-keyout", str(directory / f"{name}.key"),
                    "-out", str(directory / f"{name}.pem"), *extra],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return directory / f"{name}.pem"


class CsmsCaTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ssl = Path(tmp.name) / "ssl"
        self.data = Path(tmp.name) / "data"
        (self.ssl / "csms").mkdir(parents=True)
        self.data.mkdir()
        self.ca = openssl_cert(self.ssl / "csms", "ca", "-days", "30")

    def settings(self, path="/ssl/csms/ca.pem", url="wss://csms.test"):
        return configure.validate(dict(GOOD, csms_url=url, csms_ca_certificate=path))

    def test_copies_the_ca_into_data(self):
        path = configure.install_csms_ca(self.data, self.settings(), self.ssl)
        self.assertEqual(path, self.data / "csms-ca" / "CSMS_ROOT_CA.pem")
        self.assertEqual(path.read_text(), self.ca.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        # Cleared option (or ws://, or disconnected): no stale trust anchor.
        self.assertIsNone(configure.install_csms_ca(self.data, configure.validate(GOOD), self.ssl))
        self.assertFalse((self.data / "csms-ca").exists())

    def test_refuses_unusable_files(self):
        (self.ssl / "with-key.pem").write_text(self.ca.read_text() + (self.ssl / "csms/ca.key").read_text())
        (self.ssl / "junk.pem").write_text("not a certificate\n")
        (self.ssl / "big.pem").write_text(self.ca.read_text() + "#" * configure.CSMS_CA_MAX_BYTES)
        outside = self.ssl.parent / "outside.pem"
        outside.write_text(self.ca.read_text())
        (self.ssl / "link.pem").symlink_to(outside)
        (self.ssl / "dir.pem").mkdir()
        for name in ("missing.pem", "with-key.pem", "junk.pem", "big.pem", "link.pem", "dir.pem"):
            with self.subTest(name=name), self.assertRaises(ValueError) as caught:
                configure.install_csms_ca(self.data, self.settings("/ssl/" + name), self.ssl)
            self.assertNotIn("BEGIN", str(caught.exception))
        self.assertFalse((self.data / "csms-ca").exists())

    def test_leaf_signed_by_another_ca_is_refused(self):
        # Not self-signed: libevse-security would not treat it as installed.
        key = self.ssl / "csms" / "ca.key"
        subprocess.run(["openssl", "req", "-new", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-subj", "/CN=leaf", "-keyout", str(self.ssl / "leaf.key"),
                        "-out", str(self.ssl / "leaf.csr")], check=True, stderr=subprocess.DEVNULL)
        subprocess.run(["openssl", "x509", "-req", "-in", str(self.ssl / "leaf.csr"), "-CA", str(self.ca),
                        "-CAkey", str(key), "-days", "5", "-out", str(self.ssl / "leaf.pem")],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self.assertRaises(ValueError):
            configure.install_csms_ca(self.data, self.settings("/ssl/leaf.pem"), self.ssl)

    def test_configure_checks_the_ca_before_binding(self):
        source = component_fixture(self.data.parent / "source")
        options = dict(GOOD, csms_url="wss://csms.test", csms_ca_certificate="/ssl/missing.pem")
        with self.assertRaises(ValueError):
            configure.configure(self.data, options, source, pki_password="b" * 24, ssl_dir=self.ssl)
        self.assertFalse((self.data / "test-identity.json").exists())
        options["csms_ca_certificate"] = "/ssl/csms/ca.pem"
        settings, path = configure.configure(self.data, options, source, pki_password="b" * 24,
                                             ssl_dir=self.ssl)
        self.assertEqual(settings["security_profile"], 2)
        self.assertIn("csms_ca_bundle: " + str(self.data / "csms-ca" / "CSMS_ROOT_CA.pem"), path.read_text())
        self.assertNotIn("a" * 32, path.read_text())
        # ws:// to wss:// for the same host is a destination change.
        with self.assertRaises(ValueError):
            configure.configure(self.data, dict(options, csms_url="wss://csms.test:443"), source,
                                pki_password="b" * 24, ssl_dir=self.ssl)


FAKE_CERTS = r"""#!/bin/bash
# Test double for Josev create_certs.sh: two self-signed 60-day leaves.
set -e
while getopts "v:p:" o; do case $o in p) PW=$OPTARG;; v) ;; esac; done
d=iso15118_20/certs/client
mkdir -p $d/cso $d/vehicle
for leaf in cso/SECC_LEAF vehicle/VEHICLE_LEAF; do
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days ${DAYS:-60} \
    -subj /CN=test -keyout $d/$leaf.key -out $d/$leaf.pem 2>/dev/null
done
printf '%s' "$PW" > $d/cso/SECC_LEAF_PASSWORD.txt
"""


class PkiTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.script = self.root / "josev-pki"
        self.script.mkdir()
        (self.script / "create_certs.sh").write_text(FAKE_CERTS)

    def test_generate_once_then_reuse(self):
        data = self.root / "data"
        first, certs, made = pki.ensure(data, self.script)
        self.assertTrue(made)
        self.assertRegex(first, r"^[0-9a-f]{24}$")
        self.assertTrue(pki.valid(certs))
        again, _, made = pki.ensure(data, self.script)
        self.assertFalse(made)
        self.assertEqual(again, first)
        self.assertEqual(sorted(p.name for p in (data / "pki").iterdir()), ["certs"])

    def test_renews_when_close_to_expiry(self):
        data = self.root / "data"
        import os
        os.environ["DAYS"] = "3"
        try:
            first, certs, _ = pki.ensure(data, self.script)
        finally:
            del os.environ["DAYS"]
        self.assertFalse(pki.valid(certs))
        second, _, made = pki.ensure(data, self.script)
        self.assertTrue(made)
        self.assertNotEqual(first, second)

    def test_bad_password_file_is_invalid(self):
        _, certs, _ = pki.ensure(self.root / "data", self.script)
        (certs / pki.PASSWORD_FILE).write_text("short")
        self.assertFalse(pki.valid(certs))

    def test_link(self):
        _, certs, _ = pki.ensure(self.root / "data", self.script)
        prefix = self.root / "prefix"
        (prefix / "etc/everest/certs").mkdir(parents=True)
        pki.link(prefix, certs)
        pki.link(prefix, certs)
        self.assertEqual((prefix / "etc/everest/certs").resolve(), certs.resolve())


IF_INET6 = """fe80000000000000a8bbccfffe000001 05 40 20 80     v2g0
fe80000000000000a8bbccfffe000002 06 40 20 00     v2g1
fd000000000000000000000000000001 06 40 00 00     v2g1
00000000000000000000000000000001 01 80 10 80       lo
"""


class FakeRun:
    def __init__(self, fail=None, exists=False):
        self.calls, self.fail, self.exists = [], fail, exists

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs.get("input")))
        code = 0
        if command[:3] == ["ip", "link", "show"]:
            code = 0 if self.exists else 1
        elif self.fail and command[0] == self.fail:
            code = 1
        return type("Result", (), {"returncode": code, "stdout": "boom"})()


class NetguardTest(unittest.TestCase):
    def test_ruleset_drops_by_default(self):
        rules = netguard.ruleset()
        self.assertIn("policy drop;", rules)
        self.assertTrue(rules.startswith("add table inet ha_everest_v2g\ndelete table inet ha_everest_v2g\n"))
        self.assertIn("ip saddr 172.30.32.2 tcp dport 8099 counter accept", rules)
        self.assertIn('iifname { "v2g0", "v2g1" } counter accept', rules)
        inbound, outbound = rules.split("  chain output {")
        self.assertTrue(inbound.rstrip().endswith('counter comment "dropped by policy"\n  }'))
        self.assertIn("ct state established,related counter accept", rules)
        for open_port in ("15118", "50000", "dport 1883"):
            self.assertNotIn(open_port, inbound)
        # Outbound: only discovery off the private link is dropped.
        self.assertIn("policy accept;", outbound)
        self.assertIn('oifname != { "lo", "v2g0", "v2g1" } udp dport 15118 counter drop', outbound)
        self.assertEqual(outbound.count("drop"), 1)

    def test_link_local_skips_tentative_and_global(self):
        self.assertEqual(netguard.link_local("v2g0", IF_INET6), "fe80:0000:0000:0000:a8bb:ccff:fe00:0001")
        self.assertEqual(netguard.link_local("v2g1", IF_INET6), "fe80:0000:0000:0000:a8bb:ccff:fe00:0002")
        self.assertIsNone(netguard.link_local("lo", IF_INET6))
        self.assertIsNone(netguard.link_local("eth0", IF_INET6))
        tentative = IF_INET6.replace("20 80     v2g0", "20 40     v2g0")
        self.assertIsNone(netguard.link_local("v2g0", tentative))

    def test_setup_order_and_fail_closed(self):
        original = netguard.link_local
        netguard.link_local = lambda name, text=None: "fe80::1"
        try:
            run = FakeRun()
            netguard.setup(run=run, sleep=lambda s: None)
            commands = [c for c, _ in run.calls]
            self.assertEqual(commands[0], ["nft", "-f", "-"])
            self.assertEqual(run.calls[0][1], netguard.ruleset())
            self.assertIn(["ip", "link", "add", "v2g0", "type", "veth", "peer", "name", "v2g1"], commands)
            run = FakeRun(exists=True)
            netguard.setup(run=run, sleep=lambda s: None)
            self.assertNotIn("add", [c[2] for c, _ in run.calls if c[0] == "ip"])
            with self.assertRaisesRegex(RuntimeError, "firewall"):
                netguard.setup(run=FakeRun(fail="nft"), sleep=lambda s: None)
            with self.assertRaisesRegex(RuntimeError, "failed"):
                netguard.setup(run=FakeRun(fail="ip"), sleep=lambda s: None)
            netguard.link_local = lambda name, text=None: None
            with self.assertRaisesRegex(RuntimeError, "link-local"):
                netguard.setup(run=FakeRun(), timeout=0.05, sleep=lambda s: None)
        finally:
            netguard.link_local = original


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
        latest = ocpp_log.latest_profile(events)
        self.assertEqual(latest["message_id"], "csms-3")
        self.assertEqual(latest["payload"]["chargingProfile"]["chargingProfilePurpose"], "TxDefaultProfile")
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

    def test_oversized_priced_profile_shows_power_schedule(self):
        # A 48 h OpenADR price schedule (288 stacks) makes the profile about 13 KiB.
        stacks = [{"duration": 600, "priceRule": [{"energyFee": {"value": 969 + i, "exponent": -4},
                                                   "powerRangeStart": {"value": 0, "exponent": 0}}]}
                  for i in range(288)]
        periods = [{"startPeriod": 0, "limit": 4500, "dischargeLimit": 0, "setpoint": 4500,
                    "operationMode": "CentralSetpoint"}]
        profile = {"evseId": 1, "chargingProfile": {
            "id": 9001, "stackLevel": 1, "chargingProfilePurpose": "TxProfile", "chargingProfileKind": "Absolute",
            "transactionId": "tx-1", "chargingSchedule": [{
                "id": 9001, "chargingRateUnit": "W", "duration": 600, "chargingSchedulePeriod": periods,
                "absolutePriceSchedule": {"timeAnchor": "2026-10-19T04:30:00Z", "priceScheduleID": 1,
                                          "currency": "AUD", "language": "en",
                                          "priceAlgorithm": "urn:iso:std:iso:15118:-20:PriceAlgorithm:1-Power",
                                          "priceRuleStacks": stacks}}]}}
        text = "2026-10-19T04:27:51.436Z: CentralSystem>ChargePoint  SetChargingProfile\n" + \
            json.dumps([2, "big", "SetChargingProfile", profile])
        event = ocpp_log.profile_events(text)[0]
        self.assertGreater(event["payload_bytes"], 8192)
        self.assertEqual(event["omitted"], ["absolutePriceSchedule"])
        schedule = event["payload"]["chargingProfile"]["chargingSchedule"][0]
        self.assertNotIn("absolutePriceSchedule", schedule)
        self.assertEqual(schedule["chargingSchedulePeriod"], periods)
        self.assertEqual(ocpp_log.latest_tx_profile([event])["message_id"], "big")
        summary = ocpp_log.price_schedules(event)
        self.assertEqual(summary[0]["count"], 288)
        self.assertEqual(summary[0]["intervals"][0]["energy_fee"], 0.0969)
        self.assertEqual(summary[0]["intervals"][1]["start"], "2026-10-19T04:40:00Z")

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

    def test_ocpp_multi_module_name(self):
        # EVerest 2026.10 runs OCPPmulti: the same filters apply to its lines.
        import app
        lines = ["2026-10-25 07:27:41.098538 [INFO] ocpp:OCPPmulti  : {", '    "limit": 1', "}",
                 "2026-10-25 07:27:42.000000 [INFO] ocpp:OCPPmulti  : OCPP client successfully connected "
                 "to server with version: ocpp2.1"]
        log_filter = app.LogFilter()
        self.assertEqual([line for line in lines if log_filter.keep(line)], lines[3:])
        self.assertEqual(app.VERSION_LINE.search(lines[3]).group(1), "ocpp2.1")
        warning = ("2026-10-25 06:50:38.123456 [WARN] ocpp:OCPPmulti  : Can not apply external limits! "
                   "No evse energy sink configured for evse_id: 0")
        self.assertFalse(app.LogFilter().keep(warning))

    def test_drops_only_the_station_sink_warning(self):
        # Issue #28: logged every 10 s because EVSE 0 deliberately has no sink.
        import app
        warning = ("2026-10-17 06:50:38.123456 [WARN] ocpp:OCPP201   : Can not apply external limits! "
                   "No evse energy sink configured for evse_id: ")
        log_filter = app.LogFilter()
        self.assertFalse(log_filter.keep(warning + "0"))
        self.assertTrue(log_filter.keep(warning + "1"))
        self.assertTrue(log_filter.keep(warning + "01"))
        self.assertTrue(log_filter.keep("2026-10-17 06:50:39.000000 [WARN] api:API        : "
                                        "No evse energy sink configured for evse_id: 0"))


class PumpTest(unittest.TestCase):
    def run_pump(self, lines):
        import app
        import io
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(setattr, app, "RUN", app.RUN)
        app.RUN = Path(tmp.name)
        output = io.StringIO()
        stdout, sys.stdout = sys.stdout, output
        try:
            app.pump(io.StringIO("".join(line + "\n" for line in lines)))
        finally:
            sys.stdout = stdout
        return json.loads((app.RUN / "state.json").read_text()), output.getvalue()

    def test_ev_giving_up_is_recorded_once(self):
        # Issue #33: Josev logs the message and again at the end of its traceback.
        line = ("2026-10-11 21:50:52.000000 [ERRO] iso15118_car:   : EVCC tried to initiate a "
                "V2GCommunicationSession, but maximum number of SDP retry cycles (1) is now reached. "
                "Shutting down high-level communication.")
        state, output = self.run_pump([line, "Traceback (most recent call last):",
                                       "SDPFailedError: EVCC tried to initiate a V2GCommunicationSession, "
                                       "but maximum number of SDP retry cycles (1) is now reached."])
        self.assertEqual(state["ev_gave_up_count"], 1)
        self.assertGreater(state["ev_gave_up_at"], 0)
        self.assertIn("SDP retry cycles", state["ev_gave_up_line"])
        self.assertIn("maximum number of SDP retry cycles", output)  # still forwarded

    def test_sdp_drops_before_slac_are_counted(self):
        # The discovery self-test reads this count (diag.DLINK_NOT_READY).
        line = ("2026-10-25 05:58:01.000000 [INFO] iso15118_charge: Ignoring SDP request because dlink "
                "is not ready")
        state, output = self.run_pump([line, line])
        self.assertEqual(state["charger_sdp_dlink_ignored"], 2)
        self.assertIn("dlink is not ready", output)


class FakeBus:
    def __init__(self):
        self.sent = []
        self.last_command = None

    def snapshot(self):
        return {"session_info": {"value": {"state": "Unplugged"}, "age_s": 1.0}}

    def send(self, name, state):
        self.sent.append((name, state.get("max_power_kw")))
        return True


class UiServerTest(unittest.TestCase):
    def setUp(self):
        import ui_server
        from http.server import ThreadingHTTPServer
        self.tmp = tempfile.TemporaryDirectory()
        run = Path(self.tmp.name)
        (run / "state.json").write_text(json.dumps({"max_power_kw": 7}))
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
        self.assertEqual(self.request("/api/ev/pause", "POST", {"X-HA-EVerest": "1"})[0], 404)
        self.assertEqual(self.bus.sent, [("plugin", 7)])

    def test_plug_in_waits_for_selftest_lock(self):
        self.ui.SELFTEST_WAIT_S = 0.5
        held = self.ui.SelftestLock()
        self.assertTrue(held.__enter__())
        try:
            self.assertFalse(self.ui.SelftestLock().__enter__())  # second holder refused
            self.assertEqual(self.request("/api/ev/plugin", "POST", {"X-HA-EVerest": "1"})[0], 409)
            self.assertIsNone(self.ui.run_selftest("on request"))
        finally:
            held.__exit__(None, None, None)
        self.assertEqual(self.request("/api/ev/plugin", "POST", {"X-HA-EVerest": "1"})[0], 200)
        self.assertEqual(self.bus.sent, [("plugin", 7)])

    def test_selftest_needs_unplugged(self):
        self.bus.snapshot = lambda: {"session_info": {"value": {"state": "Charging"}, "age_s": 1.0}}
        code, body = self.request("/api/diag/selftest", "POST", {"X-HA-EVerest": "1"})
        self.assertEqual(code, 409)
        self.assertEqual(json.loads(body)["state"], "Charging")

    def test_command_strings(self):
        commands = self.ui.ev_commands({"max_power_kw": 11})
        self.assertEqual(set(commands), {"plugin", "stop", "unplug"})
        self.assertEqual(commands["plugin"], ("execute_charging_session", configure.ev_session()))
        self.assertTrue(commands["stop"][1].startswith("iso_stop_charging"))
        self.assertEqual(commands["unplug"], ("modify_charging_session", "unplug"))


class EvModelTest(unittest.TestCase):
    """The simulated EV's needs (ISO 15118-20 Dynamic mode) and battery."""

    def setUp(self):
        sys.path.insert(0, str(ROOT / "rootfs/opt/ha-everest"))
        import ev_model
        self.m = ev_model

    def test_validation(self):
        now = 1_800_000_000
        ok = self.m.validate_needs({"mode": "charge_by", "target_soc": 90, "ready_by": now + 3600}, now)
        self.assertEqual((ok["mode"], ok["target_soc"], ok["ready_by"]), ("charge_by", 90, now + 3600))
        for bad in ({"mode": "discharge"}, {"mode": "charge_by"},  # charge_by needs a time
                    {"mode": "charge_by", "ready_by": now - 1}, {"mode": "charge_by", "ready_by": now + 8 * 86400},
                    {"target_soc": 101}, {"target_soc": True}, {"min_soc": 80, "target_soc": 80},
                    {"start_soc": -1}, {"power_kw": 5}, ["mode"]):
            with self.assertRaises(ValueError, msg=bad):
                self.m.validate_needs(bad, now)

    def test_iso20_needs(self):
        now = 1_800_000_000
        allow = self.m.validate_needs({"mode": "allow_discharge", "min_soc": 20, "target_soc": 80}, now)
        iso = self.m.iso20_needs(allow, 50.0, 25000, now)
        self.assertEqual(iso["departure_time"], self.m.DEFAULT_DEPARTURE_S)
        self.assertEqual((iso["min_soc"], iso["target_soc"], iso["present_soc"]), (20, 80, 50))
        self.assertEqual((iso["target_wh"], iso["max_wh"], iso["min_wh"]), (18000, 30000, -18000))
        self.assertEqual((iso["v2x_min_wh"], iso["v2x_max_wh"]), (-18000, 30000))
        self.assertEqual((iso["max_discharge_w"], iso["min_discharge_w"], iso["max_discharge_a"]), (25000, 300, 66))
        # At the floor the EV stops offering discharge.
        self.assertEqual(self.m.iso20_needs(allow, 20.0, 25000, now)["max_discharge_w"], 0)
        charge = self.m.validate_needs({"mode": "charge_by", "target_soc": 80, "ready_by": now + 7200}, now)
        iso = self.m.iso20_needs(charge, 50.0, 25000, now + 600)
        self.assertEqual((iso["departure_time"], iso["min_soc"], iso["min_wh"]), (6600, 80, 18000))
        self.assertEqual((iso["v2x_min_wh"], iso["v2x_max_wh"], iso["max_discharge_w"]), (None, None, 0))
        self.assertEqual(iso["remaining_time_to_target_soc"], int(18000 / 25000 * 3600))
        # A ready_by that has passed: depart now.
        self.assertEqual(self.m.iso20_needs(charge, 50.0, 25000, now + 9000)["departure_time"], 0)

    def test_battery_follows_the_meter(self):
        battery = self.m.Battery(capacity_wh=60000)
        self.assertEqual(battery.update("Unplugged", 100.0, 5.0, 50), (50.0, False))
        self.assertEqual(battery.update("Charging", 100.0, 5.0, 50), (50.0, True))  # baseline at plug-in
        self.assertEqual(battery.update("Charging", 700.0, 5.0, 50), (51.0, True))  # +600 Wh = +1 %
        self.assertEqual(battery.update("Charging", 700.0, 1205.0, 50), (49.0, True))  # discharge lowers it
        self.assertEqual(battery.update("Unplugged", 700.0, 1205.0, 50), (50.0, False))  # reset on unplug
        self.assertEqual(battery.update("Charging", 0.0, 0.0, 99)[0], 99.0)
        self.assertEqual(battery.update("Charging", 5000.0, 0.0, 99)[0], 100.0)  # clamped

    def test_load_needs_keeps_a_passed_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / self.m.NEEDS_FILE
            self.assertEqual(self.m.load_needs(path), self.m.DEFAULT_NEEDS)
            path.write_text(json.dumps({"mode": "charge_by", "target_soc": 70, "min_soc": 30,
                                        "start_soc": 40, "ready_by": 1000}))
            self.assertEqual(self.m.load_needs(path)["ready_by"], 1000)
            path.write_text("{")
            self.assertEqual(self.m.load_needs(path), self.m.DEFAULT_NEEDS)


NEEDS_LOG = """2026-10-26T06:15:45.000Z: ChargePoint>CentralSystem NotifyEVChargingNeeds
[2, "n-1", "NotifyEVChargingNeeds", {"evseId": 1, "chargingNeeds": {"requestedEnergyTransfer": "DC_BPT",
 "departureTime": "2026-10-27T06:15:45Z", "v2xChargingParameters": {"targetSoC": 80}}}]
2026-10-26T06:15:45.200Z: CentralSystem>ChargePoint  NotifyEVChargingNeedsResponse
[3, "n-1", {"status": "Rejected"}]
2026-10-26T06:15:46.000Z: CentralSystem>ChargePoint  SetChargingProfile
[2, "n-1", "SetChargingProfile", {"evseId": 1}]
"""


class ChargingNeedsLogTest(unittest.TestCase):
    def test_station_requests_pair_with_csms_replies(self):
        sys.path.insert(0, str(ROOT / "rootfs/opt/ha-everest"))
        import ocpp_log
        events = ocpp_log.charging_needs_events(NEEDS_LOG)
        self.assertEqual([(e["action"], e["status"]) for e in events], [("NotifyEVChargingNeeds", "Rejected")])
        self.assertEqual(events[0]["payload"]["chargingNeeds"]["requestedEnergyTransfer"], "DC_BPT")
        # CSMS-side tracking is unchanged: a CSMS request with a reused id is its own event.
        self.assertEqual([e["action"] for e in ocpp_log.profile_events(NEEDS_LOG)], ["SetChargingProfile"])


class EvNeedsEndpointTest(UiServerTest):
    def setUp(self):
        import ui_server
        from http.server import ThreadingHTTPServer
        self.tmp = tempfile.TemporaryDirectory()
        run = Path(self.tmp.name)
        (run / "state.json").write_text(json.dumps({"max_power_kw": 7}))
        ui_server.RUN = run
        ui_server.LOGS = run / "logs"
        self.bus = FakeBus()
        self.ev = ui_server.EV(self.bus, data=run, run=run)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), ui_server.make_handler(self.bus, ev=self.ev))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ui = ui_server

    def post(self, body, headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        return self.request("/api/ev/needs", "POST",
                            {"X-HA-EVerest": "1", "Content-Type": "application/json", **(headers or {})}, data)

    def test_needs_endpoint(self):
        ready = int(time.time()) + 3600
        code, body = self.post({"mode": "charge_by", "target_soc": 90, "ready_by": ready})
        self.assertEqual(code, 200, body)
        run = Path(self.tmp.name)
        self.assertEqual(json.loads((run / "ev-needs.json").read_text())["target_soc"], 90)
        iso = json.loads((run / "ev-iso20.json").read_text())  # what Josev reads
        self.assertEqual((iso["mode"], iso["min_soc"], iso["max_discharge_w"]), ("charge_by", 90, 0))
        status = json.loads(self.request("/api/status")[1])["ev"]
        self.assertEqual((status["needs"]["mode"], status["iso20"]["target_soc"]), ("charge_by", 90))
        self.assertEqual(self.post({"mode": "charge_by"})[0], 400)  # no ready_by
        self.assertEqual(self.post(b"{")[0], 400)
        self.assertEqual(self.post({"mode": "allow_discharge", "x": "y" * 600})[0], 400)  # too large
        self.assertEqual(self.post({"mode": "allow_discharge"}, {"X-HA-EVerest": ""})[0], 403)
        self.assertEqual(self.post({"mode": "allow_discharge"}, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/api/ev/needs", "POST", {"X-HA-EVerest": "1"})[0], 415)
        # A rejected request leaves the stored needs as they were.
        self.assertEqual(json.loads((run / "ev-needs.json").read_text())["mode"], "charge_by")
        self.assertEqual(self.bus.sent, [])  # needs never send a car-simulator command


class WatchdogBus:
    """Session state and power as EVerest's API reports them."""

    def __init__(self, state="AuthRequired", power=0.0):
        self.state, self.power = state, power
        self.sent = []
        self.last_command = None

    def snapshot(self):
        return {"session_info": {"value": {"state": self.state}, "age_s": 1.0},
                "powermeter": {"value": {"power_W": {"total": self.power}}, "age_s": 1.0}}

    def send(self, name, state, source="operator"):
        self.sent.append((name, source))
        self.last_command = {"command": name, "at": 1000.0, "source": source}
        if name == "unplug":
            self.state = "Unplugged"
        elif name == "plugin":
            self.state = "AuthRequired"
        return True


class WatchdogTest(unittest.TestCase):
    """Issue #33: re-plug the EV after it gives up, never during a session."""

    def setUp(self):
        import ui_server
        self.ui = ui_server
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr, ui_server, "RUN", ui_server.RUN)
        ui_server.RUN = Path(self.tmp.name)
        self.now = 1000.0
        self.slept = []

    def gave_up(self, at):
        (self.ui.RUN / "state.json").write_text(json.dumps({"ev_gave_up_at": at, "max_power_kw": 25}))

    def watchdog(self, bus):
        return self.ui.Watchdog(bus, sleep=self.slept.append, clock=lambda: self.now)

    def test_decision(self):
        decide = self.ui.recovery_decision
        self.assertIsNone(decide(None, 0, "AuthRequired", 0, None, 0, 100))
        self.assertIsNone(decide(90, 90, "AuthRequired", 0, None, 0, 100))  # already handled
        self.assertEqual(decide(98, 0, "AuthRequired", 0, None, 0, 100), "wait")
        self.assertEqual(decide(90, 0, "AuthRequired", 0, None, 0, 100), "recover")
        self.assertEqual(decide(90, 0, "Preparing", None, None, 0, 100), "recover")
        self.assertEqual(decide(90, 0, "Charging", -20000, None, 0, 100), "skip: power flowing")
        self.assertEqual(decide(90, 0, "Charging", 6000, None, 0, 100), "skip: power flowing")
        self.assertEqual(decide(90, 0, "Unplugged", 0, None, 0, 100), "skip: not plugged in")
        self.assertEqual(decide(90, 0, None, 0, None, 0, 100), "skip: not plugged in")
        self.assertEqual(decide(90, 0, "AuthRequired", 0, 88, 0, 100), "skip: operator command")
        self.assertEqual(decide(90, 0, "AuthRequired", 0, 80, 0, 100), "recover")  # older command
        self.assertTrue(decide(90, 0, "AuthRequired", 0, None, 3, 100).startswith("skip: retry limit"))

    def test_recovers_by_unplug_then_plug_in(self):
        bus = WatchdogBus()
        watchdog = self.watchdog(bus)
        self.assertIsNone(watchdog.tick())
        self.gave_up(998.0)
        self.assertEqual(watchdog.tick(), "wait")
        self.assertEqual(watchdog.snapshot()["ev_session"], "gave_up")
        self.assertEqual(bus.sent, [])
        self.now = 1004.0
        self.assertEqual(watchdog.tick(), "recover")
        self.assertEqual(bus.sent, [("unplug", "watchdog"), ("plugin", "watchdog")])
        self.assertIn(self.ui.RECOVERY_SETTLE_S, self.slept)
        snap = watchdog.snapshot()
        self.assertEqual(snap["ev_session"], "ok")
        self.assertEqual(snap["recoveries"], 1)
        self.assertEqual(snap["last_recovery"]["result"], "re-plugged")
        self.assertIsNone(watchdog.tick())  # handled once only

    def test_never_replugs_while_power_flows_or_after_operator(self):
        bus = WatchdogBus("Charging", 20000.0)
        watchdog = self.watchdog(bus)
        self.gave_up(990.0)
        self.assertEqual(watchdog.tick(), "skip: power flowing")
        self.assertEqual(bus.sent, [])
        self.assertEqual(watchdog.snapshot()["ev_session"], "ok")
        bus = WatchdogBus()
        bus.last_command = {"command": "unplug", "at": 991.0}  # operator, no source key
        watchdog = self.watchdog(bus)
        self.assertEqual(watchdog.tick(), "skip: operator command")
        self.assertEqual(bus.sent, [])

    def test_retry_limit_until_power_flows(self):
        bus = WatchdogBus()
        watchdog = self.watchdog(bus)
        for attempt in range(self.ui.MAX_RECOVERIES):
            self.gave_up(self.now)
            self.now += 6
            self.assertEqual(watchdog.tick(), "recover")
            self.now += 60
        self.gave_up(self.now)
        self.now += 6
        self.assertTrue(watchdog.tick().startswith("skip: retry limit"))
        self.assertEqual(watchdog.snapshot()["ev_session"], "gave_up")
        self.assertEqual(len(bus.sent), 2 * self.ui.MAX_RECOVERIES)
        bus.power = 6000.0  # a working session resets the limit
        watchdog.tick()
        bus.power = 0.0
        self.gave_up(self.now)
        self.now += 6
        self.assertEqual(watchdog.tick(), "recover")

    def test_failed_unplug_is_reported(self):
        bus = WatchdogBus()
        bus.send = lambda name, state, source="operator": False
        watchdog = self.watchdog(bus)
        self.gave_up(990.0)
        self.assertEqual(watchdog.tick(), "recover")
        self.assertEqual(watchdog.snapshot()["ev_session"], "gave_up")
        self.assertEqual(watchdog.snapshot()["last_recovery"]["result"], "failed: unplug not sent")

    def test_status_reports_watchdog(self):
        watchdog = self.watchdog(WatchdogBus())
        body = self.ui.status(FakeBus(), watchdog)
        self.assertEqual(body["ev_watchdog"], {"ev_session": "ok", "recoveries": 0, "last_recovery": None})
        self.assertIsNone(self.ui.status(FakeBus())["ev_watchdog"])


class DynamicPricingConfigTest(unittest.TestCase):
    def test_tariff_and_cost_enabled_in_aud_with_california_pricing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        source = component_fixture(Path(tmp.name) / "source")
        target = Path(tmp.name) / "target"
        configure.component_config(source, target, configure.validate(GOOD), "a" * 32)
        for prop in ("TariffCostCtrlrAvailableTariff", "TariffCostCtrlrEnabledTariff",
                     "TariffCostCtrlrAvailableCost", "TariffCostCtrlrEnabledCost"):
            self.assertIs(value(target, "TariffCostCtrlr", prop), True, prop)
        self.assertEqual(value(target, "TariffCostCtrlr", "TariffCostCtrlrCurrency"), "AUD")
        self.assertEqual(value(target, "TariffCostCtrlr", "NumberOfDecimalsForCostValues"), 4)
        self.assertIs(value(target, "CustomizationCtrlr", "CustomImplementationCaliforniaPricingEnabled"), True)
        # Only California Pricing; the generic and multi-language switches stay upstream.
        self.assertNotIn("value", json.loads((target / "standardized/CustomizationCtrlr.json").read_text())
                         ["properties"]["CustomImplementationMultiLanguageEnabled"]["attributes"][0])
        doc = json.loads((target / "standardized/TariffCostCtrlr.json").read_text())
        # Available is ReadOnly (no SetVariables), so the file carries the value;
        # the variable, instance and mutability stay as upstream defines them.
        available = doc["properties"]["TariffCostCtrlrAvailableCost"]
        self.assertEqual((available["variable_name"], available["instance"]), ("Available", "Cost"))
        self.assertEqual(available["attributes"][0]["mutability"], "ReadOnly")
        self.assertEqual(value(target, "TariffCostCtrlr", "TotalCostFallbackMessage"), "")


PRICING_LOG = """2026-10-18T05:00:00.000Z: CentralSystem>ChargePoint  SetChargingProfile
[2, "p-1", "SetChargingProfile", {"evseId": 1, "chargingProfile": {"id": 7, "chargingProfilePurpose": "TxProfile"}}]
2026-10-18T05:00:00.100Z: ChargePoint>CentralSystem SetChargingProfileResponse
[3, "p-1", {"status": "Accepted"}]
2026-10-18T05:00:01.000Z: CentralSystem>ChargePoint  CostUpdated
[
  2,
  "c-1",
  "CostUpdated",
  {"totalCost": 1.23, "transactionId": "tx-1", "customData": {"vendorId": "org.openchargealliance.costmsg",
   "chargingPrice": {"kWhPrice": 0.2512}, "priceText": "0.2512 AUD/kWh"}}
]
2026-10-18T05:00:01.050Z: ChargePoint>CentralSystem CostUpdatedResponse
[
  3,
  "c-1",
  {}
]
2026-10-18T05:00:02.000Z: CentralSystem>ChargePoint  SetDefaultTariff
[2, "t-1", "SetDefaultTariff", {"evseId": 0, "tariff": {"tariffId": "AMBER-1", "currency": "AUD"}}]
2026-10-18T05:00:02.010Z: ChargePoint>CentralSystem Unknown
[
  4,
  "t-1",
  "NotImplemented",
  "",
  {}
]
2026-10-18T05:00:03.000Z: CentralSystem>ChargePoint  GetTariffs
[2, "t-2", "GetTariffs", {"evseId": 0}]
2026-10-18T05:00:03.010Z: ChargePoint>CentralSystem Unknown
[4, "t-2", "NotImplemented", "", {}]
2026-10-18T05:00:04.000Z: CentralSystem>ChargePoint  ClearTariffs
[2, "t-3", "ClearTariffs", {}]
2026-10-18T05:00:05.000Z: CentralSystem>ChargePoint  ChangeTransactionTariff
[2, "t-4", "ChangeTransactionTariff", {"transactionId": "tx-1", "tariff": {"tariffId": "AMBER-2", "currency": "AUD"}}]
2026-10-18T05:00:05.010Z: ChargePoint>CentralSystem Unknown
[4, "t-4", "NotImplemented", "", {}]
"""


def priced_profile(schedule):
    return {"payload": {"evseId": 1, "chargingProfile": {
        "id": 8, "chargingProfilePurpose": "TxDefaultProfile",
        "chargingSchedule": [dict({"id": 2, "chargingRateUnit": "W",
                                   "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 7000.0}]}, **schedule)]}}}


class PricingLogTest(unittest.TestCase):
    def test_pricing_messages_and_call_errors_tracked(self):
        for action in ("CostUpdated", "SetDefaultTariff", "GetTariffs", "ClearTariffs",
                       "ChangeTransactionTariff", "SetChargingProfile", "ClearChargingProfile"):
            self.assertIn(action, ocpp_log.TRACKED)
        events = ocpp_log.pricing_events(PRICING_LOG)
        self.assertEqual([e["action"] for e in events],
                         ["ChangeTransactionTariff", "ClearTariffs", "GetTariffs", "SetDefaultTariff", "CostUpdated"])
        by_id = {e["message_id"]: e for e in events}
        self.assertEqual(by_id["c-1"]["status"], "Replied")  # CostUpdatedResponse has no status
        self.assertEqual(by_id["c-1"]["payload"]["customData"]["chargingPrice"]["kWhPrice"], 0.2512)
        for uid in ("t-1", "t-2", "t-4"):
            self.assertEqual(by_id[uid]["status"], "CallError")
            self.assertEqual(by_id[uid]["status_info"]["reasonCode"], "NotImplemented")
        self.assertIsNone(by_id["t-3"]["status"])  # no reply recorded yet
        # Profiles are listed apart, so cost updates never push them out.
        profiles = ocpp_log.profile_events(PRICING_LOG)
        self.assertEqual([e["message_id"] for e in profiles], ["p-1"])
        flood = PRICING_LOG + "".join(
            f"2026-10-18T06:00:{i:02d}.000Z: CentralSystem>ChargePoint  CostUpdated\n"
            f'[2, "f-{i}", "CostUpdated", {{"totalCost": {i}, "transactionId": "tx-1"}}]\n' for i in range(20))
        self.assertEqual(ocpp_log.latest_profile(ocpp_log.profile_events(flood))["message_id"], "p-1")
        self.assertEqual(len(ocpp_log.pricing_events(flood)), 10)

    def test_absolute_price_schedule_summary(self):
        stacks = [{"duration": 1800, "priceRule": [
                       {"energyFee": {"value": 45, "exponent": -2}, "powerRangeStart": {"value": 7, "exponent": 0}},
                       {"energyFee": {"value": 2512, "exponent": -4}, "powerRangeStart": {"value": 0, "exponent": 0}}]}
                  ] + [{"duration": 1800, "priceRule": [{"energyFee": {"value": 30 + i, "exponent": -2},
                                                         "powerRangeStart": {"value": 0, "exponent": 0}}]}
                       for i in range(9)]
        found = ocpp_log.price_schedules(priced_profile({"absolutePriceSchedule": {
            "timeAnchor": "2026-10-18T05:00:00Z", "priceScheduleID": 3, "currency": "AUD", "language": "en",
            "priceAlgorithm": "org.openchargealliance.costcalc", "priceScheduleDescription": "Amber import",
            "priceRuleStacks": stacks}}))
        self.assertEqual(len(found), 1)
        summary = found[0]
        self.assertEqual((summary["kind"], summary["id"], summary["currency"], summary["count"]),
                         ("absolutePriceSchedule", 3, "AUD", 10))
        self.assertEqual(len(summary["intervals"]), ocpp_log.PRICE_INTERVALS)
        first, second = summary["intervals"][:2]
        # The lowest power range is the plain energy price.
        self.assertEqual((first["start"], first["duration_s"], first["energy_fee"], first["rules"]),
                         ("2026-10-18T05:00:00Z", 1800, 0.2512, 2))
        self.assertEqual((second["offset_s"], second["start"], second["energy_fee"]),
                         (1800, "2026-10-18T05:30:00Z", 0.3))

    def test_price_level_and_sales_tariff_summary(self):
        levels = ocpp_log.price_schedules(priced_profile({"priceLevelSchedule": {
            "timeAnchor": "2026-10-18T15:00:00+10:00", "priceScheduleId": 4, "numberOfPriceLevels": 5,
            "priceLevelScheduleEntries": [{"duration": 300, "priceLevel": 1}, {"duration": 600, "priceLevel": 4}]}}))
        self.assertEqual(levels[0]["kind"], "priceLevelSchedule")
        self.assertEqual(levels[0]["number_of_price_levels"], 5)
        self.assertEqual([(i["start"], i["price_level"]) for i in levels[0]["intervals"]],
                         [("2026-10-18T05:00:00Z", 1), ("2026-10-18T05:05:00Z", 4)])
        sales = ocpp_log.price_schedules(priced_profile({"startSchedule": "2026-10-18T05:00:00Z", "salesTariff": {
            "id": 5, "numEPriceLevels": 3, "salesTariffEntry": [
                {"relativeTimeInterval": {"start": 0, "duration": 900}, "ePriceLevel": 2,
                 "consumptionCost": [{"startValue": 0, "cost": [{"costKind": "RelativePricePercentage",
                                                                 "amount": 25, "amountMultiplier": -1}]}]}]}}))
        self.assertEqual(sales[0]["kind"], "salesTariff")
        self.assertEqual(sales[0]["intervals"][0]["start"], "2026-10-18T05:00:00Z")
        self.assertEqual((sales[0]["intervals"][0]["price_level"], sales[0]["intervals"][0]["cost"]), (2, 2.5))

    def test_no_or_malformed_price_information(self):
        self.assertEqual(ocpp_log.price_schedules(None), [])
        self.assertEqual(ocpp_log.price_schedules({"payload": None}), [])
        self.assertEqual(ocpp_log.price_schedules(priced_profile({})), [])
        broken = ocpp_log.price_schedules(priced_profile({"absolutePriceSchedule": {
            "timeAnchor": "not a time", "priceRuleStacks": [{"duration": "x", "priceRule": "y"}, 5]}}))
        self.assertEqual(broken[0]["count"], 2)
        self.assertEqual(broken[0]["intervals"], [{"offset_s": 0, "start": None, "duration_s": "x",
                                                   "energy_fee": None, "rules": 0}])
        self.assertIsNone(ocpp_log._number({"value": 1, "exponent": 10 ** 6}))


SESSION_COST = {
    "session_id": "tx-1", "status": "Running", "currency": {"code": "AUD", "decimals": 4},
    "cost_chunks": [{"cost": {"value": 12300}, "timestamp_to": "2026-10-18T05:00:01.000Z", "metervalue_to": 4200}],
    "charging_price": [
        {"category": "Energy", "price": {"currency": {"code": "AUD", "decimals": 4}, "value": {"value": 2512}}},
        {"category": "Time", "price": {"currency": {"code": "AUD", "decimals": 4}, "value": {"value": 10000}}}],
    "next_period": {"timestamp_from": "2026-10-18T05:30:00.000Z", "charging_price": [
        {"category": "Energy", "price": {"currency": {"code": "AUD", "decimals": 4}, "value": {"value": 3100}}}]},
    "message": [{"content": "0.2512 AUD/kWh"}, {"content": "0,2512 AUD/kWh", "language": "de"}],
}


class SessionCostTest(unittest.TestCase):
    def setUp(self):
        import ui_server
        self.ui = ui_server

    def test_topic_and_var_unwrapping(self):
        # EVerest 2026.10 framework: one topic per var, payload
        # {"msg_type": "Var", "data": {"data": <value>}} (lib/everest.cpp).
        self.assertEqual(self.ui.TOPICS[self.ui.SESSION_COST_TOPIC], "session_cost")
        self.assertEqual(self.ui.SESSION_COST_TOPIC, "everest/modules/ocpp/impl/session_cost/var/session_cost")
        self.assertEqual(self.ui.unwrap_var({"msg_type": "Var", "data": {"data": {"a": 1}}}),
                         ("session_cost", {"a": 1}))
        self.assertEqual(self.ui.unwrap_var({"msg_type": "Cmd", "data": {"data": {}}}), (None, None))
        # The 2025.10.0 envelope is not on this topic any more.
        self.assertEqual(self.ui.unwrap_var({"name": "session_cost", "data": {"a": 1}}), (None, None))
        self.assertEqual(self.ui.unwrap_var("garbage"), (None, None))

    def test_bus_stores_only_session_cost(self):
        bus = self.ui.Bus()
        message = type("Message", (), {})
        for topic, payload in (("everest/modules/ocpp/impl/session_cost/var/tariff_message",
                                {"msg_type": "Var", "data": {"data": {}}}),
                               (self.ui.SESSION_COST_TOPIC, {"msg_type": "Var", "data": {"data": SESSION_COST}})):
            m = message()
            m.topic = topic
            m.payload = json.dumps(payload).encode()
            bus.on_message(None, None, m)
        self.assertEqual(bus.snapshot()["session_cost"]["value"], SESSION_COST)
        self.assertEqual(set(bus.snapshot()), {"session_cost"})

    def test_session_price_summary(self):
        price = self.ui.session_price(SESSION_COST)
        self.assertEqual(price["total_cost"], 1.23)
        self.assertEqual(price["kwh_price"], 0.2512)
        self.assertEqual(price["hour_price"], 1.0)
        self.assertEqual(price["next_kwh_price"], 0.31)
        self.assertEqual(price["next_at"], "2026-10-18T05:30:00.000Z")
        self.assertEqual(price["currency"], "AUD")
        self.assertEqual(price["text"], "0.2512 AUD/kWh / 0,2512 AUD/kWh")
        self.assertEqual((price["timestamp"], price["meter_wh"], price["session_id"]),
                         ("2026-10-18T05:00:01.000Z", 4200, "tx-1"))

    def test_session_price_without_california_pricing(self):
        # Plain CostUpdated (no customData): total cost only.
        price = self.ui.session_price({"session_id": "tx-2", "status": "Running",
                                       "currency": {"code": "AUD", "decimals": 4},
                                       "cost_chunks": [{"cost": {"value": 5}}]})
        self.assertEqual(price["total_cost"], 0.0005)
        self.assertIsNone(price["kwh_price"])
        self.assertIsNone(price["next_at"])
        self.assertIsNone(price["text"])
        self.assertIsNone(self.ui.session_price("garbage"))
        self.assertIsNone(self.ui.session_price({"currency": {"decimals": 99}, "cost_chunks": [{"cost": {}}]})["total_cost"])

    def test_status_and_profiles_carry_pricing(self):
        class Bus:
            last_command = None

            def snapshot(self):
                return {"session_cost": {"value": SESSION_COST, "age_s": 3.0}}
        status = self.ui.status(Bus())
        self.assertEqual(status["session_cost"]["value"]["kwh_price"], 0.2512)
        self.assertEqual(status["session_cost"]["age_s"], 3.0)
        with tempfile.TemporaryDirectory() as tmp:
            old = self.ui.LOGS
            self.ui.LOGS = Path(tmp)
            try:
                (Path(tmp) / "libocpp_201.log").write_text(PRICING_LOG)
                body = self.ui.profiles()
            finally:
                self.ui.LOGS = old
        self.assertEqual(body["latest_profile"]["message_id"], "p-1")
        self.assertEqual(body["price_schedules"], [])
        self.assertEqual(body["pricing"][-1]["action"], "CostUpdated")
        self.assertEqual(body["recent"][0]["action"], "SetChargingProfile")


class PublishWorkflowTest(unittest.TestCase):
    """Publication stays an explicit, gated, non-overwriting operator action."""

    def setUp(self):
        workflows = ROOT.parent / ".github/workflows"
        self.publish = (workflows / "everest-v2g-publish.yml").read_text()
        self.ci = (workflows / "everest-v2g.yml").read_text()

    def test_image_name_matches_workflow(self):
        # main builds on the host; the Green branch (green-mirror.yml) adds
        # the aarch64 image named in .github/green-e2e-images.yaml.
        self.assertNotIn("\nimage:", CONFIG_TEXT)
        green = (ROOT.parent / ".github/green-e2e-images.yaml").read_text()
        self.assertIn("everest_v2g_simulator: ghcr.io/purcell-lab/{arch}-everest-v2g-simulator\n", green)
        self.assertIn("IMAGE=ghcr.io/purcell-lab/${{ matrix.arch }}-everest-v2g-simulator", self.publish)

    def test_only_tags_or_manual_runs_trigger_publication(self):
        trigger = self.publish.split("\non:", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn('"everest_v2g_simulator-v*"', trigger)
        self.assertIn("workflow_dispatch:", trigger)
        for forbidden in ("pull_request", "branches", "schedule"):
            self.assertNotIn(forbidden, trigger)
        self.assertNotIn("packages: write", self.ci)

    def test_manual_run_tags_built_commit_after_push_and_never_moves_a_tag(self):
        publish, tag = self.publish.split("\n  tag:\n", 1)
        # The publish job checks the requested version and refuses an existing tag.
        self.assertIn('test "$REQUESTED" = "$version"', publish)
        self.assertIn('git ls-remote --exit-code --tags origin "refs/tags/$tag"', publish)
        self.assertNotIn("contents: write", publish)
        # Only the tag job may write, only on a manual run, after publish, on
        # the exact commit that was built.
        self.assertIn("needs: publish", tag)
        self.assertIn("if: github.event_name == 'workflow_dispatch'", tag)
        self.assertIn("contents: write", tag)
        self.assertIn("ref: ${{ needs.publish.outputs.sha }}", tag)
        self.assertIn('git tag -a "$TAG"', tag)
        self.assertNotIn("--force", tag)
        self.assertNotIn("git tag -f", tag)

    def test_gate_before_push_and_no_overwrite_or_latest(self):
        order = [self.publish.index(step) for step in (
            "Tag or requested version must match the App version", "Refuse to overwrite a published version",
            "ci_image_checks.sh", 'docker push "$IMAGE:$VERSION"')]
        self.assertEqual(order, sorted(order))
        self.assertEqual(self.publish.count("docker push"), 1)
        self.assertNotIn(":latest", self.publish)
        self.assertIn("ci_image_checks.sh", self.ci)

    def test_release_gate_covers_isolation(self):
        gate = (ROOT / "tests/ci_image_checks.sh").read_text()
        for check in ("--cap-add NET_ADMIN everest-v2g:smoke", "V2G isolation setup failed",
                      "listeners.py", "fwprobe.py private-link", "probe expect-silence",
                      "nft delete table", "probe expect-reachable"):
            self.assertIn(check, gate)

    def test_merge_gate_checks_public_pull(self):
        self.assertIn("published-image:", self.ci)
        gate = self.ci.split("published-image:", 1)[1]
        self.assertIn("docker manifest inspect", gate)
        self.assertNotIn("docker login", gate)


if __name__ == "__main__":
    unittest.main()
