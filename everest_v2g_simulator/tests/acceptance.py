"""End-to-end acceptance of the packaged V2G App against a local mock CSMS.

Runs the real entrypoint (firewall, private veth link, test PKI, mosquitto,
EVerest manager, UI service, nginx) in a container with NET_ADMIN. Scenarios:

  v2g21      CSMS prefers 2.1 -> ocpp2.1; OCPP 2.1 DER control after boot
             (DCDERCtrlr in the device model; SetDERControl accepted with
             NotifyDERStartStop, a mismatched control rejected,
             GetDERControl answered with ReportDERControl, ClearDERControl;
             the active set on the Status page); ISO 15118-20 DC_BPT
             session; a CentralSetpoint TxProfile charges then discharges
             (V2G export) at 380 V, including direct reversals between
             charge and discharge; after stop and unplug a fresh session,
             started 40 s after plug-in, charges again; dynamic pricing
             (CostUpdated with California Pricing on the Status page, a
             price schedule shown, SetDefaultTariff answered NotImplemented)
  fallback   CSMS supports only 2.0.1 -> ocpp2.0.1; charging-only W limit;
             CostUpdated with California Pricing on the Status page
  pinned201  App option ocpp_version 2.0.1; CSMS prefers 2.1 -> ocpp2.0.1
  offline    Empty csms_url: no connection attempt leaves the host; the
             discovery self-test passes at start
  recovery   Discovery blocked on the private link: the EV's SDP requests
             fail and upstream Josev idles; after unblocking, unplug and
             plug-in, the patched module replaces that stack and a fresh
             EV stack completes discovery; unplugging before authorisation
             leaves the charger ignoring discovery, which the App reports
  watchdog   No authorisation: after the charger's limit (55 s from EVerest
             2026.10) the EV gives up its session; the App re-plugs it, and
             a later start still charges
  tls        wss:// (Security Profile 2, Basic Auth) to a TLS mock CSMS:
             connects with csms_ca_certificate and with the CA in the
             system store; refuses a hostname mismatch, and a server whose
             CA is in the system store but is not the configured one

Each charging step compares mean measured DC power with the setpoint, and
mean DC voltage with the simulated battery voltage, and metered import and
export energy with the integral of measured power.
"""
import asyncio
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import ssl
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
# Charge, stop, discharge (V2G export), stop, charge, then direct reversals
# to discharge and back. Signed W: negative is discharge. The 0 W steps failed
# before 0.1.8: the EV stayed at 6,000 W, and after a discharge the previous
# magnitude reappeared as charging (VALIDATION.md). The 20 kW steps exceed
# the limits before 0.1.9: 5 kW discharge (EV 25 A at 200 V) and 11.04 /
# 22.08 kW from the simulated board. The direct reversals (-5000, +3000)
# guard against EvseManager's stale-target race (UPSTREAM.md, issue #70).
SETPOINTS_W = [6000, 0, -20000, 0, 20000, -5000, 3000]
RATING_KW = 25
# 2.0.1 has no setpoints: one plain import limit below the rating.
FALLBACK_LIMIT_W = 4000
POWER_TOLERANCE = 0.03
# Discharge voltage: the DC supply minimum (configure.DC_VOLTAGE). Charging
# runs at the EV's 900 V maximum (issue #70, UPSTREAM.md).
DC_VOLTAGE = 380
VOLTAGE_TOLERANCE = 0.05
# Issue #33: before 0.1.10 the EV gave up about 60 s after plug-in, and the
# charger (libiso15118 v0.9.0) waited 3 minutes, so 0.1.10 to 0.1.13 started
# 75 s after plug-in. From EVerest 2026.10 the charger itself stops an
# ISO 15118-20 EIM wait after 55 s ([V2G20-2102]), so a start must come
# sooner; a later one is the watchdog scenario's case.
LATE_START_S = 40
# OCPP 2.1 DER control: the App declares all 22 DERControlEnum types.
DER_TYPES = 22


