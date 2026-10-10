"""End-to-end acceptance of the packaged V2G App against a local mock CSMS.

Runs the real entrypoint (firewall, private veth link, test PKI, mosquitto,
EVerest manager, UI service, nginx) in a container with NET_ADMIN. Scenarios:

  v2g21      CSMS prefers 2.1 -> ocpp2.1; ISO 15118-20 DC_BPT session; a
             CentralSetpoint TxProfile charges then discharges (V2G export);
             after stop and unplug a fresh session charges again
  fallback   CSMS supports only 2.0.1 -> ocpp2.0.1; charging-only W limit
  pinned201  App option ocpp_version 2.0.1; CSMS prefers 2.1 -> ocpp2.0.1
  offline    Empty csms_url: no connection attempt leaves the host; the
             discovery self-test passes at start
  recovery   Discovery blocked on the private link: the EV's SDP requests
             fail and upstream Josev idles; after unblocking, unplug and
             plug-in, the patched module replaces that stack and a fresh
             EV stack completes discovery

Each charging step compares mean measured DC power with the setpoint, and
metered import and export energy with the integral of measured power.
"""
import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mock_csms import MockCsms  # noqa: E402

DATA = Path(os.environ.get("HA_EVEREST_DATA", "/data"))
UI = "http://127.0.0.1:8000"
STEP = int(os.environ.get("STEP_S", "20"))
CPID = "SIM-EV-EVEREST-V2G-01"
# Charge, then discharge (V2G export). Signed W: negative is discharge.
# Charging again after a discharge in the same session is a known EVerest
# 2025.10.0 limitation (VALIDATION.md), so the transaction stops after export.
SETPOINTS_W = [6000, -5000, 3000]
# 2.0.1 has no setpoints: one plain import limit below the 11 kW rating.
FALLBACK_LIMIT_W = 4000
POWER_TOLERANCE = 0.03


def setpoint_period(offset, watts):
    # Every period carries a setpoint: EVerest 2025.10.0 applies the nearest
    # setpoint to periods without one (VALIDATION.md).
    return {"startPeriod": offset, "limit": 11000.0, "dischargeLimit": -11000.0,
            "setpoint": float(watts), "operationMode": "CentralSetpoint"}


