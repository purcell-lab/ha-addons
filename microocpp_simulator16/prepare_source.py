"""Fail-closed adaptations of the pinned OCPP 1.6 simulator."""
import gzip
import re
import subprocess
import sys
from pathlib import Path

REVISION = "2cb07cdbe53954a694a29336ab31eac2d2b48673"


def replace(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise ValueError(f"upstream context changed in {path.name}: {old[:50]}")
    path.write_text(text.replace(old, new))


def prepare(root):
    revision = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if revision != REVISION:
        raise ValueError("unreviewed upstream revision")
    replace(root / "CMakeLists.txt", "    MO_TRAFFIC_OUT\n", "")
    replace(root / "CMakeLists.txt", "MO_DBG_LEVEL=MO_DL_INFO", "MO_DBG_LEVEL=MO_DL_WARN")
    main = root / "src/main.cpp"
    text = main.read_text()
    start, end = text.index("void load_ocpp_version("), text.index("\nvoid app_setup(")
    main.write_text(text[:start] +
                    "void load_ocpp_version(std::shared_ptr<MicroOcpp::FilesystemAdapter>) {\n"
                    "    g_isOcpp201 = false;\n}\n" + text[end:])
    replace(main, '"http://0.0.0.0:8000"', '"http://127.0.0.1:8000"')
    replace(main, '"ws://echo.websocket.events"', '""')
    replace(main, '"charger-01"', '"SIM-16-MICROOCPP-01"')
    replace(main, "mg_log_set(MG_LL_INFO)", "mg_log_set(MG_LL_ERROR)")
    replace(main, "sigaction(SIGINT, &sigIntHandler, NULL);",
            "sigaction(SIGINT, &sigIntHandler, NULL);\n"
            "    sigaction(SIGTERM, &sigIntHandler, NULL);")
    # The original 1.6 integer transaction ID and smart-charging callback
    # are deliberately retained. Network identity must not be changed by CSMS.
    client = root / "lib/MicroOcppMongoose/src/MicroOcppMongooseClient.cpp"
    replace(client, "readonly = false;", "readonly = true;")
    metering = root / "lib/MicroOcpp/src/MicroOcpp/Model/Metering"
    measurands = "Energy.Active.Import.Register,Power.Active.Import,Current.Import,Voltage"
    replace(metering / "MeteringService.cpp",
            '"MeterValuesSampledData", "Energy.Active.Import.Register,Power.Active.Import"',
            f'"MeterValuesSampledData", "{measurands}"')
    replace(metering / "MeteringService.cpp", '"StopTxnSampledData", ""',
            f'"StopTxnSampledData", "{measurands}"')
    replace(metering / "MeteringConnector.cpp", '"MeterValueSampleInterval", 60',
            '"MeterValueSampleInterval", 10')
    smart = root / "lib/MicroOcpp/src/MicroOcpp/Model/SmartCharging/SmartChargingModel.cpp"
    replace(smart, "if (t > validTo && validTo > MIN_TIME)",
            "if (t >= validTo && validTo > MIN_TIME)")
    replace(smart,
            "    return chargingSchedule.calculateLimit(t, startOfCharging, limit, nextChange);",
            "    // Re-evaluate when the profile validity window expires, even\n"
            "    // if its final schedule period has no subsequent boundary.\n"
            "    if (validTo > MIN_TIME) {\n"
            "        nextChange = std::min(nextChange, validTo);\n"
            "    }\n"
            "    return chargingSchedule.calculateLimit(t, startOfCharging, limit, nextChange);")

    # Same sample-time correction as the staged 2.0.1 post-stop fix.
    header, evse = root / "src/evse.h", root / "src/evse.cpp"
    replace(header, "    std::string status;", "    std::string status;\n    void updateMeter();")
    replace(header, "    int getEnergy() {\n", "    int getEnergy() {\n        updateMeter();\n")
    for old in ("        return simulate_energy;", "        return simulate_power;"):
        replace(evse, old, "        updateMeter();\n" + old)
    replace(evse, "            return (int32_t) (simulate_power >",
            "            updateMeter();\n            return (int32_t) (simulate_power >")
    replace(evse, "int Evse::getPower() {\n", "int Evse::getPower() {\n    updateMeter();\n")
    replace(evse, "    bool simulate_isCharging =",
            "    updateMeter();\n}\n\nvoid Evse::updateMeter() {\n"
            "    const auto now = mocpp_tick_ms();\n"
            "    if (simulate_power >= 1.f) {\n"
            "        simulate_energy += (float) (now - simulate_energy_track_time)\n"
            "            * simulate_power * (0.001f / 3600.f);\n"
            "    }\n    simulate_energy_track_time = now;\n\n"
            "    bool simulate_isCharging =")
    replace(evse, "        if (simulate_power >= 1.f) {\n"
            "            simulate_energy += (float) (mocpp_tick_ms() - simulate_energy_track_time) * simulate_power * (0.001f / 3600.f);\n"
            "        }\n\n", "")
    replace(evse, "        simulate_energy_track_time = mocpp_tick_ms();",
            "        // Simulation noise must never exceed the permitted ceiling.\n"
            "        simulate_power = std::min(simulate_power, limit_power);")
    web = root / "src/net_mongoose.cpp"
    replace(web,
            'opts.extra_headers = "Content-Type: text/html\\r\\nContent-Encoding: gzip\\r\\n";',
            'opts.extra_headers = "Cache-Control: no-cache\\r\\nVary: Accept-Encoding\\r\\n";')
    replace(web, 'mg_http_serve_file(c, message_data, "public/bundle.html.gz", &opts);',
            'mg_http_serve_file(c, message_data, "public/bundle.html", &opts);')
    bundle = root / "public/bundle.html.gz"
    text = gzip.decompress(bundle.read_bytes()).decode()
    replacements = (
        ('"http://localhost:8000/api"', 'new URL("api",window.location.href).href'),
        ("t.evPlugged===O&&t.evReady===x&&t.evseReady===E",
         "t.evPlugged===e&&t.evsePlugged===e&&t.evReady===n&&t.evseReady===r"),
        ("DateFormatter.fullDate(new Date)", "(new Date).toLocaleString()"),
        (',onClick:function(){M("Charging")}', ""),
    )
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError("upstream UI context changed")
        text = text.replace(old, new)
    text, count = re.subn(r"evPlugged:([A-Za-z_$][A-Za-z0-9_$]*),",
                         lambda m: f"evPlugged:{m[1]},evsePlugged:{m[1]},", text)
    if count != 2:
        raise ValueError("upstream plug controls changed")
    bundle.with_suffix("").write_text(text)
    bundle.write_bytes(gzip.compress(text.encode(), mtime=0))


if __name__ == "__main__":
    prepare(Path(sys.argv[1]).resolve())