def setpoint_period(offset, watts):
    # Every period carries a setpoint: EVerest 2025.10.0 applies the nearest
    # setpoint to periods without one (VALIDATION.md).
    return {"startPeriod": offset, "limit": RATING_KW * 1000.0, "dischargeLimit": -RATING_KW * 1000.0,
            "setpoint": float(watts), "operationMode": "CentralSetpoint"}


def http(path, method="GET", timeout=30):
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


# Dynamic pricing: CostUpdated with California Pricing customData reaches the
# Status page; on OCPP 2.1 a profile's absolutePriceSchedule is shown
# (information only) and SetDefaultTariff is answered NotImplemented
# (libocpp v0.30.3). Prices are exact at NumberOfDecimalsForCostValues 4.
PRICE_TEXT = "0.2512 AUD/kWh now, 0.31 AUD/kWh from the next half hour"


def utc_text(when):
    return when.isoformat(timespec="seconds").replace("+00:00", "Z")


async def pricing_checks(csms, txid, ocpp21, unit, limit, profile_id):
    report = {}
    later = dt.datetime.now(dt.timezone.utc).replace(microsecond=0) + dt.timedelta(minutes=30)
    reply = await csms.call("CostUpdated", {"totalCost": 1.23, "transactionId": txid, "customData": {
        "vendorId": "org.openchargealliance.costmsg", "state": "Charging",
        "chargingPrice": {"kWhPrice": 0.2512},
        "nextPeriod": {"atTime": utc_text(later), "chargingPrice": {"kWhPrice": 0.31}},
        "priceText": PRICE_TEXT}})
    assert reply[0] == 3, reply
    price = await wait_for(lambda: (http("/api/status").get("session_cost") or {}).get("value"), 20,
                           what="session cost on the Status page")
    expected = {"currency": "AUD", "total_cost": 1.23, "kwh_price": 0.2512, "next_kwh_price": 0.31,
                "text": PRICE_TEXT, "session_id": txid}
    assert {k: price.get(k) for k in expected} == expected, price
    assert price["next_at"] and price["next_at"].startswith(utc_text(later)[:16]), price
    report["session_cost"] = price
    expect_pricing = 1
    if ocpp21:
        stacks = [{"duration": 1800, "priceRule": [{"energyFee": {"value": 2512, "exponent": -4},
                                                    "powerRangeStart": {"value": 0, "exponent": 0}}]},
                  {"duration": 1800, "priceRule": [{"energyFee": {"value": 31, "exponent": -2},
                                                    "powerRangeStart": {"value": 0, "exponent": 0}}]}]
        profile = {"evseId": 1, "chargingProfile": {
            "id": profile_id, "stackLevel": 0, "chargingProfilePurpose": "TxDefaultProfile",
            "chargingProfileKind": "Relative",
            "chargingSchedule": [{"id": 2, "chargingRateUnit": unit,
                                  "chargingSchedulePeriod": [{"startPeriod": 0, "limit": limit}],
                                  "absolutePriceSchedule": {
                                      "timeAnchor": utc_text(later - dt.timedelta(minutes=30)),
                                      "priceScheduleID": 1, "currency": "AUD", "language": "en",
                                      "priceAlgorithm": "org.openchargealliance.costcalc",
                                      "priceRuleStacks": stacks}}]}}
        reply = await csms.call("SetChargingProfile", profile)
        assert reply[2]["status"] == "Accepted", reply
        shown = await wait_for(lambda: http("/api/profiles")["price_schedules"], 20,
                               what="price schedule on the Status page")
        assert shown[0]["kind"] == "absolutePriceSchedule" and shown[0]["count"] == 2, shown
        assert [i["energy_fee"] for i in shown[0]["intervals"]] == [0.2512, 0.31], shown
        report["price_schedule"] = shown[0]
        reply = await csms.call("ClearChargingProfile", {"chargingProfileId": profile_id})
        assert reply[2]["status"] == "Accepted", reply
        reply = await csms.call("SetDefaultTariff", {"evseId": 0, "tariff": {
            "tariffId": "AMBER-TEST", "currency": "AUD",
            "energy": {"prices": [{"priceKwh": 0.2512}]}}})
        assert reply[0] == 4 and reply[2] == "NotImplemented", reply
        expect_pricing = 2
    events = await wait_for(lambda: [e for e in http("/api/profiles")["pricing"] if e["status"]]
                            if len([e for e in http("/api/profiles")["pricing"] if e["status"]]) >= expect_pricing
                            else None, 20, what="pricing messages in the OCPP log view")
    assert events[-1]["action"] == "CostUpdated" and events[-1]["status"] == "Replied", events
    if ocpp21:
        assert events[0]["action"] == "SetDefaultTariff", events
        assert events[0]["status"] == "CallError", events
        assert events[0]["status_info"]["reasonCode"] == "NotImplemented", events
    report["pricing_log"] = [(e["action"], e["status"]) for e in events]
    return report


