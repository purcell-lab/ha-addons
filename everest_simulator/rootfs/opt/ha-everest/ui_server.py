"""Loopback-only Status UI and bounded EV-simulator controls.

Reads EVerest's API module and the OCPP module's session cost over the
private MQTT bus, and the libocpp message log. The only writes are four
fixed car-simulator commands; no OCPP message, configuration or charging
profile can be sent from this UI.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ocpp_log  # noqa: E402

ROOT = Path(__file__).resolve().parent
WWW = ROOT / "www"
DATA = Path(os.environ.get("HA_EVEREST_DATA", "/data"))
RUN = Path(os.environ.get("HA_EVEREST_RUN", "/run/ha-everest"))
LOGS = DATA / "everest" / "ocpp_logs"
EVSE = "evse_manager_1"
SESSION_COST_TOPIC = "everest/modules/ocpp/impl/session_cost/var"
TOPICS = {
    f"everest_api/{EVSE}/var/session_info": "session_info",
    f"everest_api/{EVSE}/var/powermeter": "powermeter",
    f"everest_api/{EVSE}/var/limits": "limits",
    f"everest_api/{EVSE}/var/hardware_capabilities": "hardware_capabilities",
    "everest_api/ocpp/var/connection_status": "ocpp_connection",
    "everest_api/ocpp/var/charging_schedules": "charging_schedules",
    # The OCPP201 module's session_cost implementation (framework topic, not
    # the API module), wrapped as {"name": "session_cost", "data": <value>}.
    SESSION_COST_TOPIC: "session_cost",
}
CARSIM = "everest_external/nodered/1/carsim/cmd/"
CONTENT = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
           ".css": "text/css; charset=utf-8"}


def ev_commands(state):
    amps = int(state.get("max_current_a", 32))
    phases = int(state.get("phases", 1))
    draw = f"draw_power_regulated {amps},{phases};sleep 86400"
    return {
        "plugin": ("execute_charging_session", f"sleep 1;iec_wait_pwr_ready;sleep 1;{draw}"),
        "pause": ("modify_charging_session", "pause;sleep 86400"),
        "resume": ("modify_charging_session", draw),
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
        if message.topic == SESSION_COST_TOPIC:
            key, value = unwrap_var(value)
            if key is None:
                return
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


def unwrap_var(message):
    """("session_cost", value) of an EVerest framework var message, or
    (None, None) for any other var on that topic (tariff_message)."""
    if isinstance(message, dict) and message.get("name") == "session_cost" and "data" in message:
        return "session_cost", message["data"]
    return None, None


def _minor(amount, decimals):
    """EVerest MoneyAmount {value} in minor units to a currency amount."""
    value = amount.get("value") if isinstance(amount, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= 12:
        decimals = 2  # the type's default
    return round(value / 10 ** decimals, decimals)


def _prices(components):
    """EVerest ChargingPriceComponent list to {category: amount}."""
    prices = {}
    for component in components if isinstance(components, list) else []:
        if not isinstance(component, dict):
            continue
        price = component.get("price") or {}
        currency = price.get("currency") or {}
        prices[component.get("category") or "Other"] = _minor(price.get("value"), currency.get("decimals"))
    return prices


def session_price(cost):
    """Readable summary of an EVerest SessionCost (OCPP201 publishes one for
    each CostUpdated, and for a TransactionEventResponse with totalCost, when
    TariffCostCtrlr Cost is enabled). California Pricing customData supplies
    the current and next-period prices and the price text."""
    if not isinstance(cost, dict):
        return None
    currency = cost.get("currency") or {}
    decimals = currency.get("decimals")
    chunks = [c for c in cost.get("cost_chunks") or [] if isinstance(c, dict)]
    totals = [_minor(c.get("cost"), decimals) for c in chunks]
    totals = [t for t in totals if t is not None]
    last = chunks[-1] if chunks else {}
    now = _prices(cost.get("charging_price"))
    nxt = cost.get("next_period") if isinstance(cost.get("next_period"), dict) else {}
    upcoming = _prices(nxt.get("charging_price"))
    idle = (cost.get("idle_price") or {}).get("hour_price") or {}
    messages = [m.get("content") for m in cost.get("message") or [] if isinstance(m, dict) and m.get("content")]
    return {
        "session_id": cost.get("session_id"),
        "status": cost.get("status"),
        "currency": currency.get("code"),
        "total_cost": round(sum(totals), 12) if totals else None,
        "kwh_price": now.get("Energy"),
        "hour_price": now.get("Time"),
        "flat_fee": now.get("FlatFee"),
        "idle_hour_price": _minor(idle.get("value"), (idle.get("currency") or {}).get("decimals")),
        "next_at": nxt.get("timestamp_from"),
        "next_kwh_price": upcoming.get("Energy"),
        "next_hour_price": upcoming.get("Time"),
        "text": " / ".join(messages) or None,
        "qr_code": cost.get("qr_code"),
        "timestamp": last.get("timestamp_to"),
        "meter_wh": last.get("metervalue_to"),
    }


def read_state():
    try:
        return json.loads((RUN / "state.json").read_text())
    except (OSError, ValueError):
        return {}


def price_status(entry):
    """Latest session cost with its age; kept until the next one arrives."""
    if not entry:
        return None
    return {"value": session_price(entry.get("value")), "age_s": entry.get("age_s")}


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
        "session_cost": price_status(data.get("session_cost")),
        "last_command": bus.last_command,
        "server_time": time.time(),
    }


def profiles():
    text = ocpp_log.read_logs(LOGS)
    events = ocpp_log.profile_events(text)
    latest = ocpp_log.latest_profile(events)
    return {"latest_profile": latest,
            "latest_tx_profile": ocpp_log.latest_tx_profile(events), "recent": events,
            # Price information in the latest profile (stored by libocpp, not acted on).
            "price_schedules": ocpp_log.price_schedules(latest),
            # CostUpdated and OCPP 2.1 tariff requests with the station's replies.
            "pricing": ocpp_log.pricing_events(text)}


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
            if not path.startswith("/api/ev/") or name not in ev_commands({}):
                return self.send_body(404, {"error": "not found"})
            # Custom header forces a CORS preflight for any cross-site request.
            if self.headers.get("X-HA-EVerest") != "1":
                return self.send_body(403, {"error": "missing request header"})
            if int(self.headers.get("Content-Length") or 0) > 0:
                return self.send_body(400, {"error": "no body accepted"})
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
