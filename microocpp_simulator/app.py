"""Validated HA options, persistent state, and bounded two-process supervision."""
import errno
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path("/opt/microocpp")
DATA = Path("/data")


def validate(options):
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    backend = options.get("backend_url", "")
    cpid = options.get("charge_point_id", "SIM-MICROOCPP-01")
    acknowledged = options.get("acknowledge_test_isolation", False)
    if not isinstance(cpid, str) or not re.fullmatch(r"SIM-[A-Za-z0-9_-]{1,40}", cpid):
        raise ValueError("charge_point_id must be a SIM- test identity")
    if not isinstance(options.get("archive_and_rebind", False), bool):
        raise ValueError("archive_and_rebind must be true or false")
    if not isinstance(backend, str) or len(backend) > 200:
        raise ValueError("backend_url must be a string of at most 200 characters")
    if backend:
        try:
            url = urlsplit(backend)
            port = url.port
        except ValueError:
            raise ValueError("invalid backend URL") from None
        if (
            url.scheme != "ws" or not url.hostname or not port
            or url.username is not None or url.password is not None
            or url.query or url.fragment
            or any(c.isspace() or ord(c) < 32 for c in backend)
            or "\\" in backend or "%" in backend
        ):
            raise ValueError("use ws://test-host:port[/base-path], without credentials")
        if acknowledged is not True:
            raise ValueError("acknowledge_test_isolation is required before connecting")
        # The client appends the CPID itself.
        if url.path.rstrip("/").endswith("/" + cpid):
            raise ValueError("backend_url must not include charge_point_id")
    return backend.rstrip("/"), cpid


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value))
    temporary.chmod(0o600)
    temporary.replace(path)


def update_config(path, values):
    if path.exists():
        doc = json.loads(path.read_text())
        entries = doc["configurations"]
        if not isinstance(entries, list):
            raise ValueError("invalid persisted configuration")
    else:
        doc = {"head": {"content-type": "ocpp_config_file", "version": "2.0"},
               "configurations": []}
        entries = doc["configurations"]
    entries[:] = [entry for entry in entries if entry["key"] not in values]
    for key, value in values.items():
        kind = "bool" if isinstance(value, bool) else "int" if isinstance(value, int) else "string"
        entries.append({"type": kind, "key": key, "value": value})
    atomic_json(path, doc)


def archive_if_requested(data, options):
    """Explicit, operator-selected rebinding: move state aside, never delete it."""
    if options.get("archive_and_rebind") is not True:
        return None
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archive = data / f"archive-{stamp}"
    archive.mkdir(mode=0o700)
    for name in ("mo_store", "test-identity.json"):
        if (data / name).exists():
            (data / name).rename(archive / name)
    return archive


def configure(data, options):
    backend, cpid = validate(options)
    data.mkdir(parents=True, exist_ok=True)
    archived = archive_if_requested(data, options)
    if archived:
        print(f"Archived previous simulator state to {archived.name}; set archive_and_rebind back to false.", flush=True)
    identity = data / "test-identity.json"
    target = {"backend_url": backend, "charge_point_id": cpid}
    # A paused (empty URL) start must not erase the previous destination.
    if identity.exists() and backend and json.loads(identity.read_text()) != target:
        raise ValueError("test destination changed; archive/reset App data before rebinding")
    if backend and not identity.exists():
        existing = data / "mo_store"
        if existing.exists() and any(
            p.name.startswith(("tx-", "tx201-")) for p in existing.iterdir()
        ):
            raise ValueError("unbound transaction data exists; archive/reset App data")
        atomic_json(identity, target)
    store = data / "mo_store"
    store.mkdir(exist_ok=True, mode=0o700)
    update_config(store / "ws-conn.jsn", {
        "Cst_BackendUrl": backend, "Cst_ChargeBoxId": cpid,
        "AuthorizationKey": "", "WebSocketPingInterval": 30,
        "Cst_ReconnectInterval": 30,
    })
    atomic_json(store / "ws-conn-v201.jsn", {"variables": [
        {"component": "SecurityCtrlr", "name": name, "valActual": value}
        for name, value in (("CsmsUrl", backend), ("Identity", cpid), ("BasicAuthPassword", ""))
    ]})
    # Deliberately retain transaction/config files; boot unloaded and not ready.
    update_config(store / "simulator.jsn", {
        "OcppVersion": "2.0.1",
        **{f"{key}_cId_{n}": False for n in (1, 2)
           for key in ("evPlugged", "evsePlugged", "evReady", "evseReady")},
    })
    atomic_json(store / "api.jsn", {"url": "http://127.0.0.1:8000", "user": "", "pass": ""})
    return bool(backend)


def lab_dns_url(resolv_conf):
    """Mongoose does not consult libc resolv.conf; give it the Supervisor resolver."""
    for value in re.findall(r"^nameserver\s+(\S+)", resolv_conf, re.M):
        try:
            return "udp://" + str(ipaddress.IPv4Address(value)) + ":53"
        except ValueError:
            continue
    return None


# Connection diagnostics (#31): Mongoose resolves the CSMS host itself and
# connects to the first A/AAAA record only, so log what it is given and what
# it gets, next to what libc (as used by other Apps) gets. Bounded, start-up only.
def mongoose_a_query(name, txnid=1):
    """The A query exactly as Mongoose's mg_dns_send builds it."""
    labels = b"".join(bytes([len(p)]) + p.encode("ascii") for p in name.split("."))
    return txnid.to_bytes(2, "big") + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00" + \
        labels + b"\x00\x00\x01\x00\x01"