def station_calls(csms, action, after=0.0):
    """Payloads of station-initiated calls of `action` received after `after`."""
    return [f[1][3] for f in csms.frames
            if f[0] == "in" and f[1][0] == 2 and f[1][2] == action and f[2] > after]


async def der_checks(csms):
    """OCPP 2.1 DER control against the App's declared DC capability.

    The App's HaGridSupport module declares the DC capability, so OCPPmulti
    enables DCDERCtrlr on EVSE 1 and libocpp accepts every declared type. The
    active set reaches the module (Status page); nothing changes power."""
    report = {}
    der = await wait_for(lambda: (http("/api/status").get("der") or {}).get("control_types"), 60,
                         what="DER capability on the Status page")
    assert len(der) == DER_TYPES and "LimitMaxDischarge" in der, der
    reply = await csms.call("GetVariables", {"getVariableData": [
        {"component": {"name": "DCDERCtrlr", "evse": {"id": 1}}, "variable": {"name": name}}
        for name in ("Available", "Enabled", "ModesSupported")]})
    results = {r["variable"]["name"]: (r["attributeStatus"], r.get("attributeValue"))
               for r in reply[2]["getVariableResult"]}
    assert results["Available"] == ("Accepted", "true"), results
    assert results["Enabled"] == ("Accepted", "true"), results
    assert results["ModesSupported"][0] == "Accepted", results
    assert set(results["ModesSupported"][1].split(",")) == set(der), results
    report["device_model"] = {k: v[1] if k != "ModesSupported" else f"{len(v[1].split(','))} types"
                              for k, v in results.items()}

    t0 = asyncio.get_running_loop().time()
    start = utc_text(dt.datetime.now(dt.timezone.utc).replace(microsecond=0) - dt.timedelta(seconds=2))
    reply = await csms.call("SetDERControl", {
        "isDefault": False, "controlId": "ha-der-1", "controlType": "LimitMaxDischarge",
        "limitMaxDischarge": {"priority": 1, "pctMaxDischargePower": 50.0, "startTime": start, "duration": 600.0}})
    assert reply[0] == 3 and reply[2]["status"] == "Accepted", reply
    started = await wait_for(lambda: [n for n in station_calls(csms, "NotifyDERStartStop", t0)
                                      if n.get("controlId") == "ha-der-1"], 20, what="NotifyDERStartStop")
    assert started[0]["started"] is True, started
    reply = await csms.call("SetDERControl", {
        "isDefault": True, "controlId": "ha-der-default", "controlType": "FixedPFInject",
        "fixedPFInject": {"priority": 2, "displacement": 0.95, "excitation": False}})
    assert reply[2]["status"] == "Accepted", reply
    # The control field must match controlType (R04.FR.16): Rejected.
    reply = await csms.call("SetDERControl", {
        "isDefault": False, "controlId": "ha-der-bad", "controlType": "LimitMaxDischarge",
        "fixedVar": {"priority": 1, "setpoint": 10.0, "unit": "PctMaxVar"}})
    assert reply[2]["status"] == "Rejected", reply
    active = await wait_for(
        lambda: [d for d in (http("/api/status").get("der") or {}).get("active") or []
                 if d["id"] in ("ha-der-1", "ha-der-default")], 30, what="active DER set on the Status page")
    shown = {d["id"]: d for d in active}
    assert len(shown) == 2, active
    assert shown["ha-der-1"]["type"] == "LimitMaxDischarge", shown
    assert shown["ha-der-1"]["detail"] == "50 % of rated discharge power", shown
    assert shown["ha-der-default"]["type"] == "FixedPFInject" and shown["ha-der-default"]["is_default"], shown
    report["active"] = sorted(shown)

    t0 = asyncio.get_running_loop().time()
    reply = await csms.call("GetDERControl", {"requestId": 42})
    assert reply[2]["status"] == "Accepted", reply
    reports = await wait_for(lambda: [r for r in station_calls(csms, "ReportDERControl", t0)
                                      if r.get("requestId") == 42], 20, what="ReportDERControl")
    text = json.dumps(reports)
    assert "ha-der-1" in text and "ha-der-default" in text and "ha-der-bad" not in text, reports
    report["reported"] = [k for k in reports[0] if isinstance(reports[0][k], list)]

    reply = await csms.call("ClearDERControl", {"isDefault": False, "controlId": "ha-der-1"})
    assert reply[2]["status"] == "Accepted", reply
    reply = await csms.call("ClearDERControl", {"isDefault": False, "controlId": "ha-der-1"})
    assert reply[2]["status"] == "NotFound", reply
    reply = await csms.call("ClearDERControl", {"isDefault": True})
    assert reply[2]["status"] == "Accepted", reply
    await wait_for(lambda: not (http("/api/status").get("der") or {}).get("active"), 30,
                   what="empty active DER set after ClearDERControl")
    reply = await csms.call("GetDERControl", {"requestId": 43})
    assert reply[2]["status"] == "NotFound", reply
    events = http("/api/profiles")["der"]
    assert [(e["action"], e["status"]) for e in events][:2] == [("GetDERControl", "NotFound"),
                                                                ("ClearDERControl", "Accepted")], events
    report["messages"] = [(e["action"], e["status"]) for e in events][::-1]
    return report


