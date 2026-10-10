"""Validated HA options and bounded supervision of the EVerest DC V2G SIL App.

Before any process starts: inbound firewall and private ISO 15118 link
(netguard.py), then the per-install test PKI (pki.py). Processes: private
mosquitto (loopback only), EVerest manager, UI service (loopback only) and
nginx (Ingress port, Supervisor peer only), and with `ha_control` the
outbound-only Home Assistant bridge (ha_bridge.py). Once the charger's SDP
server is up, the discovery self-test (diag.py) runs once and logs its result.
"""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import configure  # noqa: E402
import netguard  # noqa: E402
import pki  # noqa: E402

ROOT = Path("/opt/ha-everest")
PREFIX = Path("/opt/everest")
DATA = Path(os.environ.get("HA_EVEREST_DATA", "/data"))
RUN = Path(os.environ.get("HA_EVEREST_RUN", "/run/ha-everest"))
SOURCE = PREFIX / "share/everest/modules/OCPP201/component_config"
VERSION_LINE = re.compile(r"successfully connected to server with version: (ocpp[0-9.]+)")
SDP_READY = "Starting SDP server"
EV_STACK_STOPPED = "ha-everest: EV ISO 15118 stack stopped"
SELFTEST_DELAY_S = 3
DISCONNECT_LINE = re.compile(r"(Disconnected|connection failed|Failed to connect)", re.I)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
STAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")
# The pinned demo image logs every composite schedule (multi-line JSON from
# OCPP201, one line from API) every CompositeScheduleIntervalS. The OCPP
# frames stay in /data/everest/ocpp_logs and on the Status page.
JSON_START = re.compile(r"\] ocpp:OCPP201\s*: \{$")
# The demo build also prints certificate-chain debug lines (SHANKARI:).
NOISY = ("Received OCPP charging schedule update", "About to publish composite charging schedules",
         "SHANKARI: ")


def write_state(**values):
    state_path = RUN / "state.json"
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    state.update(values)
    configure.atomic_write(state_path, json.dumps(state), mode=0o644)


class LogFilter:
    """Drop repetitive composite-schedule output; pass everything else."""

    def __init__(self):
        self.in_json = False

    def keep(self, line):
        if line.startswith("libgcov profiling error"):
            return False
        if STAMP.match(line):
            self.in_json = bool(JSON_START.search(line))
            return not self.in_json and not any(n in line for n in NOISY)
        return not self.in_json


def pump(stream, prefix="", sdp_ready=None):
    """Forward EVerest output to the App log and record the negotiated version."""
    log_filter = LogFilter()
    restarts = 0
    for raw in iter(stream.readline, ""):
        line = ANSI.sub("", raw.rstrip("\n"))
        if not log_filter.keep(line):
            continue
        match = VERSION_LINE.search(line)
        if match:
            write_state(negotiated=match.group(1), connected_at=time.time())
        elif "websocket" in line.lower() and DISCONNECT_LINE.search(line):
            write_state(negotiated=None)
        elif SDP_READY in line and sdp_ready is not None:
            sdp_ready.set()
        elif EV_STACK_STOPPED in line:
            restarts += 1
            write_state(ev_stack_restarts=restarts, ev_stack_last_error=line[-300:])
        print(prefix + line, flush=True)


def startup_selftest(sdp_ready, stopping, timeout=90):
    """Run the discovery self-test once the charger's SDP server is up."""
    import ui_server
    if not sdp_ready.wait(timeout):
        print("Discovery self-test skipped: the SDP server did not start within "
              f"{timeout} s.", flush=True)
        return
    time.sleep(SELFTEST_DELAY_S)
    if not stopping():
        try:
            ui_server.run_selftest("at start")
        except OSError as error:
            print(f"Discovery self-test error ({error}).", flush=True)


