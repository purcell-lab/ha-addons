"""Read-only parser for libocpp's 'log' message format.

Each entry is a header line followed by a pretty-printed OCPP-J frame:
    2026-10-10T07:13:33.909Z: CentralSystem>ChargePoint  SetChargingProfile
    [ 2, "id", "SetChargingProfile", {...} ]
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

HEADER = re.compile(r"^(\d{4}-\d\d-\d\dT[0-9:.]+Z): (\w+)>(\w+)\s+(\w+)\s*$")
MAX_BYTES = 4 * 1024 * 1024
MAX_PAYLOAD = 8 * 1024
PROFILE_ACTIONS = ("SetChargingProfile", "ClearChargingProfile")
# Dynamic pricing. libocpp (v0.30.3 and EVerest 2026.10.0-rc1) answers
# CostUpdated (2.0.1 and 2.1) and replies NotImplemented (CALLERROR) to the
# OCPP 2.1 tariff messages.
PRICING_ACTIONS = ("CostUpdated", "SetDefaultTariff", "GetTariffs", "ClearTariffs",
                   "ChangeTransactionTariff")
# OCPP 2.1 DER control (libocpp DERControl, EVerest 2026.10.0-rc1).
DER_ACTIONS = ("SetDERControl", "GetDERControl", "ClearDERControl")
TRACKED = PROFILE_ACTIONS + PRICING_ACTIONS + DER_ACTIONS
PRICE_INTERVALS = 6  # intervals of a price schedule shown on the Status page
# Price information in a charging schedule. A 48 h absolutePriceSchedule is
# over 8 KiB, so an oversized profile is shown with these left out (only the
# power setpoint schedule) and they are summarised separately.
PRICE_KEYS = ("absolutePriceSchedule", "priceLevelSchedule", "salesTariff")


def frames(text):
    """Yield (timestamp, direction, action, frame) for each parsable entry."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = HEADER.match(lines[i])
        i += 1
        if not match:
            continue
        body = []
        while i < len(lines) and not HEADER.match(lines[i]):
            body.append(lines[i])
            i += 1
        raw = "\n".join(body).strip()
        if not raw.startswith("["):
            continue
        try:
            frame = json.loads(raw)
        except ValueError:
            continue
        stamp, source, _target, action = match.groups()
        yield stamp, "csms" if source == "CentralSystem" else "station", action, frame


def read_logs(directory):
    """Oldest-first text of the current and rotated message logs, bounded."""
    directory = Path(directory)
    files = sorted(directory.glob("libocpp_201.log*"), key=lambda p: p.stat().st_mtime)
    chunks, total = [], 0
    for path in reversed(files):
        try:
            data = path.read_bytes()[-MAX_BYTES:]
        except OSError:
            continue
        chunks.append(data.decode("utf-8", "replace"))
        total += len(data)
        if total >= MAX_BYTES:
            break
    return "\n".join(reversed(chunks))


def tracked_events(text, actions=TRACKED, limit=10, origin="csms"):
    """Latest requests of the given actions from origin ("csms", or "station"
    for the station's own requests), each paired with the other side's reply
    (CALLRESULT, or CALLERROR such as NotImplemented)."""
    requests, order = {}, []
    for stamp, direction, action, frame in frames(text):
        if direction == origin and len(frame) == 4 and frame[0] == 2 and frame[2] in actions:
            uid = frame[1]
            payload = frame[3]
            size = len(json.dumps(payload))
            requests[uid] = {
                "message_id": uid,
                "action": frame[2],
                "received": stamp,
                "payload": payload,
                "payload_bytes": size,
                "status": None,
                "status_info": None,
                "responded": None,
            }
            order.append(uid)
        elif direction != origin and frame and frame[0] in (3, 4) and frame[1] in requests:
            entry = requests[frame[1]]
            entry["responded"] = stamp
            if frame[0] == 3 and isinstance(frame[2], dict):
                # CostUpdatedResponse and ClearTariffsResponse carry no status.
                entry["status"] = frame[2].get("status") or "Replied"
                entry["status_info"] = frame[2].get("statusInfo")
            else:
                entry["status"] = "CallError"
                entry["status_info"] = {"reasonCode": frame[2] if len(frame) > 2 else None,
                                        "additionalInfo": frame[3] if len(frame) > 3 else None}
    return [_shown(requests[uid]) for uid in order[-limit:]][::-1]


