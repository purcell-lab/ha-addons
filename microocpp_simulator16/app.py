"""Validated HA options, persistent state, and bounded two-process supervision."""
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
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
    cpid = options.get("charge_point_id", "SIM-16-MICROOCPP-01")
    acknowledged = options.get("acknowledge_test_isolation", False)
    if not isinstance(cpid, str) or not re.fullmatch(r"SIM-16-[A-Za-z0-9_-]{1,37}", cpid):
        raise ValueError("charge_point_id must be a SIM-16- test identity")
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
    # Deliberately retain transaction/config files; boot unloaded and not ready.
    update_config(store / "simulator.jsn", {
        "OcppVersion": "1.6",
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


def run():
    os.umask(0o077)
    try:
        enabled = configure(DATA, json.loads((DATA / "options.json").read_text()))
    except (ValueError, KeyError, TypeError, OSError):
        print("Invalid options/state. Check App documentation; no processes started.", flush=True)
        return 1
    print("OCPP 1.6 test simulator: " + ("connection enabled." if enabled else "disconnected."), flush=True)
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
        dns = lab_dns_url(Path("/etc/resolv.conf").read_text())
        if dns:
            os.environ["MO_LAB_DNS_URL"] = dns
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