async def operation_mode_checks(csms):
    """libocpp (2026.10) accepts a 2.1 profile period only for an
    operationMode in the EVSE's V2XChargingCtrlr SupportedOperationModes;
    EVerest builds it as ChargingOnly,Idle and the App adds CentralSetpoint."""
    written = await wait_for(
        lambda: ((http("/api/status").get("der") or {}).get("v2x_operation_modes") or {}).get("status"), 60,
        what="V2X operation modes written")
    assert written == "Accepted", written
    reply = await csms.call("GetVariables", {"getVariableData": [
        {"component": {"name": "V2XChargingCtrlr", "evse": {"id": 1}},
         "variable": {"name": "SupportedOperationModes"}}]})
    result = reply[2]["getVariableResult"][0]
    assert result["attributeStatus"] == "Accepted", result
    modes = set(result["attributeValue"].split(","))
    assert {"ChargingOnly", "CentralSetpoint"} <= modes, result
    return sorted(modes)


def reading():
    status = http("/api/status")
    pm = (status["evse"].get("powermeter") or {}).get("value") or {}
    si = (status["evse"].get("session_info") or {}).get("value") or {}
    return {
        "power": (pm.get("power_W") or {}).get("total"),
        "voltage": (pm.get("voltage_V") or {}).get("DC"),
        "current": (pm.get("current_A") or {}).get("DC"),
        "imported": (pm.get("energy_Wh_import") or {}).get("total"),
        "exported": (pm.get("energy_Wh_export") or {}).get("total"),
        "state": si.get("state"),
        "status": status,
    }


def iso_start(seconds=3):
    start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)
    return start, start.isoformat(timespec="seconds").replace("+00:00", "Z")


