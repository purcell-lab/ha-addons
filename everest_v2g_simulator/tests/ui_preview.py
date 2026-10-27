"""Preview the Status page without building the image.

Serves rootfs/opt/ha-everest/www with recorded API responses (shapes from a
live 0.3.1 App on the Green, 27 October 2026), so a layout change can be seen
in a browser in seconds:

    python3 everest_v2g_simulator/tests/ui_preview.py [--port 8099]
    open http://127.0.0.1:8099/?scenario=charging

Scenarios: unplugged, auth, charging, discharging (the page keeps its query
string, so the scenario sticks). Commands and charging needs are accepted and
kept in memory; nothing reaches EVerest.

    python3 everest_v2g_simulator/tests/ui_preview.py --screenshots DIR

renders every scenario at 1440 and 390 px wide with the pre-installed Chromium
(Playwright), writes PNGs to DIR, and fails on a script error or horizontal
overflow.
"""
import argparse
import copy
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

WWW = Path(__file__).resolve().parents[1] / "rootfs/opt/ha-everest/www"
SCENARIOS = ("unplugged", "auth", "charging", "discharging")
CONTENT = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
           ".css": "text/css; charset=utf-8"}

STATUS = {
    "app": {"charge_point_id": "SIM-EV-EVEREST-V2G-03", "csms_configured": True, "ocpp_version_option": "2.1",
            "offered_subprotocols": ["ocpp2.1", "ocpp2.0.1"], "csms_scheme": "ws", "security_profile": 1,
            "csms_trust": None, "max_power_kw": 25, "charger": "DC bidirectional (ISO 15118-20 DC_BPT)",
            "negotiated": "ocpp2.1", "ha_control": True, "ev_charging_needs": True, "ev_stack_restarts": 0,
            "charger_sdp_blocked": False},
    "evse": {
        "session_info": {"value": {"state": "Unplugged"}, "age_s": 0.9},
        "powermeter": {"value": {"meter_id": "DC_POWERMETER", "energy_Wh_import": {"total": 0},
                                 "energy_Wh_export": {"total": 0}, "power_W": {"total": 0},
                                 "voltage_V": {"DC": 0}, "current_A": {"DC": 0}}, "age_s": 0.1},
    },
    "ocpp_connection": {"value": "connected", "age_s": 0.9},
    "composite_schedule": {"charging_rate_unit": "W", "duration": 600, "evse": 1,
                           "charging_schedule_period": [{"limit": 25000, "stack_level": 0, "start_period": 0}]},
    "session_cost": None,
    "der": {"control_types": ["FixedPFAbsorb", "FixedPFInject", "FixedVar", "LimitMaxDischarge"],
            "active": [], "active_at": None, "relay": "accepted"},
    "ev_watchdog": {"ev_session": "ok", "recoveries": 0, "last_recovery": None},
    "ev": {"needs": {"mode": "allow_discharge", "target_soc": 80, "min_soc": 30, "start_soc": 50, "ready_by": None},
           "soc": 50, "in_session": False, "capacity_wh": 60000,
           "iso20": {"mode": "allow_discharge", "departure_time": 86400, "present_soc": 50, "min_soc": 30,
                     "target_soc": 80, "max_soc": 100, "target_wh": 18000, "max_wh": 30000, "min_wh": -12000,
                     "v2x_min_wh": -12000, "v2x_max_wh": 30000, "max_discharge_w": 25000,
                     "min_discharge_w": 300, "max_discharge_a": 66, "remaining_time_to_target_soc": 2592,
                     "battery_capacity_wh": 60000},
           "ev_info": None, "selected_protocol": {"value": "Unknown", "age_s": 0.9}},
}

SETPOINT = {"startPeriod": 0, "limit": 25000, "dischargeLimit": -25000, "setpoint": -9500,
            "operationMode": "CentralSetpoint"}
NEEDS_EVENT = {"message_id": "needs-1", "action": "NotifyEVChargingNeeds", "received": "2026-10-26T09:51:33.813Z",
               "responded": "2026-10-26T09:51:34.289Z", "status": "NoChargingProfile", "status_info": None,
               "payload": {"evseId": 1, "chargingNeeds": {
                   "requestedEnergyTransfer": "DC_BPT", "controlMode": "DynamicControl", "mobilityNeedsMode": "EVCC",
                   "v2xChargingParameters": {"evTargetEnergyRequest": 18000, "evMaxEnergyRequest": 30000,
                                             "evMinEnergyRequest": -12000, "evMinV2XEnergyRequest": -12000,
                                             "evMaxV2XEnergyRequest": 30000, "maxDischargePower": -25000}}}}


def status(scenario, needs):
    s = copy.deepcopy(STATUS)
    s["server_time"] = time.time()
    s["ev"]["needs"] = needs
    s["ev"]["iso20"]["at"] = time.time()
    meter = s["evse"]["powermeter"]["value"]
    if scenario == "unplugged":
        return s
    s["ev"]["in_session"] = True
    s["ev"]["selected_protocol"]["value"] = "ISO15118_20_DC"
    s["ev"]["ev_info"] = {"value": {"evcc_id": "WMIV1234567890ABCDEX", "soc": 50, "maximum_voltage_limit": 900}}
    if scenario == "auth":
        s["evse"]["session_info"]["value"]["state"] = "AuthRequired"
        return s
    s["evse"]["session_info"]["value"]["state"] = "Charging"
    charging = scenario == "charging"
    power = 11000 if charging else -9500
    meter.update(power_W={"total": power}, voltage_V={"DC": 380.0}, current_A={"DC": round(power / 380, 1)},
                 energy_Wh_import={"total": 812.4 if charging else 2.5},
                 energy_Wh_export={"total": 0 if charging else 224.1})
    s["ev"]["soc"] = 51.4 if charging else 49.7
    if not charging:
        s["composite_schedule"]["charging_schedule_period"] = [
            {"limit": 25000, "discharge_limit": -25000, "setpoint": -9500, "start_period": 0}]
    s["session_cost"] = {"value": {"currency": "AUD", "kwh_price": 0.2251, "next_kwh_price": 0.3105,
                                   "next_at": "2026-10-27T02:00:00Z", "total_cost": 0.42, "status": "Charging",
                                   "timestamp": "2026-10-27T01:20:00Z", "session_id": "af5e641a"}, "age_s": 3}
    return s


