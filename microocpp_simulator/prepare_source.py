"""Small, fail-closed downstream adaptations of an exactly pinned upstream tree."""
import gzip
import re
import subprocess
import sys
from pathlib import Path

REVISION = "2cb07cdbe53954a694a29336ab31eac2d2b48673"


def replace_once(path, old, new, count=1):
    text = path.read_text()
    if text.count(old) != count:
        raise ValueError(f"upstream context changed: {path.name}")
    path.write_text(text.replace(old, new, count))


def guard_legacy_evse_hooks(path):
    """Do not look up legacy Connector objects in the 2.0.1 EVSE model."""
    text = path.read_text()
    for function in ("addErrorCodeInput", "setSmartChargingPowerOutput"):
        start_marker = f"    {function}([this]"
        if text.count(start_marker) != 1:
            raise ValueError(f"upstream {function} context changed")
        start = text.index(start_marker)
        end = text.index("    }, connectorId);", start) + len("    }, connectorId);")
        block = text[start:end]
        guarded = (
            "    // This hook only supports the legacy 1.6 Connector model.\n"
            "    if (getOcppContext()->getVersion().major == 1) {\n"
            + "\n".join("    " + line for line in block.splitlines())
            + "\n    }"
        )
        text = text[:start] + guarded + text[end:]
    path.write_text(text)


def fix_ui_power_controls(text):
    """The UI's single cable control must plug/unplug both simulated ends."""
    text, count = re.subn(
        r"evPlugged:([A-Za-z_$][A-Za-z0-9_$]*),",
        lambda match: f"evPlugged:{match[1]},evsePlugged:{match[1]},",
        text,
    )
    if count != 2:
        raise ValueError("upstream UI plug payload context changed")
    # Occupied is a valid 2.0.1 connector status, not a fault and not proof
    # of energy transfer. Keep the raw label and use non-error styling.
    if text.count('case"Charging":') != 3:
        raise ValueError("upstream UI status context changed")
    text = text.replace('case"Charging":', 'case"Occupied":case"Charging":')
    for old, new in (
        ("t.evPlugged===O&&t.evReady===x&&t.evseReady===E",
         "t.evPlugged===e&&t.evsePlugged===e&&t.evReady===n&&t.evseReady===r"),
        ("DateFormatter.fullDate(new Date)", "(new Date).toLocaleString()"),
        (',onClick:function(){M("Charging")}', ""),
    ):
        if text.count(old) != 1:
            raise ValueError("upstream UI live-control context changed")
        text = text.replace(old, new)
    return text


def refresh_meter_at_sample_time(root):
    """Keep protocol and HTTP readings current even inside mocpp_loop()."""
    header = root / "src/evse.h"
    source = root / "src/evse.cpp"
    replace_once(header, "    std::string status;",
                 "    std::string status;\n    void updateMeter();")
    replace_once(header, "    int getEnergy() {\n",
                 "    int getEnergy() {\n        updateMeter();\n")
    replace_once(source, "        return simulate_energy;",
                 "        updateMeter();\n        return simulate_energy;")
    replace_once(source, "        return simulate_power;",
                 "        updateMeter();\n        return simulate_power;")
    replace_once(source, "            return (int32_t) (simulate_power >",
                 "            updateMeter();\n            return (int32_t) (simulate_power >")
    replace_once(source, "int Evse::getPower() {\n",
                 "int Evse::getPower() {\n    updateMeter();\n")
    replace_once(source, "    bool simulate_isCharging =",
                 "    updateMeter();\n}\n\nvoid Evse::updateMeter() {\n"
                 "    // Account for the last powered interval before refreshing state.\n"
                 "    // Sampling can occur inside mocpp_loop(), before Evse::loop().\n"
                 "    const auto now = mocpp_tick_ms();\n"
                 "    if (simulate_power >= 1.f) {\n"
                 "        simulate_energy += (float) (now - simulate_energy_track_time)\n"
                 "            * simulate_power * (0.001f / 3600.f);\n"
                 "    }\n"
                 "    simulate_energy_track_time = now;\n\n"
                 "    bool simulate_isCharging =")
    replace_once(source,
                 "        if (simulate_power >= 1.f) {\n"
                 "            simulate_energy += (float) (mocpp_tick_ms() - simulate_energy_track_time) * simulate_power * (0.001f / 3600.f);\n"
                 "        }\n\n", "")
    replace_once(source, "        simulate_energy_track_time = mocpp_tick_ms();\n", "")


