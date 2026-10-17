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
import patch_yeti  # noqa: E402

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


ROUTES = """ff000000000000000000000000000000 08 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000003 00000000 00000001     eth0
fe800000000000000000000000000000 40 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00000001     v2g1
ff000000000000000000000000000000 08 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000002 00000000 00000001     v2g1
ff000000000000000000000000000000 08 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000002 00000000 00000001     v2g0
"""


class RouteTest(unittest.TestCase):
    def test_multicast_route_order(self):
        self.assertEqual(diag.multicast_routes(ROUTES), ["eth0", "v2g1", "v2g0"])
        self.assertEqual(diag.multicast_routes(""), [])

    def test_summary_names_the_unscoped_interface(self):
        result = {"pass": True, "unicast": {"result": "reply"}, "multicast": {"result": "reply"},
                  "unscoped_multicast_interface": "eth0"}
        self.assertTrue(diag.summary(result).endswith("unscoped-multicast-via=eth0"))


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
        self.assertTrue(diag.summary(failed).startswith("Discovery self-test FAILED: unicast=reply multicast=silent"))

    def test_summary_lists_captures(self):
        result = {"pass": False, "unicast": {"result": "reply"}, "multicast": {"result": "silent"},
                  "capture": {"v2g0": {"available": True, "frames": []},
                              "v2g1": {"available": True, "frames": [{"direction": "out", "sdp": "request"}]}}}
        self.assertIn("v2g0=[none] v2g1=[out:request]", diag.summary(result))
        result["charger_sdp_blocked"] = True
        self.assertIn("charger=ignoring-discovery(restart the App)", diag.summary(result))
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
SIM_FILE = Path("/tmp/deb12/opt/everest/libexec/everest/3rd_party/josev/iso15118/evcc/controller/simulator.py")
# The BPT discharge limits of Josev 2025.9.0 iso15118/evcc/controller/simulator.py.
SIM_UPSTREAM = '''def f(RationalNumber, a, d):
    ac = dict(
        **a,
        ev_max_discharge_power=RationalNumber(exponent=3, value=11),
        ev_min_discharge_power=RationalNumber(exponent=0, value=100),
    )
    dc = dict(
        **d,
        # Todo(sl): Update later if bpt is also available
        ev_max_discharge_power=RationalNumber(exponent=3, value=11),
        ev_min_discharge_power=RationalNumber(exponent=3, value=1),
        ev_max_discharge_current=RationalNumber(exponent=0, value=25),
        ev_min_discharge_current=RationalNumber(exponent=0, value=0),
    )
    dynamic = dict(
        **d,
        ev_max_discharge_power=RationalNumber(exponent=3, value=11),
        ev_min_discharge_power=RationalNumber(exponent=0, value=300),
        ev_max_discharge_current=RationalNumber(exponent=0, value=25),
    )
    return ac, dc, dynamic
'''
AUTH_FILE = Path("/tmp/deb12/opt/everest/libexec/everest/3rd_party/josev/iso15118/evcc/states/iso15118_20_states.py")
# Verbatim excerpts of Josev 2025.9.0 iso15118/evcc/states/iso15118_20_states.py:
# the import and the Authorization state's ongoing loop.
AUTH_UPSTREAM = '''import time
from iso15118.shared.messages.timeouts import Timeouts as TimeoutsShared


class Timeouts:
    AUTHORIZATION_REQ = 2


def ongoing(comm_session, create_next_message, stop_state_machine):
    elapsed_time: float = 0
    if comm_session.ongoing_timer >= 0:
        elapsed_time = time.time() - comm_session.ongoing_timer
        if elapsed_time > TimeoutsShared.V2G_EVCC_ONGOING_TIMEOUT:
            stop_state_machine(
                "Ongoing timer timed out for " "AuthorizationRes"
            )
            return
    else:
        comm_session.ongoing_timer = time.time()

    create_next_message(
        min(
            Timeouts.AUTHORIZATION_REQ,
            TimeoutsShared.V2G_EVCC_ONGOING_TIMEOUT - elapsed_time,
        ),
    )
'''
UDP_FILE = Path("/tmp/deb12/opt/everest/libexec/everest/3rd_party/josev/iso15118/evcc/transport/udp_client.py")
# Verbatim excerpt of Josev's UDPClient._create_socket (EVerest 2025.10.0).
UDP_UPSTREAM = '''import socket
import struct


def _create_socket(iface: str) -> socket.socket:
        sock = socket.socket(family=socket.AF_INET6, type=socket.SOCK_DGRAM)
        ttl = struct.pack("@i", 1)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_HOPS, ttl)
        interface_index = socket.if_nametoindex(iface)
        # sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, interface_index)

        return sock
'''


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

    def test_udp_client_sends_on_configured_interface(self):
        upstream = (UDP_UPSTREAM if not UDP_FILE.exists() else UDP_FILE.read_text())
        patched = patch_josev.patch_udp(upstream)
        self.assertIn("        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, interface_index)\n",
                      patched)
        self.assertNotIn("# sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF", patched)
        self.assertEqual(patch_josev.patch_udp(patched), patched)
        with self.assertRaises(ValueError):
            patch_josev.patch_udp(upstream.replace("interface_index = socket", "index = socket"))

    def test_ev_discharges_25_kw(self):
        upstream = (SIM_UPSTREAM if not SIM_FILE.exists() else SIM_FILE.read_text())
        patched = patch_josev.patch_sim(upstream)
        compile(patched, "simulator.py", "exec")
        self.assertEqual(patched.count("ev_max_discharge_current=RationalNumber(exponent=0, value=66)"), 2)
        self.assertEqual(patched.count("ev_max_discharge_power=RationalNumber(exponent=3, value=25)"), 3)
        self.assertNotIn("value=25),\n", patched.replace("exponent=3, value=25)", ""))
        self.assertEqual(patch_josev.patch_sim(patched), patched)
        with self.assertRaises(ValueError):
            patch_josev.patch_sim(upstream.replace("exponent=0, value=25)", "exponent=0, value=30)", 1))

    def test_ev_waits_for_authorisation_as_long_as_the_charger(self):
        # Issue #33: Josev gave up 60 s after the first Ongoing reply.
        upstream = (AUTH_UPSTREAM if not AUTH_FILE.exists() else AUTH_FILE.read_text())
        patched = patch_josev.patch_auth(upstream)
        self.assertIn(patch_josev.AUTH_MARKER, patched)
        self.assertNotIn("TimeoutsShared.V2G_EVCC_ONGOING_TIMEOUT", patched)
        self.assertEqual(patch_josev.patch_auth(patched), patched)
        self.assertGreater(patch_josev.AUTH_WAIT_S, 180)  # libiso15118 TIMEOUT_EIM_ONGOING
        with self.assertRaises(ValueError):
            patch_josev.patch_auth(upstream.replace("TimeoutsShared.V2G_EVCC_ONGOING_TIMEOUT", "60", 1))
        if AUTH_FILE.exists():
            return
        stub = type("Shared", (), {"V2G_EVCC_ONGOING_TIMEOUT": 60})
        namespace = {"TimeoutsShared": stub}
        exec(compile(patched.replace(patch_josev.AUTH_IMPORT, ""), "states", "exec"), namespace)
        self.assertEqual(namespace["HA_EVEREST_AUTH_WAIT_S"], patch_josev.AUTH_WAIT_S)
        session = type("Session", (), {"ongoing_timer": time.time() - 120})()
        stopped, sent = [], []
        namespace["ongoing"](session, sent.append, stopped.append)
        self.assertEqual((stopped, sent), ([], [2]))  # still waiting after 120 s
        session.ongoing_timer = time.time() - 200
        namespace["ongoing"](session, sent.append, stopped.append)
        self.assertEqual(len(stopped), 1)

    def test_refuses_unexpected_upstream(self):
        with self.assertRaises(ValueError):
            patch_josev.patch(UPSTREAM.replace("break", "return"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "module.py"
            path.write_text("class X:\n" + UPSTREAM)
            udp = Path(tmp) / "udp_client.py"
            udp.write_text(UDP_UPSTREAM)
            sim = Path(tmp) / "simulator.py"
            sim.write_text(SIM_UPSTREAM)
            auth = Path(tmp) / "iso15118_20_states.py"
            auth.write_text(AUTH_UPSTREAM)
            patch_josev.main(path, udp, sim, auth)
            self.assertIn(patch_josev.MARKER, path.read_text())
            self.assertIn(patch_josev.UDP_MARKER, udp.read_text())
            self.assertIn(patch_josev.SIM_MARKER, sim.read_text())
            self.assertIn(patch_josev.AUTH_MARKER, auth.read_text())

    @unittest.skipUnless(UPSTREAM_FILE.exists(), "everest-core checkout not present")
    def test_matches_real_upstream_file(self):
        patched = patch_josev.patch(UPSTREAM_FILE.read_text())
        compile(patched, "module.py", "exec")
        self.assertIn(patch_josev.MARKER, patched)


if __name__ == "__main__":
    unittest.main()


class YetiBoardLimitTest(unittest.TestCase):
    """patch_yeti.py: exact binaries and bytes only; real files when present."""

    REAL = {"amd64": Path("/tmp/yeti/amd64_YetiSimulator"), "arm64": Path("/tmp/yeti/arm64_YetiSimulator")}

    def test_known_binary_is_patched_at_exact_offsets(self):
        data = bytearray(64)
        data[8:12] = patch_yeti.F32
        data[16:20] = patch_yeti.FMOV_16
        digest = __import__("hashlib").sha256(bytes(data)).hexdigest()
        edits = [(8, patch_yeti.F32, patch_yeti.F128), (16, patch_yeti.FMOV_16, patch_yeti.MOVI_128)]
        original = dict(patch_yeti.PATCHES)
        patch_yeti.PATCHES[digest] = ("test", edits)
        try:
            patched, arch = patch_yeti.patch(bytes(data))
            self.assertEqual(arch, "test")
            self.assertEqual(patched[8:12], patch_yeti.F128)
            self.assertEqual(patched[16:20], patch_yeti.MOVI_128)
            self.assertEqual(sum(a != b for a, b in zip(patched, data)), 5)
            self.assertEqual(patch_yeti.patch(patched), (patched, "test"))
            broken = bytearray(data)
            broken[20] = 1
            with self.assertRaises(ValueError):
                patch_yeti.patch(bytes(broken))
        finally:
            patch_yeti.PATCHES.clear()
            patch_yeti.PATCHES.update(original)

    def test_constants(self):
        self.assertEqual(struct.unpack("<f", patch_yeti.F128)[0], 128.0)
        # movi v0.2s, #imm8, lsl #24: imm8 0x42 -> 32.0, 0x43 -> 128.0 (bits 9:5 differ).
        self.assertEqual(int.from_bytes(patch_yeti.MOVI_128, "little") - int.from_bytes(patch_yeti.MOVI_32, "little"),
                         1 << 5)
        # 128 A x 3 x 230 V carries the 25 kW rating with margin.
        self.assertGreater(patch_yeti.BOARD_AMPS * 230, 25000)

    def test_real_binaries_when_present(self):
        for arch, path in self.REAL.items():
            if not path.exists():
                continue
            patched, found = patch_yeti.patch(path.read_bytes())
            self.assertEqual(found, arch)
            self.assertEqual(patch_yeti.patch(patched), (patched, arch))
