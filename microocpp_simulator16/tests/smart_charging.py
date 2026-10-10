"""Bounded OCPP 1.6J integration test against a loopback-only mock CSMS."""
import asyncio
from datetime import datetime, timezone, timedelta
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOT = Path(sys.argv[1]).resolve()
app_file = ROOT / "app.py"
if not app_file.exists():
    app_file = Path(__file__).resolve().parents[1] / "app.py"
spec = importlib.util.spec_from_file_location("app16", app_file)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
BINARY = ROOT / "mo_simulator"
if not BINARY.exists():
    BINARY = ROOT / "build/mo_simulator"


def http(path, data=None):
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=None if data is None else json.dumps(data).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=2) as response:
        return json.load(response)


async def until(predicate, label, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("timeout: " + label)


async def main():
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8000))
    received, connections, replies = [], [], {}

    async def csms(ws):
        assert ws.subprotocol == "ocpp1.6"
        assert ws.request.path == "/SIM-16-MICROOCPP-01"
        connections.append(ws)
        while True:
            try:
                raw = await ws.recv()
            except ConnectionClosed:
                break
            msg = json.loads(raw)
            if msg[0] != 2:
                replies[msg[1]] = msg
                continue
            _, uid, action, payload = msg
            received.append((action, payload))
            reply = {}
            if action == "BootNotification":
                assert "chargePointVendor" in payload
                reply = {"status": "Accepted", "interval": 10,
                         "currentTime": datetime.now(timezone.utc).isoformat()}
            elif action == "Heartbeat":
                reply = {"currentTime": datetime.now(timezone.utc).isoformat()}
            elif action in ("Authorize", "StopTransaction"):
                reply = {"idTagInfo": {"status": "Accepted"}}
            elif action == "StartTransaction":
                reply = {"idTagInfo": {"status": "Accepted"}, "transactionId": 1601}
            await ws.send(json.dumps([3, uid, reply]))

    async def call(action, payload):
        uid = str(len(replies) + 1)
        await connections[0].send(json.dumps([2, uid, action, payload]))
        await until(lambda: uid in replies, action)
        result = replies[uid]
        assert result[0] == 3, result
        return result[2]

    def profile(pid, limit, purpose="TxProfile", unit="W", **kwargs):
        p = {"chargingProfileId": pid, "stackLevel": 0,
             "chargingProfilePurpose": purpose, "chargingProfileKind": "Absolute",
             "chargingSchedule": {"chargingRateUnit": unit,
                                  "chargingSchedulePeriod": [{"startPeriod": 0, "limit": limit}]}}
        if purpose == "TxProfile":
            p["transactionId"] = 1601
        p.update(kwargs)
        return p

    async def install(p, connector=1):
        return await call("SetChargingProfile", {"connectorId": connector, "csChargingProfiles": p})

    async def power_is(limit, timeout=15):
        await until(lambda: abs(http("/api/connector/1/meter")["power"] - limit) <= 12,
                    f"power reaches {limit}", timeout)
        power = http("/api/connector/1/meter")["power"]
        assert power <= limit, (power, limit)

    async with serve(csms, "127.0.0.1", 0, subprotocols=["ocpp1.6"]) as server:
        port = server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            app.configure(data, {"backend_url": f"ws://127.0.0.1:{port}",
                                 "acknowledge_test_isolation": True})
            (data / "public").symlink_to(ROOT / "public")
            with (data / "native.log").open("w+") as log:
                process = subprocess.Popen([str(BINARY)], cwd=data, stdout=log, stderr=log)
                try:
                    await until(lambda: any(a == "BootNotification" for a, _ in received), "boot")
                    assert http("/api/connector/1/meter")["power"] == 0
                    with urllib.request.urlopen("http://127.0.0.1:8000/") as response:
                        html = response.read().decode()
                        assert response.headers.get_all("Content-Type") == ["text/html; charset=utf-8"]
                        assert "OCPP 1.6 Connection" in html
                        assert "OCPP 2.0.1 Connection" not in html
                        assert 'new URL("api",window.location.href).href' in html
                    assert (await call("ChangeConfiguration", {
                        "key": "MeterValueSampleInterval", "value": "1"}))["status"] == "Accepted"
                    assert (await call("ChangeConfiguration", {
                        "key": "Cst_ChargeBoxId", "value": "REAL-CHARGER"}))["status"] != "Accepted"
                    config = await call("GetConfiguration", {"key": [
                        "SupportedFeatureProfiles", "ChargingScheduleAllowedChargingRateUnit"]})
                    keys = {k["key"]: k["value"] for k in config["configurationKey"]}
                    assert "SmartCharging" in keys["SupportedFeatureProfiles"]
                    assert keys["ChargingScheduleAllowedChargingRateUnit"] == "Power"
                    # 1.6 simulator's existing callback explicitly supports W, not A.
                    assert (await install(profile(9, 16, "TxDefaultProfile", "A")))["status"] != "Accepted"
                    assert (await install(profile(10, 4200, "TxDefaultProfile")))["status"] == "Accepted"
                    http("/api/connector/1/evse", {
                        "evPlugged": True, "evsePlugged": True,
                        "evReady": True, "evseReady": True})
                    http("/api/connector/1/transaction", {"idTag": "SIM16-TEST"})
                    await until(lambda: any(a == "StartTransaction" for a, _ in received), "start")
                    await power_is(4200)
                    assert http("/api/connector/1/transaction")["transactionId"] == 1601
                    # Schedule ramp, pause and resume, without changing transaction.
                    start = datetime.now(timezone.utc) + timedelta(seconds=1)
                    limits = [4200, 7000, 11000, 4200, 0, 7000]
                    p = profile(11, 4200)
                    p["chargingSchedule"] = {
                        "chargingRateUnit": "W", "startSchedule": start.isoformat(),
                        "duration": 30,
                        "chargingSchedulePeriod": [
                            {"startPeriod": i * 4, "limit": limit}
                            for i, limit in enumerate(limits)]}
                    assert (await install(p))["status"] == "Accepted"
                    readings = []
                    for i, limit in enumerate(limits):
                        wait = (start + timedelta(seconds=i * 4 + 1)
                                - datetime.now(timezone.utc)).total_seconds()
                        if wait > 0:
                            await asyncio.sleep(wait)
                        await power_is(limit)
                        meter = http("/api/connector/1/meter")
                        assert http("/api/connector/1/transaction")["transactionId"] == 1601
                        assert not any(a == "StopTransaction" for a, _ in received)
                        readings.append({"limit_W": limit, **meter})
                        if limit == 0:
                            await asyncio.sleep(0.5)
                            assert http("/api/connector/1/meter")["energy"] == meter["energy"]
                    print("PASS ramp/pause/resume:", json.dumps(readings))
                    # On-wire meter samples must reflect the limits, including zero.
                    samples = [s for a, p in received if a == "MeterValues"
                               for m in p["meterValue"] for s in m["sampledValue"]
                               if s.get("measurand") == "Power.Active.Import"]
                    for limit in limits:
                        assert any(abs(float(s["value"]) - limit) <= 12 for s in samples), limit
                    assert (await install(profile(12, 5000, "ChargePointMaxProfile"), 0))["status"] == "Accepted"
                    await power_is(5000)
                    composite = await call("GetCompositeSchedule", {
                        "connectorId": 1, "duration": 3, "chargingRateUnit": "W"})
                    assert composite["status"] == "Accepted", composite
                    assert composite["chargingSchedule"]["chargingSchedulePeriod"][0]["limit"] <= 5000
                    # Clear profiles: TxDefault again governs; then factory ceiling.
                    for pid in (12, 11):
                        assert (await call("ClearChargingProfile", {"id": pid}))["status"] == "Accepted"
                    await power_is(4200)
                    assert (await call("ClearChargingProfile", {"id": 10}))["status"] == "Accepted"
                    await power_is(11000)
                    # Expiry must remove the temporary cap rather than latch it.
                    for future_period in (False, True):
                        now = datetime.now(timezone.utc)
                        expiry = now + timedelta(seconds=2)
                        expiring = profile(13, 4200, validTo=expiry.isoformat())
                        expiring["chargingSchedule"]["startSchedule"] = now.isoformat()
                        if future_period:
                            expiring["chargingSchedule"]["chargingSchedulePeriod"].append(
                                {"startPeriod": 10, "limit": 7000})
                        assert (await install(expiring))["status"] == "Accepted"
                        await power_is(4200)
                        await asyncio.sleep(2.2)
                        await power_is(11000, timeout=1.5)
                    energy = http("/api/connector/1/meter")["energy"]
                    http("/api/connector/1/evse", {"evPlugged": False, "evsePlugged": False,
                                                  "evReady": False, "evseReady": False})
                    await until(lambda: any(a == "StopTransaction" for a, _ in received), "stop")
                    stop = next(p for a, p in received if a == "StopTransaction")
                    assert stop["transactionId"] == 1601 and stop["meterStop"] >= energy
                    terminal = {s["measurand"]: float(s["value"])
                                for m in stop.get("transactionData", []) for s in m["sampledValue"]
                                if s.get("context") == "Transaction.End"}
                    assert terminal.get("Power.Active.Import") == 0, terminal
                    assert terminal.get("Current.Import") == 0, terminal
                    assert terminal.get("Energy.Active.Import.Register", -1) >= energy, terminal
                    meter = http("/api/connector/1/meter")
                    assert meter["power"] == meter["current"] == meter["voltage"] == 0
                    assert http("/api/connector/2/meter")["energy"] == 0
                    print("PASS max/default profiles, composite, clear, expiry, final zero samples, connector isolation")
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise AssertionError("native SIGTERM failed")
                    if process.returncode:
                        log.seek(0)
                        print(log.read()[-3000:])
                    assert process.returncode == 0
            app.configure(data, {})
            with (data / "offline.log").open("w") as log:
                process = subprocess.Popen([str(BINARY)], cwd=data, stdout=log, stderr=log)
                try:
                    await asyncio.sleep(1)
                    assert http("/api/websocket")["backendUrl"] == ""
                    assert http("/api/connector/1/meter")["power"] == 0
                    assert len(connections) == 1
                finally:
                    process.terminate()
                    process.wait(timeout=8)
            print("PASS disconnected restart, no fallback network")


if __name__ == "__main__":
    asyncio.run(main())
