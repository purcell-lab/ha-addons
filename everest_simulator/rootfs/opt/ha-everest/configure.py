"""Validated HA options to an isolated EVerest OCPP 2.1/2.0.1 SIL configuration.

Pure functions so the CI unit tests can exercise every rule without EVerest.
"""
import json
from pathlib import Path
import re
import secrets
import shutil
import time
from urllib.parse import urlsplit

DEFAULT_CPID = "SIM-EV-EVEREST-01"
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
    phases = options.get("phases", 1)
    current = options.get("max_current_a", 32)
    acknowledged = options.get("acknowledge_test_isolation", False)
    if not isinstance(cpid, str) or not re.fullmatch(r"SIM-EV-[A-Za-z0-9_-]{1,36}", cpid):
        raise ValueError("charge_point_id must be a SIM-EV- test identity")
    if version not in VERSIONS:
        raise ValueError("ocpp_version must be 2.1 or 2.0.1")
    # HA list() options arrive as strings.
    if phases in ("1", "3"):
        phases = int(phases)
    if isinstance(phases, bool) or phases not in (1, 3):
        raise ValueError("phases must be 1 or 3")
    if isinstance(current, bool) or not isinstance(current, int) or not 6 <= current <= 32:
        raise ValueError("max_current_a must be 6-32")
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
        "phases": phases,
        "max_current_a": current,
    }


def atomic_write(path, text, mode=0o600):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text)
    temporary.chmod(mode)
    temporary.replace(path)


def bind(data, settings):
    """Bind the first real endpoint and identity to this App's data volume."""
    identity = data / "test-identity.json"
    target = {k: settings[k] for k in ("csms_url", "charge_point_id")}
    if not settings["csms_url"]:
        return  # A disconnected start never erases or changes the binding.
    if identity.exists():
        if json.loads(identity.read_text()) != target:
            raise ValueError("test destination changed; archive/reset App data before rebinding")
        return
    store = data / "everest" / "ocpp201"
    if store.exists() and any(store.glob("*.db")):
        raise ValueError("unbound OCPP data exists; archive/reset App data")
    atomic_write(identity, json.dumps(target))


def basic_auth_password(data):
    """Security Profile 1 password, generated once and never logged."""
    path = data / "basic-auth-password"
    if not path.exists():
        atomic_write(path, secrets.token_hex(16))
    value = path.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("invalid stored basic auth password")
    return value


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
        "ChargePointModel": "EVerest-SIL-HA",
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
    watts = settings["max_current_a"] * 230 * settings["phases"]
    edit("SmartChargingCtrlr", {
        "CompositeScheduleDefaultLimitAmps": settings["max_current_a"],
        "CompositeScheduleDefaultLimitWatts": watts,
        "CompositeScheduleDefaultNumberPhases": settings["phases"],
    })
    # ChargingStationSupplyPhases stays at the upstream value (3): setting it to 1
    # made libocpp drop every profile from composite schedules (2025.10.0).
    # One-second transaction samples, as in the V2G App, so step response
    # can be timed from the CSMS record (#41).
    edit("SampledDataCtrlr", {"SampledDataTxUpdatedInterval": 1})
    edit("OCPPCommCtrlr", {"HeartbeatInterval": 60})


def everest_config(settings, data):
    """One AC EVSE, IEC 61851 only (no ISO 15118 or V2G), with simulated EV."""
    store = str(data / "everest")
    phases = settings["phases"]
    amps = settings["max_current_a"]
    ev_session = (f"sleep 1;iec_wait_pwr_ready;sleep 1;"
                  f"draw_power_regulated {amps},{phases};sleep 86400")
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
                    "connector_id": 1, "evse_id": "1", "connector_type": "cType2",
                    "charge_mode": "AC", "ac_hlc_enabled": False,
                    "max_current_import_A": amps, "max_current_export_A": 0,
                    "session_logging": False,
                    "request_zero_power_in_idle": True,
                    "external_ready_to_start_charging": True,
                },
                "connections": {
                    "bsp": [{"module_id": "yeti_driver_1", "implementation_id": "board_support"}],
                    "powermeter_grid_side": [{"module_id": "yeti_driver_1", "implementation_id": "powermeter"}],
                },
            },
            "yeti_driver_1": {
                "module": "YetiSimulator",
                "mapping": {"module": {"evse": 1}},
                "config_module": {"connector_id": 1},
            },
            "ev_manager_1": {
                "module": "EvManager",
                "config_module": {
                    "connector_id": 1, "auto_enable": True, "auto_exec": False,
                    "max_current": amps, "three_phases": phases == 3,
                    "auto_exec_commands": ev_session,
                },
                "connections": {
                    "ev_board_support": [{"module_id": "yeti_driver_1", "implementation_id": "ev_board_support"}],
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
                    "evse_energy_sink": [
                        {"module_id": "grid_connection_point", "implementation_id": "external_limits"},
                        {"module_id": "evse_manager_1_ocpp_sink", "implementation_id": "external_limits"},
                    ],
                    "reservation": [{"module_id": "auth", "implementation_id": "reservation"}],
                },
            },
            "persistent_store": {
                "module": "PersistentStore",
                "config_module": {"sqlite_db_file_path": store + "/persistent_store.db"},
            },
            "evse_security": {"module": "EvseSecurity", "config_module": {"private_key_password": "123456"}},
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
                "connections": {"energy_trunk": [{"module_id": "grid_connection_point", "implementation_id": "energy_grid"}]},
            },
            "evse_manager_1_ocpp_sink": {
                "module": "EnergyNode",
                "mapping": {"module": {"evse": 1}},
                "config_module": {"fuse_limit_A": float(amps), "phase_count": phases},
                "connections": {"energy_consumer": [{"module_id": "evse_manager_1", "implementation_id": "energy_grid"}]},
            },
            "grid_connection_point": {
                "module": "EnergyNode",
                "mapping": {"module": {"evse": 0}},
                "config_module": {"fuse_limit_A": float(amps), "phase_count": phases},
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


def configure(data, options, source, prefix=Path("/opt/everest")):
    """Return (settings, path_to_everest_yaml). Raises ValueError on unsafe input."""
    settings = validate(options)
    data.mkdir(parents=True, exist_ok=True)
    archive_if_requested(data, options)
    bind(data, settings)
    password = basic_auth_password(data)
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
    atomic_write(path, yaml.safe_dump(everest_config(settings, data), sort_keys=False))
    return settings, path