def check_meter(r):
    """DC current times voltage gives the metered power."""
    assert abs(r["current"] * r["voltage"] - r["power"]) <= max(100, 0.05 * abs(r["power"])), r
    return {"W": round(r["power"]), "V": round(r["voltage"], 1), "A": round(r["current"], 2)}


async def start_session(csms, first=True, start_delay_s=0):
    await wait_for(lambda: reading()["state"] == "Unplugged", 60, what="idle EVSE")
    assert http("/api/ev/plugin", "POST")["sent"]
    await wait_for(lambda: reading()["state"] in ("AuthRequired", "Preparing"), 30,
                   what="plugged state")
    # The EV waits for authorisation as long as the charger (3 minutes).
    await asyncio.sleep(start_delay_s)
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
        samples.append((time.time() - t0, r["power"], r["imported"], r["exported"], r["state"],
                        r["voltage"]))
        await asyncio.sleep(1)
    return samples


def check_steps(samples, targets):
    steps = []
    for i, target in enumerate(targets):
        window = [s for s in samples if i * STEP + 6 <= s[0] <= (i + 1) * STEP - 2 and s[1] is not None]
        assert window, f"no samples for step {i}"
        mean_w = sum(s[1] for s in window) / len(window)
        ok = abs(mean_w - target) <= max(50, POWER_TOLERANCE * abs(target))
        step = {"target_W": target, "mean_W": round(mean_w)}
        volts = [s[5] for s in window if s[5] is not None]
        if target < 0:
            # Discharge runs at the supply minimum, not its 200 V default.
            mean_v = sum(volts) / len(volts) if volts else None
            step["mean_V"] = round(mean_v, 1) if volts else None
            ok = ok and volts and abs(mean_v - DC_VOLTAGE) <= VOLTAGE_TOLERANCE * DC_VOLTAGE
        step["pass"] = bool(ok)
        steps.append(step)
    trace = [(round(s[0]), s[1]) for s in samples]
    assert all(s["pass"] for s in steps), {"steps": steps, "trace": trace}
    return steps


def check_energy(samples):
    """Metered import/export vs. integral of positive/negative measured power."""
    rows = [s for s in samples if None not in s[1:4]]
    pos = neg = 0.0
    for a, b in zip(rows, rows[1:]):
        dt = b[0] - a[0]
        if a[1] >= 0 and b[1] >= 0:
            pos += dt * (a[1] + b[1]) / 2 / 3600
        elif a[1] <= 0 and b[1] <= 0:
            neg -= dt * (a[1] + b[1]) / 2 / 3600
        else:
            # A direct reversal: split the trapezoid at the linear zero crossing,
            # so neither direction loses the energy of the crossing interval.
            f = a[1] / (a[1] - b[1])
            first, second = f * dt * a[1] / 2 / 3600, (1 - f) * dt * b[1] / 2 / 3600
            pos += max(first, second)
            neg -= min(first, second)
    imported = rows[-1][2] - rows[0][2]
    exported = rows[-1][3] - rows[0][3]
    result = {"import_metered": round(imported, 1), "import_integrated": round(pos, 1),
              "export_metered": round(exported, 1), "export_integrated": round(neg, 1)}
    # 1 s polling under-samples ramps, hence the margin.
    trace = [(round(s[0], 1), s[1], s[2], s[3]) for s in rows]
    assert abs(imported - pos) <= max(5.0, 0.1 * pos), {**result, "trace": trace}
    assert abs(exported - neg) <= max(5.0, 0.1 * neg), {**result, "trace": trace}
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


