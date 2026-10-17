"""Optional Home Assistant control surface (option `ha_control`, default off).

Lets Home Assistant automations and the HA MCP server operate the simulated
EV without opening any port or weakening the Ingress peer rule. All traffic is
outbound from this App to Home Assistant Core through the Supervisor proxy:

- Status: one state object, `sensor.<charge_point_id>_v2g_app` (for example
  `sensor.sim_ev_everest_v2g_01_v2g_app`), refreshed on change and every
  60 s. It is not a registry entity and disappears when HA restarts until the
  next refresh.
- Commands: HA event `everest_v2g_command` with data
  `{"charge_point_id": "<this App's ID>", "command": "<name>"}`. Only
  `plugin`, `stop`, `unplug`, `selftest` and `diagnostics` are accepted, at
  most one every 2 s. Firing events on the HA bus needs an HA admin
  (REST /api/events or WebSocket fire_event) or an automation.
- Results: HA event `everest_v2g_command_result`, and `last_command` on the
  status object.

Direction and power still come only from the CSMS over OCPP. No OCPP
message, profile or configuration can be sent from here. The Supervisor
token is used only for the three endpoints above.
"""
import base64
import json
import os
from pathlib import Path
import re
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))

CORE = os.environ.get("HA_EVEREST_CORE", "http://supervisor/core")
UI = os.environ.get("HA_EVEREST_UI", "http://127.0.0.1:8000")
EVENT = "everest_v2g_command"
RESULT_EVENT = "everest_v2g_command_result"
COMMANDS = ("plugin", "stop", "unplug", "selftest", "diagnostics")
MIN_INTERVAL_S = 2.0
REFRESH_S = 60.0
POLL_S = 5.0


def entity_id(charge_point_id):
    return "sensor." + re.sub(r"[^a-z0-9]+", "_", charge_point_id.lower()).strip("_") + "_v2g_app"