def _without_prices(payload):
    """A SetChargingProfile payload with the price information left out of each
    charging schedule, and the keys removed; None when there is nothing to remove."""
    profile = payload.get("chargingProfile") if isinstance(payload, dict) else None
    if not isinstance(profile, dict):
        return None, []
    removed, schedules = [], []
    for schedule in _list(profile.get("chargingSchedule")):
        if isinstance(schedule, dict):
            removed += [k for k in PRICE_KEYS if k in schedule and k not in removed]
            schedule = {k: v for k, v in schedule.items() if k not in PRICE_KEYS}
        schedules.append(schedule)
    if not removed:
        return None, []
    return {**payload, "chargingProfile": {**profile, "chargingSchedule": schedules}}, removed


def _shown(entry):
    """Finish an event for display. A SetChargingProfile keeps a summary of its
    price schedules; a payload over MAX_PAYLOAD is shown without its price
    information, or withheld if it is still too large."""
    payload = entry["payload"]
    if entry["action"] == "SetChargingProfile":
        entry["price_schedules"] = price_schedules(entry)
    entry["omitted"] = []
    if entry["payload_bytes"] > MAX_PAYLOAD:
        trimmed, removed = _without_prices(payload) if entry["action"] == "SetChargingProfile" else (None, [])
        if trimmed is not None and len(json.dumps(trimmed)) <= MAX_PAYLOAD:
            entry["payload"], entry["omitted"] = trimmed, removed
        else:
            entry["payload"] = None
    return entry


def profile_events(text, limit=10):
    """Latest SetChargingProfile and ClearChargingProfile requests."""
    return tracked_events(text, PROFILE_ACTIONS, limit)


def pricing_events(text, limit=10):
    """Latest CostUpdated and OCPP 2.1 tariff requests, kept apart from the
    profile list so frequent cost updates never push profiles out of it."""
    return tracked_events(text, PRICING_ACTIONS, limit)


def der_events(text, limit=10):
    """Latest SetDERControl, GetDERControl and ClearDERControl requests with
    the station's replies (Accepted, Rejected, NotSupported, NotFound)."""
    return tracked_events(text, DER_ACTIONS, limit)


def charging_needs_events(text, limit=5):
    """The station's NotifyEVChargingNeeds with the CSMS's replies (Accepted,
    Rejected, Processing, NoChargingProfile). On OCPP 2.1 a Rejected reply to
    ISO 15118-20 needs makes libocpp stop the transaction."""
    return tracked_events(text, ("NotifyEVChargingNeeds",), limit, origin="station")


def latest_profile(events):
    """The newest SetChargingProfile of any purpose (TxProfile, TxDefaultProfile,
    ChargingStationMaxProfile, ChargingStationExternalConstraints, ...)."""
    return next((e for e in events if e["action"] == "SetChargingProfile"), None)


def latest_tx_profile(events):
    for event in events:
        payload = event.get("payload") or {}
        profile = payload.get("chargingProfile") or {}
        if event["action"] == "SetChargingProfile" and profile.get("chargingProfilePurpose") == "TxProfile":
            return event
    return None


def _list(value):
    return value if isinstance(value, list) else []


def _number(rational):
    """OCPP 2.1 RationalNumber {value, exponent} as a float."""
    if not isinstance(rational, dict) or not isinstance(rational.get("value"), (int, float)):
        return None
    exponent = rational.get("exponent", 0)
    if not isinstance(exponent, int) or not -20 <= exponent <= 20:
        return None
    return round(rational["value"] * 10 ** exponent, max(0, -exponent))


