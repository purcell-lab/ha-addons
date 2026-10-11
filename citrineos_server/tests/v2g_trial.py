"""Pinned CitrineOS + real EVerest App + actual HA API client, disposable CI only."""
import base64
import datetime as dt
import json
import math
from pathlib import Path
import secrets
import statistics
import subprocess
import time

STATION = "SIM-EV-EVEREST-V2G-01"


def discovery_ready(value):
    """Absent/null self-test means pending, not ready and not an exception."""
    return (isinstance(value, dict) and isinstance(value.get("selftest"), dict)
            and value["selftest"].get("pass") is True)


def trial(docker, request, server_options, names, secret_values, temporary):
    password, commander = secrets.token_hex(16), secrets.token_hex(32)
    secret_values.extend([password, commander,
        base64.b64encode((STATION + ":" + password).encode()).decode()])
    reader = server_options["api_token"]
    report = {"result": "running", "station": STATION, "steps": []}
    output = Path("v2g-integration-evidence.json")

    def until(fn, label, seconds=120):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                result = fn()
                if result:
                    return result
            except (ValueError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError):
                pass
            time.sleep(2)
        raise AssertionError(label + " timed out")

    def gql(query):
        status, result = request("/v1/graphql", body={"query": query})
        if status != 200 or result.get("errors"):
            raise AssertionError("Bounded GraphQL query failed")
        return result["data"]

    def rows():
        return gql('query { ChargingStations { id ocppConnectionName protocol isOnline } }')["ChargingStations"]

    def transactions():
        sid = next(s["id"] for s in rows() if s["ocppConnectionName"] == STATION)
        return gql('query { Transactions(where:{stationId:{_eq:%d}}) { id transactionId isActive endTime } }' % sid)["Transactions"]

    def probe(action, **kwargs):
        p = subprocess.run(["docker", "exec", "-i", "lab-client", "python", "/opt/client_probe.py"],
            input=json.dumps({"reader": reader, "commander": commander, "action": action, **kwargs}),
            capture_output=True, text=True, timeout=35)
        try:
            value = json.loads(p.stdout)
        except ValueError:
            raise AssertionError("Client probe failed without JSON") from None
        if p.returncode:
            raise AssertionError("Client probe: " + json.dumps(value))
        return value

    def ui(path="/api/status", method="GET"):
        code = """import urllib.request,json,sys
x=json.load(sys.stdin)
r=urllib.request.Request('http://127.0.0.1:8000'+x['path'],method=x['method'],
 headers={'X-HA-EVerest':'1'})
with urllib.request.urlopen(r,timeout=30 if x['method']=='POST' else 5) as response: print(response.read().decode())
"""
        p = subprocess.run(["docker", "exec", "-i", "lab-v2g", "python3", "-c", code],
            input=json.dumps({"path": path, "method": method}), capture_output=True, text=True, timeout=40 if method=="POST" else 12)
        if p.returncode:
            raise RuntimeError("Simulator UI not ready")
        return json.loads(p.stdout)

    def reading():
        s = ui()
        meter = (s.get("evse", {}).get("powermeter") or {}).get("value") or {}
        session = (s.get("evse", {}).get("session_info") or {}).get("value") or {}
        return {"time": time.time(), "power_w": (meter.get("power_W") or {}).get("total"),
                "import_wh": (meter.get("energy_Wh_import") or {}).get("total"),
                "export_wh": (meter.get("energy_Wh_export") or {}).get("total"),
                "state": session.get("state")}

    def stamp():
        return dt.datetime.now(dt.timezone.utc).isoformat()

    server_options.update(profile_simulator_enabled=True, profile_simulator_password=password,
                          command_control_enabled=True, command_token=commander)
    p = temporary / "lab-server.json"
    p.write_text(json.dumps(server_options)); p.chmod(0o600)
    docker("cp", str(p), "lab-server:/data/options.json")
    docker("restart", "lab-server")
    until(lambda: request("/lab/status")[0] == 200, "Scoped server readiness")
    path = "/ocpp/2.1/evdriver/requestStartTransaction?identifier=" + STATION + "&tenantId=1"
    payload = {"remoteStartId": 7, "evseId": 1, "idToken": {"idToken":"C17E0001","type":"ISO14443"}}
    assert request(path, body=payload)[0] == 403, "Reader must not send commands"
    assert request(path, body=payload, extra={"Authorization": "Bearer wrong"})[0] == 401
    assert request(path.replace(STATION, "REAL"), body=payload,
                   extra={"Authorization": "Bearer " + commander})[0] == 400
    report["security_negative_controls"] = "reader/wrong-credential/foreign-station rejected"
    docker("create", "--name", "lab-client", "--network", "citrine-ci", "citrine-client:test")
    names.append("lab-client"); docker("start", "lab-client")
    assert probe("ping")["policy"] == "verified"
    docker("create", "--name", "lab-v2g", "--network", "citrine-ci", "--cap-add", "NET_ADMIN",
           "--memory", "1536m", "citrine-v2g:test")
    names.append("lab-v2g")
    p = temporary / "lab-v2g.json"
    p.write_text(json.dumps({"csms_url": "ws://lab-server:8081", "charge_point_id": STATION,
        "ocpp_version": "2.1", "max_power_kw": 11, "acknowledge_test_isolation": True,
        "csms_basic_auth_password": password, "ha_control": False}))
    p.chmod(0o600); docker("cp", str(p), "lab-v2g:/data/options.json")
    docker("start", "lab-v2g")
    txid = None
    try:
        until(lambda: any(s["ocppConnectionName"] == STATION and s["protocol"] == "ocpp2.1"
                          and s["isOnline"] for s in rows()), "Native 2.1 registration")
        until(lambda: ui()["app"].get("negotiated") == "ocpp2.1", "EVSE observed 2.1")
        until(lambda: reading()["state"] == "Unplugged", "Idle EVSE")
        # The boot-time discovery self-test owns the plugin lock. An idle
        # session does not mean that this independent readiness test finished.
        until(lambda: discovery_ready(ui("/api/diagnostics?brief=1")),
              "Boot-time discovery self-test", 60)
        report["registered_at"] = stamp()
        assert ui("/api/ev/plugin", "POST").get("sent")
        until(lambda: reading()["state"] in ("AuthRequired", "Preparing"), "Plugged readiness")
        report["start_dispatch"] = probe("start")
        until(lambda: reading()["state"] == "Charging" and (reading()["power_w"] or 0) > 1000,
              "DC charging")
        tx = until(lambda: next((t for t in transactions() if t["isActive"]), None), "CSMS active transaction")
        txid = tx["transactionId"]; report["transaction_id"] = txid
        report["charging_observed_at"] = stamp()
        time.sleep(10)
        targets = [6000, -5000, 3000, 0]
        step = 30
        start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=8)
        periods = [{"startPeriod": i*step, "limit":11000, "dischargeLimit":-11000,
                    "setpoint": watts, "operationMode":"CentralSetpoint"} for i,watts in enumerate(targets)]
        report["profile_dispatch"] = probe("profile", transaction_id=txid, periods=periods,
            duration=180, start_at=start.isoformat())
        event = until(lambda: (p if (p:=ui("/api/profiles").get("latest_tx_profile"))
                              and p["status"] == "Accepted" else None), "EVSE profile Accepted", 25)
        assert event["payload"]["chargingProfile"]["transactionId"] == txid
        assert event["payload"]["chargingProfile"]["chargingSchedule"][0]["chargingSchedulePeriod"] == periods
        report["profile_evidence"] = event
        samples = []
        while time.time() < start.timestamp() + step*len(targets):
            sample = reading(); sample["relative_s"] = sample["time"] - start.timestamp()
            samples.append(sample)
            time.sleep(1)
        for i, watts in enumerate(targets):
            window = [s for s in samples if i*step+8 <= s["relative_s"] <= (i+1)*step-3]
            assert len(window) >= 8 and all(isinstance(s["power_w"],(int,float)) for s in window)
            mean = statistics.mean(s["power_w"] for s in window)
            report["steps"].append({"setpoint_w": watts, "mean_power_w": mean, "samples": len(window)})
            assert abs(mean-watts) <= max(50,abs(watts)*0.03), report["steps"][-1]
        usable = [s for s in samples if s["relative_s"] >= 0]
        energies = {}
        for key, direction in (("import",1),("export",-1)):
            actual = usable[-1][key+"_wh"] - usable[0][key+"_wh"]
            integral = sum(max(0,direction*(a["power_w"]+b["power_w"])/2)*
                (b["time"]-a["time"])/3600 for a,b in zip(usable,usable[1:]))
            assert actual > 0 and abs(actual-integral) <= max(5,integral*0.10), (key,actual,integral)
            energies[key] = {"metered_wh":actual,"integrated_wh":integral}
        report["energy"] = energies
        report["client_meter"] = probe("meter")
        assert report["client_meter"]["meter_transaction_id"] == txid
        assert report["client_meter"]["meter_fresh"] is True
        assert report["client_meter"]["import_kwh"] is not None
        assert report["client_meter"]["export_kwh"] is not None
        report["stop_dispatch"] = probe("stop", transaction_id=txid)
        until(lambda: any(t["transactionId"] == txid and not t["isActive"] and t["endTime"]
                          for t in transactions()), "Closed CSMS transaction")
        until(lambda: (p:=reading()["power_w"]) is not None and abs(p) <= 1, "Measured zero after stop")
        report["closed_at"] = stamp()
        assert ui("/api/ev/unplug","POST").get("sent")
        until(lambda: reading()["state"] == "Unplugged", "Final unplugged state")
        report["clear_dispatch"] = probe("clear")
        report["samples"] = samples
        report["result"] = "passed"
    except Exception as error:
        report.update(result="failed", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        # No retries of uncertain payments/physical controls: these are synthetic
        # CI containers. EV unplug/stop and container termination bound this trial.
        try:
            ui("/api/ev/stop", "POST")
            ui("/api/ev/unplug", "POST")
        except Exception:
            pass
        try:
            docker("stop", "--time", "30", "lab-v2g")
        except Exception:
            pass
        text = json.dumps(report, indent=2)
        for secret in secret_values:
            text = text.replace(secret,"[redacted]")
        output.write_text(text)
        print(text)
