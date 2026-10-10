"""Bounded native lifecycle against a loopback-only mock CSMS. Never targets HA."""
import asyncio
from datetime import datetime, timezone
import gzip
import importlib.util
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOT = Path(sys.argv[1]).resolve()
app_path = ROOT / "app.py"
if not app_path.exists():
    app_path = Path(__file__).resolve().parents[1] / "app.py"
spec = importlib.util.spec_from_file_location("app", app_path)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
BINARY = ROOT / "mo_simulator"
if not BINARY.exists():
    BINARY = ROOT / "build/mo_simulator"


def http(path, data=None, port=8000, headers=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw


def check_html_response():
    bodies = []
    for encoding in ("identity", "gzip"):
        request = urllib.request.Request(
            "http://127.0.0.1:8000/", headers={"Accept-Encoding": encoding})
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 200
            assert response.headers.get_all("Content-Type") == ["text/html; charset=utf-8"]
            assert response.headers.get("Content-Disposition") is None
            assert response.headers.get("Vary") == "Accept-Encoding"
            raw = response.read()
            if encoding == "gzip":
                assert response.headers.get_all("Content-Encoding") == ["gzip"]
                raw = gzip.decompress(raw)
            else:
                assert response.headers.get("Content-Encoding") is None
            bodies.append(raw)
    assert bodies[0] == bodies[1]
    assert b"<html" in bodies[0].lower()
    assert b"OCPP 1.6" not in bodies[0]
    assert b"OCPP 2.0.1 Connection" in bodies[0]


async def until(predicate, description, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("timed out: " + description)


async def main():
    # Never accidentally drive another already-running local simulator.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8000))
    received = []
    connections = []
    responses = {}

    async def csms(ws):
        assert ws.subprotocol == "ocpp2.0.1"
        assert ws.request.path == "/SIM-MICROOCPP-01"
        connections.append(ws)
        while True:
            try:
                raw = await ws.recv()
            except ConnectionClosed:
                break
            message = json.loads(raw)
            if message[0] != 2:
                responses[message[1]] = message
                continue
            _, uid, action, payload = message
            received.append((action, payload))
            result = {}
            if action == "BootNotification":
                result = {"status": "Accepted", "interval": 30,
                          "currentTime": datetime.now(timezone.utc).isoformat()}
                assert "chargingStation" in payload, payload
            elif action == "Heartbeat":
                result = {"currentTime": datetime.now(timezone.utc).isoformat()}
            elif action == "Authorize":
                result = {"idTokenInfo": {"status": "Accepted"}}
            elif action == "TransactionEvent":
                result = {"idTokenInfo": {"status": "Accepted"}}
            await ws.send(json.dumps([3, uid, result]))

    async with serve(csms, "127.0.0.1", 0, subprotocols=["ocpp2.0.1"]) as server:
        port = server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            app.configure(data, {"backend_url": f"ws://127.0.0.1:{port}",
                                 "acknowledge_test_isolation": True})
            (data / "public").symlink_to(ROOT / "public")
            with (data / "native.log").open("w+") as log:
                process = subprocess.Popen([str(BINARY)], cwd=data, stdout=log, stderr=log)
                try:
                    await until(lambda: connections, "2.0.1 WebSocket connection")
                    await until(lambda: any(a == "BootNotification" for a, _ in received), "boot")
                    check_html_response()
                    html = http("/").decode()
                    assert "http://localhost:8000/api" not in html
                    assert 'new URL("api",window.location.href).href' in html
                    settings = json.loads(http("/api/websocket"))
                    assert settings["chargeBoxId"] == "SIM-MICROOCPP-01"
                    assert json.loads(http("/api/connector/1/meter"))["power"] == 0
                    http("/api/connector/1/evse", {
                        "evPlugged": True, "evsePlugged": True,
                        "evReady": True, "evseReady": True,
                    })
                    http("/api/connector/1/transaction", {"idTag": "SIM-TEST"})
                    await until(lambda: any(a == "Authorize" for a, _ in received), "authorization")
                    await until(lambda: any(a == "TransactionEvent" and p["eventType"] == "Started"
                                            for a, p in received), "Started TransactionEvent")
                    await until(lambda: json.loads(http("/api/connector/1/meter"))["energy"] > 0,
                                "positive imported energy")
                    await until(lambda: any(a == "TransactionEvent" and p["eventType"] == "Updated"
                                            and p.get("meterValue") for a, p in received),
                                "periodic sampled meter values")
                    tx = next(p for a, p in received
                              if a == "TransactionEvent" and p["eventType"] == "Started")
                    api_tx = json.loads(http("/api/connector/1/transaction"))
                    assert api_tx["transactionId"] == tx["transactionInfo"]["transactionId"]
                    # Explicitly test the capability gap rather than claiming smart charging.
                    await connections[0].send(json.dumps([2, "profile-gap", "SetChargingProfile", {
                        "evseId": 1, "chargingProfile": {"id": 1, "stackLevel": 0,
                            "chargingProfilePurpose": "TxProfile", "chargingProfileKind": "Relative",
                            "transactionId": tx["transactionInfo"]["transactionId"],
                            "chargingSchedule": [{"id": 1, "chargingRateUnit": "W",
                                "chargingSchedulePeriod": [{"startPeriod": 0, "limit": 1000}]}]}}]))
                    await until(lambda: "profile-gap" in responses, "profile capability response")
                    assert responses["profile-gap"][0] == 4, responses["profile-gap"]
                    assert responses["profile-gap"][2] in ("NotImplemented", "NotSupported"), responses["profile-gap"]
                    # Network identity must be read-only through the CSMS device model.
                    await connections[0].send(json.dumps([2, "identity-guard", "SetVariables", {
                        "setVariableData": [{"attributeValue": "REAL-CHARGER",
                            "component": {"name": "SecurityCtrlr"},
                            "variable": {"name": "Identity"}}]}]))
                    await until(lambda: "identity-guard" in responses, "identity guard")
                    assert responses["identity-guard"][2]["setVariableResult"][0]["attributeStatus"] != "Accepted"
                    http("/api/connector/1/evse", {"evPlugged": False, "evsePlugged": False,
                                                  "evReady": False, "evseReady": False})
                    await until(lambda: any(a == "TransactionEvent" and p["eventType"] == "Ended"
                                            for a, p in received), "Ended TransactionEvent")
                    sampled = [s for a, p in received if a == "TransactionEvent"
                               for m in p.get("meterValue", []) for s in m["sampledValue"]]
                    assert any(s.get("measurand") == "Power.Active.Import" and s["value"] > 0
                               for s in sampled), sampled
                    print("PASS: ocpp2.0.1 negotiation, boot, authorize, start/end, energy,"
                          " string transaction ID, read-only identity, explicit profile gap.")
                finally:
                    process.send_signal(signal.SIGTERM)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                        raise AssertionError("SIGTERM did not stop native process")
                    log.seek(0)
                    output = log.read()
                    if process.returncode != 0:
                        print(output[-4000:])
                    assert process.returncode == 0, process.returncode
                    assert "connector with connectorId" not in output, output[-4000:]
                    assert "could not find connector" not in output, output[-4000:]
            # Startup remains disconnected even if previous endpoint state exists.
            app.configure(data, {})
            with (data / "offline.log").open("w") as log:
                process = subprocess.Popen([str(BINARY)], cwd=data, stdout=log, stderr=log)
                try:
                    await asyncio.sleep(1)
                    assert json.loads(http("/api/websocket"))["backendUrl"] == ""
                    assert len(connections) == 1
                    assert json.loads(http("/api/connector/1/meter"))["power"] == 0
                    assert json.loads(http("/api/connector/2/meter"))["power"] == 0
                    # Ended transaction history may survive restart. Do not
                    # mistake retained history for a new active transaction.
                    assert json.loads(http("/api/connector/1/transaction"))["transactionId"] in (
                        "", api_tx["transactionId"])
                    assert json.loads(http("/api/connector/2/transaction"))["transactionId"] == ""
                finally:
                    process.terminate()
                    process.wait(timeout=8)
            offline_output = (data / "offline.log").read_text()
            assert process.returncode == 0, process.returncode
            assert "connector with connectorId" not in offline_output, offline_output
            assert "could not find connector" not in offline_output, offline_output
            print("PASS: disconnected restart, no public fallback, safe stopped meter.")


asyncio.run(main())