def charging_needs_checks(csms):
    """NotifyEVChargingNeeds (ev_charging_needs) carries the needs the
    patched Josev sends over ISO 15118-20 (ev_model.py defaults: plug in at
    50 %, allow discharge down to 30 %, target 80 %, 60 kWh). EVerest
    2026.10 maps the energy requests and the V2X window, not DepartureTime
    or TargetSOC."""
    needs = csms.calls("NotifyEVChargingNeeds")
    assert needs, "no NotifyEVChargingNeeds"
    charging = needs[-1]["chargingNeeds"]
    assert charging.get("v2xChargingParameters"), charging  # ISO 15118-20 needs (libocpp's test)
    v2x = charging["v2xChargingParameters"]
    # Schedule exchange comes before any energy flows, so the SoC is still 50 %.
    expected = {"evTargetEnergyRequest": 18000, "evMaxEnergyRequest": 30000, "evMinEnergyRequest": -12000,
                "evMinV2XEnergyRequest": -12000, "evMaxV2XEnergyRequest": 30000}
    assert {k: v2x.get(k) for k in expected} == expected, charging
    ui = http("/api/status")["ev"]
    assert ui["needs"]["mode"] == "allow_discharge" and ui["iso20"]["min_soc"] == 30, ui
    return {"count": len(needs), "requestedEnergyTransfer": charging.get("requestedEnergyTransfer"),
            "controlMode": charging.get("controlMode"), "chargingNeeds": charging}


async def v2g_scenario():
    csms = await MockCsms(accept=("ocpp2.1", "ocpp2.0.1"), port=9220).start()
    app = App({"csms_url": "ws://127.0.0.1:9220", "charge_point_id": CPID, "ocpp_version": "2.1",
               "max_power_kw": RATING_KW, "acknowledge_test_isolation": True,
               "ev_charging_needs": True})
    app.start()
    report = {"scenario": "v2g21"}
    try:
        await asyncio.wait_for(csms.boot.wait(), 120)
        assert csms.subprotocol == "ocpp2.1", csms.subprotocol
        assert csms.path == "/" + CPID and csms.authorization == CPID
        await wait_for(lambda: http("/api/status")["app"].get("negotiated") == "ocpp2.1", 20,
                       what="UI negotiated version")
        report["der"] = await der_checks(csms)
        report["v2x_operation_modes"] = await operation_mode_checks(csms)
        txid = await start_session(csms)
        await wait_for(lambda: csms.calls("NotifyEVChargingNeeds"), 30, what="NotifyEVChargingNeeds")
        report["charging_needs"] = charging_needs_checks(csms)
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
        report["pricing"] = await pricing_checks(csms, txid, True, "W", RATING_KW * 1000.0, 210102)
        await finish(csms, txid)
        # A new session after unplug charges normally (default limit), also
        # when the start comes more than 60 s after plug-in (issue #33).
        txid = await start_session(csms, first=False, start_delay_s=LATE_START_S)
        report["second_session"] = check_meter(reading())
        assert "maximum number of SDP retry cycles" not in log_text(app), "EV gave up waiting"
        assert http("/api/status")["ev_watchdog"]["recoveries"] == 0
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
    # Issue #28: the EVSE 0 warning is dropped; EVSE 1 has its sink.
    assert "Can not apply external limits" not in log, "external limits warning in the App log"
    return report


async def fallback_scenario():
    csms = await MockCsms(accept=("ocpp2.0.1",), port=9220).start()
    app = App({"csms_url": "ws://127.0.0.1:9220", "charge_point_id": CPID, "ocpp_version": "2.1",
               "max_power_kw": RATING_KW, "acknowledge_test_isolation": True})
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
        report["pricing"] = await pricing_checks(csms, txid, False, "W", RATING_KW * 1000.0, 201102)
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
        # Unplugged while waiting for authorisation: upstream libiso15118
        # never ends that charger session, so it ignores discovery from now
        # on. The App must say so, and the self-test must show it.
        http("/api/ev/unplug", "POST")
        await wait_for(lambda: reading()["state"] == "Unplugged", 60, what="unplugged again")
        await asyncio.sleep(10)
        snapshot = http("/api/diagnostics")["snapshot"]
        rules = {r["rule"]: r["packets"] for r in snapshot["firewall"]["rules"]}
        assert rules["SDP kept on the private link"] == 0, rules  # the patched EV used v2g1
        print("unscoped multicast via", snapshot["unscoped_multicast_interface"], flush=True)
        selftest = http("/api/diag/selftest", "POST", timeout=20)
        assert not selftest["pass"] and selftest["charger_sdp_blocked"], selftest
        assert selftest["capture"]["v2g0"]["count"] >= 2, selftest  # requests arrived; no reply
        assert "Restart the App to clear it" in log_text(app)
        assert "charger=ignoring-discovery" in selftest["summary"], selftest
    finally:
        code = app.stop()
    assert code == 0
    return {"scenario": "recovery", "result": "pass"}


