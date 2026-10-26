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


# Known runtime defects by setpoint: recorded and annotated, but they do not
# fail the trial. Strict: once such a step passes, the trial fails so its
# allowance is removed. Empty since everest_v2g_simulator 0.1.8, which honours
# 0 W setpoints (it used to hold the previous setpoint, +3 kW in every run).
KNOWN_DEFECT_SETPOINTS = {}


def evaluate_steps(targets, samples, step):
    """Return (steps, failures, known_defects) for each setpoint window."""
    steps, failures, known = [], [], []
    for i, watts in enumerate(targets):
        window = [s for s in samples if i*step+8 <= s["relative_s"] <= (i+1)*step-3]
        assert len(window) >= 8 and all(isinstance(s["power_w"],(int,float)) for s in window)
        mean = statistics.mean(s["power_w"] for s in window)
        passed = abs(mean-watts) <= max(50,abs(watts)*0.03)
        steps.append({"setpoint_w": watts, "mean_power_w": mean,
                      "samples": len(window), "passed": passed})
        if watts in KNOWN_DEFECT_SETPOINTS:
            if passed:
                failures.append(f"{watts} W step now passes; remove its known-defect allowance")
            else:
                known.append(f"{KNOWN_DEFECT_SETPOINTS[watts]}: mean {mean} W")
        elif not passed:
            failures.append(f"Power tracking failed at {watts} W: mean {mean} W")
    return steps, failures, known


