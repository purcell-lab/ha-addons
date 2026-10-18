"""Validated HA options to an isolated EVerest DC V2G (ISO 15118-20 DC_BPT) SIL configuration.

Pure functions so the CI unit tests can exercise every rule without EVerest.
"""
import json
import math
from pathlib import Path
import re
import secrets
import shutil
import time
from urllib.parse import urlsplit

DEFAULT_CPID = "SIM-EV-EVEREST-V2G-01"
from netguard import EVCC_LINK, SECC_LINK  # noqa: E402  private veth pair
# Simulated battery voltage: the EV's target and the DC supply's minimum. The
# supply's default 200 V minimum set the voltage whenever it discharged.
DC_VOLTAGE = 380
GRID_VOLTAGE = 230
# The simulated board (YetiSimulator) reported 32 A import and 16 A export per
# phase (22.08 / 11.04 kW). patch_yeti.py raises both to 128 A at build time,
# so the per-phase allowance below (up to 109 A) is the limit; patch_josev.py
# lets the simulated EV discharge 25 kW.
MAX_POWER_KW = 25
# ISO 15118 EVSEID syntax with a test-only operator code.
EVSE_ID = "AU*PUR*ESIM01*1"
# Per-session ISO 15118 traces stay in the container, never in /data.
ISO_LOG_DIR = "/tmp/iso15118"
# A closed loopback port: "disconnected" never reaches another host.
DISCONNECTED_URL = "ws://127.0.0.1:9"
VERSIONS = {
    # Offer 2.1 first; libocpp falls back when the CSMS selects 2.0.1.
    "2.1": "ocpp2.1,ocpp2.0.1",
    "2.0.1": "ocpp2.0.1",
}


def validate(options):
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    csms = options.get("csms_url", "")
    cpid = options.get("charge_point_id", DEFAULT_CPID)
    version = options.get("ocpp_version", "2.1")
    power = options.get("max_power_kw", MAX_POWER_KW)
    acknowledged = options.get("acknowledge_test_isolation", False)
    ha_control = options.get("ha_control", False)
    provisioned = options.get("csms_basic_auth_password", "")
    interval = options.get("tx_sample_interval_s", 5)
    if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 60:
        raise ValueError("tx_sample_interval_s must be 1-60")
    if not isinstance(provisioned, str) or (provisioned and not re.fullmatch(r"[0-9a-f]{32}", provisioned)):
        raise ValueError("CSMS credential must be empty or a provisioned 32-character lowercase hex value")
    if not isinstance(ha_control, bool):
        raise ValueError("ha_control must be true or false")
    if not isinstance(cpid, str) or not re.fullmatch(r"SIM-EV-[A-Za-z0-9_-]{1,36}", cpid):
        raise ValueError("charge_point_id must be a SIM-EV- test identity")
    if version not in VERSIONS:
        raise ValueError("ocpp_version must be 2.1 or 2.0.1")
    if isinstance(power, bool) or not isinstance(power, int) or not 3 <= power <= MAX_POWER_KW:
        raise ValueError(f"max_power_kw must be 3-{MAX_POWER_KW}")
    if not isinstance(csms, str) or len(csms) > 200:
        raise ValueError("csms_url must be a string of at most 200 characters")
    if csms:
        try:
            url = urlsplit(csms)
            port = url.port
        except ValueError:
            raise ValueError("invalid CSMS URL") from None
        if (
            url.scheme != "ws" or not url.hostname or not port
            or url.username is not None or url.password is not None
            or url.query or url.fragment
            or any(c.isspace() or ord(c) < 32 for c in csms)
            or "\\" in csms or "%" in csms
        ):
            raise ValueError("use ws://test-host:port[/base-path], without credentials")
        if url.hostname in ("127.0.0.1", "localhost", "::1") and port == 9:
            raise ValueError("port 9 is reserved for the disconnected state")
        if acknowledged is not True:
            raise ValueError("acknowledge_test_isolation is required before connecting")
        # libocpp appends the station identity itself.
        if url.path.rstrip("/").endswith("/" + cpid):
            raise ValueError("csms_url must not include charge_point_id")
    return {
        "csms_url": csms.rstrip("/"),
        "charge_point_id": cpid,
        "ocpp_version": version,
        "max_power_kw": power,
        "ha_control": ha_control,
        "tx_sample_interval_s": interval,
    }


