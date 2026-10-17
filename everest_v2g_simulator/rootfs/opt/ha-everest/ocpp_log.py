"""Read-only parser for libocpp's 'log' message format.

Each entry is a header line followed by a pretty-printed OCPP-J frame:
    2026-10-10T07:13:33.909Z: CentralSystem>ChargePoint  SetChargingProfile
    [ 2, "id", "SetChargingProfile", {...} ]
"""
import json
from pathlib import Path
import re

HEADER = re.compile(r"^(\d{4}-\d\d-\d\dT[0-9:.]+Z): (\w+)>(\w+)\s+(\w+)\s*$")
MAX_BYTES = 4 * 1024 * 1024
MAX_PAYLOAD = 8 * 1024
TRACKED = ("SetChargingProfile", "ClearChargingProfile")


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


def profile_events(text, limit=10):
    """Latest CSMS profile requests, each paired with the station's reply."""
    requests, order = {}, []
    for stamp, direction, action, frame in frames(text):
        if direction == "csms" and len(frame) == 4 and frame[0] == 2 and frame[2] in TRACKED:
            uid = frame[1]
            payload = frame[3]
            size = len(json.dumps(payload))
            requests[uid] = {
                "message_id": uid,
                "action": frame[2],
                "received": stamp,
                "payload": payload if size <= MAX_PAYLOAD else None,
                "payload_bytes": size,
                "status": None,
                "status_info": None,
                "responded": None,
            }
            order.append(uid)
        elif direction == "station" and frame and frame[0] in (3, 4) and frame[1] in requests:
            entry = requests[frame[1]]
            entry["responded"] = stamp
            if frame[0] == 3 and isinstance(frame[2], dict):
                entry["status"] = frame[2].get("status")
                entry["status_info"] = frame[2].get("statusInfo")
            else:
                entry["status"] = "CallError"
                entry["status_info"] = {"reasonCode": frame[2] if len(frame) > 2 else None}
    return [requests[uid] for uid in order[-limit:]][::-1]


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
