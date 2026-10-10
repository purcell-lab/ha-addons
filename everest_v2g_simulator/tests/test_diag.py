"""Diagnostics parsing, self-test verdicts and the PyEvJosev restart patch."""
import asyncio
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
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


# The two upstream methods the patch edits, verbatim from everest-core
# 2025.10.0 modules/EV/PyEvJosev/module.py (not adjacent upstream).
UPSTREAM = '''    def start_evcc_handler(self):
        while True:
            self._ready_event.wait()
            try:
                asyncio.run(evcc_handler_main_loop(self._setup.configs.module))
                self._mod.publish_variable('ev', 'v2g_session_finished', None)
            except KeyboardInterrupt:
                log.debug("SECC program terminated manually")
                break
            self._ready_event.clear()

    def _handler_start_charging(self, args) -> bool:

        self._es.EnergyTransferMode = args['EnergyTransferMode']

        self._ready_event.set()

        return True
'''
UPSTREAM_FILE = Path("/tmp/everest-core/modules/EV/PyEvJosev/module.py")


class Log:
    def __init__(self):
        self.lines = []

    def error(self, text):
        self.lines.append(text)

    debug = error


def load(behaviours):
    """Patched class with Josev replaced by scripted main loops."""
    namespace = {"asyncio": asyncio, "log": Log()}
    runs = []

    async def main_loop(config):
        behaviour = behaviours[len(runs)]
        runs.append(behaviour)
        if behaviour == "hang":  # Josev after SDPFailedError: never returns
            await asyncio.Event().wait()
        elif behaviour == "fail":
            raise RuntimeError("SDPRequest was not successful")
        elif behaviour == "exit":
            raise KeyboardInterrupt

    namespace["evcc_handler_main_loop"] = main_loop
    exec("class Module:\n" + patch_josev.patch(UPSTREAM), namespace)
    module = namespace["Module"]()
    module._ready_event = threading.Event()
    module._setup = type("S", (), {"configs": type("C", (), {"module": {}})()})()
    module._es = type("E", (), {})()
    module.published = []
    module._mod = type("M", (), {"publish_variable": lambda self, *a: module.published.append(a)})()
    return module, runs, namespace["log"]


def plug_in(module):
    return module._handler_start_charging({"EnergyTransferMode": "DC_extended"})


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class PatchJosevTest(unittest.TestCase):
    def test_patch_is_idempotent_and_compiles(self):
        patched = patch_josev.patch(UPSTREAM)
        self.assertIn(patch_josev.MARKER, patched)
        self.assertEqual(patch_josev.patch(patched), patched)
        compile("class X:\n" + patched, "patched", "exec")

    def test_new_plug_in_replaces_a_hung_stack(self):
        module, runs, log = load(["hang", "ok", "exit"])
        thread = threading.Thread(target=module.start_evcc_handler, daemon=True)
        thread.start()
        plug_in(module)
        self.assertTrue(wait_until(lambda: module._ha_stack is not None))
        plug_in(module)  # re-plug while the first stack is stuck
        self.assertTrue(wait_until(lambda: len(runs) == 2 and module._ha_stack is None))
        self.assertIn("replaced by a new plug-in", log.lines[0])
        plug_in(module)
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(runs, ["hang", "ok", "exit"])
        self.assertEqual(len(module.published), 2)

    def test_failed_session_waits_for_next_plug_in(self):
        module, runs, log = load(["fail", "exit"])
        thread = threading.Thread(target=module.start_evcc_handler, daemon=True)
        thread.start()
        plug_in(module)
        self.assertTrue(wait_until(lambda: module.published))
        self.assertIn("stack stopped (RuntimeError", log.lines[0])
        plug_in(module)
        thread.join(5)
        self.assertEqual(runs, ["fail", "exit"])

    def test_refuses_unexpected_upstream(self):
        with self.assertRaises(ValueError):
            patch_josev.patch(UPSTREAM.replace("break", "return"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "module.py"
            path.write_text("class X:\n" + UPSTREAM)
            patch_josev.main(path)
            self.assertIn(patch_josev.MARKER, path.read_text())

    @unittest.skipUnless(UPSTREAM_FILE.exists(), "everest-core checkout not present")
    def test_matches_real_upstream_file(self):
        patched = patch_josev.patch(UPSTREAM_FILE.read_text())
        compile(patched, "module.py", "exec")
        self.assertIn(patch_josev.MARKER, patched)


if __name__ == "__main__":
    unittest.main()