def ratings(settings):
    """Derived DC and grid-side ratings for one bidirectional DC EVSE."""
    watts = settings["max_power_kw"] * 1000
    return {
        "watts": watts,
        # Per-phase grid allowance large enough for the full rating on one
        # phase. EnergyManager drops to one phase below the simulated board's
        # three-phase minimum (6 A x 3 x 230 V = 4.14 kW); without this, lower
        # charging targets are enforced as 0 W. Total power stays bounded by
        # the OCPP default limit and the DC supply rating (both `watts`).
        "phase_amps": math.ceil(watts / GRID_VOLTAGE),
        "dc_amps": math.ceil(watts / DC_VOLTAGE),
    }


def atomic_write(path, text, mode=0o600):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text)
    temporary.chmod(mode)
    temporary.replace(path)


DISCONNECTED_ONLY = "ocpp-disconnected-only"


def bind(data, settings):
    """Bind the first real endpoint and identity to this App's data volume.

    State created only by disconnected starts (marker file, written before
    EVerest first runs) never reached any CSMS, so the first connected start
    archives it (moved, never deleted) and binds. Any other unbound state is
    refused, as before.
    """
    identity = data / "test-identity.json"
    marker = data / DISCONNECTED_ONLY
    target = {k: settings[k] for k in ("csms_url", "charge_point_id")}
    store = data / "everest" / "ocpp201"
    has_state = store.exists() and any(store.glob("*.db"))
    if not settings["csms_url"]:
        # A disconnected start never erases or changes the binding.
        if not identity.exists() and not has_state:
            atomic_write(marker, "state created by disconnected starts only\n", mode=0o644)
        return None
    if identity.exists():
        if json.loads(identity.read_text()) != target:
            raise ValueError("test destination changed; archive/reset App data before rebinding")
        return None
    archived = None
    if has_state:
        if not marker.exists():
            raise ValueError("unbound OCPP data exists; archive/reset App data")
        archived = archive_if_requested(data, {"archive_and_rebind": True})
    if marker.exists():
        marker.unlink()
    atomic_write(identity, json.dumps(target))
    return archived


def basic_auth_password(data, provisioned=""):
    """Use an explicit lab credential or preserve the original local password.

    A supplied credential is never copied into status/settings or written over
    the original file. Clearing the option restores the old password for rollback.
    """
    if provisioned:
        if not isinstance(provisioned, str) or not re.fullmatch(r"[0-9a-f]{32}", provisioned):
            raise ValueError("invalid provisioned CSMS credential")
        return provisioned
    path = data / "basic-auth-password"
    if not path.exists():
        atomic_write(path, secrets.token_hex(16))
    value = path.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("invalid stored basic auth password")
    return value


# Device-model property keys (libocpp v0.30.3 component config) to values.
PRICING = {
    "TariffCostCtrlrAvailableTariff": True,  # Available[Tariff]
    "TariffCostCtrlrEnabledTariff": True,  # Enabled[Tariff]
    "TariffCostCtrlrAvailableCost": True,  # Available[Cost]
    "TariffCostCtrlrEnabledCost": True,  # Enabled[Cost]
    "TariffCostCtrlrCurrency": "AUD",
    # Prices in $/kWh to 0.01 c (Amber publishes c/kWh to two decimals).
    "NumberOfDecimalsForCostValues": 4,
}
# CustomImplementationEnabled[org.openchargealliance.costmsg]
CALIFORNIA_PRICING = {"CustomImplementationCaliforniaPricingEnabled": True}


def _set(doc, prop, value):
    attributes = doc["properties"][prop]["attributes"]
    for attribute in attributes:
        if attribute.get("type", "Actual") == "Actual":
            attribute["value"] = value
            return
    raise KeyError(prop)