def http(path, method="GET", timeout=5):
    req = urllib.request.Request(UI + path, method=method, headers={"X-HA-EVerest": "1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


class App:
    def __init__(self, options):
        self.options = options
        self.proc = None

    def start(self):
        if DATA.exists():
            shutil.rmtree(DATA)
        DATA.mkdir(parents=True)
        (DATA / "options.json").write_text(json.dumps(self.options))
        self.log_path = f"/tmp/app-{int(time.time())}.log"
        self.log = open(self.log_path, "w")
        self.proc = subprocess.Popen([sys.executable, "/opt/ha-everest/app.py"],
                                     stdout=self.log, stderr=subprocess.STDOUT)

    def stop(self):
        self.proc.terminate()
        code = self.proc.wait(30)
        self.log.close()
        if sys.exc_info()[0] is not None or code != 0:
            print(f"== App log tail ({self.log_path})", flush=True)
            lines = [l for l in Path(self.log_path).read_text(errors="replace").splitlines()
                     if "ocpp:OCPP201" not in l and "api:API" not in l]
            print("\n".join(lines[-150:]), flush=True)
        return code


async def wait_for(predicate, timeout, interval=0.5, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception:
            pass
        await asyncio.sleep(interval)
    raise AssertionError(f"timed out waiting for {what}")


def reading():
    status = http("/api/status")
    pm = (status["evse"].get("powermeter") or {}).get("value") or {}
    si = (status["evse"].get("session_info") or {}).get("value") or {}
    return {
        "power": (pm.get("power_W") or {}).get("total"),
        "imported": (pm.get("energy_Wh_import") or {}).get("total"),
        "exported": (pm.get("energy_Wh_export") or {}).get("total"),
        "state": si.get("state"),
        "status": status,
    }


def iso_start(seconds=3):
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)
    return start, start.isoformat(timespec="seconds").replace("+00:00", "Z")


async def start_session(csms, first=True):
    await wait_for(lambda: reading()["state"] == "Unplugged", 60, what="idle EVSE")
    assert http("/api/ev/plugin", "POST")["sent"]
    await wait_for(lambda: reading()["state"] in ("AuthRequired", "Preparing"), 30,
                   what="plugged state")
    reply = await csms.call("RequestStartTransaction", {
        "idToken": {"idToken": "SIM-TEST", "type": "Central"}, "evseId": 1, "remoteStartId": 7})
    assert reply[2]["status"] == "Accepted", reply
    # SLAC, TLS 1.3, cable check and pre-charge take about 15 s. Profiles are
    # sent only once current flows in the charging loop (see VALIDATION.md).
    await wait_for(lambda: reading()["state"] == "Charging" and (reading()["power"] or 0) > 1000,
                   90, what="DC charging")
    await asyncio.sleep(10)
    events = [e for e in csms.calls("TransactionEvent") if e["eventType"] == "Started"]
    assert len(events) == (1 if first else 2), events
    return events[-1]["transactionInfo"]["transactionId"]


async def sample(t0, duration):
    samples = []
    while time.time() < t0 + duration:
        r = reading()
        samples.append((time.time() - t0, r["power"], r["imported"], r["exported"], r["state"]))
        await asyncio.sleep(1)
    return samples


def check_steps(samples, targets):
    steps = []
    for i, target in enumerate(targets):
        window = [s for s in samples if i * STEP + 6 <= s[0] <= (i + 1) * STEP - 2 and s[1] is not None]
        assert window, f"no samples for step {i}"
        mean_w = sum(s[1] for s in window) / len(window)
        ok = abs(mean_w - target) <= max(50, POWER_TOLERANCE * abs(target))
        steps.append({"target_W": target, "mean_W": round(mean_w), "pass": ok})
    trace = [(round(s[0]), s[1]) for s in samples]
    assert all(s["pass"] for s in steps), {"steps": steps, "trace": trace}
    return steps


def check_energy(samples):
    """Metered import/export vs. integral of positive/negative measured power."""
    rows = [s for s in samples if None not in s[1:4]]
    pos = neg = 0.0
    for a, b in zip(rows, rows[1:]):
        area = (b[0] - a[0]) * (a[1] + b[1]) / 2 / 3600
        if a[1] >= 0 and b[1] >= 0:
            pos += area
        elif a[1] <= 0 and b[1] <= 0:
            neg -= area
    imported = rows[-1][2] - rows[0][2]
    exported = rows[-1][3] - rows[0][3]
    result = {"import_metered": round(imported, 1), "import_integrated": round(pos, 1),
              "export_metered": round(exported, 1), "export_integrated": round(neg, 1)}
    # Sign-change intervals are excluded from the integrals, hence the margin.
    assert abs(imported - pos) <= max(5.0, 0.1 * pos), result
    assert abs(exported - neg) <= max(5.0, 0.1 * neg), result
    return result


async def finish(csms, txid):
    events = [e for e in csms.calls("TransactionEvent") if e["transactionInfo"]["transactionId"] == txid]
    assert not [e for e in events if e["eventType"] == "Ended"], "transaction ended early"
    ended_before = len([e for e in csms.calls("TransactionEvent") if e["eventType"] == "Ended"])
    reply = await csms.call("RequestStopTransaction", {"transactionId": txid})
    assert reply[2]["status"] == "Accepted", reply
    await wait_for(lambda: len([e for e in csms.calls("TransactionEvent")
                                if e["eventType"] == "Ended"]) > ended_before,
                   60, what="TransactionEvent Ended")
    await wait_for(lambda: abs(reading()["power"] or 0) < 1, 30, what="zero power after stop")
    http("/api/ev/unplug", "POST")
    await wait_for(lambda: reading()["state"] == "Unplugged", 60, what="unplugged")
    # The EV's ISO 15118 TLS session closes a few seconds after unplug.
    await asyncio.sleep(15)


def tx_profile(profile_id, txid, start_text, periods):
    return {"evseId": 1, "chargingProfile": {
        "id": profile_id, "stackLevel": 0, "chargingProfilePurpose": "TxProfile",
        "chargingProfileKind": "Absolute", "transactionId": txid,
        "chargingSchedule": [{"id": 1, "chargingRateUnit": "W", "startSchedule": start_text,
                              "chargingSchedulePeriod": periods}]}}


async def v2g_scenario():
    csms = await MockCsms(accept=("ocpp2.1", "ocpp2.0.1"), port=9220).start()
    app = App({"csms_url": "ws://127.0.0.1:9220", "charge_point_id": CPID, "ocpp_version": "2.1",
               "max_power_kw": 11, "acknowledge_test_isolation": True})
    app.start()
    report = {"scenario": "v2g21"}
    try:
        await asyncio.wait_for(csms.boot.wait(), 120)
        assert csms.subprotocol == "ocpp2.1", csms.subprotocol
        assert csms.path == "/" + CPID and csms.authorization == CPID
        await wait_for(lambda: http("/api/status")["app"].get("negotiated") == "ocpp2.1", 20,
                       what="UI negotiated version")
        txid = await start_session(csms)
        start, start_text = iso_start()
        periods = []
        for i, watts in enumerate(SETPOINTS_W):
            periods.append(setpoint_period(i * STEP, watts))
        reply = await csms.call("SetChargingProfile", tx_profile(210101, txid, start_text, periods))
        assert reply[2]["status"] == "Accepted", reply
        samples = await sample(start.timestamp(), STEP * len(SETPOINTS_W))
        report["steps"] = check_steps(samples, SETPOINTS_W)
        report["energy_Wh"] = check_energy(samples)
        assert report["energy_Wh"]["export_metered"] > 10, "no V2G export metered"
        tx = http("/api/profiles")["latest_tx_profile"]
        assert tx and tx["status"] == "Accepted", tx
        assert tx["payload"]["chargingProfile"]["chargingSchedule"][0]["chargingSchedulePeriod"] == periods
        await finish(csms, txid)
        # A new session after unplug charges normally (default limit).
        txid = await start_session(csms, first=False)
        report["second_session_W"] = reading()["power"]
        await finish(csms, txid)
        report["result"] = "pass"
    finally:
        report["app_exit"] = app.stop()
        csms.server.close()
    assert report["app_exit"] == 0, report
    log = open(app.log_path).read()
    for evidence in ("Selected DC_BPT service parameters",  # bidirectional DC service
                     "Client supports TLS1.3: Change verify mode to SSL_VERIFY_PEER",  # mutual TLS 1.3
                     "Handshake complete!"):
        assert evidence in log, f"missing ISO 15118-20 evidence: {evidence}"
    report["iso15118_20"] = "DC_BPT over mutual TLS 1.3"
    return report


async def fallback_scenario():
    csms = await MockCsms(accept=("ocpp2.0.1",), port=9220).start()
    app = App({"csms_url": "ws://127.0.0.1:9220", "charge_point_id": CPID, "ocpp_version": "2.1",
               "max_power_kw": 11, "acknowledge_test_isolation": True})
    app.start()
    report = {"scenario": "fallback"}
    try:
        await asyncio.wait_for(csms.boot.wait(), 120)
        assert csms.subprotocol == "ocpp2.0.1", csms.subprotocol
        await wait_for(lambda: http("/api/status")["app"].get("negotiated") == "ocpp2.0.1", 20,
                       what="UI negotiated version")
        txid = await start_session(csms)
        start, start_text = iso_start()
        periods = [{"startPeriod": 0, "limit": float(FALLBACK_LIMIT_W)}]
        reply = await csms.call("SetChargingProfile", tx_profile(201101, txid, start_text, periods))
        assert reply[2]["status"] == "Accepted", reply
        samples = await sample(start.timestamp(), STEP)
        report["steps"] = check_steps(samples, [FALLBACK_LIMIT_W])
        assert all((s[1] or 0) >= -1 for s in samples), "2.0.1 fallback must not discharge"
        await finish(csms, txid)
        report["result"] = "pass"
    finally:
        report["app_exit"] = app.stop()
        csms.server.close()
    assert report["app_exit"] == 0, report
    return report


async def version_only_scenario(name, app_version, csms_accept, expect):
    csms = await MockCsms(accept=csms_accept, port=9220).start()
    app = App({"csms_url": "ws://127.0.0.1:9220", "charge_point_id": "SIM-EV-EVEREST-V2G-02",
               "ocpp_version": app_version, "acknowledge_test_isolation": True})
    app.start()
    try:
        await asyncio.wait_for(csms.boot.wait(), 90)
        assert csms.subprotocol == expect, (csms.subprotocol, expect)
        await wait_for(lambda: http("/api/status")["app"].get("negotiated") == expect, 20,
                       what="UI negotiated version")
        result = {"scenario": name, "negotiated": csms.subprotocol, "result": "pass"}
    finally:
        code = app.stop()
        csms.server.close()
    assert code == 0
    return result


async def offline_scenario():
    csms = await MockCsms(port=9220).start()
    app = App({"csms_url": "", "charge_point_id": CPID})
    app.start()
    try:
        status = await wait_for(lambda: http("/api/status"), 60, what="UI")
        await wait_for(lambda: reading()["state"] == "Unplugged", 90, what="EVerest ready")
        await asyncio.sleep(5)
        assert not csms.connected.is_set(), "disconnected App must not connect"
        assert status["app"]["csms_configured"] is False
        assert not (DATA / "test-identity.json").exists()
        assert (DATA / "pki" / "certs" / "client" / "cso" / "SECC_LEAF.pem").is_file()
    finally:
        code = app.stop()
        csms.server.close()
    assert code == 0
    return {"scenario": "offline", "result": "pass"}


def log_text(app):
    app.log.flush()
    return Path(app.log_path).read_text(errors="replace")


def nft(*args):
    return subprocess.run(["nft", *args], check=True, text=True, stdout=subprocess.PIPE).stdout


async def recovery_scenario():
    app = App({"csms_url": "", "charge_point_id": CPID})
    app.start()
    try:
        await wait_for(lambda: reading()["state"] == "Unplugged", 90, what="EVerest ready")
        await wait_for(lambda: "Discovery self-test PASSED" in log_text(app), 60, what="self-test at start")
        # Block only SDP into the charger end, like an unanswered discovery.
        nft("insert", "rule", "inet", "ha_everest_v2g", "input", "iifname", "v2g0", "udp", "dport", "15118",
            "counter", "drop", "comment", '"acceptance block"')
        before = log_text(app).count("Got SDP request")
        assert http("/api/ev/plugin", "POST")["sent"]
        await wait_for(lambda: "SDPRequest was not successful" in log_text(app), 90,
                       what="EV discovery failure")
        assert log_text(app).count("Got SDP request") == before, "blocked SDP still reached the charger"
        listing = nft("-a", "list", "chain", "inet", "ha_everest_v2g", "input")
        handle = [line.rsplit("# handle ", 1)[1] for line in listing.splitlines() if "acceptance block" in line][0]
        nft("delete", "rule", "inet", "ha_everest_v2g", "input", "handle", handle.strip())
        http("/api/ev/unplug", "POST")
        await wait_for(lambda: reading()["state"] == "Unplugged", 60, what="unplugged")
        await asyncio.sleep(5)
        assert http("/api/ev/plugin", "POST")["sent"]
        await wait_for(lambda: "stack stopped (replaced by a new plug-in)" in log_text(app), 30,
                       what="stuck EV stack replaced")
        await wait_for(lambda: http("/api/status")["app"].get("ev_stack_restarts") == 1, 10,
                       what="restart counted")
        await wait_for(lambda: log_text(app).count("Got SDP request") > before, 60,
                       what="discovery by a fresh EV stack after re-plug")
        # Discovery, TLS and ISO 15118-20 session setup by the fresh stack.
        await wait_for(lambda: "Received session setup with evccid" in
                       log_text(app).rsplit("replaced by a new plug-in", 1)[1],
                       30, what="session setup by the fresh EV stack")
        http("/api/ev/unplug", "POST")
        await wait_for(lambda: reading()["state"] == "Unplugged", 60, what="unplugged again")
        await asyncio.sleep(15)  # the charger's session closes after unplug
        selftest = http("/api/diag/selftest", "POST", timeout=20)
        assert selftest["pass"], selftest
    finally:
        code = app.stop()
    assert code == 0
    return {"scenario": "recovery", "result": "pass"}


async def main(selected):
    results = []
    if "offline" in selected:
        results.append(await offline_scenario())
    if "recovery" in selected:
        results.append(await recovery_scenario())
    if "v2g21" in selected:
        results.append(await v2g_scenario())
    if "fallback" in selected:
        results.append(await fallback_scenario())
    if "pinned201" in selected:
        results.append(await version_only_scenario("pinned201", "2.0.1", ("ocpp2.1", "ocpp2.0.1"), "ocpp2.0.1"))
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["offline", "recovery", "v2g21", "fallback", "pinned201"]))
