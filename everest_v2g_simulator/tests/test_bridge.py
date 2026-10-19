"""HA control bridge against a fake Core (REST + WebSocket) and a fake App UI."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/ha-everest"))
import ha_bridge  # noqa: E402

CPID = "SIM-EV-EVEREST-V2G-01"
STATUS = {"app": {"charge_point_id": CPID, "negotiated": "ocpp2.1", "csms_configured": True},
          "evse": {"session_info": {"value": {"state": "Charging"}, "age_s": 1},
                   "powermeter": {"value": {"power_W": {"total": -5000}}, "age_s": 1}}}


class Recorder:
    def __init__(self):
        self.requests = []
        self.lock = threading.Lock()

    def add(self, item):
        with self.lock:
            self.requests.append(item)


def http_server(recorder, routes):
    class Handler(BaseHTTPRequestHandler):
        def handle_any(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            recorder.add({"method": self.command, "path": self.path, "body": body,
                          "auth": self.headers.get("Authorization"),
                          "x": self.headers.get("X-HA-EVerest")})
            code, reply = routes.get((self.command, self.path.split("?")[0]), (404, {"error": "nf"}))
            data = json.dumps(reply).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = handle_any

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def ws_frame(obj):
    data = json.dumps(obj).encode()
    head = struct.pack("!BB", 0x81, len(data)) if len(data) < 126 else struct.pack("!BBH", 0x81, 126, len(data))
    return head + data


def ws_read(conn):
    first, second = conn.recv(2, socket.MSG_WAITALL)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", conn.recv(2, socket.MSG_WAITALL))[0]
    mask = conn.recv(4, socket.MSG_WAITALL)
    payload = conn.recv(length, socket.MSG_WAITALL)
    assert second & 0x80, "client frames must be masked"
    return json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


class FakeCoreWebSocket:
    """Accepts one client, checks auth and subscription, then sends events."""

    def __init__(self, token, events):
        self.token, self.events, self.seen = token, events, []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        conn, _ = self.sock.accept()
        request = b""
        while b"\r\n\r\n" not in request:
            request += conn.recv(1024)
        key = [l.split(b": ", 1)[1] for l in request.split(b"\r\n") if l.lower().startswith(b"sec-websocket-key")][0]
        accept = base64.b64encode(hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
        self.path = request.split(b" ")[1].decode()
        conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n" + ws_frame({"type": "auth_required"}))
        auth = ws_read(conn)
        self.seen.append(auth)
        if auth.get("access_token") != self.token:
            conn.sendall(ws_frame({"type": "auth_invalid"}))
            conn.close()
            return
        conn.sendall(ws_frame({"type": "auth_ok"}))
        subscribe = ws_read(conn)
        self.seen.append(subscribe)
        conn.sendall(ws_frame({"id": subscribe["id"], "type": "result", "success": True}))
        conn.sendall(b"\x89\x02hi")  # ping; client must answer with a masked pong
        pong = conn.recv(2, socket.MSG_WAITALL)
        self.seen.append({"pong_opcode": pong[0] & 0x0F})
        conn.recv(4 + 2, socket.MSG_WAITALL)
        for data in self.events:
            conn.sendall(ws_frame({"id": 1, "type": "event",
                                   "event": {"event_type": ha_bridge.EVENT, "data": data}}))
        conn.sendall(b"\x88\x00")  # close
        conn.close()


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.rec = Recorder()
        self.ui = http_server(self.rec, {
            ("GET", "/api/status"): (200, STATUS),
            ("GET", "/api/diagnostics"): (200, {"selftest": {"pass": False, "summary": "Discovery self-test FAILED"}}),
            ("POST", "/api/ev/plugin"): (200, {"sent": True, "command": "plugin"}),
            ("POST", "/api/diag/selftest"): (200, {"pass": True}),
        })
        self.core = http_server(self.rec, {
            ("POST", f"/api/states/{ha_bridge.entity_id(CPID)}"): (201, {}),
            ("POST", f"/api/events/{ha_bridge.RESULT_EVENT}"): (200, {}),
        })
        self.clock = [100.0]
        self.bridge = ha_bridge.Bridge(CPID, "token-1", core=f"http://127.0.0.1:{self.core.server_port}",
                                       ui=f"http://127.0.0.1:{self.ui.server_port}", now=lambda: self.clock[0])

    def tearDown(self):
        for server in (self.ui, self.core):
            server.shutdown()
            server.server_close()

    def paths(self, method=None):
        return [r["path"] for r in self.rec.requests if method is None or r["method"] == method]

    def test_entity_id(self):
        self.assertEqual(ha_bridge.entity_id(CPID), "sensor.sim_ev_everest_v2g_01_v2g_app")

    def test_status_object(self):
        attributes, state = ha_bridge.status_attributes(STATUS, {"selftest": {"pass": True, "summary": "ok"}})
        self.assertEqual(state, "Charging")
        self.assertEqual(attributes["direction"], "discharge")
        self.assertEqual(attributes["discovery_selftest"], "passed")
        self.assertEqual(ha_bridge.status_attributes({}, {})[1], "unknown")
        # Issue #33: the EV watchdog's state.
        self.assertEqual(attributes["ev_session"], "unknown")
        recovery = {"at": 1.0, "result": "re-plugged", "attempt": 1}
        watched = dict(STATUS, ev_watchdog={"ev_session": "ok", "recoveries": 1, "last_recovery": recovery})
        attributes, _ = ha_bridge.status_attributes(watched, {})
        self.assertEqual((attributes["ev_session"], attributes["ev_last_recovery"]), ("ok", recovery))
        self.assertTrue(self.bridge.publish())
        self.assertFalse(self.bridge.publish())  # unchanged within the refresh interval
        self.clock[0] += ha_bridge.REFRESH_S + 1
        self.assertTrue(self.bridge.publish())
        posts = [r for r in self.rec.requests if r["method"] == "POST"]
        self.assertEqual({r["path"] for r in posts}, {"/api/states/sensor.sim_ev_everest_v2g_01_v2g_app"})
        self.assertTrue(all(r["auth"] == "Bearer token-1" for r in posts))
        self.assertEqual(posts[0]["body"]["attributes"]["discovery_selftest"], "failed")

    def test_commands_allowlist_target_and_rate_limit(self):
        self.assertIsNone(self.bridge.handle({"charge_point_id": "SIM-EV-OTHER", "command": "plugin"}))
        self.assertIsNone(self.bridge.handle("not a dict"))
        self.assertIn("unknown command", self.bridge.handle({"charge_point_id": CPID, "command": "reboot"})["error"])
        self.assertTrue(self.bridge.handle({"charge_point_id": CPID, "command": "plugin"})["ok"])
        self.assertIn("rate limited", self.bridge.handle({"charge_point_id": CPID, "command": "plugin"})["error"])
        self.clock[0] += ha_bridge.MIN_INTERVAL_S
        self.assertTrue(self.bridge.handle({"charge_point_id": CPID, "command": "selftest"})["ok"])
        ui_posts = [r for r in self.rec.requests if r["method"] == "POST" and r["path"].startswith("/api/ev/")
                    or r["path"] == "/api/diag/selftest"]
        self.assertEqual([r["path"] for r in ui_posts], ["/api/ev/plugin", "/api/diag/selftest"])
        self.assertTrue(all(r["x"] == "1" and r["auth"] is None for r in ui_posts))
        core_posts = {p for p in self.paths("POST") if not p.startswith(("/api/ev/", "/api/diag/"))}
        self.assertEqual(core_posts, {"/api/events/everest_v2g_command_result",
                                      "/api/states/sensor.sim_ev_everest_v2g_01_v2g_app"})

    def test_websocket_auth_subscribe_and_dispatch(self):
        fake = FakeCoreWebSocket("token-1", [{"charge_point_id": CPID, "command": "plugin"},
                                             {"charge_point_id": "SIM-EV-OTHER", "command": "unplug"}])
        self.bridge.websocket = f"ws://127.0.0.1:{fake.port}/websocket"
        with self.assertRaises(ConnectionError):  # the fake closes after its events
            self.bridge.listen_once()
        self.assertEqual(fake.path, "/websocket")
        self.assertEqual(fake.seen[0], {"type": "auth", "access_token": "token-1"})
        self.assertEqual(fake.seen[1], {"id": 1, "type": "subscribe_events", "event_type": ha_bridge.EVENT})
        self.assertEqual(fake.seen[2], {"pong_opcode": 0xA})
        self.assertEqual([p for p in self.paths("POST") if p.startswith("/api/ev/")], ["/api/ev/plugin"])

    def test_bad_token_is_refused(self):
        fake = FakeCoreWebSocket("token-1", [])
        self.bridge.websocket, self.bridge.token = f"ws://127.0.0.1:{fake.port}/websocket", "wrong"
        with self.assertRaisesRegex(ConnectionError, "authentication failed"):
            self.bridge.listen_once()

    def test_only_documented_core_endpoints_in_source(self):
        source = (ROOT / "rootfs/opt/ha-everest/ha_bridge.py").read_text()
        core_calls = [line.strip() for line in source.splitlines() if "self.core}" in line]
        self.assertEqual(len(core_calls), 2)
        self.assertTrue(any("/api/events/{RESULT_EVENT}" in c for c in core_calls))
        self.assertTrue(any("/api/states/{self.entity}" in c for c in core_calls))
        for forbidden in ("/api/services", "call_service", "/api/config", "hassio", "/addons"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