def component_config(source, target, settings, password):
    """Copy the standard device model and apply only the documented overrides."""
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    std = target / "standardized"

    def edit(name, values):
        path = std / f"{name}.json"
        doc = json.loads(path.read_text())
        for prop, value in values.items():
            _set(doc, prop, value)
        path.write_text(json.dumps(doc, indent=2))

    cpid = settings["charge_point_id"]
    url = settings["csms_url"] or DISCONNECTED_URL
    profile = [{
        "configurationSlot": 1,
        "connectionData": {
            "messageTimeout": 30,
            "ocppCsmsUrl": url,
            "ocppInterface": "Wired0",
            "ocppTransport": "JSON",
            "ocppVersion": "OCPP20",
            "securityProfile": 1,
        },
    }]
    edit("InternalCtrlr", {
        "ChargePointId": cpid,
        "NetworkConnectionProfiles": json.dumps(profile),
        "SupportedOcppVersions": VERSIONS[settings["ocpp_version"]],
        "ChargePointVendor": "purcell-lab",
        "ChargePointModel": "EVerest-SIL-DC-V2G",  # OCPP: at most 20 characters
        "ChargeBoxSerialNumber": cpid[:25],
        "LogMessagesFormat": "log",
        "LogRotation": True,
        "LogRotationMaximumFileSize": 1048576,
        "LogRotationMaximumFileCount": 3,
    })
    edit("SecurityCtrlr", {
        "SecurityCtrlrIdentity": cpid,
        "BasicAuthPassword": password,
        "SecurityProfile": 1,
    })
    rating = ratings(settings)
    edit("SmartChargingCtrlr", {
        "CompositeScheduleDefaultLimitAmps": rating["phase_amps"],
        "CompositeScheduleDefaultLimitWatts": rating["watts"],
        "CompositeScheduleDefaultNumberPhases": 3,
    })
    # ChargingStationSupplyPhases stays at the upstream value (3): setting it to 1
    # made libocpp drop every profile from composite schedules (2025.10.0).
    # Transaction sample interval (option tx_sample_interval_s, default 5 s).
    # One-second samples outran CitrineOS on the Green (about one
    # TransactionEvent every 2 s), so long sessions queued minutes of samples.
    edit("SampledDataCtrlr", {"SampledDataTxUpdatedInterval": settings["tx_sample_interval_s"]})
    # The upstream lists omit export energy even though the simulated meter
    # provides it. Preserve existing measurands and request both directions
    # in Started, Updated and Ended frames; never synthesize export from net.
    sampled_path = std / "SampledDataCtrlr.json"
    sampled = json.loads(sampled_path.read_text())
    required = ("Energy.Active.Import.Register", "Energy.Active.Export.Register",
                "Power.Active.Import")
    for event in ("Started", "Updated", "Ended"):
        prop = "SampledDataTx" + event + "Measurands"
        definition = sampled["properties"][prop]
        actual = next(a for a in definition["attributes"] if a.get("type", "Actual") == "Actual")
        current = actual.get("value") or definition.get("default") or ""
        if not isinstance(current, str):
            raise ValueError("Invalid upstream sampled measurands")
        measurands = [x.strip() for x in current.split(",") if x.strip()]
        for measurand in required:
            if measurand not in measurands:
                measurands.append(measurand)
        _set(sampled, prop, ",".join(measurands))
    sampled_path.write_text(json.dumps(sampled, indent=2))
    edit("OCPPCommCtrlr", {"HeartbeatInterval": 60})
    # Dynamic pricing: libocpp passes CostUpdated and TransactionEventResponse
    # totalCost to EVerest (session_cost) only when Cost is available and
    # enabled, and reads California Pricing customData (current and next
    # price, price text) only with costmsg enabled. Available is ReadOnly, so
    # it can only be set here. libocpp v0.30.3 still answers the OCPP 2.1
    # tariff messages (SetDefaultTariff and others) NotImplemented.
    edit("TariffCostCtrlr", PRICING)
    edit("CustomizationCtrlr", CALIFORNIA_PRICING)


def ev_session():
    """Simulated EV: SLAC, ISO 15118-20 session (DC_BPT preferred), then hold."""
    return ("sleep 1;iso_wait_slac_matched;iso_start_v2g_session DC 86400 0;"
            "iso_wait_pwr_ready;iso_dc_power_on;iso_wait_for_stop 86400;"
            "iso_wait_v2g_session_stopped;unplug")


