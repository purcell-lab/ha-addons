"""Private-link diagnostics and the ISO 15118 discovery (SDP) self-test.

Read-only except for the self-test, which sends two SDP requests from the EV
end of the private link (v2g1) to the charger's SDP server on v2g0:

- unicast to the charger's link-local address, the path CI's probe uses;
- multicast to ff02::1, the path the simulated EV (Josev) uses.

While it runs, an AF_PACKET capture on each link end counts UDP 15118
frames, so a failure shows whether the request left v2g1, reached v2g0 and
was answered. Capture needs CAP_NET_RAW; if the container lacks it the
result says so and the SDP results still stand. Nothing here opens a
listener or changes the firewall.
"""
import json
import os
from pathlib import Path
import select
import socket
import struct
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netguard  # noqa: E402

SDP_PORT = 15118
# V2GTP v1, payload type 0x9000 (SDP request), length 2: no TLS (0x10), TCP
# (0x00). The same request CI's firewall probe sends.
SDP_REQUEST = bytes.fromhex("01fe9000000000021000")
SDP_RESPONSE_TYPE = bytes.fromhex("01fe9001")
LINKS = (netguard.SECC_LINK, netguard.EVCC_LINK)
PROC = Path(os.environ.get("HA_EVEREST_PROC", "/proc"))
SYS = Path(os.environ.get("HA_EVEREST_SYS", "/sys"))
SYSCTLS = ("disable_ipv6", "accept_dad", "forwarding", "mc_forwarding", "mldv1_unsolicited_report_interval")
ETH_P_ALL = 0x0003
ETH_P_IPV6 = 0x86DD


def _read(path, default=None):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def _hex_ipv6(text):
    return ":".join(text[i:i + 4] for i in range(0, 32, 4))


def addresses(text=None):
    """IPv6 addresses per interface from /proc/net/if_inet6."""
    if text is None:
        text = _read(PROC / "net/if_inet6", "")
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 6:
            continue
        flags = int(fields[4], 16)
        result.setdefault(fields[5], []).append({
            "address": _hex_ipv6(fields[0]), "prefix": int(fields[2], 16),
            "scope": {0x00: "global", 0x20: "link", 0x10: "host"}.get(int(fields[3], 16), fields[3]),
            "tentative": bool(flags & netguard.TENTATIVE), "dadfailed": bool(flags & 0x08)})
    return result


def multicast_groups(text=None):
    """Joined IPv6 multicast groups per interface from /proc/net/igmp6."""
    if text is None:
        text = _read(PROC / "net/igmp6", "")
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 4:
            result.setdefault(fields[1], []).append({"group": _hex_ipv6(fields[2]), "users": int(fields[3])})
    return result


def udp_listeners(port=SDP_PORT, text=None):
    """IPv6 UDP sockets bound to `port` from /proc/net/udp6."""
    if text is None:
        text = _read(PROC / "net/udp6", "")
    found = []
    for line in text.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 4 or ":" not in fields[1]:
            continue
        address, hex_port = fields[1].split(":")
        if int(hex_port, 16) == port:
            # /proc stores each 32-bit word in host byte order.
            raw = b"".join(struct.pack("@I", int(address[i:i + 8], 16)) for i in range(0, 32, 8))
            found.append(socket.inet_ntop(socket.AF_INET6, raw))
    return found


def link_state(name):
    base = SYS / "class/net" / name
    return {"operstate": _read(base / "operstate"), "flags": _read(base / "flags"),
            "mtu": _read(base / "mtu"), "ifindex": _read(base / "ifindex"),
            "sysctl": {key: _read(PROC / "sys/net/ipv6/conf" / name / key) for key in SYSCTLS}}


