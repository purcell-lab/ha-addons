"""Diagnostics parsing, self-test verdicts and the PyEvJosev restart patch."""
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rootfs/opt/ha-everest"))
import diag  # noqa: E402
import patch_josev  # noqa: E402

IF_INET6 = """fe80000000000000a8bbccfffe000001 05 40 20 80     v2g0
fe80000000000000a8bbccfffe000002 06 40 20 40     v2g1
fd0020260010000000000000000000a1 02 40 00 00     eth0
"""
IGMP6 = """1    lo              ff020000000000000000000000000001     1 0000000C 0
5    v2g0            ff0200000000000000000001ff000001     1 00000004 0
5    v2g0            ff020000000000000000000000000001     1 0000000C 0
6    v2g1            ff020000000000000000000000000001     1 0000000C 0
"""
# :: bound to 15118 (0x3B0E) and fe80::1 bound to 50000 (0xC350).
UDP6 = """  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
   1: 00000000000000000000000000000000:3B0E 00000000000000000000000000000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 1 2 0 0
   2: 000080FE000000000000000001000000:C350 00000000000000000000000000000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 1 2 0 0
"""


def frame(src, dst, sport, dport, payload):
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = (struct.pack("!IHBB", 0x60000000, len(udp), 17, 255)
          + socket.inet_pton(socket.AF_INET6, src) + socket.inet_pton(socket.AF_INET6, dst))
    return b"\x33\x33\x00\x00\x00\x01" + b"\x02" * 6 + b"\x86\xdd" + ip + udp


class ParseTest(unittest.TestCase):
    def test_addresses_flags(self):
        found = diag.addresses(IF_INET6)
        self.assertEqual(found["v2g0"][0]["scope"], "link")
        self.assertFalse(found["v2g0"][0]["tentative"])
        self.assertTrue(found["v2g1"][0]["tentative"])
        self.assertEqual(found["eth0"][0]["scope"], "global")

    def test_multicast_groups(self):
        groups = diag.multicast_groups(IGMP6)
        self.assertEqual([g["group"] for g in groups["v2g0"]],
                         ["ff02:0000:0000:0000:0000:0001:ff00:0001", "ff02:0000:0000:0000:0000:0000:0000:0001"])
        self.assertIn("v2g1", groups)

    def test_udp_listeners_only_sdp_port(self):
        self.assertEqual(diag.udp_listeners(text=UDP6), ["::"])

    def test_parse_frame(self):
        request = frame("fe80::2", "ff02::1", 40000, 15118, diag.SDP_REQUEST)
        self.assertEqual(diag.parse_frame(request), {"src": "fe80::2", "dst": "ff02::1", "sport": 40000,
                                                     "dport": 15118, "sdp": "request"})
        reply = frame("fe80::1", "fe80::2", 15118, 40000, diag.SDP_RESPONSE_TYPE + b"\x00" * 24)
        self.assertEqual(diag.parse_frame(reply)["sdp"], "response")
        self.assertIsNone(diag.parse_frame(frame("fe80::1", "fe80::2", 53, 40000, b"x" * 8)))
        self.assertIsNone(diag.parse_frame(b"\x00" * 20))

    def test_firewall_counters(self):
        listing = {"nftables": [{"metainfo": {}}, {"table": {"name": "ha_everest_v2g"}},
                                {"rule": {"handle": 4, "comment": "private V2G link",
                                          "expr": [{"match": {}}, {"counter": {"packets": 7, "bytes": 560}},
                                                   {"accept": None}]}},
                                {"rule": {"handle": 9, "comment": "dropped by policy",
                                          "expr": [{"counter": {"packets": 3, "bytes": 180}}]}}]}

        def run(cmd, **kw):
            self.assertEqual(cmd, ["nft", "-j", "list", "table", "inet", "ha_everest_v2g"])
            return type("R", (), {"returncode": 0, "stdout": json.dumps(listing)})()
        counters = diag.firewall_counters(run)
        self.assertEqual(counters["rules"], [
            {"rule": "private V2G link", "packets": 7, "bytes": 560},
            {"rule": "dropped by policy", "packets": 3, "bytes": 180}])
        failing = diag.firewall_counters(lambda cmd, **kw: type("R", (), {"returncode": 1, "stdout": "no table"})())
        self.assertEqual(failing, {"error": "no table"})