def everest_config(settings, data, pki_password):
    """One bidirectional DC EVSE (ISO 15118-20 DC_BPT over TLS 1.3) with simulated EV.

    Charger and EV talk over a private veth pair; SLAC, isolation monitor and
    DC supply are simulators. Discharge happens only when energy management
    hands the EVSE a negative target, which here means an OCPP 2.1
    CentralSetpoint period with a negative setpoint.
    """
    store = str(data / "everest")
    rating = ratings(settings)
    return {
        "settings": {
            "telemetry_enabled": False,
            "mqtt_broker_host": "127.0.0.1",
            "mqtt_broker_port": 1883,
        },
        "active_modules": {
            "evse_manager_1": {
                "module": "EvseManager",
                "mapping": {"module": {"evse": 1}},
                "config_module": {
                    "connector_id": 1, "evse_id": EVSE_ID, "connector_type": "cCCS2",
                    "charge_mode": "DC",
                    "bpt_channel": "Unified", "bpt_generator_mode": "GridFollowing",
                    "max_current_import_A": rating["phase_amps"],
                    "max_current_export_A": rating["phase_amps"],
                    "session_logging": False,
                    "request_zero_power_in_idle": True,
                    "external_ready_to_start_charging": True,
                },
                "connections": {
                    "bsp": [{"module_id": "yeti_driver_1", "implementation_id": "board_support"}],
                    "powermeter_car_side": [{"module_id": "powersupply_dc", "implementation_id": "powermeter"}],
                    "slac": [{"module_id": "slac", "implementation_id": "evse"}],
                    "hlc": [{"module_id": "iso15118_charger", "implementation_id": "charger"}],
                    "powersupply_DC": [{"module_id": "powersupply_dc", "implementation_id": "main"}],
                    "imd": [{"module_id": "imd", "implementation_id": "main"}],
                },
            },
            "yeti_driver_1": {
                "module": "YetiSimulator",
                "mapping": {"module": {"evse": 1}},
                "config_module": {"connector_id": 1},
            },
            "powersupply_dc": {
                "module": "DCSupplySimulator",
                "config_implementation": {"main": {
                    "bidirectional": True,
                    # Upstream defaults to 1 A at 200 V min: EvseManager then
                    # sees a 200 W minimum, ignores a 0 W target (min > max)
                    # and keeps the previous current in the new direction.
                    "min_current": 0.0,
                    "min_voltage": float(DC_VOLTAGE),
                    "max_power": float(rating["watts"]),
                    "max_current": float(rating["dc_amps"] + 5),
                }},
            },
            "slac": {"module": "SlacSimulator"},
            "imd": {"module": "IMDSimulator", "config_implementation": {"main": {"selftest_success": True}}},
            "iso15118_charger": {
                "module": "Evse15118D20",
                "config_module": {"device": SECC_LINK, "logging_path": ISO_LOG_DIR},
                "connections": {"security": [{"module_id": "evse_security", "implementation_id": "main"}]},
            },
            "iso15118_car": {
                "module": "PyEvJosev",
                "config_module": {
                    "device": EVCC_LINK,
                    "supported_DIN70121": False,
                    "supported_ISO15118_2": False,
                    "supported_ISO15118_20_DC": True,
                    "tls_active": True,
                    "enable_tls_1_3": True,
                    # Josev picks the first service the charger also offers.
                    "supported_d20_energy_services": "DC_BPT,DC",
                },
            },
            "ev_manager_1": {
                "module": "EvManager",
                "config_module": {
                    "connector_id": 1, "auto_enable": True, "auto_exec": False,
                    "dc_target_current": rating["dc_amps"], "dc_target_voltage": DC_VOLTAGE,
                    "auto_exec_commands": ev_session(),
                },
                "connections": {
                    "ev_board_support": [{"module_id": "yeti_driver_1", "implementation_id": "ev_board_support"}],
                    "ev": [{"module_id": "iso15118_car", "implementation_id": "ev"}],
                    "slac": [{"module_id": "slac", "implementation_id": "ev"}],
                },
            },
            "ocpp": {
                "module": "OCPP201",
                "config_module": {
                    "MessageLogPath": store + "/ocpp_logs",
                    "CoreDatabasePath": store + "/ocpp201",
                    "DeviceModelDatabasePath": store + "/ocpp201/device_model_storage.db",
                    "EverestDeviceModelDatabasePath": store + "/ocpp201/everest_device_model_storage.db",
                    "DeviceModelConfigPath": store + "/component_config",
                    "RequestCompositeScheduleUnit": "W",
                    "CompositeScheduleIntervalS": 10,
                },
                "connections": {
                    "evse_manager": [{"module_id": "evse_manager_1", "implementation_id": "evse"}],
                    "auth": [{"module_id": "auth", "implementation_id": "main"}],
                    "system": [{"module_id": "system", "implementation_id": "main"}],
                    "security": [{"module_id": "evse_security", "implementation_id": "main"}],
                    # EVSE 1 only. libocpp reports the EVSE 0 composite as per-phase
                    # shares (limit = L1) and EVerest 2025.10.0 applies that share as
                    # the total, capping every target at a third of the rating.
                    "evse_energy_sink": [
                        {"module_id": "evse_manager_1_ocpp_sink", "implementation_id": "external_limits"},
                    ],
                    "reservation": [{"module_id": "auth", "implementation_id": "reservation"}],
                },
            },
            "persistent_store": {
                "module": "PersistentStore",
                "config_module": {"sqlite_db_file_path": store + "/persistent_store.db"},
            },
            "evse_security": {"module": "EvseSecurity", "config_module": {"private_key_password": pki_password}},
            "token_provider_1": {"module": "DummyTokenProviderManual"},
            "auth": {
                "module": "Auth",
                "config_module": {"connection_timeout": 60, "selection_algorithm": "FindFirst"},
                "connections": {
                    "token_provider": [
                        {"module_id": "token_provider_1", "implementation_id": "main"},
                        {"module_id": "ocpp", "implementation_id": "auth_provider"},
                    ],
                    "token_validator": [{"module_id": "ocpp", "implementation_id": "auth_validator"}],
                    "evse_manager": [{"module_id": "evse_manager_1", "implementation_id": "evse"}],
                    "kvs": [{"module_id": "persistent_store", "implementation_id": "main"}],
                },
            },
            "energy_manager": {
                "module": "EnergyManager",
                # See ratings(): one-phase fallback for low charging targets.
                "config_module": {"switch_3ph1ph_while_charging_mode": "Both",
                                  "switch_3ph1ph_time_hysteresis_s": 1},
                "connections": {"energy_trunk": [{"module_id": "grid_connection_point", "implementation_id": "energy_grid"}]},
            },
            "evse_manager_1_ocpp_sink": {
                "module": "EnergyNode",
                "mapping": {"module": {"evse": 1}},
                "config_module": {"fuse_limit_A": float(rating["phase_amps"]), "phase_count": 3},
                "connections": {"energy_consumer": [{"module_id": "evse_manager_1", "implementation_id": "energy_grid"}]},
            },
            "grid_connection_point": {
                "module": "EnergyNode",
                "mapping": {"module": {"evse": 0}},
                "config_module": {"fuse_limit_A": float(rating["phase_amps"]), "phase_count": 3},
                "connections": {"energy_consumer": [{"module_id": "evse_manager_1_ocpp_sink", "implementation_id": "energy_grid"}]},
            },
            "api": {
                "module": "API",
                "connections": {
                    "evse_manager": [{"module_id": "evse_manager_1", "implementation_id": "evse"}],
                    "ocpp": [{"module_id": "ocpp", "implementation_id": "ocpp_generic"}],
                    "error_history": [{"module_id": "error_history", "implementation_id": "error_history"}],
                },
            },
            "error_history": {
                "module": "ErrorHistory",
                "config_implementation": {"error_history": {"database_path": store + "/error_history.db"}},
            },
            "system": {"module": "System"},
        },
    }