async def watchdog_scenario():
    csms = await MockCsms(accept=("ocpp2.1", "ocpp2.0.1"), port=9220).start()
    app = App({"csms_url": "ws://127.0.0.1:9220", "charge_point_id": CPID, "ocpp_version": "2.1",
               "max_power_kw": RATING_KW, "acknowledge_test_isolation": True})
    app.start()
    report = {"scenario": "watchdog"}
    try:
        await asyncio.wait_for(csms.boot.wait(), 120)
        await wait_for(lambda: reading()["state"] == "Unplugged", 60, what="idle EVSE")
        assert http("/api/ev/plugin", "POST")["sent"]
        await wait_for(lambda: reading()["state"] in ("AuthRequired", "Preparing"), 30,
                       what="plugged state")
        # No authorisation: the charger fails the session after 3 minutes
        # (libiso15118 EIM limit), and the EV starts no new one.
        await wait_for(lambda: "maximum number of SDP retry cycles" in log_text(app), 240,
                       interval=2, what="EV giving up")
        await wait_for(lambda: http("/api/status")["ev_watchdog"]["recoveries"] == 1, 120,
                       what="automatic re-plug")
        report["watchdog"] = http("/api/status")["ev_watchdog"]
        assert report["watchdog"]["last_recovery"]["result"] == "re-plugged", report
        await wait_for(lambda: log_text(app).count("Received session setup with evccid") >= 2, 60,
                       what="session setup by the re-plugged EV")
        reply = await csms.call("RequestStartTransaction", {
            "idToken": {"idToken": "SIM-TEST", "type": "Central"}, "evseId": 1, "remoteStartId": 8})
        assert reply[2]["status"] == "Accepted", reply
        await wait_for(lambda: reading()["state"] == "Charging" and (reading()["power"] or 0) > 1000,
                       90, what="DC charging after the re-plug")
        await asyncio.sleep(10)
        report["charging"] = check_meter(reading())
        started = [e for e in csms.calls("TransactionEvent") if e["eventType"] == "Started"]
        await finish(csms, started[-1]["transactionInfo"]["transactionId"])
        report["result"] = "pass"
    finally:
        report["app_exit"] = app.stop()
        csms.server.close()
    assert report["app_exit"] == 0, report
    return report


TLS_PORT = 9221
TLS_PKI = Path("/tmp/tls-pki")       # keys stay here, never under /ssl
SSL_CAS = Path("/ssl/test-csms")     # CA certificates only, as an operator would
SYSTEM_CA = Path("/usr/local/share/ca-certificates/ha-everest-acceptance.crt")