def prepare(root):
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != REVISION:
        raise ValueError("unreviewed upstream revision")
    cmake = root / "CMakeLists.txt"
    # Retain upstream 2.0.1 compilation and select it unconditionally below.
    replace_once(cmake, "    MO_TRAFFIC_OUT\n", "")
    replace_once(cmake, "MO_DBG_LEVEL=MO_DL_INFO", "MO_DBG_LEVEL=MO_DL_WARN")
    main = root / "src/main.cpp"
    start = main.read_text().index("void load_ocpp_version(")
    end = main.read_text().index("\nvoid app_setup(", start)
    main.write_text(main.read_text()[:start] +
                    "void load_ocpp_version(std::shared_ptr<MicroOcpp::FilesystemAdapter>) {\n"
                    "    g_isOcpp201 = true;\n}\n" + main.read_text()[end:])
    replace_once(main, '"http://0.0.0.0:8000"', '"http://127.0.0.1:8000"')
    replace_once(main, '"ws://echo.websocket.events"', '""')
    replace_once(main, '"charger-01"', '"SIM-MICROOCPP-01"')
    replace_once(main, "mg_log_set(MG_LL_INFO)", "mg_log_set(MG_LL_ERROR)")
    replace_once(main, "sigaction(SIGINT, &sigIntHandler, NULL);",
                 "sigaction(SIGINT, &sigIntHandler, NULL);\n"
                 "    sigaction(SIGTERM, &sigIntHandler, NULL);")
    replace_once(main, "#include <iostream>", "#include <iostream>\n#include <cstdlib>")
    replace_once(main, "mg_mgr_init(&mgr);", """mg_mgr_init(&mgr);
    // Use Supervisor/Docker DNS, never the upstream public resolver.
    if (const char *dns = std::getenv("MO_LAB_DNS_URL")) {
        mgr.dns4.url = dns;
    }""")
    # Keep CSMS ChangeConfiguration from changing the network identity.
    client = root / "lib/MicroOcppMongoose/src/MicroOcppMongooseClient.cpp"
    replace_once(client, "readonly = false;", "readonly = true;")
    # Connection diagnostics (#31): name the address Mongoose resolved and tried.
    replace_once(client, 'MG_ERROR(("%p %s", c->fd, (char *) ev_data));',
                 'MG_ERROR(("%p %s peer %M", c->fd, (char *) ev_data, mg_print_ip_port, &c->rem));')
    for variable in ("csmsUrl", "identity", "basicAuthPassword"):
        replace_once(client, f"{variable}->setPersistent();",
                     f"{variable}->setPersistent();\n"
                     f"        {variable}->setMutability(Variable::Mutability::ReadOnly);")
    # The original HTTP API returns the legacy integer ID (-1 in 2.x).
    replace_once(root / "src/evse.h", "int getTransactionId();",
                 "const char *getTransactionId();")
    guard_legacy_evse_hooks(root / "src/evse.cpp")
    refresh_meter_at_sample_time(root)
    replace_once(root / "src/evse.cpp",
                 "int Evse::getTransactionId() {\n"
                 "    return getTransaction(connectorId) ? getTransaction(connectorId)->getTransactionId() : -1;\n}",
                 "const char *Evse::getTransactionId() {\n"
                 "    auto service = getOcppContext()->getModel().getTransactionService();\n"
                 "    auto evse = service ? service->getEvse(connectorId) : nullptr;\n"
                 "    auto tx = evse ? evse->getTransaction() : nullptr;\n"
                 '    return tx ? tx->transactionId : "";\n}')
    # Upstream 2.x defaults send no sampled data. Provide useful lab defaults.
    metering = root / "lib/MicroOcpp/src/MicroOcpp/Model/Metering/MeterValuesV201.cpp"
    for name in ("TxStartedMeasurands", "TxUpdatedMeasurands", "TxEndedMeasurands"):
        replace_once(metering, f'"SampledDataCtrlr", "{name}", ""',
                     f'"SampledDataCtrlr", "{name}", '
                     '"Energy.Active.Import.Register,Power.Active.Import,Current.Import,Voltage,SoC"', count=2)
    replace_once(root / "lib/MicroOcpp/src/MicroOcpp/Model/Transactions/TransactionService.cpp",
                 '"SampledDataCtrlr", "TxUpdatedInterval", 0',
                 '"SampledDataCtrlr", "TxUpdatedInterval", 10')
    # Serve the HTML name so Mongoose infers a single correct MIME type and
    # negotiates its .gz sibling. Extra Content-Type headers do not override
    # Mongoose's application/gzip type for an explicitly served .gz filename.
    web = root / "src/net_mongoose.cpp"
    replace_once(web,
                 'opts.extra_headers = "Content-Type: text/html\\r\\nContent-Encoding: gzip\\r\\n";',
                 'opts.extra_headers = "Cache-Control: no-cache\\r\\nVary: Accept-Encoding\\r\\n";')
    replace_once(web,
                 'mg_http_serve_file(c, message_data, "public/bundle.html.gz", &opts);',
                 'mg_http_serve_file(c, message_data, "public/bundle.html", &opts);')
    bundle = root / "public/bundle.html.gz"
    text = gzip.decompress(bundle.read_bytes()).decode()
    old = '"http://localhost:8000/api"'
    if text.count(old) != 1:
        raise ValueError("upstream UI API-root context changed")
    text = text.replace(old, 'new URL("api",window.location.href).href')
    for old_label, new_label in (
        ("OCPP 1.6 Connection", "OCPP 2.0.1 Connection"),
        ("OCPP 1.6 Websocket", "OCPP 2.0.1 WebSocket"),
    ):
        if text.count(old_label) != 1:
            raise ValueError("upstream protocol label context changed")
        text = text.replace(old_label, new_label)
    text = fix_ui_power_controls(text)
    bundle.with_suffix("").write_text(text)
    bundle.write_bytes(gzip.compress(text.encode(), mtime=0))


if __name__ == "__main__":
    prepare(Path(sys.argv[1]).resolve())