def archive_if_requested(data, options):
    """Explicit, operator-selected rebinding: move state aside, never delete it."""
    if options.get("archive_and_rebind") is not True:
        return None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archive = data / f"archive-{stamp}"
    archive.mkdir(mode=0o700)
    for name in ("everest", "test-identity.json"):
        if (data / name).exists():
            (data / name).rename(archive / name)
    return archive


def configure(data, options, source, prefix=Path("/opt/everest"), pki_password=None):
    """Return (settings, path_to_everest_yaml). Raises ValueError on unsafe input."""
    settings = validate(options)
    data.mkdir(parents=True, exist_ok=True)
    archive_if_requested(data, options)
    archived = bind(data, settings)
    if archived:
        print(f"First connection: state from disconnected starts moved to {archived.name}/.", flush=True)
    password = basic_auth_password(data, options.get("csms_basic_auth_password", ""))
    store = data / "everest"
    for sub in ("ocpp201", "ocpp_logs"):
        (store / sub).mkdir(parents=True, exist_ok=True, mode=0o700)
    component_config(source, store / "component_config", settings, password)
    # Rebuild the device model from the generated files on every start so
    # option changes take effect deterministically. Core data (transactions,
    # charging profiles) is retained.
    for name in ("device_model_storage.db", "everest_device_model_storage.db"):
        (store / "ocpp201" / name).unlink(missing_ok=True)
    import yaml  # runtime dependency only
    path = store / "config-ha-sil-ocpp.yaml"
    if pki_password is None:
        raise ValueError("test PKI is not ready")
    atomic_write(path, yaml.safe_dump(everest_config(settings, data, pki_password), sort_keys=False))
    return settings, path
