"""The simulated EV's charging needs and battery (ISO 15118-20 Dynamic mode).

An ISO 15118-20 EV never chooses charge or discharge itself. It states its
needs and the charger, steered by the CSMS, sets power and direction:
DepartureTime, MinimumSOC and TargetSOC in ScheduleExchangeReq, and in each
DC_BPT CurrentDemandReq the energy requests (EVTargetEnergyRequest,
EVMaximumEnergyRequest, EVMinimumEnergyRequest), the discharge window
(EVMinimumV2XEnergyRequest, EVMaximumV2XEnergyRequest) and the discharge
limits. The operator picks one of two needs:

- charge_by: reach target_soc by ready_by. The minimum SoC is the target, so
  there is no discharge window and the EV offers 0 W discharge.
- allow_discharge: the EV may be discharged down to min_soc (it stops
  offering discharge at that floor) and wants target_soc by ready_by, or in
  24 hours if no time is set.

EVerest's car simulator counts DC power as charging in either direction, so
its SoC rises while the EV discharges. The App models the battery itself
from the charger's import and export meter, and the patched Josev
(patch_josev.py, patch_needs) reports this model's SoC and needs.
"""
import json
import time

NEEDS_FILE = "ev-needs.json"  # under /data: the operator's choice, kept across restarts
ISO20_FILE = "ev-iso20.json"  # under /run/ha-everest: what Josev sends, refreshed every second
CAPACITY_WH = 60000  # EvManager dc_energy_capacity (default)
DEFAULT_DEPARTURE_S = 86400  # EvManager departure_time (default)
MAX_READY_BY_S = 7 * 86400
MODES = ("charge_by", "allow_discharge")
DEFAULT_NEEDS = {"mode": "allow_discharge", "target_soc": 80, "min_soc": 30, "start_soc": 50,
                 "ready_by": None}
MIN_DISCHARGE_W = 300  # Josev's upstream EVMinimumDischargePower
NOT_PLUGGED = (None, "Unplugged", "Disabled")


def _soc(value, name, low=0):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= 100:
        raise ValueError(f"{name} must be a whole number from {low} to 100")
    return value


def validate_needs(body, now=None, check_time=True):
    """Operator input to stored needs. Raises ValueError with a readable message.
    check_time=False accepts a ready_by that has passed (stored needs)."""
    now = time.time() if now is None else now
    if not isinstance(body, dict):
        raise ValueError("needs must be a JSON object")
    unknown = set(body) - set(DEFAULT_NEEDS)
    if unknown:
        raise ValueError("unknown fields: " + ", ".join(sorted(unknown)))
    needs = dict(DEFAULT_NEEDS, **body)
    if needs["mode"] not in MODES:
        raise ValueError("mode must be charge_by or allow_discharge")
    target = _soc(needs["target_soc"], "target_soc", 1)
    start = _soc(needs["start_soc"], "start_soc")
    floor = _soc(needs["min_soc"], "min_soc")
    if needs["mode"] == "allow_discharge" and floor >= target:
        raise ValueError("min_soc must be below target_soc")
    ready_by = needs["ready_by"]
    if ready_by is not None:
        if isinstance(ready_by, bool) or not isinstance(ready_by, (int, float)):
            raise ValueError("ready_by must be a Unix time in seconds")
        if check_time and not now < ready_by <= now + MAX_READY_BY_S:
            raise ValueError("ready_by must be in the next 7 days")
        ready_by = int(ready_by)
    elif needs["mode"] == "charge_by":
        raise ValueError("charge_by needs a ready_by time")
    return {"mode": needs["mode"], "target_soc": target, "min_soc": floor, "start_soc": start,
            "ready_by": ready_by}


def load_needs(path):
    try:
        return validate_needs(json.loads(path.read_text()), check_time=False)
    except (OSError, ValueError):
        return dict(DEFAULT_NEEDS)


def iso20_needs(needs, soc, rated_w, now, capacity_wh=CAPACITY_WH):
    """What the EV sends in ISO 15118-20 (Dynamic control mode, DC_BPT) for
    these needs at this SoC. Energies in Wh, positive to charge."""
    def energy(to_soc):
        return round((to_soc - soc) / 100 * capacity_wh)

    allow = needs["mode"] == "allow_discharge"
    floor = needs["min_soc"] if allow else needs["target_soc"]
    ready_by = needs.get("ready_by")
    departure = max(0, int(ready_by - now)) if ready_by else DEFAULT_DEPARTURE_S
    discharge_w = int(rated_w) if allow and soc > floor else 0
    target_wh = energy(needs["target_soc"])
    result = {
        "mode": needs["mode"],
        "departure_time": departure,  # DepartureTime, s from now
        "present_soc": int(round(soc)),  # DisplayParameters PresentSOC
        "min_soc": floor,  # MinimumSOC
        "target_soc": needs["target_soc"],  # TargetSOC
        "max_soc": 100,  # MaximumSOC
        "target_wh": target_wh,  # EVTargetEnergyRequest
        "max_wh": energy(100),  # EVMaximumEnergyRequest
        "min_wh": energy(floor),  # EVMinimumEnergyRequest
        "v2x_min_wh": energy(floor) if allow else None,  # EVMinimumV2XEnergyRequest
        "v2x_max_wh": energy(100) if allow else None,  # EVMaximumV2XEnergyRequest
        "max_discharge_w": discharge_w,  # EVMaximumDischargePower
        "min_discharge_w": MIN_DISCHARGE_W if discharge_w else 0,  # EVMinimumDischargePower
        "max_discharge_a": round(discharge_w / 380) if discharge_w else 0,  # EVMaximumDischargeCurrent
        "remaining_time_to_target_soc": (int(target_wh / rated_w * 3600) if target_wh > 0 and rated_w
                                         else 0),  # RemainingTimeToTargetSOC
        "battery_capacity_wh": capacity_wh,  # BatteryEnergyCapacity
        "at": now,
    }
    return result


class Battery:
    """SoC from the charger's meter: start_soc at plug-in plus net energy."""

    def __init__(self, capacity_wh=CAPACITY_WH):
        self.capacity_wh = capacity_wh
        self.base = None  # (import Wh, export Wh, start SoC) at plug-in

    def update(self, state, import_wh, export_wh, start_soc):
        plugged = state not in NOT_PLUGGED
        if not plugged or not isinstance(import_wh, (int, float)):
            self.base = None
            return float(start_soc), False
        export_wh = export_wh if isinstance(export_wh, (int, float)) else 0.0
        if self.base is None:
            self.base = (import_wh, export_wh, float(start_soc))
        net = (import_wh - self.base[0]) - (export_wh - self.base[1])
        return max(0.0, min(100.0, self.base[2] + net / self.capacity_wh * 100)), True