def wait_group(pgid, timeout):
    """Wait until every EVerest module in the manager's group has exited."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # As PID 1 (init: false) this process inherits orphaned modules; reap
        # only members of the EVerest group so they do not linger as zombies.
        try:
            while os.waitpid(-pgid, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        time.sleep(0.1)
    raise subprocess.TimeoutExpired("everest modules", timeout)


def run():
    os.umask(0o077)
    RUN.mkdir(parents=True, exist_ok=True)
    try:
        options = json.loads((DATA / "options.json").read_text())
        configure.validate(options)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Invalid options/state ({error}). No processes started.", flush=True)
        return 1
    try:
        netguard.setup()
        Path(configure.ISO_LOG_DIR).mkdir(parents=True, exist_ok=True)
        key_password, certs, renewed = pki.ensure(DATA)
        pki.link(PREFIX, certs)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"V2G isolation setup failed ({error}). No processes started.", flush=True)
        return 1
    print("Private ISO 15118 link and inbound firewall ready; test PKI "
          + ("generated." if renewed else "reused."), flush=True)
    try:
        settings, config_path = configure.configure(DATA, options, SOURCE, PREFIX, key_password)
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Invalid options/state ({error}). No processes started.", flush=True)
        return 1
    connected = bool(settings["csms_url"])
    offered = configure.VERSIONS[settings["ocpp_version"]]
    configure.atomic_write(RUN / "state.json", json.dumps({
        "charge_point_id": settings["charge_point_id"],
        "csms_configured": connected,
        "ocpp_version_option": settings["ocpp_version"],
        "offered_subprotocols": offered.split(","),
        "max_power_kw": settings["max_power_kw"],
        "charger": "DC bidirectional (ISO 15118-20 DC_BPT)",
        "negotiated": None,
        "ha_control": settings["ha_control"],
        "ev_stack_restarts": 0,
    }), mode=0o644)
    print("EVerest DC V2G test charger: " + (
        f"connection enabled, offering {offered}." if connected else "disconnected."), flush=True)

    children = []
    extras = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    # The demo build is coverage-instrumented; keep its exit-time .gcda
    # writes away from the (absent) build tree.
    env = dict(os.environ, LD_LIBRARY_PATH=str(PREFIX / "lib"), PYTHONUNBUFFERED="1",
               GCOV_PREFIX="/tmp/gcov", GCOV_PREFIX_STRIP="0")
    result = 1
    manager = None
    try:
        children.append(subprocess.Popen(
            ["mosquitto", "-c", str(ROOT / "mosquitto.conf")]))
        time.sleep(0.5)
        manager = subprocess.Popen(
            [str(PREFIX / "bin/manager"), "--prefix", str(PREFIX), "--conf", str(config_path)],
            cwd=DATA / "everest", env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", start_new_session=True)
        children.append(manager)
        sdp_ready = threading.Event()
        threading.Thread(target=pump, args=(manager.stdout, "", sdp_ready), daemon=True).start()
        children.append(subprocess.Popen(
            [sys.executable, str(ROOT / "ui_server.py")], env=env))
        children.append(subprocess.Popen(
            ["nginx", "-c", str(ROOT / "nginx.conf"), "-g", "daemon off;"]))
        threading.Thread(target=startup_selftest, args=(sdp_ready, lambda: stopping),
                         daemon=True).start()
        if settings["ha_control"]:
            # Outbound only. Not in `children`: a bridge failure must not stop
            # the charger; it retries with back-off on its own.
            bridge = subprocess.Popen([sys.executable, str(ROOT / "ha_bridge.py"),
                                       settings["charge_point_id"]], env=env)
            extras.append(bridge)
        while not stopping and all(child.poll() is None for child in children):
            time.sleep(0.2)
        result = 0 if stopping else 1
    finally:
        for extra in extras:
            if extra.poll() is None:
                extra.terminate()
                try:
                    extra.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    extra.kill()
                    extra.wait()
        # Stop in reverse start order and wait for each, so EVerest closes OCPP
        # cleanly while its MQTT broker is still running.
        for child in reversed(children):
            if child.poll() is None:
                try:
                    if child is manager:
                        os.killpg(child.pid, signal.SIGTERM)
                    else:
                        child.terminate()
                except ProcessLookupError:
                    pass
            try:
                child.wait(timeout=8)
                if child is manager:
                    wait_group(child.pid, 8)
            except subprocess.TimeoutExpired:
                try:
                    if child is manager:
                        os.killpg(child.pid, signal.SIGKILL)
                    else:
                        child.kill()
                except ProcessLookupError:
                    pass
                child.wait()
    return result


if __name__ == "__main__":
    sys.exit(run())
