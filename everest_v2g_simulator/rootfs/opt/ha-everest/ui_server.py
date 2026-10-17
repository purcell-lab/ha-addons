"""Loopback-only Status UI, diagnostics and bounded EV-simulator controls.

Reads EVerest's API module over the private MQTT bus and the libocpp message
log. The only writes are three fixed car-simulator commands and the
discovery self-test (two SDP requests on the private link); no OCPP message,
configuration or charging profile can be sent from this UI.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import configure  # noqa: E402
import diag  # noqa: E402
import ocpp_log  # noqa: E402

ROOT = Path(__file__).resolve().parent
WWW = ROOT / "www"
DATA = Path(os.environ.get("HA_EVEREST_DATA", "/data"))
RUN = Path(os.environ.get("HA_EVEREST_RUN", "/run/ha-everest"))
LOGS = DATA / "everest" / "ocpp_logs"
EVSE = "evse_manager_1"
TOPICS = {
    f"everest_api/{EVSE}/var/session_info": "session_info",
    f"everest_api/{EVSE}/var/powermeter": "powermeter",
    f"everest_api/{EVSE}/var/limits": "limits",
    f"everest_api/{EVSE}/var/hardware_capabilities": "hardware_capabilities",
    "everest_api/ocpp/var/connection_status": "ocpp_connection",
    "everest_api/ocpp/var/charging_schedules": "charging_schedules",
}
CARSIM = "everest_external/nodered/1/carsim/cmd/"
CONTENT = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
           ".css": "text/css; charset=utf-8"}


def ev_commands(state):
    """Fixed EV actions. Direction and power come only from the CSMS (OCPP)."""
    return {
        "plugin": ("execute_charging_session", configure.ev_session()),
        "stop": ("modify_charging_session", "iso_stop_charging;iso_wait_v2g_session_stopped;unplug"),
        "unplug": ("modify_charging_session", "unplug"),
    }


class Bus:
    def __init__(self):
        self.values = {}
        self.updated = {}
        self.lock = threading.Lock()
        self.client = None
        self.last_command = None

    def start(self):
        import paho.mqtt.client as mqtt
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)  # paho >= 2
        except AttributeError:
            client = mqtt.Client()  # paho 1.x (Debian 12)
        client.on_connect = lambda c, u, f, rc: [c.subscribe(t) for t in TOPICS]
        client.on_message = self.on_message
        client.reconnect_delay_set(1, 10)
        client.connect_async("127.0.0.1", 1883)
        client.loop_start()
        self.client = client

    def on_message(self, client, userdata, message):
        key = TOPICS.get(message.topic)
        if not key:
            return
        try:
            value = json.loads(message.payload.decode("utf-8"))
        except ValueError:
            value = message.payload.decode("utf-8", "replace")
        with self.lock:
            self.values[key] = value
            self.updated[key] = time.time()

    def snapshot(self):
        with self.lock:
            now = time.time()
            return {k: {"value": v, "age_s": round(now - self.updated[k], 1)}
                    for k, v in self.values.items()}

    def send(self, name, state):
        topic, payload = ev_commands(state)[name]
        info = self.client.publish(CARSIM + topic, payload, qos=1)
        self.last_command = {"command": name, "at": time.time()}
        return info.rc == 0


def read_state():
    try:
        return json.loads((RUN / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def status(bus):
    data = bus.snapshot()
    schedules = (data.get("charging_schedules", {}).get("value") or {})
    if isinstance(schedules, dict):
        evse_schedules = [s for s in schedules.get("schedules", []) if s.get("evse") == 1]
    else:
        evse_schedules = []
    return {
        "app": read_state(),
        "evse": {k: data.get(k) for k in ("session_info", "powermeter", "limits", "hardware_capabilities")},
        "ocpp_connection": data.get("ocpp_connection"),
        "composite_schedule": evse_schedules[0] if evse_schedules else None,
        "last_command": bus.last_command,
        "server_time": time.time(),
    }


SELFTEST_WAIT_S = 20


class SelftestLock:
    """File lock shared by the App process (self-test at start) and this
    service, so a plug-in never overlaps a self-test."""

    def __init__(self, blocking_s=0):
        self.blocking_s, self.handle = blocking_s, None

    def __enter__(self):
        import fcntl
        RUN.mkdir(parents=True, exist_ok=True)
        self.handle = open(RUN / "selftest.lock", "a")
        deadline = time.monotonic() + self.blocking_s
        while True:
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.2)

    def __exit__(self, *exc):
        self.handle.close()  # releases the lock


def last_selftest():
    try:
        return json.loads((RUN / "selftest.json").read_text())
    except (OSError, ValueError):
        return None


def run_selftest(source, lock_held=False):
    """Run the discovery self-test once at a time; record and log the result."""
    if lock_held:  # the caller already holds the self-test lock
        return _selftest(source)
    with SelftestLock() as locked:
        return _selftest(source) if locked else None


def _selftest(source):
    """Run the probes, then record and log the result."""
    result = diag.selftest()
    result["charger_sdp_blocked"] = bool(read_state().get("charger_sdp_blocked"))
    result["summary"] = diag.summary(result)
    result["source"] = source
    configure.atomic_write(RUN / "selftest.json", json.dumps(result), mode=0o644)
    print(f"{result['summary']} ({source})", flush=True)
    if not result["pass"]:
        print("Discovery diagnostics: " + json.dumps(diag.snapshot(), separators=(",", ":")), flush=True)
    return result


def diagnostics(brief=False):
    body = {"selftest": last_selftest()}
    if not brief:
        body["snapshot"] = diag.snapshot()
    return body


def profiles():
    events = ocpp_log.profile_events(ocpp_log.read_logs(LOGS))
    return {"latest_profile": ocpp_log.latest_profile(events),
            "latest_tx_profile": ocpp_log.latest_tx_profile(events), "recent": events}


def make_handler(bus):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ha-everest"

        def send_body(self, code, body, kind="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/status":
                return self.send_body(200, status(bus))
            if path == "/api/diagnostics":
                return self.send_body(200, diagnostics(brief="brief=1" in self.path))
            if path == "/api/profiles":
                try:
                    return self.send_body(200, profiles())
                except OSError:
                    return self.send_body(503, {"error": "message log unavailable"})
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            target = WWW / name
            if "/" in name or target.suffix not in CONTENT or not target.is_file():
                return self.send_body(404, {"error": "not found"})
            return self.send_body(200, target.read_bytes(), CONTENT[target.suffix])

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            name = path.rsplit("/", 1)[-1]
            selftest = path == "/api/diag/selftest"
            if not selftest and (not path.startswith("/api/ev/") or name not in ev_commands({})):
                return self.send_body(404, {"error": "not found"})
            # Custom header forces a CORS preflight for any cross-site request.
            if self.headers.get("X-HA-EVerest") != "1":
                return self.send_body(403, {"error": "missing request header"})
            if int(self.headers.get("Content-Length") or 0) > 0:
                return self.send_body(400, {"error": "no body accepted"})
            if selftest:
                # Probes would be ignored during a session, and must never
                # touch a real one: only with the EV unplugged.
                info = (bus.snapshot().get("session_info") or {}).get("value") or {}
                if info.get("state") != "Unplugged":
                    return self.send_body(409, {"error": "unplug the simulated EV first",
                                                "state": info.get("state")})
                result = run_selftest("on request")
                if result is None:
                    return self.send_body(409, {"error": "self-test already running"})
                return self.send_body(200, result)
            # Wait for a running self-test; its probes and the charger's
            # session clean-up must not overlap a plug-in.
            with SelftestLock(SELFTEST_WAIT_S) as free:
                if not free:
                    return self.send_body(409, {"error": "discovery self-test still running"})
                ok = bus.send(name, read_state())
            return self.send_body(200 if ok else 503, {"sent": ok, "command": name})

        def log_message(self, *args):
            pass

    return Handler


def main():
    bus = Bus()
    bus.start()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), make_handler(bus))
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