def der_round_trip(request, until, commander):
    """OCPP 2.1 DER control through the gateway (source patch 0003) during the session."""
    auth = {"Authorization": "Bearer " + commander}
    query = "?identifier=" + STATION + "&tenantId=1"
    route = lambda name: "/ocpp/2.1/smartcharging/" + name + "DERControl" + query
    status, policy = request("/lab/control-policy", extra=auth)
    der = policy["der_commands"]
    assert status == 200 and der["enabled"] and der["station_id"] == STATION, policy
    # A control with a startTime: the station sends NotifyDERStartStop when it starts.
    start = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    control = {"isDefault": False, "controlId": "ha-ci-der-1", "controlType": "LimitMaxDischarge",
               "limitMaxDischarge": {"priority": 1, "pctMaxDischargePower": 50, "startTime": start,
                                     "duration": 600}}
    assert request(route("set"), body=control)[0] == 403, "Reader must not send DER controls"
    over = {**control, "limitMaxDischarge": {"priority": 1, "pctMaxDischargePower": 101}}
    assert request(route("set"), body=over, extra=auth)[0] == 400, "DER control outside lab bounds"
    status, sent = request(route("set"), body=control, extra=auth)
    assert status == 200 and sent.get("status") == "Accepted", sent
    def started():
        status, body = request("/lab/der-events", extra=auth)
        # Not swallowed by until(): a refused events read fails at once.
        assert status == 200 and isinstance(body.get("events"), list), body
        return next((e for e in body.get("events", []) if e["action"] == "NotifyDERStartStop"
                     and e["payload"].get("controlId") == "ha-ci-der-1" and e["payload"].get("started")), None)
    notified = until(started, "NotifyDERStartStop for the control", 30)
    request_id = secrets.randbelow(2**31)
    status, got = request(route("get"), body={"requestId": request_id, "controlType": "LimitMaxDischarge"},
                          extra=auth)
    assert status == 200 and got.get("status") == "Accepted", got
    reported = [x for r in got.get("reports", []) for x in (r.get("limitMaxDischarge") or [])]
    assert any(x.get("id") == "ha-ci-der-1" and x["limitMaxDischarge"]["pctMaxDischargePower"] == 50
               for x in reported), got
    clear = {"isDefault": False, "controlId": "ha-ci-der-1"}
    status, cleared = request(route("clear"), body=clear, extra=auth)
    assert status == 200 and cleared.get("status") == "Accepted", cleared
    status, again = request(route("clear"), body=clear, extra=auth)
    assert status == 200 and again.get("status") == "NotFound", again
    return {"set": sent, "notified": notified, "get": got, "clear": cleared, "clear_again": again}


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

    def ui(path="/api/status", method="GET", body=None):
        code = """import urllib.request,json,sys
x=json.load(sys.stdin)
data=None if x['body'] is None else json.dumps(x['body']).encode()
headers={'X-HA-EVerest':'1'}
if data is not None: headers['Content-Type']='application/json'
r=urllib.request.Request('http://127.0.0.1:8000'+x['path'],data=data,method=x['method'],headers=headers)
with urllib.request.urlopen(r,timeout=30 if x['method']=='POST' else 5) as response: print(response.read().decode())
"""
        p = subprocess.run(["docker", "exec", "-i", "lab-v2g", "python3", "-c", code],
            input=json.dumps({"path": path, "method": method, "body": body}), capture_output=True, text=True, timeout=40 if method=="POST" else 12)
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
                "state": session.get("state"),
                "limits": s.get("evse", {}).get("limits"),
                "ev_max_discharge_w": ((s.get("ev") or {}).get("iso20") or {}).get("max_discharge_w"),
                "composite_schedule": s.get("composite_schedule")}

    def stamp():
        return dt.datetime.now(dt.timezone.utc).isoformat()

    server_options.update(profile_simulator_enabled=True, profile_simulator_password=password,
                          command_control_enabled=True, command_token=commander,
                          price_commands_enabled=True, der_commands_enabled=True)
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
    p = temporary / "lab-v2g.json"
    p.write_text(json.dumps({"csms_url": "ws://lab-server:8081", "charge_point_id": STATION,
        "ocpp_version": "2.1", "max_power_kw": 11, "acknowledge_test_isolation": True,
        "csms_basic_auth_password": password, "ha_control": False, "ev_charging_needs": True}))
    p.chmod(0o600)
    names.append("lab-v2g")

    def station_up():
        # A new container, as an App update creates: no state from before.
        docker("create", "--name", "lab-v2g", "--network", "citrine-ci", "--cap-add", "NET_ADMIN",
               "--memory", "1536m", "citrine-v2g:test")
        docker("cp", str(p), "lab-v2g:/data/options.json")
        docker("start", "lab-v2g")
        until(lambda: any(s["ocppConnectionName"] == STATION and s["protocol"] == "ocpp2.1"
                          and s["isOnline"] for s in rows()), "Native 2.1 registration")
        until(lambda: ui()["app"].get("negotiated") == "ocpp2.1", "EVSE observed 2.1")
        until(lambda: reading()["state"] == "Unplugged", "Idle EVSE")
        # The boot-time discovery self-test owns the plugin lock. An idle
        # session does not mean that this independent readiness test finished.
        until(lambda: discovery_ready(ui("/api/diagnostics?brief=1")),
              "Boot-time discovery self-test", 60)

    def charging_needs(transaction_db_id):
        """ha-addons#106: EVerest sends NotifyEVChargingNeeds before TransactionEvent
        Started. CitrineOS answers NoChargingProfile (never Rejected, which would end
        the session) and links the stored needs to the transaction when it starts."""
        events = until(lambda: (e if (e := ui("/api/profiles").get("charging_needs"))
                                and all(x["status"] for x in e) else None),
                       "NotifyEVChargingNeeds answered", 30)
        replies = [e["status"] for e in events]
        assert replies and "Rejected" not in replies and set(replies) <= {"NoChargingProfile"}, events
        sent = events[0]["payload"]["chargingNeeds"]  # newest first
        assert sent["requestedEnergyTransfer"] == "DC_BPT" and sent.get("v2xChargingParameters"), sent
        stored = until(lambda: gql('query { ChargingNeeds(where:{transactionDatabaseId:{_eq:%d}}) '
            '{ requestedEnergyTransfer controlMode mobilityNeedsMode v2xChargingParameters } }'
            % transaction_db_id)["ChargingNeeds"] or None, "Charging needs linked to the transaction", 30)
        assert any(row["requestedEnergyTransfer"] == "DC_BPT" and row["controlMode"] == sent.get("controlMode")
                   and row["v2xChargingParameters"] == sent["v2xChargingParameters"] for row in stored), stored
        return {"station_events": events, "stored": stored}

    def needs_profile(txid):
        """The test profile: one discharge setpoint while the EV's needs go
        allow_discharge, charge_by (no discharge offered: 0 W), allow_discharge."""
        step, setpoint = 30, -5000
        start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=8)
        periods = [{"startPeriod": 0, "limit": 11000, "dischargeLimit": -11000,
                    "setpoint": setpoint, "operationMode": "CentralSetpoint"}]
        dispatch = probe("profile", transaction_id=txid, periods=periods, duration=3*step+20,
                         start_at=start.isoformat())
        until(lambda: (p if (p := ui("/api/profiles").get("latest_tx_profile")) and p["status"] == "Accepted"
                       and p["payload"]["chargingProfile"]["chargingSchedule"][0]["chargingSchedulePeriod"] == periods
                       else None), "Needs profile Accepted", 25)
        allow = {"mode": "allow_discharge", "target_soc": 80, "min_soc": 30}
        plan = [("allow_discharge", allow, setpoint),
                ("charge_by", {"mode": "charge_by", "target_soc": 80, "ready_by": int(time.time()) + 7200}, 0),
                ("allow_discharge", allow, setpoint)]
        samples, sent = [], []
        for i, (mode, needs, _) in enumerate(plan):
            while time.time() < start.timestamp() + i*step:
                time.sleep(0.5)
            reply = ui("/api/ev/needs", "POST", needs)
            sent.append({"at": stamp(), "needs": needs, "reply": reply})
            while time.time() < start.timestamp() + (i+1)*step:
                sample = reading(); sample["relative_s"] = sample["time"] - start.timestamp()
                samples.append(sample)
                time.sleep(1)
        steps, _, _ = evaluate_steps([w for _, _, w in plan], samples, step)
        for s, (mode, _, _) in zip(steps, plan):
            s["needs"] = mode
        return {"dispatch": dispatch, "needs_sent": sent, "steps": steps, "samples": samples}

    def active(txid):
        return any(t["transactionId"] == txid and t["isActive"] for t in transactions())

    txid = None
    try:
        station_up()
        # Stale transaction (the Green, 19 October 2026): a station recreated
        # mid-session no longer has its transaction, CitrineOS kept it active
        # and refused every later start. The gateway asks the station
        # (GetTransactionStatus); upstream closes what is not ongoing there.
        assert ui("/api/ev/plugin", "POST").get("sent")
        until(lambda: reading()["state"] in ("AuthRequired", "Preparing"), "Plugged readiness (stale case)")
        probe("start")
        stale = until(lambda: next((t["transactionId"] for t in transactions() if t["isActive"]), None),
                      "Stale case: CSMS active transaction")
        docker("rm", "-f", "lab-v2g")
        station_up()
        commander_auth = {"Authorization": "Bearer " + commander}
        status, policy = request("/lab/control-policy", extra=commander_auth)
        assert status == 200 and policy["transaction_reconcile"]["route"] == "/lab/reconcile-transactions", policy
        assert request("/lab/reconcile-transactions", body={})[0] == 403, "Reader must not reconcile"
        # The watcher may already be checking (station online); the route shares that check.
        status, reconciled = request("/lab/reconcile-transactions", body={}, extra=commander_auth)
        assert status == 200, reconciled
        until(lambda: not active(stale), "Stale transaction closed", 90)
        report["stale_transaction"] = {"transaction_id": stale, "reconcile": reconciled,
                                       "closed_at": stamp()}
        report["registered_at"] = stamp()
        assert ui("/api/ev/plugin", "POST").get("sent")
        until(lambda: reading()["state"] in ("AuthRequired", "Preparing"), "Plugged readiness")
        report["start_dispatch"] = probe("start")
        until(lambda: reading()["state"] == "Charging" and (reading()["power_w"] or 0) > 1000,
              "DC charging")
        tx = until(lambda: next((t for t in transactions() if t["isActive"]), None), "CSMS active transaction")
        txid = tx["transactionId"]; report["transaction_id"] = txid
        report["charging_observed_at"] = stamp()
        report["charging_needs"] = charging_needs(tx["id"])
        time.sleep(10)
        targets = [6000, -5000, 3000, 0]
        step = 30
        start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=8)
        periods = [{"startPeriod": i*step, "limit":11000, "dischargeLimit":-11000,
                    "setpoint": watts, "operationMode":"CentralSetpoint"} for i,watts in enumerate(targets)]
        # B: the same CentralSetpoint profile carries the Amber import forecast.
        report["profile_dispatch"] = probe("profile", transaction_id=txid, periods=periods,
            duration=180, start_at=start.isoformat(), priced=True)
        event = until(lambda: (p if (p:=ui("/api/profiles").get("latest_tx_profile"))
                              and p["status"] == "Accepted" else None), "EVSE profile Accepted", 25)
        assert event["payload"]["chargingProfile"]["transactionId"] == txid
        assert event["payload"]["chargingProfile"]["chargingSchedule"][0]["chargingSchedulePeriod"] == periods
        priced = event["payload"]["chargingProfile"]["chargingSchedule"][0].get("absolutePriceSchedule")
        assert priced and priced["currency"] == "AUD" and priced["priceRuleStacks"], event
        shown = ui("/api/profiles").get("price_schedules")
        assert shown, "Status page shows no price schedule"
        report["price_schedule_evidence"] = {"rule_stacks": len(priced["priceRuleStacks"]), "shown": shown}
        report["profile_evidence"] = event
        samples = []
        report["samples"] = samples
        while time.time() < start.timestamp() + step*len(targets):
            sample = reading(); sample["relative_s"] = sample["time"] - start.timestamp()
            samples.append(sample)
            time.sleep(1)
        steps, failures, known = evaluate_steps(targets, samples, step)
        report["steps"].extend(steps)
        report["acceptance_failures"] = failures
        report["known_defects"] = known
        for note in known:
            print(f"::warning title=Known V2G defect::{note}", flush=True)
        usable = [s for s in samples if s["relative_s"] >= 0]
        energies = {}
        for key, direction in (("import",1),("export",-1)):
            actual = usable[-1][key+"_wh"] - usable[0][key+"_wh"]
            integral = sum(max(0,direction*(a["power_w"]+b["power_w"])/2)*
                (b["time"]-a["time"])/3600 for a,b in zip(usable,usable[1:]))
            passed = actual > 0 and abs(actual-integral) <= max(5,integral*0.10)
            energies[key] = {"metered_wh":actual,"integrated_wh":integral,"passed":passed}
            if not passed:
                failures.append(f"{key} energy consistency failed")
        report["energy"] = energies
        # C: CostUpdated with California Pricing shows the price at the station.
        report["cost_dispatch"] = probe("cost", transaction_id=txid)
        sent = report["cost_dispatch"]["body"]["customData"]
        cost = until(lambda: (c if (c := (ui().get("session_cost") or {}).get("value")) and c.get("kwh_price") is not None
                              and abs(c["kwh_price"] - sent["chargingPrice"]["kWhPrice"]) < 1e-3 else None),
                     "Station shows the Amber price", 30)
        assert abs(cost["next_kwh_price"] - sent["nextPeriod"]["chargingPrice"]["kWhPrice"]) < 1e-3, cost
        assert cost["currency"] == "AUD", cost
        report["cost_evidence"] = cost
        # D: SetDefaultTariff. libocpp v0.30.3 answers NotImplemented; the reply is recorded.
        tariff = probe("tariff")
        report["tariff_evidence"] = tariff
        assert tariff["dispatch"]["station_status"] == "CALLERROR NotImplemented", tariff
        report["der"] = der_round_trip(request, until, commander)
        report["needs_profile"] = needs_profile(txid)
        failures.extend(f"EV needs {s['needs']}: mean {s['mean_power_w']} W, expected {s['setpoint_w']} W"
                        for s in report["needs_profile"]["steps"] if not s["passed"])
        report["client_meter"] = probe("meter")
        for key, expected in (("meter_transaction_id", txid), ("meter_fresh", True)):
            if report["client_meter"].get(key) != expected:
                failures.append(f"CSMS meter {key} mismatch")
        for key in ("import_kwh", "export_kwh"):
            if report["client_meter"].get(key) is None:
                failures.append(f"CSMS meter {key} unavailable")
        report["stop_dispatch"] = probe("stop", transaction_id=txid)
        until(lambda: any(t["transactionId"] == txid and not t["isActive"] and t["endTime"]
                          for t in transactions()), "Closed CSMS transaction")
        until(lambda: (p:=reading()["power_w"]) is not None and abs(p) <= 1, "Measured zero after stop")
        report["closed_at"] = stamp()
        report["final_meter"] = probe("meter")
        if (report["final_meter"].get("meter_transaction_id") != txid
                or report["final_meter"].get("transaction_closed") is not True):
            failures.append("Client did not observe exact transaction closure")
        assert ui("/api/ev/unplug","POST").get("sent")
        until(lambda: reading()["state"] == "Unplugged", "Final unplugged state")
        report["clear_dispatch"] = probe("clear")
        report["acceptance_failures"] = failures
        assert not failures, "; ".join(failures)
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