def _skip_name(packet, offset):
    while True:
        if offset >= len(packet):
            raise ValueError("truncated DNS name")
        length = packet[offset]
        if length & 0xC0:
            return offset + 2
        if length == 0:
            return offset + 1
        offset += length + 1


def parse_dns_answers(packet):
    """(rcode, [(type, value)]) for the answer section; A/AAAA values as text."""
    if len(packet) < 12:
        raise ValueError("short DNS reply")
    rcode = packet[3] & 0x0F
    questions = int.from_bytes(packet[4:6], "big")
    answers = int.from_bytes(packet[6:8], "big")
    offset = 12
    for _ in range(questions):
        offset = _skip_name(packet, offset) + 4
    records = []
    for _ in range(answers):
        offset = _skip_name(packet, offset)
        if offset + 10 > len(packet):
            raise ValueError("truncated DNS record")
        kind = int.from_bytes(packet[offset:offset + 2], "big")
        klass = int.from_bytes(packet[offset + 2:offset + 4], "big")
        length = int.from_bytes(packet[offset + 8:offset + 10], "big")
        data = packet[offset + 10:offset + 10 + length]
        offset += 10 + length
        if len(data) != length:
            raise ValueError("truncated DNS record")
        if klass == 1 and kind == 1 and length == 4:
            records.append(("A", str(ipaddress.IPv4Address(data))))
        elif klass == 1 and kind == 28 and length == 16:
            records.append(("AAAA", str(ipaddress.IPv6Address(data))))
        else:
            records.append((f"type{kind}", ""))
    return rcode, records


def tcp_probe(address, port, timeout=3.0):
    """Open and close a TCP connection, sending nothing; 'open' or errno name."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        try:
            probe.connect((address, port))
        except socket.timeout:
            return "timeout"
        except OSError as error:
            return errno.errorcode.get(error.errno, str(error.errno))
    return "open"


def connection_diagnostics(backend, resolv_conf, dns_url, timeout=2.0):
    url = urlsplit(backend)
    host, port = url.hostname, url.port
    servers = re.findall(r"^nameserver\s+(\S+)", resolv_conf, re.M)
    lines = [f"resolv.conf nameservers: {', '.join(servers) or 'none'}; "
             f"Mongoose DNS: {dns_url or 'upstream default udp://8.8.8.8:53'}"]
    try:
        ipaddress.ip_address(host)
        lines.append(f"CSMS host {host} is an address; no DNS lookup.")
        targets = [host]
    except ValueError:
        targets = []
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            libc = list(dict.fromkeys(info[4][0] for info in infos))
            lines.append(f"libc getaddrinfo {host}: {', '.join(libc) or 'none'}")
            targets += libc[:2]
        except OSError as error:
            lines.append(f"libc getaddrinfo {host}: failed ({error})")
        if dns_url:
            server = urlsplit(dns_url)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                    udp.settimeout(timeout)
                    udp.connect((server.hostname, server.port or 53))
                    udp.send(mongoose_a_query(host))
                    rcode, records = parse_dns_answers(udp.recv(4096))
                shown = ", ".join(f"{k} {v}".strip() for k, v in records) or "none"
                first = next((v for k, v in records if k in ("A", "AAAA")), None)
                lines.append(f"Mongoose-style A query {host} @ {server.hostname}: "
                             f"rcode {rcode}, answers {shown}; Mongoose connects to "
                             f"{first or 'nothing (lookup fails)'}")
                if first:
                    targets.insert(0, first)
            except (OSError, ValueError) as error:
                lines.append(f"Mongoose-style A query {host} @ {server.hostname}: failed ({error})")
    for address in list(dict.fromkeys(targets))[:3]:
        lines.append(f"TCP probe {address} port {port}: {tcp_probe(address, port)}")
    return ["Connection diagnostics: " + line for line in lines]


def run():
    os.umask(0o077)
    try:
        enabled = configure(DATA, json.loads((DATA / "options.json").read_text()))
    except (ValueError, KeyError, TypeError, OSError):
        print("Invalid options/state. Check App documentation; no processes started.", flush=True)
        return 1
    print("OCPP 2.0.1 test simulator: " + ("connection enabled." if enabled else "disconnected."), flush=True)
    public = DATA / "public"
    if not public.exists():
        public.symlink_to(ROOT / "public", target_is_directory=True)
    children = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    result = 1
    try:
        resolv_conf = Path("/etc/resolv.conf").read_text()
        dns = lab_dns_url(resolv_conf)
        if dns:
            os.environ["MO_LAB_DNS_URL"] = dns
        if enabled:
            try:
                backend = json.loads((DATA / "test-identity.json").read_text())["backend_url"]
                for line in connection_diagnostics(backend, resolv_conf, dns):
                    print(line, flush=True)
            except Exception as error:  # diagnostics must never block start-up
                print(f"Connection diagnostics: skipped ({type(error).__name__})", flush=True)
        children.append(subprocess.Popen([str(ROOT / "mo_simulator")], cwd=DATA))
        children.append(subprocess.Popen(["nginx", "-c", str(ROOT / "nginx.conf"),
                                          "-g", "daemon off;"]))
        while not stopping and all(child.poll() is None for child in children):
            time.sleep(0.2)
        result = 0 if stopping else 1
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 8
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return result


if __name__ == "__main__":
    sys.exit(run())
