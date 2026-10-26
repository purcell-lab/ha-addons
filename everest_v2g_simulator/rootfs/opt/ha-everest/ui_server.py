"""Loopback-only Status UI, diagnostics and bounded EV-simulator controls.

Reads EVerest's API module and the OCPP module's session cost over the
private MQTT bus, and the libocpp message log. The only writes are three
fixed car-simulator commands, the simulated EV's charging needs (what the EV
asks for over ISO 15118-20, ev_model.py) and the discovery self-test (two
SDP requests on the private link); no OCPP message, configuration or
charging profile can be sent from this UI, and the CSMS still sets power
and direction. The EV watchdog uses the same unplug and plug-in commands.
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
import ev_model  # noqa: E402
import ocpp_log  # noqa: E402

ROOT = Path(__file__).resolve().parent
WWW = ROOT / "www"
DATA = Path(os.environ.get("HA_EVEREST_DATA", "/data"))
RUN = Path(os.environ.get("HA_EVEREST_RUN", "/run/ha-everest"))
LOGS = DATA / "everest" / "ocpp_logs"
EVSE = "evse_manager_1"
# The OCPP module's session_cost implementation (framework topic, not the API
# module). EVerest 2026.10 publishes each var on .../var/<name> as
# {"msg_type": "Var", "data": {"data": <value>}} (2025.10.0: one .../var
# topic with {"name": <name>, "data": <value>}).
SESSION_COST_TOPIC = "everest/modules/ocpp/impl/session_cost/var/session_cost"
TOPICS = {
    f"everest_api/{EVSE}/var/session_info": "session_info",
    f"everest_api/{EVSE}/var/powermeter": "powermeter",
    f"everest_api/{EVSE}/var/limits": "limits",
    f"everest_api/{EVSE}/var/hardware_capabilities": "hardware_capabilities",
    # What the charger received from the EV over ISO 15118 (EvseManager EVInfo)
    # and the negotiated protocol (for example ISO15118-20).
    f"everest_api/{EVSE}/var/ev_info": "ev_info",
    f"everest_api/{EVSE}/var/selected_protocol": "selected_protocol",
    "everest_api/ocpp/var/connection_status": "ocpp_connection",
    "everest_api/ocpp/var/charging_schedules": "charging_schedules",
    SESSION_COST_TOPIC: "session_cost",
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

    def send(self, name, state, source="operator"):
        topic, payload = ev_commands(state)[name]
        info = self.client.publish(CARSIM + topic, payload, qos=1)
        self.last_command = {"command": name, "at": time.time(), "source": source}
        return info.rc == 0


def unwrap_var(message):
    """("session_cost", value) of an EVerest framework var message on the
    session_cost topic, or (None, None) for anything else."""
    if not isinstance(message, dict):
        return None, None
    if message.get("msg_type") == "Var" and isinstance(message.get("data"), dict) and "data" in message["data"]:
        return "session_cost", message["data"]["data"]
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
    """Readable summary of an EVerest SessionCost (the OCPP module publishes one for
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


DER_PAYLOADS = ("curve", "enter_service", "freq_droop", "fixed_pf", "fixed_var", "gradient",
                "limit_max_discharge")


def der_directive(directive):
    """One grid_support Directive (types/grid_support.yaml) for display."""
    payload = next(((k, directive[k]) for k in DER_PAYLOADS if k in directive), (None, None))
    detail = None
    if payload[0] == "limit_max_discharge":
        pct = (payload[1] or {}).get("pct_max_discharge_power")
        detail = f"{pct:g} % of rated discharge power" if isinstance(pct, (int, float)) else "limit"
    elif payload[0] == "curve":
        detail = f"curve, {len((payload[1] or {}).get('curve_data') or [])} points"
    elif payload[0] == "fixed_pf":
        detail = f"power factor {(payload[1] or {}).get('displacement')}"
    elif payload[0] == "fixed_var":
        value = payload[1] or {}
        detail = f"{value.get('setpoint')} {value.get('unit')}"
    elif payload[0]:
        detail = payload[0].replace("_", " ")
    return {"id": directive.get("id"), "type": directive.get("directive_type"),
            "priority": directive.get("priority"), "is_default": directive.get("is_default"),
            "start_time": directive.get("start_time"), "duration_s": directive.get("duration_s"),
            "detail": detail}


def der_status(path=None):
    """What the HaGridSupport module recorded: the declared capability and the
    active DER directive set OCPPmulti pushed (recorded, never applied)."""
    try:
        state = json.loads((path or RUN / configure.DER_STATE).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    capability = ((state.get("capability") or {}).get("capability") or {})
    active = state.get("active") or {}
    return {
        "control_types": capability.get("supported_types") or [],
        "nameplate": capability.get("nameplate"),
        "capability_at": state.get("capability_at"),
        "active": [der_directive(d) for d in active.get("directives") or [] if isinstance(d, dict)],
        "active_at": state.get("active_at"),
        "updates": state.get("updates"),
        "relay": state.get("relay"),
        "alarms": state.get("alarms") or [],
        # V2XChargingCtrlr SupportedOperationModes as written at start.
        "v2x_operation_modes": state.get("v2x_operation_modes"),
    }


class EV:
    """The simulated EV's needs and battery model (ev_model.py). Refreshes
    the file the patched Josev reads (ev-iso20.json) every second."""

    def __init__(self, bus, data=DATA, run=RUN, clock=time.time):
        self.bus, self.data, self.run, self.clock = bus, data, run, clock
        self.needs = ev_model.load_needs(data / ev_model.NEEDS_FILE)
        self.battery = ev_model.Battery()
        self.soc, self.in_session, self.iso20 = float(self.needs["start_soc"]), False, None
        self.lock = threading.Lock()

    def set_needs(self, body):
        needs = ev_model.validate_needs(body, self.clock())
        configure.atomic_write(self.data / ev_model.NEEDS_FILE, json.dumps(needs), mode=0o644)
        with self.lock:
            self.needs = needs
        self.tick()
        return needs

    def tick(self):
        data = self.bus.snapshot()
        state = ((data.get("session_info") or {}).get("value") or {}).get("state")
        meter = (data.get("powermeter") or {}).get("value") or {}
        imported = (meter.get("energy_Wh_import") or {}).get("total")
        exported = (meter.get("energy_Wh_export") or {}).get("total")
        rated_w = (read_state().get("max_power_kw") or 0) * 1000
        with self.lock:
            needs = dict(self.needs)
            soc, in_session = self.battery.update(state, imported, exported, needs["start_soc"])
            iso20 = ev_model.iso20_needs(needs, soc, rated_w, self.clock(), self.battery.capacity_wh)
            self.soc, self.in_session, self.iso20 = soc, in_session, iso20
        self.run.mkdir(parents=True, exist_ok=True)
        configure.atomic_write(self.run / ev_model.ISO20_FILE, json.dumps(iso20), mode=0o644)

    def snapshot(self):
        data = self.bus.snapshot()
        with self.lock:
            return {"needs": dict(self.needs), "soc": round(self.soc, 1), "in_session": self.in_session,
                    "capacity_wh": self.battery.capacity_wh, "iso20": self.iso20,
                    "ev_info": data.get("ev_info"), "selected_protocol": data.get("selected_protocol")}

    def run_forever(self, interval=1.0):
        while True:
            try:
                self.tick()
            except Exception as error:  # report, never stop the UI service
                print(f"EV model error ({type(error).__name__}: {error}).", flush=True)
            time.sleep(interval)


def status(bus, watchdog=None, ev=None):
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
        "der": der_status(),
        "last_command": bus.last_command,
        "ev_watchdog": watchdog.snapshot() if watchdog else None,
        "ev": ev.snapshot() if ev else None,
        "server_time": time.time(),
    }


SELFTEST_WAIT_S = 20
NEEDS_MAX_BYTES = 512


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
    # app.py counts the charger's "dlink is not ready" drops (diag.DLINK_NOT_READY).
    result = diag.selftest(ignored=lambda: read_state().get("charger_sdp_dlink_ignored", 0))
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
    text = ocpp_log.read_logs(LOGS)
    events = ocpp_log.profile_events(text)
    latest = ocpp_log.latest_profile(events)
    return {"latest_profile": latest,
            "latest_tx_profile": ocpp_log.latest_tx_profile(events), "recent": events,
            # Price information in the latest profile (stored by libocpp, not acted on).
            "price_schedules": ocpp_log.price_schedules(latest),
            # CostUpdated and OCPP 2.1 tariff requests with the station's replies.
            "pricing": ocpp_log.pricing_events(text),
            # OCPP 2.1 DER control requests with the station's replies.
            "der": ocpp_log.der_events(text),
            # The station's NotifyEVChargingNeeds with the CSMS's replies.
            "charging_needs": ocpp_log.charging_needs_events(text)}


# Issue #33: when the simulated EV's ISO 15118 session ends before charging
# (for example at the charger's 55 s limit for authorisation), Josev
# starts no new session and EvManager refuses a new plug-in until the EV is
# unplugged. app.py records Josev's give-up line (ev_gave_up_at); this
# watchdog then does the manual recovery: unplug, wait, plug in. It never
# acts while power flows, after an operator command or while unplugged.
RECOVERY_GRACE_S = 5
RECOVERY_SETTLE_S = 10
RECOVERY_UNPLUG_S = 60
MAX_RECOVERIES = 3
POWER_FLOWING_W = 50
NOT_PLUGGED = (None, "Unplugged", "Disabled")


def recovery_decision(gave_up_at, handled_at, state, power, operator_at, attempts, now):
    """What to do about the EV giving up: None (nothing new), "wait",
    "recover" or "skip: <reason>"."""
    if not isinstance(gave_up_at, (int, float)) or gave_up_at <= handled_at:
        return None
    if now - gave_up_at < RECOVERY_GRACE_S:
        return "wait"  # an unplug in progress reaches session_info first
    if isinstance(power, (int, float)) and abs(power) > POWER_FLOWING_W:
        return "skip: power flowing"
    if isinstance(operator_at, (int, float)) and operator_at >= gave_up_at - RECOVERY_GRACE_S:
        return "skip: operator command"
    if state in NOT_PLUGGED:
        return "skip: not plugged in"
    if attempts >= MAX_RECOVERIES:
        return "skip: retry limit reached; unplug and plug in"
    return "recover"


class Watchdog:
    """Re-plugs the simulated EV after it gives up (see recovery_decision)."""

    def __init__(self, bus, sleep=time.sleep, clock=time.time):
        self.bus, self.sleep, self.clock = bus, sleep, clock
        self.handled_at = 0.0
        self.attempts = 0
        self.recoveries = 0
        self.ev_session = "ok"
        self.last_recovery = None

    def snapshot(self):
        return {"ev_session": self.ev_session, "recoveries": self.recoveries,
                "last_recovery": self.last_recovery}

    def reading(self):
        data = self.bus.snapshot()
        state = ((data.get("session_info") or {}).get("value") or {}).get("state")
        meter = (data.get("powermeter") or {}).get("value") or {}
        return state, (meter.get("power_W") or {}).get("total")

    def tick(self):
        now = self.clock()
        state, power = self.reading()
        command = self.bus.last_command or {}
        operator_at = command.get("at") if command.get("source", "operator") == "operator" else None
        if isinstance(power, (int, float)) and abs(power) > POWER_FLOWING_W:
            self.attempts = 0  # a working session resets the retry limit
        elif command.get("command") == "plugin" and operator_at and operator_at > self.handled_at:
            self.attempts = 0
        gave_up_at = read_state().get("ev_gave_up_at")
        decision = recovery_decision(gave_up_at, self.handled_at, state, power,
                                     operator_at, self.attempts, now)
        if decision is None:
            return None
        if decision == "wait":
            self.ev_session = "gave_up"
            return decision
        self.handled_at = gave_up_at
        if decision == "recover":
            self.attempts += 1
            self.ev_session = "recovering"
            print("EV watchdog: the simulated EV gave up its ISO 15118 session while plugged in; "
                  f"unplugging and plugging in again (attempt {self.attempts} of {MAX_RECOVERIES}).",
                  flush=True)
            result = self.recover()
            # Ignore anything the old EV stack logged during the recovery.
            self.handled_at = max(gave_up_at, self.clock())
            ok = result == "re-plugged"
            self.recoveries += ok
            self.ev_session = "ok" if ok else "gave_up"
        else:
            result = "skipped (" + decision[len("skip: "):] + ")"
            self.ev_session = "gave_up" if "retry limit" in decision else "ok"
        self.last_recovery = {"at": now, "result": result, "attempt": self.attempts}
        print(f"EV watchdog: {result}.", flush=True)
        return decision

    def recover(self):
        if not self.bus.send("unplug", read_state(), source="watchdog"):
            return "failed: unplug not sent"
        waited = 0.0
        while self.reading()[0] != "Unplugged":
            if waited >= RECOVERY_UNPLUG_S:
                return "failed: still plugged in after unplug"
            self.sleep(0.5)
            waited += 0.5
        # The EV's TLS session closes a few seconds after unplug.
        self.sleep(RECOVERY_SETTLE_S)
        with SelftestLock(SELFTEST_WAIT_S) as free:
            if not free:
                return "failed: discovery self-test still running"
            if not self.bus.send("plugin", read_state(), source="watchdog"):
                return "failed: plug-in not sent"
        return "re-plugged"

    def run(self, interval=1.0):
        while True:
            try:
                self.tick()
            except Exception as error:  # report, never stop the UI service
                print(f"EV watchdog error ({type(error).__name__}: {error}).", flush=True)
            self.sleep(interval)


def make_handler(bus, watchdog=None, ev=None):
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
                return self.send_body(200, status(bus, watchdog, ev))
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
            if path == "/api/ev/needs" and ev is not None:
                return self.post_needs()
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

        def post_needs(self):
            """The EV's charging needs: a small JSON object, nothing else."""
            if self.headers.get("X-HA-EVerest") != "1":
                return self.send_body(403, {"error": "missing request header"})
            if (self.headers.get("Content-Type") or "").split(";")[0].strip() != "application/json":
                return self.send_body(415, {"error": "JSON body required"})
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= NEEDS_MAX_BYTES:
                return self.send_body(400, {"error": "body must be 1 to 512 bytes"})
            try:
                needs = ev.set_needs(json.loads(self.rfile.read(length)))
            except ValueError as error:
                return self.send_body(400, {"error": str(error)})
            return self.send_body(200, {"needs": needs})

        def log_message(self, *args):
            pass

    return Handler


def main():
    bus = Bus()
    bus.start()
    watchdog = Watchdog(bus)
    threading.Thread(target=watchdog.run, daemon=True).start()
    ev = EV(bus)
    threading.Thread(target=ev.run_forever, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), make_handler(bus, watchdog, ev))
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