def tls_pki():
    """Test-only CSMS CA with a localhost server certificate, and an unrelated CA."""
    shutil.rmtree(TLS_PKI, ignore_errors=True)
    TLS_PKI.mkdir(mode=0o700)
    SSL_CAS.mkdir(parents=True, exist_ok=True)

    def run(*args):
        subprocess.run(["openssl", *map(str, args)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ec = ("-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes")
    for name in ("ca", "other-ca"):
        run("req", "-x509", *ec, "-subj", f"/CN=Acceptance {name}", "-days", "2",
            "-keyout", TLS_PKI / f"{name}.key", "-out", SSL_CAS / f"{name}.pem")
    run("req", "-new", *ec, "-subj", "/CN=localhost", "-keyout", TLS_PKI / "server.key",
        "-out", TLS_PKI / "server.csr")
    (TLS_PKI / "server.ext").write_text("subjectAltName=DNS:localhost\nbasicConstraints=CA:FALSE\n"
                                        "extendedKeyUsage=serverAuth\n")
    run("x509", "-req", "-in", TLS_PKI / "server.csr", "-CA", SSL_CAS / "ca.pem",
        "-CAkey", TLS_PKI / "ca.key", "-set_serial", "2", "-days", "2",
        "-extfile", TLS_PKI / "server.ext", "-out", TLS_PKI / "server.pem")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(TLS_PKI / "server.pem", TLS_PKI / "server.key")
    return context


async def tls_mock(context):
    csms = MockCsms(accept=("ocpp2.1", "ocpp2.0.1"), host=["127.0.0.1", "::1"], port=TLS_PORT,
                    ssl=context)
    try:
        return await csms.start()
    except OSError:  # no IPv6 loopback
        csms.host = "127.0.0.1"
        return await csms.start()


def tls_options(url, ca=""):
    return {"csms_url": url, "charge_point_id": CPID, "ocpp_version": "2.1",
            "acknowledge_test_isolation": True, "csms_ca_certificate": ca}


async def tls_connects(context, options, trust):
    csms = await tls_mock(context)
    app = App(options)
    app.start()
    try:
        await asyncio.wait_for(csms.boot.wait(), 120)
        assert csms.subprotocol == "ocpp2.1", csms.subprotocol
        assert csms.authorization == CPID, csms.authorization  # Basic Auth over TLS
        assert "localhost" in csms.client_hellos, csms.client_hellos  # SNI, as Cloudflare needs
        status = await wait_for(lambda: http("/api/status")["app"], 30, what="UI")
        shown = (status["csms_scheme"], status["security_profile"], status["csms_trust"])
        assert shown == ("wss", 2, trust), status
        log = log_text(app)
        assert f"connection enabled (wss://, Security Profile 2, CSMS trust: {trust})" in log
        password = (DATA / "basic-auth-password").read_text().strip()
        assert password and password not in log, "Basic Auth password in the App log"
    finally:
        code = app.stop()
        csms.server.close()
        await csms.server.wait_closed()
    assert code == 0


async def tls_refused(context, options, what):
    csms = await tls_mock(context)
    app = App(options)
    app.start()
    try:
        await wait_for(lambda: csms.client_hellos, 120, what=f"TLS attempt ({what})")
        await asyncio.sleep(15)
        assert not csms.connected.is_set() and not csms.boot.is_set(), f"connected despite {what}"
        assert app.proc.poll() is None, "App stopped"
    finally:
        code = app.stop()
        csms.server.close()
        await csms.server.wait_closed()
    assert code == 0


async def tls_scenario():
    url = f"wss://localhost:{TLS_PORT}/ocpp"
    ca = str(SSL_CAS / "ca.pem")
    context = tls_pki()
    await tls_connects(context, tls_options(url, ca), ca)
    # Right CA, wrong name: the certificate is for localhost only.
    await tls_refused(context, tls_options(f"wss://127.0.0.1:{TLS_PORT}/ocpp", ca), "a hostname mismatch")
    # Default trust: OpenSSL's default paths (Debian ca-certificates).
    shutil.copy(SSL_CAS / "ca.pem", SYSTEM_CA)
    subprocess.run(["update-ca-certificates"], check=True, stdout=subprocess.DEVNULL, cwd="/")
    try:
        await tls_connects(context, tls_options(url), "system CA store")
        # csms_ca_certificate is the only trust anchor: the system store
        # (which now trusts this server) is not used.
        await tls_refused(context, tls_options(url, str(SSL_CAS / "other-ca.pem")),
                          "an unrelated configured CA")
    finally:
        SYSTEM_CA.unlink()
        subprocess.run(["update-ca-certificates", "--fresh"], check=True, stdout=subprocess.DEVNULL, cwd="/")
    return {"scenario": "tls", "result": "pass"}


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
    if "watchdog" in selected:
        results.append(await watchdog_scenario())
    if "tls" in selected:
        results.append(await tls_scenario())
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["offline", "recovery", "v2g21", "fallback", "pinned201", "watchdog", "tls"]))