def firewall_counters(run=subprocess.run):
    """Packet and byte counters per rule of the App's nftables table."""
    try:
        listed = run(["nft", "-j", "list", "table", "inet", netguard.TABLE],
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        return {"error": str(error)[:200]}
    if listed.returncode != 0:
        return {"error": (listed.stdout or "").strip()[:200]}
    try:
        items = json.loads(listed.stdout).get("nftables", [])
    except ValueError:
        return {"error": "unparseable nft output"}
    rules = []
    for item in items:
        rule = item.get("rule")
        if not rule:
            continue
        counter = next((e["counter"] for e in rule.get("expr", []) if "counter" in e), None)
        if counter is not None:
            rules.append({"rule": rule.get("comment") or f"handle {rule.get('handle')}",
                          "packets": counter.get("packets"), "bytes": counter.get("bytes")})
    return {"table": netguard.TABLE, "rules": rules}


def snapshot(run=subprocess.run):
    addrs, groups = addresses(), multicast_groups()
    return {
        "links": {name: dict(link_state(name), addresses=addrs.get(name, []),
                             multicast=groups.get(name, [])) for name in LINKS},
        "all_sysctl": {key: _read(PROC / "sys/net/ipv6/conf/all" / key) for key in SYSCTLS},
        "sdp_udp_listeners": udp_listeners(),
        "firewall": firewall_counters(run),
        "taken_at": time.time(),
    }


class Capture:
    """Count UDP 15118 frames on one interface (needs CAP_NET_RAW)."""

    def __init__(self, ifname):
        self.ifname, self.frames, self.error = ifname, [], None
        self._stop = threading.Event()
        self._thread = None
        try:
            self.sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
            self.sock.bind((ifname, 0))
        except (OSError, AttributeError) as error:
            self.sock, self.error = None, f"{type(error).__name__}: {error}"[:120]

    def start(self):
        if self.sock:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def _loop(self):
        while not self._stop.is_set():
            ready, _, _ = select.select([self.sock], [], [], 0.1)
            if not ready:
                continue
            frame, meta = self.sock.recvfrom(2048)
            info = parse_frame(frame)
            if info:
                info["direction"] = "out" if meta[2] == socket.PACKET_OUTGOING else "in"
                self.frames.append(info)

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(1)
        if self.sock:
            self.sock.close()
        if self.error:
            return {"available": False, "error": self.error}
        return {"available": True, "frames": self.frames[:20], "count": len(self.frames)}


def parse_frame(frame):
    """Summary of an Ethernet/IPv6/UDP frame to or from port 15118, else None."""
    if len(frame) < 14 + 40 + 8 or struct.unpack("!H", frame[12:14])[0] != ETH_P_IPV6:
        return None
    ip = frame[14:54]
    if ip[6] != 17:  # next header UDP (no extension headers on this link)
        return None
    sport, dport = struct.unpack("!HH", frame[54:58])
    if SDP_PORT not in (sport, dport):
        return None
    payload = frame[62:70]
    kind = ("request" if payload.startswith(SDP_REQUEST[:4]) else
            "response" if payload.startswith(SDP_RESPONSE_TYPE) else payload[:4].hex())
    return {"src": socket.inet_ntop(socket.AF_INET6, ip[8:24]),
            "dst": socket.inet_ntop(socket.AF_INET6, ip[24:40]),
            "sport": sport, "dport": dport, "sdp": kind}


# Upstream libiso15118 (v0.9.0) creates a session for every SDP request it
# answers and ignores later requests until that session ends, which only
# happens after a TCP/TLS exchange. An answered probe would otherwise block
# the simulated EV's next discovery until the App restarts.
INVALID_V2GTP = b"\x00" * 8


def release_session(reply, index, timeout=2.0):
    """Close the charger session an answered probe opened: connect to the
    offered plain-TCP endpoint and send an invalid V2GTP header, which makes
    the charger shut the session down."""
    try:
        address = socket.inet_ntop(socket.AF_INET6, reply[8:24])
        port = int.from_bytes(reply[24:26], "big")
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            conn.connect((address, port, 0, index))
            conn.sendall(INVALID_V2GTP)
            try:
                conn.recv(16)  # the charger closes the connection
            except socket.timeout:
                return {"released": False, "error": "no close"}
        return {"released": True, "port": port}
    except (OSError, ValueError) as error:
        return {"released": False, "error": str(error)[:120]}


# The charger closes a released session gracefully, blocking discovery for
# about 2 s; probes wait longer than that and the test waits it out.
CHARGER_CLOSE_S = 2.5


def sdp_probe(address, via, timeout=4.0):
    """Send one SDP request out of `via`; return reply, silent or an error."""
    try:
        index = socket.if_nametoindex(via)
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, index)
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_LOOP, 0)
            sock.settimeout(timeout)
            started = time.monotonic()
            sock.sendto(SDP_REQUEST, (address, SDP_PORT, 0, index))
            while True:
                data, peer = sock.recvfrom(256)
                if data.startswith(SDP_RESPONSE_TYPE) and len(data) >= 28:
                    result = {"result": "reply", "from": peer[0],
                              "ms": round((time.monotonic() - started) * 1000)}
                    result.update(release_session(data, index))
                    return result
    except socket.timeout:
        return {"result": "silent"}
    except OSError as error:
        return {"result": "error", "error": f"{error.errno}: {error.strerror}"}


def selftest(capture=True, settle=CHARGER_CLOSE_S):
    """Multicast (as the EV sends it) then unicast SDP from v2g1 to the
    charger on v2g0, with packet capture on both ends."""
    secc = netguard.link_local(netguard.SECC_LINK)
    captures = [Capture(name).start() for name in LINKS] if capture else []
    time.sleep(0.2 if capture else 0)
    multicast = sdp_probe("ff02::1", netguard.EVCC_LINK)
    time.sleep(settle if multicast["result"] == "reply" else 0)  # let the charger drop the session
    unicast = sdp_probe(secc, netguard.EVCC_LINK) if secc else {"result": "error", "error": "no SECC link-local"}
    time.sleep(settle if unicast["result"] == "reply" else 0)
    time.sleep(0.3 if capture else 0)
    seen = {c.ifname: c.stop() for c in captures}
    released = all(p.get("released") for p in (unicast, multicast) if p["result"] == "reply")
    return {"secc_address": secc, "unicast": unicast, "multicast": multicast, "capture": seen,
            "pass": unicast["result"] == "reply" and multicast["result"] == "reply" and released,
            "sessions_released": released, "at": time.time()}


def summary(result):
    """One log line for the App log (and for ha_get_logs)."""
    parts = [f"unicast={result['unicast']['result']}", f"multicast={result['multicast']['result']}"]
    for name, seen in (result.get("capture") or {}).items():
        if seen.get("available"):
            kinds = [f"{f['direction']}:{f['sdp']}" for f in seen["frames"]]
            parts.append(f"{name}=[{' '.join(kinds) or 'none'}]")
        else:
            parts.append(f"{name}=capture-unavailable")
    if not result.get("sessions_released", True):
        parts.append("session-release=failed")
    if result.get("charger_sdp_blocked"):
        parts.append("charger=ignoring-discovery(restart the App)")
    return ("Discovery self-test " + ("PASSED" if result["pass"] else "FAILED") + ": " + " ".join(parts))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    out = selftest() if command == "selftest" else snapshot()
    print(json.dumps(out, indent=2))
    if command == "selftest":
        print(summary(out))
        sys.exit(0 if out["pass"] else 1)