class WebSocket:
    """Minimal RFC 6455 client over plain TCP (the Supervisor proxy is HTTP)."""

    def __init__(self, url, timeout=30):
        match = re.fullmatch(r"ws://([^/:]+)(?::(\d+))?(/.*)", url)
        if not match:
            raise ValueError("ws:// URL required")
        host, port, path = match.group(1), int(match.group(2) or 80), match.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("closed during handshake")
            head += chunk
            if len(head) > 16384:
                raise ConnectionError("oversized handshake")
        header, self.buffer = head.split(b"\r\n\r\n", 1)
        if not header.startswith(b"HTTP/1.1 101"):
            raise ConnectionError(header.split(b"\r\n", 1)[0].decode("latin-1")[:80])

    def _exact(self, count):
        while len(self.buffer) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("connection closed")
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def _send_frame(self, opcode, payload):
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            head = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
        elif length < 65536:
            head = struct.pack("!BBH", 0x80 | opcode, 0xFE, length)
        else:
            head = struct.pack("!BBQ", 0x80 | opcode, 0xFF, length)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(head + mask + masked)

    def send(self, obj):
        self._send_frame(0x1, json.dumps(obj).encode())

    def recv(self):
        """Next text message as JSON; answers pings, joins fragments."""
        message = b""
        while True:
            first, second = self._exact(2)
            opcode, length = first & 0x0F, second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._exact(8))[0]
            if length > 4 * 1024 * 1024:
                raise ConnectionError("oversized frame")
            mask = self._exact(4) if second & 0x80 else None
            payload = self._exact(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x8:
                raise ConnectionError("closed by server")
            if opcode in (0x0, 0x1):
                message += payload
                if first & 0x80:
                    return json.loads(message.decode())

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def http(method, url, token=None, body=None, timeout=10, local=False):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if local:  # the App's own loopback UI service: no token, CSRF header only
        headers["X-HA-EVerest"] = "1"
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        error.close()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, None
    except (OSError, ValueError) as error:  # unreachable, timeout or bad JSON
        return 0, {"error": f"{type(error).__name__}: {error}"[:200]}


def status_attributes(status, diag):
    app = status.get("app") or {}
    evse = status.get("evse") or {}
    session = ((evse.get("session_info") or {}).get("value") or {})
    meter = ((evse.get("powermeter") or {}).get("value") or {})
    power = (meter.get("power_W") or {}).get("total")
    selftest = (diag or {}).get("selftest") or {}
    watchdog = status.get("ev_watchdog") or {}
    return {
        "friendly_name": f"{app.get('charge_point_id', 'EVerest V2G')} V2G App",
        "icon": "mdi:car-electric",
        "charge_point_id": app.get("charge_point_id"),
        "ocpp_negotiated": app.get("negotiated"),
        "csms_configured": app.get("csms_configured"),
        "power_w": power,
        "direction": "discharge" if isinstance(power, (int, float)) and power < -50 else
                     "charge" if isinstance(power, (int, float)) and power > 50 else "idle",
        "discovery_selftest": "passed" if selftest.get("pass") else
                              "failed" if selftest else "not run",
        "discovery_detail": selftest.get("summary"),
        "ev_stack_restarts": app.get("ev_stack_restarts", 0),
        # ok, gave_up or recovering; see the EV watchdog (DOCS.md).
        "ev_session": watchdog.get("ev_session", "unknown"),
        "ev_last_recovery": watchdog.get("last_recovery"),
        "charger_ignoring_discovery": bool(app.get("charger_sdp_blocked")),
        "commands": list(COMMANDS),
        "command_event": EVENT,
    }, session.get("state") or "unknown"


class Bridge:
    def __init__(self, charge_point_id, token, core=CORE, ui=UI, now=time.monotonic, websocket=None):
        self.cpid, self.token, self.core, self.ui, self.now = charge_point_id, token, core, ui, now
        self.websocket = websocket or core.replace("http://", "ws://", 1) + "/websocket"
        self.entity = entity_id(charge_point_id)
        self.last_command = None
        self.last_accepted = -1e9
        self.published = None
        self.published_at = -1e9
        self.lock = threading.Lock()

    # -- commands -------------------------------------------------------
    def handle(self, data):
        """Validate and run one command event; returns the result payload."""
        if not isinstance(data, dict) or data.get("charge_point_id") != self.cpid:
            return None  # addressed to another App: ignore silently
        name = data.get("command")
        result = {"charge_point_id": self.cpid, "command": name, "at": time.time()}
        if name not in COMMANDS:
            result.update(ok=False, error=f"unknown command; use one of {', '.join(COMMANDS)}")
        elif self.now() - self.last_accepted < MIN_INTERVAL_S:
            result.update(ok=False, error="rate limited; retry in 2 s")
        else:
            self.last_accepted = self.now()
            if name == "diagnostics":
                code, body = http("GET", self.ui + "/api/diagnostics", local=True)
            elif name == "selftest":
                code, body = http("POST", self.ui + "/api/diag/selftest", timeout=20, local=True)
            else:
                code, body = http("POST", self.ui + "/api/ev/" + name, local=True)
            result.update(ok=code == 200, http_status=code, response=body)
        with self.lock:
            self.last_command = {k: result.get(k) for k in ("command", "ok", "error", "at")}
        http("POST", f"{self.core}/api/events/{RESULT_EVENT}", self.token, result)
        self.publish(force=True)
        return result

    # -- status ---------------------------------------------------------
    def publish(self, force=False):
        _, status = http("GET", self.ui + "/api/status", local=True)
        _, diag = http("GET", self.ui + "/api/diagnostics?brief=1", local=True)
        attributes, state = status_attributes(status or {}, diag or {})
        with self.lock:
            attributes["last_command"] = self.last_command
        key = json.dumps([state, attributes], sort_keys=True, default=str)
        if not force and key == self.published and self.now() - self.published_at < REFRESH_S:
            return False
        code, _ = http("POST", f"{self.core}/api/states/{self.entity}", self.token,
                       {"state": state, "attributes": attributes})
        if code in (200, 201):
            self.published, self.published_at = key, self.now()
        return code in (200, 201)

    def status_loop(self, stop):
        while not stop.is_set():
            try:
                self.publish()
            except (OSError, ValueError) as error:
                print(f"HA control: status update failed ({error})", flush=True)
            stop.wait(POLL_S)

    # -- event subscription ----------------------------------------------
    def listen_once(self):
        ws = WebSocket(self.websocket)
        try:
            if ws.recv().get("type") != "auth_required":
                raise ConnectionError("unexpected greeting")
            ws.send({"type": "auth", "access_token": self.token})
            if ws.recv().get("type") != "auth_ok":
                raise ConnectionError("authentication failed")
            ws.send({"id": 1, "type": "subscribe_events", "event_type": EVENT})
            reply = ws.recv()
            if not reply.get("success"):
                raise ConnectionError("subscription refused")
            print(f"HA control: listening for {EVENT} events for {self.cpid}; "
                  f"status in {self.entity}.", flush=True)
            ws.sock.settimeout(None)
            while True:
                message = ws.recv()
                if message.get("type") == "event":
                    event = message.get("event") or {}
                    if event.get("event_type") == EVENT:
                        result = self.handle(event.get("data"))
                        if result:
                            print(f"HA control: {result['command']} -> "
                                  f"{'ok' if result.get('ok') else result.get('error') or result.get('http_status')}",
                                  flush=True)
        finally:
            ws.close()

    def run(self, stop):
        threading.Thread(target=self.status_loop, args=(stop,), daemon=True).start()
        delay = 2
        while not stop.is_set():
            try:
                self.listen_once()
                delay = 2
            except (OSError, ValueError, ConnectionError) as error:
                print(f"HA control: reconnecting in {delay} s ({error})", flush=True)
                stop.wait(delay)
                delay = min(delay * 2, 60)


def main():
    token = os.environ.get("SUPERVISOR_TOKEN")
    cpid = sys.argv[1] if len(sys.argv) > 1 else ""
    if not token or not cpid:
        print("HA control: no Supervisor token or charge point ID; disabled.", flush=True)
        return 1
    stop = threading.Event()
    Bridge(cpid, token).run(stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