class SelftestTest(unittest.TestCase):
    def setUp(self):
        self.saved = diag.sdp_probe, diag.netguard.link_local

    def tearDown(self):
        diag.sdp_probe, diag.netguard.link_local = self.saved

    def run_with(self, unicast, multicast, released=True):
        self.order = []
        diag.netguard.link_local = lambda name, text=None: "fe80::1"
        def probe(address, via, timeout=2.0):
            result = {"result": unicast if address == "fe80::1" else multicast}
            if result["result"] == "reply":
                result["released"] = released
            self.order.append(address)
            return result
        diag.sdp_probe = probe
        return diag.selftest(capture=False, settle=0)

    def test_pass_needs_both_paths(self):
        self.assertTrue(self.run_with("reply", "reply")["pass"])
        self.assertEqual(self.order, ["ff02::1", "fe80::1"])  # the EV's path first
        unreleased = self.run_with("reply", "reply", released=False)
        self.assertFalse(unreleased["pass"])
        self.assertIn("session-release=failed", diag.summary(unreleased))
        failed = self.run_with("reply", "silent")
        self.assertFalse(failed["pass"])
        self.assertEqual(diag.summary(failed), "Discovery self-test FAILED: unicast=reply multicast=silent")

    def test_summary_lists_captures(self):
        result = {"pass": False, "unicast": {"result": "reply"}, "multicast": {"result": "silent"},
                  "capture": {"v2g0": {"available": True, "frames": []},
                              "v2g1": {"available": True, "frames": [{"direction": "out", "sdp": "request"}]}}}
        self.assertIn("v2g0=[none] v2g1=[out:request]", diag.summary(result))
        result["capture"] = {"v2g0": {"available": False, "error": "PermissionError"}}
        self.assertIn("v2g0=capture-unavailable", diag.summary(result))

    def test_release_session_sends_invalid_header(self):
        server = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        server.bind(("::1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        got = []

        def accept():
            conn, _ = server.accept()
            got.append(conn.recv(8))
            conn.close()
        thread = threading.Thread(target=accept)
        thread.start()
        reply = diag.SDP_RESPONSE_TYPE + (20).to_bytes(4, "big") + socket.inet_pton(socket.AF_INET6, "::1") \
            + port.to_bytes(2, "big") + b"\x10\x00"
        self.assertEqual(diag.release_session(reply, socket.if_nametoindex("lo")), {"released": True, "port": port})
        thread.join(5)
        server.close()
        self.assertEqual(got, [diag.INVALID_V2GTP])
        self.assertFalse(diag.release_session(reply, socket.if_nametoindex("lo"), timeout=0.5)["released"])

    def test_probe_reports_errors_not_raises(self):
        self.assertEqual(self.saved[0]("fe80::1", "no-such-if0")["result"], "error")


UPSTREAM_LOOP = '''    def start_evcc_handler(self):
        while True:
            self._ready_event.wait()
            try:
                asyncio.run(evcc_handler_main_loop(self._setup.configs.module))
                self._mod.publish_variable('ev', 'v2g_session_finished', None)
            except KeyboardInterrupt:
                log.debug("SECC program terminated manually")
                break
            self._ready_event.clear()
'''


class PatchJosevTest(unittest.TestCase):
    def test_patch_keeps_loop_alive_and_is_idempotent(self):
        patched = patch_josev.patch(UPSTREAM_LOOP)
        self.assertIn(patch_josev.MARKER, patched)
        self.assertIn("except Exception as error:", patched)
        self.assertEqual(patch_josev.patch(patched), patched)
        compile("class X:\n" + patched, "patched", "exec")

    def test_patched_loop_survives_a_failed_session(self):
        namespace = {}
        code = "class Module:\n" + patch_josev.patch(UPSTREAM_LOOP)
        calls = []

        class Event:
            def __init__(self):
                self.waits = 0

            def wait(self):
                self.waits += 1
                if self.waits > 2:
                    raise KeyboardInterrupt  # stop the test after two plug-ins

            def clear(self):
                pass

        class Asyncio:
            @staticmethod
            def run(coro):
                calls.append(coro)
                if len(calls) == 1:
                    raise RuntimeError("SDPRequest was not successful")

        class Log:
            errors = []

            @classmethod
            def error(cls, text):
                cls.errors.append(text)

            debug = error

        namespace.update(asyncio=Asyncio, log=Log, evcc_handler_main_loop=lambda cfg: "session")
        exec(code, namespace)
        module = namespace["Module"]()
        module._ready_event = Event()
        module._setup = type("S", (), {"configs": type("C", (), {"module": {}})()})()
        published = []
        module._mod = type("M", (), {"publish_variable": lambda self, *a: published.append(a)})()
        with self.assertRaises(KeyboardInterrupt):
            module.start_evcc_handler()
        self.assertEqual(len(calls), 2)  # the second plug-in ran a fresh stack
        self.assertIn("stack stopped (RuntimeError", Log.errors[0])
        self.assertEqual(len(published), 2)

    def test_refuses_unexpected_upstream(self):
        with self.assertRaises(ValueError):
            patch_josev.patch(UPSTREAM_LOOP.replace("break", "return"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "module.py"
            path.write_text("class X:\n" + UPSTREAM_LOOP)
            patch_josev.main(path)
            self.assertIn(patch_josev.MARKER, path.read_text())


if __name__ == "__main__":
    unittest.main()
