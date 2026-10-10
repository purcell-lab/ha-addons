"""End-to-end acceptance of the packaged App against a local mock CSMS.

Runs the real entrypoint (mosquitto, EVerest manager, UI service, nginx) in
an offline container. Scenarios:

  ocpp21     App default (offers 2.1, 2.0.1); CSMS prefers 2.1  -> ocpp2.1
  fallback   App default; CSMS supports only 2.0.1             -> ocpp2.0.1
  pinned201  App option ocpp_version 2.0.1; CSMS prefers 2.1   -> ocpp2.0.1
  offline    Empty csms_url: no connection attempt leaves the host

The charging scenarios check one stepped single-phase TxProfile against
measured EVSE power and energy, zero-power pause without ending the
transaction, the Status-page profile record, remote stop and unplug.
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
STEP = int(os.environ.get("STEP_S", "15"))
# Plugfest-style steps: import limit, household clipping, pause, restore.
SCHEDULE_W = [4000, 7360, 0, 2000, 7360]
VOLTAGE_MARGIN = 0.10   # simulator voltage sits a few per cent below 230 V
CURRENT_FLOOR_A = 6.0


def http(path, method="GET"):
    req = urllib.request.Request(UI + path, method=method, headers={"X-HA-EVerest": "1"})
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read())


def expected_current(limit_w, max_a=32):
    amps = min(limit_w / 230.0, max_a)
    return 0.0 if amps < CURRENT_FLOOR_A else amps


class App:
    def __init__(self, options):
        self.options = options
        self.proc = None

    def start(self):
        if DATA.exists():
            shutil.rmtree(DATA)
        DATA.mkdir(parents=True)
        (DATA / "options.json").write_text(json.dumps(self.options))
        self.log = open(f"/tmp/app-{int(time.time())}.log", "w")
        self.proc = subprocess.Popen([sys.executable, "/opt/ha-everest/app.py"],
                                     stdout=self.log, stderr=subprocess.STDOUT)

    def stop(self):
        self.proc.terminate()
        code = self.proc.wait(30)
        self.log.close()
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
        "current": (pm.get("current_A") or {}).get("L1"),
        "energy": (pm.get("energy_Wh_import") or {}).get("total"),
        "state": si.get("state"),
        "status": status,
    }


async def charging_scenario(name, app_version, csms_accept, expect):
    csms = await MockCsms(accept=csms_accept, port=9220).start()
    app = App({"csms_url": "ws://127.0.0.1:9220", "charge_point_id": "SIM-EV-EVEREST-01",
               "ocpp_version": app_version, "phases": "1", "max_current_a": 32,
               "acknowledge_test_isolation": True})
    app.start()
    report = {"scenario": name}
    try:
        await asyncio.wait_for(csms.boot.wait(), 90)
        assert csms.subprotocol == expect, (csms.subprotocol, expect)
        assert csms.path == "/SIM-EV-EVEREST-01", csms.path
        assert csms.authorization == "SIM-EV-EVEREST-01", "SP1 basic auth identity"
        await wait_for(lambda: http("/api/status")["app"].get("negotiated") == expect, 20,
                       what="UI negotiated version")
        await wait_for(lambda: reading()["state"] == "Unplugged", 30, what="idle EVSE")
        assert http("/api/ev/plugin", "POST")["sent"]
        await wait_for(lambda: reading()["state"] in ("AuthRequired", "Preparing"), 20,
                       what="plugged state")
        reply = await csms.call("RequestStartTransaction", {
            "idToken": {"idToken": "SIM-TEST", "type": "Central"}, "evseId": 1, "remoteStartId": 7})
        assert reply[2]["status"] == "Accepted", reply
        await wait_for(lambda: (reading()["power"] or 0) > 6000, 30, what="unrestricted charging")
        started = csms.calls("TransactionEvent")[0]
        txid = started["transactionInfo"]["transactionId"]

        start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=3)
        periods = [{"startPeriod": i * STEP, "limit": float(w), "numberPhases": 1}
                   for i, w in enumerate(SCHEDULE_W)]
        profile = {"evseId": 1, "chargingProfile": {
            "id": 160601, "stackLevel": 0, "chargingProfilePurpose": "TxProfile",
            "chargingProfileKind": "Absolute", "transactionId": txid,
            "chargingSchedule": [{"id": 1, "chargingRateUnit": "W",
                                  "startSchedule": start.isoformat(timespec="seconds").replace("+00:00", "Z"),
                                  "chargingSchedulePeriod": periods}]}}
        reply = await csms.call("SetChargingProfile", profile)
        assert reply[2]["status"] == "Accepted", reply
        t0 = start.timestamp()

        samples = []
        while time.time() < t0 + STEP * len(SCHEDULE_W):
            r = reading()
            samples.append((time.time() - t0, r["power"], r["current"], r["energy"], r["state"]))
            await asyncio.sleep(1)

        steps = []
        for i, limit in enumerate(SCHEDULE_W):
            # Middle of each window, after EVerest's update and EV ramp.
            window = [s for s in samples if i * STEP + 6 <= s[0] <= (i + 1) * STEP - 2]
            assert window, f"no samples for step {i}"
            amps = [s[2] for s in window if s[2] is not None]
            watts = [s[1] for s in window if s[1] is not None]
            mean_a = sum(amps) / len(amps)
            mean_w = sum(watts) / len(watts)
            want_a = expected_current(limit)
            ok = abs(mean_a - want_a) <= max(0.6, 0.03 * want_a) and mean_w <= limit * 1.01 + 5
            if want_a:
                ok = ok and mean_w >= limit * (1 - VOLTAGE_MARGIN)
            steps.append({"limit_W": limit, "expected_A": round(want_a, 2),
                          "mean_A": round(mean_a, 2), "mean_W": round(mean_w), "pass": ok})
        report["steps"] = steps
        assert all(s["pass"] for s in steps), steps

        events = csms.calls("TransactionEvent")
        assert not [e for e in events if e["eventType"] == "Ended"], "pause must not end the transaction"
        assert len({e["transactionInfo"]["transactionId"] for e in events}) == 1

        # Energy over the schedule vs. integral of measured power (trapezoid).
        sched = [s for s in samples if s[1] is not None and s[3] is not None]
        integral = sum((b[0] - a[0]) * (a[1] + b[1]) / 2 for a, b in zip(sched, sched[1:])) / 3600
        metered = sched[-1][3] - sched[0][3]
        report["energy_Wh"] = {"metered": round(metered, 1), "integrated": round(integral, 1)}
        assert abs(metered - integral) <= max(3.0, 0.08 * integral), report["energy_Wh"]

        profiles = http("/api/profiles")
        tx = profiles["latest_tx_profile"]
        assert tx and tx["status"] == "Accepted", tx
        assert tx["payload"]["chargingProfile"]["id"] == 160601
        assert tx["payload"]["chargingProfile"]["chargingSchedule"][0]["chargingSchedulePeriod"] == periods

        reply = await csms.call("RequestStopTransaction", {"transactionId": txid})
        assert reply[2]["status"] == "Accepted", reply
        await wait_for(lambda: [e for e in csms.calls("TransactionEvent") if e["eventType"] == "Ended"],
                       30, what="TransactionEvent Ended")
        await wait_for(lambda: (reading()["power"] or 0) < 1, 20, what="zero power after stop")
        assert http("/api/ev/unplug", "POST")["sent"]
        await wait_for(lambda: reading()["state"] == "Unplugged", 30, what="unplugged")
        r = reading()
        assert (r["current"] or 0) < 0.1, r
        report["result"] = "pass"
    finally:
        report["app_exit"] = app.stop()
        csms.server.close()
    assert report["app_exit"] == 0, report
    return report


async def version_only_scenario(name, app_version, csms_accept, expect):
    csms = await MockCsms(accept=csms_accept, port=9220).start()
    app = App({"csms_url": "ws://127.0.0.1:9220", "charge_point_id": "SIM-EV-EVEREST-02",
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
    app = App({"csms_url": "", "charge_point_id": "SIM-EV-EVEREST-01"})
    app.start()
    try:
        status = await wait_for(lambda: http("/api/status"), 60, what="UI")
        await wait_for(lambda: reading()["state"] == "Unplugged", 60, what="EVerest ready")
        await asyncio.sleep(5)
        assert not csms.connected.is_set(), "disconnected App must not connect"
        assert status["app"]["csms_configured"] is False
        assert not (DATA / "test-identity.json").exists()
    finally:
        code = app.stop()
        csms.server.close()
    assert code == 0
    return {"scenario": "offline", "result": "pass"}


async def main(selected):
    results = []
    if "offline" in selected:
        results.append(await offline_scenario())
    if "ocpp21" in selected:
        results.append(await charging_scenario("ocpp21", "2.1", ("ocpp2.1", "ocpp2.0.1"), "ocpp2.1"))
    if "fallback" in selected:
        results.append(await charging_scenario("fallback", "2.1", ("ocpp2.0.1",), "ocpp2.0.1"))
    if "pinned201" in selected:
        results.append(await version_only_scenario("pinned201", "2.0.1", ("ocpp2.1", "ocpp2.0.1"), "ocpp2.0.1"))
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["offline", "ocpp21", "fallback", "pinned201"]))