def profiles(scenario):
    if scenario in ("unplugged", "auth"):
        return {"latest_profile": None, "latest_tx_profile": None, "recent": [], "price_schedules": [],
                "pricing": [], "der": [], "charging_needs": [NEEDS_EVENT] if scenario == "auth" else []}
    tx = {"message_id": "tx-1", "action": "SetChargingProfile", "received": "2026-10-27T01:08:46.000Z",
          "status": "Accepted", "payload_bytes": 420, "omitted": [],
          "payload": {"evseId": 1, "chargingProfile": {
              "id": 9001, "stackLevel": 1, "chargingProfilePurpose": "TxProfile",
              "chargingProfileKind": "Absolute", "transactionId": "af5e641a-f3c5-42f4-a97a-d4acb1bef790",
              "chargingSchedule": [{"id": 9001, "duration": 300, "chargingRateUnit": "W",
                                    "chargingSchedulePeriod": [SETPOINT]}]}}}
    return {"latest_profile": tx, "latest_tx_profile": tx, "recent": [tx], "price_schedules": [],
            "pricing": [], "der": [], "charging_needs": [NEEDS_EVENT]}


DIAGNOSTICS = {"selftest": {"pass": True, "source": "at start", "at": 1793012140,
                            "unicast": {"result": "received"}, "multicast": {"result": "received"},
                            "capture": {}},
               "snapshot": {"links": {"v2g0": {"addresses": ["fe80::1"]}, "v2g1": {"addresses": ["fe80::2"]}},
                            "firewall": {"rules": [{"rule": "private V2G link", "packets": 42}]}}}


def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def scenario(self):
            referer = urlparse(self.headers.get("Referer") or "")
            asked = parse_qs(urlparse(self.path).query).get("scenario") or parse_qs(referer.query).get("scenario")
            return asked[0] if asked and asked[0] in SCENARIOS else state["scenario"]

        def send(self, code, body, kind="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlparse(self.path).path
            scenario = self.scenario()
            if path == "/api/status":
                return self.send(200, status(scenario, state["needs"]))
            if path == "/api/profiles":
                return self.send(200, profiles(scenario))
            if path == "/api/diagnostics":
                return self.send(200, DIAGNOSTICS)
            if path == "/favicon.ico":
                return self.send(204, b"", "image/x-icon")
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            target = WWW / name
            if "/" in name or target.suffix not in CONTENT or not target.is_file():
                return self.send(404, {"error": "not found"})
            return self.send(200, target.read_bytes(), CONTENT[target.suffix])

        def do_POST(self):
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            if path == "/api/ev/needs":
                state["needs"] = {**state["needs"], **json.loads(body or b"{}")}
                return self.send(200, {"needs": state["needs"]})
            if path.startswith("/api/ev/") or path == "/api/diag/selftest":
                return self.send(200, {"sent": True, "command": path.rsplit("/", 1)[-1]})
            return self.send(404, {"error": "not found"})
    return Handler


def serve(port, scenario="charging"):
    state = {"scenario": scenario, "needs": dict(STATUS["ev"]["needs"])}
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def screenshots(out):
    from playwright.sync_api import sync_playwright
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    server = serve(0)
    base = f"http://127.0.0.1:{server.server_port}/"
    problems = []
    with sync_playwright() as p:
        # The pre-installed Chromium when the Python package expects another build.
        chromium = Path("/opt/pw-browsers/chromium")
        browser = p.chromium.launch(**({"executable_path": str(chromium)} if chromium.exists() else {}))
        for width, height in ((1440, 1000), (390, 844)):
            for scenario in SCENARIOS:
                page = browser.new_page(viewport={"width": width, "height": height})
                errors = []
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
                page.on("console", lambda m, errors=errors: m.type == "error" and errors.append(m.text))
                page.goto(base + "?scenario=" + scenario)
                page.wait_for_timeout(1500)
                overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                page.screenshot(path=str(out / f"{scenario}-{width}.png"), full_page=True)
                if errors:
                    problems.append(f"{scenario} at {width} px: {errors}")
                if overflow > 0:
                    problems.append(f"{scenario} at {width} px: {overflow} px horizontal overflow")
                page.close()
        browser.close()
    server.shutdown()
    for line in problems:
        print("FAIL", line)
    print(f"{len(SCENARIOS) * 2} screenshots in {out}")
    return 1 if problems else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--scenario", choices=SCENARIOS, default="charging")
    parser.add_argument("--screenshots", metavar="DIR")
    args = parser.parse_args()
    if args.screenshots:
        return screenshots(args.screenshots)
    server = serve(args.port, args.scenario)
    print(f"Status page preview on http://127.0.0.1:{server.server_port}/?scenario={args.scenario} (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