def _at(anchor, offset):
    """UTC time `offset` seconds after an RFC 3339 anchor, or None."""
    if not isinstance(anchor, str) or not isinstance(offset, (int, float)):
        return None
    try:
        start = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return (start + timedelta(seconds=offset)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _intervals(entries, duration_of, describe, anchor, limit):
    """First `limit` back-to-back intervals with their start offsets."""
    shown, offset = [], 0
    for entry in entries[:limit]:
        if not isinstance(entry, dict):
            break
        duration = duration_of(entry)
        item = {"offset_s": offset, "start": _at(anchor, offset), "duration_s": duration}
        item.update(describe(entry))
        shown.append(item)
        offset += duration if isinstance(duration, (int, float)) else 0
    return shown


def _energy_fee(stack):
    rules = _list(stack.get("priceRule"))
    # The rule for the lowest power range is the plain energy price.
    first = min((r for r in rules if isinstance(r, dict)),
                key=lambda r: _number(r.get("powerRangeStart")) or 0, default={})
    return {"energy_fee": _number(first.get("energyFee")), "rules": len(rules)}


def _sales_entry(entry):
    costs = [c for item in _list(entry.get("consumptionCost")) if isinstance(item, dict)
             for c in _list(item.get("cost")) if isinstance(c, dict)]
    first = costs[0] if costs else {}
    amount = first.get("amount")
    multiplier = first.get("amountMultiplier") or 0
    if isinstance(amount, (int, float)) and isinstance(multiplier, int) and -20 <= multiplier <= 20:
        amount = round(amount * 10 ** multiplier, max(0, -multiplier))
    return {"price_level": entry.get("ePriceLevel"), "cost": amount, "cost_kind": first.get("costKind")}


def price_schedules(event, limit=PRICE_INTERVALS):
    """Readable summary of the price information in a SetChargingProfile:
    OCPP 2.1 absolutePriceSchedule and priceLevelSchedule, and the ISO 15118-2
    salesTariff. libocpp stores these but does not act on them."""
    if isinstance(event, dict) and "price_schedules" in event:
        return event["price_schedules"]
    payload = (event or {}).get("payload") or {}
    profile = payload.get("chargingProfile") if isinstance(payload, dict) else None
    profile = profile if isinstance(profile, dict) else {}
    found = []
    for schedule in _list(profile.get("chargingSchedule")):
        if not isinstance(schedule, dict):
            continue
        absolute = schedule.get("absolutePriceSchedule")
        if isinstance(absolute, dict):
            stacks = _list(absolute.get("priceRuleStacks"))
            found.append({
                "charging_schedule_id": schedule.get("id"),
                "kind": "absolutePriceSchedule",
                "id": absolute.get("priceScheduleID"),
                "description": absolute.get("priceScheduleDescription"),
                "time_anchor": absolute.get("timeAnchor"),
                "currency": absolute.get("currency"),
                "algorithm": absolute.get("priceAlgorithm"),
                "count": len(stacks),
                "intervals": _intervals(stacks, lambda e: e.get("duration"), _energy_fee,
                                        absolute.get("timeAnchor"), limit),
            })
        levels = schedule.get("priceLevelSchedule")
        if isinstance(levels, dict):
            entries = _list(levels.get("priceLevelScheduleEntries"))
            found.append({
                "charging_schedule_id": schedule.get("id"),
                "kind": "priceLevelSchedule",
                "id": levels.get("priceScheduleId"),
                "description": levels.get("priceScheduleDescription"),
                "time_anchor": levels.get("timeAnchor"),
                "number_of_price_levels": levels.get("numberOfPriceLevels"),
                "count": len(entries),
                "intervals": _intervals(entries, lambda e: e.get("duration"),
                                        lambda e: {"price_level": e.get("priceLevel")},
                                        levels.get("timeAnchor"), limit),
            })
        tariff = schedule.get("salesTariff")
        if isinstance(tariff, dict):
            entries = _list(tariff.get("salesTariffEntry"))
            anchor = schedule.get("startSchedule")
            shown = []
            for entry in entries[:limit]:
                if not isinstance(entry, dict):
                    break
                interval = entry.get("relativeTimeInterval") or {}
                item = {"offset_s": interval.get("start"), "start": _at(anchor, interval.get("start")),
                        "duration_s": interval.get("duration")}
                item.update(_sales_entry(entry))
                shown.append(item)
            found.append({
                "charging_schedule_id": schedule.get("id"),
                "kind": "salesTariff",
                "id": tariff.get("id"),
                "description": tariff.get("salesTariffDescription"),
                "time_anchor": anchor,
                "number_of_price_levels": tariff.get("numEPriceLevels"),
                "count": len(entries),
                "intervals": shown,
            })
    return found
