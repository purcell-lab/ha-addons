"""Validated HA options, persistent state, and bounded two-process supervision."""
import json
import ipaddress
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path("/opt/microocpp")
DATA = Path("/data")


def validate(options):
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    backend = options.get("backend_url", "")
    cpid = options.get("charge_point_id", "SIM-CITRINE-LAB-01")
    acknowledged = options.get("acknowledge_test_isolation", False)
    trial_id = options.get("bounded_trial_id", "")
    if not isinstance(trial_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{0,64}", trial_id):
        raise ValueError("bounded_trial_id must be a short safe identifier")
    if trial_id and not backend:
        raise ValueError("A bounded trial requires the isolated backend")
    if cpid != "SIM-CITRINE-LAB-01":
        raise ValueError("Dedicated CitrineOS identity required")
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
        if not re.fullmatch(r"[a-f0-9]{40}", options.get("password", "")):
            raise ValueError("Generated simulator credential required")
        if not (url.hostname.endswith("-citrineos-server") or url.hostname == "lab-server") or port != 8081:
            raise ValueError("Dedicated internal CitrineOS listener required")
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


def configure(data, options):
    backend, cpid = validate(options)
    data.mkdir(parents=True, exist_ok=True)
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
        "AuthorizationKey": options.get("password", ""), "WebSocketPingInterval": 30,
        "Cst_ReconnectInterval": 30,
    })
    atomic_json(store / "ws-conn-v201.jsn", {"variables": [
        {"component": "SecurityCtrlr", "name": name, "valActual": value}
        for name, value in (("CsmsUrl", backend), ("Identity", cpid), ("BasicAuthPassword", options.get("password", "")))
    ]})
    # Deliberately retain transaction/config files; boot unloaded and not ready.
    update_config(store / "simulator.jsn", {
        "OcppVersion": "2.0.1",
        **{f"{key}_cId_{n}": False for n in (1, 2)
           for key in ("evPlugged", "evsePlugged", "evReady", "evseReady")},
    })
    atomic_json(store / "api.jsn", {"url": "http://127.0.0.1:8000", "user": "", "pass": ""})
    return bool(backend)


def run():
    os.umask(0o077)
    try:
        options = json.loads((DATA / "options.json").read_text())
        enabled = configure(DATA, options)
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
        # Mongoose does not consult libc resolv.conf itself.
        resolvers = re.findall(r"^nameserver\s+(\S+)", Path("/etc/resolv.conf").read_text(), re.M)
        resolver = next(str(ipaddress.IPv4Address(x)) for x in resolvers if ":" not in x)
        os.environ["MO_LAB_DNS_URL"] = "udp://" + resolver + ":53"
        children.append(subprocess.Popen([str(ROOT / "mo_simulator")], cwd=DATA))
        children.append(subprocess.Popen(["nginx", "-c", str(ROOT / "nginx.conf"),
                                          "-g", "daemon off;"]))
        energized_at = None
        trial_id = options.get("bounded_trial_id", "")
        journal = DATA / "bounded-trials.json"
        completed = json.loads(journal.read_text()) if journal.exists() else []
        trial_pending = bool(trial_id and trial_id not in completed)
        trial_started = None
        trial_stop_at = None
        last_sample = 0
        boot_at = time.monotonic()
        def local_api(path, body=None):
            request = urllib.request.Request("http://127.0.0.1:8000" + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=2) as r:
                return json.load(r)
        flags = ("evPlugged", "evsePlugged", "evReady", "evseReady")
        while not stopping and all(child.poll() is None for child in children):
            # Independent 180-second limit even if the test orchestrator disappears.
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/api/connector/1/meter", timeout=1) as r:
                    meter = json.load(r)
                    power = meter.get("power", 0)
                if trial_pending and time.monotonic() - boot_at >= 30:
                    # Persist before any start action. A restart must never replay it.
                    completed.append(trial_id)
                    atomic_json(journal, completed)
                    trial_pending = False
                    trial_started = time.monotonic()
                    print(json.dumps({"bounded_trial": trial_id, "phase": "starting", "meter": meter}), flush=True)
                    local_api("/api/connector/1/evse", {k: True for k in flags})
                    local_api("/api/connector/1/transaction", {"idTag": "C17E0001"})
                if trial_started is not None and time.monotonic() - trial_started >= 45:
                    local_api("/api/connector/1/evse", {k: False for k in flags})
                    print(json.dumps({"bounded_trial": trial_id, "phase": "stopped", "meter_before_stop": meter}), flush=True)
                    trial_started = None
                    trial_stop_at = time.monotonic()
                if trial_started is not None and time.monotonic() - last_sample >= 5:
                    print(json.dumps({"bounded_trial": trial_id, "phase": "sample", "meter": meter}), flush=True)
                    last_sample = time.monotonic()
                if trial_stop_at is not None and time.monotonic() - trial_stop_at >= 5:
                    print(json.dumps({"bounded_trial": trial_id, "phase": "post_stop", "meter": meter}), flush=True)
                    trial_stop_at = None
                if power > 0 and energized_at is None:
                    energized_at = time.monotonic()
                if energized_at is not None and time.monotonic() - energized_at > 180:
                    stop_payload = json.dumps({k: False for k in ("evPlugged","evsePlugged","evReady","evseReady")}).encode()
                    for n in (1, 2):
                        request = urllib.request.Request(f"http://127.0.0.1:8000/api/connector/{n}/evse",
                            data=stop_payload, headers={"Content-Type":"application/json"})
                        with urllib.request.urlopen(request, timeout=2):
                            pass
                    print("Bounded trial stopped at the 180-second limit.", flush=True)
                    energized_at = None
            except (OSError, ValueError):
                if trial_started is not None and time.monotonic() - trial_started > 50:
                    stopping = True
                if energized_at is not None and time.monotonic() - energized_at > 180:
                    stopping = True
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
