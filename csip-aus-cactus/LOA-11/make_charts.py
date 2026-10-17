#!/usr/bin/env python3
"""Charts for the LOA-11 report, built from data/<run>/ with the standard library only.

python3 make_charts.py   # writes charts/<run>/*.svg for every run below
"""
import csv
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
AEST = timezone(timedelta(hours=10))

# Reference palette (light): categorical slots 1-3, status critical/good, ink and chrome.
CSIP, OCPP, POWER = "#2a78d6", "#eb6834", "#1baf7a"
CRITICAL, GOOD = "#d03b3b", "#0ca30c"
SURFACE, INK, INK2, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
CAP_W = 25000


def ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def hms(t):
    return datetime.fromtimestamp(t, AEST).strftime("%H:%M:%S")


# Per run: plot window, when the default control first applied, any period the integration was locked,
# and the profile the charger held through the run (for the timing lanes).
RUNS = {
    "74853": {"window": ("2026-10-17T03:07:40+00:00", "2026-10-17T03:19:20+00:00"),
              "default_from": "2026-10-17T03:07:59.491998+00:00",
              "lock": ("2026-10-17T13:09:13.29+10:00", "2026-10-17T13:16:00.70+10:00"),
              "held": "2026-10-17T03:09:12.775Z",
              "sends_note": ("2026-10-17T13:09:06+10:00", "13 sends at 1 s (ODE ramp)")},
    "74858": {"window": ("2026-10-17T03:52:00+00:00", "2026-10-17T04:03:40+00:00"),
              "default_from": "2026-10-17T03:52:05.8+00:00",
              "lock": None,
              "held": "2026-10-17T03:53:27.965Z",
              "sends_note": ("2026-10-17T13:57:12+10:00", "8 sends at 1 s (ODE ramp-down)")},
    "74865": {"window": ("2026-10-17T05:41:30+00:00", "2026-10-17T05:55:20+00:00"),
              "default_from": "2026-10-17T05:41:52.09+00:00",
              "lock": None,
              "held": "2026-10-17T15:45:13.04+10:00",
              "sends_note": ("2026-10-17T15:44:54+10:00", "4 sends in 19 s (ODE ramp)"),
              "charger": "SIM-EV-EVEREST-V2G-03, DC V2G simulator (11 kW), CentralSetpoint periods with no discharge"},
}
AC_CHARGER = "SIM-EV-EVEREST-G1, 3-phase 32 A AC (max about 22 kW)"


def csip_controls(data):
    """(start, end, watts, tag) from the raw DERControl XML."""
    text = (data / "csip-aus-derc.xml").read_text()
    controls = []
    for i, block in enumerate(re.findall(r"<DERControl .*?</DERControl>", text, re.S), 1):
        start = int(re.search(r"<start>(\d+)</start>", block).group(1))
        duration = int(re.search(r"<duration>(\d+)</duration>", block).group(1))
        mult, value = re.search(r"opModImpLimW>\s*<multiplier>(-?\d+)</multiplier>\s*<value>(-?\d+)</value>",
                                block).groups()
        # interval.start is whole seconds; the description holds Cactus's exact start.
        exact = ts(re.search(r"<description>(.*?)</description>", block).group(1))
        controls.append((exact, exact + duration, int(value) * 10 ** int(mult), f"DERC{i}"))
        assert abs(exact - start) < 1
    return controls


def csip_limit(t, controls, default_from):
    if t < default_from:
        return None
    for i, (start, end, watts, _) in enumerate(controls):
        # Consecutive controls are created about 0.1 s apart, so each ends a fraction of a second
        # before the next begins. Draw that sub-second default gap as part of the earlier control.
        nxt = controls[i + 1][0] if i + 1 < len(controls) else end
        if start <= t < (nxt if 0 < nxt - end < 1 else end):
            return watts
    return 0


def load_profiles(data):
    rows = json.loads((data / "ocpp-charging-profiles.json").read_text())["profiles"]
    out = []
    for row in rows:
        sched = row["request"]["chargingProfile"]["chargingSchedule"][0]
        out.append((ts(row["received"]), ts(sched["startSchedule"]),
                    [(p["startPeriod"], p["limit"]) for p in sched["chargingSchedulePeriod"]], sched["duration"]))
    return out


def load_sends(data):
    with open(data / "bridge-sends.csv") as f:
        return [(ts(r["time_aest"]), int(r["limit_w"]) if r["limit_w"] else None, r["result"], r["note"],
                 r.get("schedule") or "") for r in csv.DictReader(f)]


def load_power(data):
    with open(data / "charger-power.csv") as f:
        return [(ts(r["time_aest"]), int(r["power_w"])) for r in csv.DictReader(f)]


def schedule_events(profiles, sends):
    """Every accepted profile as (received, [(absolute start, limit)], end).

    Profiles captured from the charger's log are exact. A send without a captured profile is rebuilt
    from what the bridge recorded: its period-0 limit and, when present, its schedule signature
    (absolute boundary second:limit), rounded as the bridge rounds (decreases down, increases up,
    from a schedule that starts 1 s before the send).
    """
    events = [(rec, [(start + sp, lim) for sp, lim in periods], start + dur) for rec, start, periods, dur in profiles]
    for t, watts, result, _, sig in sends:
        if result != "accepted" or watts is None or any(abs(e[0] - t) < 0.6 for e in events):
            continue
        now = t - 0.15  # the bridge renders the plan about 0.15 s before the send completes
        segs, last = [(t, watts)], watts
        for item in filter(None, sig.split(",")):
            b, v = (int(x) for x in item.split(":"))
            if v == last or b <= now:
                continue
            offset = b - now + 1
            segs.append((now - 1 + (math.floor(offset) if v < last else math.ceil(offset)), v))
            last = v
        events.append((t, segs, now - 1 + 600))
    return sorted(events)


def ocpp_limit(t, events):
    """Limit the charger's TxProfile set at time t (newest accepted profile wins)."""
    current = [e for e in events if e[0] <= t]
    if not current:
        return None
    _, segs, end = current[-1]
    if t >= end:
        return None
    limit = segs[0][1]
    for start, value in segs:
        if t >= start:
            limit = value
    return limit


class Plot:
    def __init__(self, width, height, title, subtitle=""):
        self.w, self.h = width, height
        self.parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
                      f'height="{height}" font-family="system-ui,-apple-system,Segoe UI,sans-serif" font-size="12">',
                      f'<rect width="100%" height="100%" fill="{SURFACE}"/>',
                      f'<text x="16" y="24" font-size="15" font-weight="600" fill="{INK}">{title}</text>']
        if subtitle:
            self.parts.append(f'<text x="16" y="42" fill="{INK2}">{subtitle}</text>')

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, anchor="start", fill=INK2, size=12, weight="400"):
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="{fill}" font-size="{size}" '
                 f'font-weight="{weight}">{s}</text>')

    def save(self, out, name):
        out.mkdir(parents=True, exist_ok=True)
        (out / name).write_text("\n".join(self.parts + ["</svg>"]) + "\n")


def step_path(points, sx, sy):
    """Step-after polyline; None values break the line."""
    d, prev = [], None
    for t, v in points:
        if v is None:
            prev = None
            continue
        if prev is None:
            d.append(f"M{sx(t):.1f},{sy(v):.1f}")
        else:
            d.append(f"H{sx(t):.1f}V{sy(v):.1f}")
        prev = v
    if prev is not None and points:
        d.append(f"H{sx(points[-1][0]):.1f}")
    return "".join(d)


def sample(fn, t0, t1, step=0.1):
    pts, t, last = [], t0, object()
    while t <= t1:
        v = fn(t)
        if v != last:
            pts.append((t, v))
            last = v
        t += step
    pts.append((t1, fn(t1)))
    return pts


def overview(run):
    controls, events, power, cfg = run["controls"], run["events"], run["power"], run["cfg"]
    t0, t1 = (ts(x) for x in cfg["window"])
    p = Plot(920, 440, f"LOA-11 run {run['name']}: CSIP-AUS import limit, OCPP TxProfile limit and charger power",
             f"{cfg.get('charger', AC_CHARGER)}. Times AEST, 17 Oct 2026.")
    left, right, top, bottom = 64, 900, 64, 380
    ymax = 30000
    sx = lambda t: left + (t - t0) / (t1 - t0) * (right - left)
    sy = lambda w: bottom - min(w, ymax) / ymax * (bottom - top)
    if cfg["lock"]:
        lock0, lock1 = (ts(x) for x in cfg["lock"])
        p.add(f'<rect x="{sx(lock0):.1f}" y="{top}" width="{sx(lock1) - sx(lock0):.1f}" height="{bottom - top}" '
              f'fill="{CRITICAL}" fill-opacity="0.07"/>')
        p.text((sx(lock0) + sx(lock1)) / 2, sy(27000), "Integration locked after CitrineOS HTTP 500: no profiles sent",
               "middle", CRITICAL)
    for kw in range(0, 31, 5):
        y = sy(kw * 1000)
        p.add(f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID if kw else AXIS}"/>')
        p.text(left - 8, y + 4, f"{kw}", "end")
    p.text(16, top - 6, "kW", fill=INK2)
    minute = math.ceil(t0 / 60) * 60
    while minute <= t1:
        x = sx(minute)
        p.add(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{bottom}" y2="{bottom + 5}" stroke="{AXIS}"/>')
        p.text(x, bottom + 18, hms(minute)[:5], "middle")
        minute += 60
    y = sy(CAP_W)
    p.add(f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK2}" stroke-dasharray="4 4"/>')
    p.text(right - 4, y - 5, "Bridge cap 25 kW", "end")
    csip_pts = sample(lambda t: csip_limit(t, controls, run["default_from"]), t0, t1)
    p.add(f'<path d="{step_path(csip_pts, sx, sy)}" fill="none" stroke="{CSIP}" stroke-width="2"/>')
    ocpp_pts = sample(lambda t: ocpp_limit(t, events), t0, t1)
    p.add(f'<path d="{step_path(ocpp_pts, sx, sy)}" fill="none" stroke="{OCPP}" stroke-width="2" '
          f'stroke-dasharray="6 3"/>')
    pw = [(t, w) for t, w in power if t0 <= t <= t1]
    p.add(f'<path d="{step_path(pw + [(t1, pw[-1][1])], sx, sy)}" fill="none" stroke="{POWER}" '
          f'stroke-width="2"/>')
    for t, w in pw:
        p.add(f'<circle cx="{sx(t):.1f}" cy="{sy(w):.1f}" r="2.5" fill="{POWER}" stroke="{SURFACE}" '
              f'stroke-width="1"/>')
    for start, end, watts, tag in controls:
        label = f"{tag} {watts / 1000:g} kW" + (" ↑" if watts > ymax else "")
        y = sy(min(watts, ymax)) + 16 if watts >= ymax else (sy(watts) - 6 if watts else sy(0) - 22)
        p.text(sx(start) + 4, y, label, fill=INK)
    # Legend (identity never colour-alone: lines also differ in dash and markers).
    lx, ly = left, bottom + 40
    for colour, dash, label in ((CSIP, "", "CSIP-AUS opModImpLimW (Cactus)"),
                                (OCPP, "6 3", "OCPP TxProfile limit on the charger"),
                                (POWER, "", "Charger power (5 s MeterValues)")):
        p.add(f'<line x1="{lx}" x2="{lx + 22}" y1="{ly}" y2="{ly}" stroke="{colour}" stroke-width="2" '
              f'stroke-dasharray="{dash}"/>')
        p.text(lx + 28, ly + 4, label, fill=INK)
        lx += 28 + 6.5 * len(label) + 32
    p.save(run["out"], "limits-and-power.svg")


def timing(run):
    controls, events, sends, cfg = run["controls"], run["events"], run["sends"], run["cfg"]
    t0, t1 = (ts(x) for x in cfg["window"])
    held = next(e for e in events if abs(e[0] - ts(cfg["held"])) < 0.01)
    held_label = hms(held[1][0][0])
    p = Plot(920, 330, f"LOA-11 run {run['name']} timing: CSIP-AUS controls, bridge sends, charger schedule",
             f"Each lane on the same clock (AEST). The {held_label} profile held every remaining step"
             + (" through the lock." if cfg["lock"] else "."))
    left, right = 200, 900
    sx = lambda t: left + (t - t0) / (t1 - t0) * (right - left)
    held_lane = f"Charger schedule ({held_label})"
    lanes = ["CSIP-AUS controls", "Bridge sends", "Integration state", held_lane]
    lane_y = {name: 72 + i * 56 for i, name in enumerate(lanes)}
    for name, y in lane_y.items():
        p.text(16, y + 18, name, fill=INK, weight="600")
        p.add(f'<line x1="{left}" x2="{right}" y1="{y + 36}" y2="{y + 36}" stroke="{GRID}"/>')
    for start, *_ in controls:
        p.add(f'<line x1="{sx(start):.1f}" x2="{sx(start):.1f}" y1="64" y2="292" stroke="{AXIS}" '
              f'stroke-dasharray="2 3"/>')
    y = lane_y["CSIP-AUS controls"]
    d0 = run["default_from"]
    p.add(f'<rect x="{sx(d0):.1f}" y="{y + 4}" width="{sx(t1) - sx(d0):.1f}" height="24" '
          f'fill="none" stroke="{CSIP}" stroke-dasharray="3 3" rx="4"/>')
    room = sx(controls[0][0]) - sx(d0)
    p.text(sx(d0) + 4, y + 21, "Default 0 W" if room > 80 else "Default", fill=INK)
    for start, end, watts, tag in controls:
        p.add(f'<rect x="{sx(start) + 1:.1f}" y="{y + 4}" width="{sx(end) - sx(start) - 2:.1f}" height="24" '
              f'fill="{CSIP}" rx="4"/>')
        p.text((sx(start) + sx(end)) / 2, y + 21, f"{tag} {watts / 1000:g} kW", "middle", "#ffffff", weight="600")
    y = lane_y["Bridge sends"]
    for t, watts, result, *_ in sends:
        x = sx(t)
        if result == "accepted":
            p.add(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y + 6}" y2="{y + 28}" stroke="{OCPP}" stroke-width="2"/>')
        else:
            p.add(f'<path d="M{x - 6:.1f},{y + 8}L{x + 6:.1f},{y + 26}M{x + 6:.1f},{y + 8}L{x - 6:.1f},{y + 26}" '
                  f'stroke="{CRITICAL}" stroke-width="2.5"/>')
            p.text(x + 10, y + 21, f"HTTP 500 at {hms(t)}", fill=CRITICAL)
    note_t, note = cfg["sends_note"]
    p.text(sx(ts(note_t)), y + 46, note, "middle")
    y = lane_y["Integration state"]
    if cfg["lock"]:
        lock0, lock1 = (ts(x) for x in cfg["lock"])
        states = ((t0, lock0, GOOD, "OK"), (lock0, lock1, CRITICAL, "Locked: outcome unknown"),
                  (lock1, t1, GOOD, "OK after reload"))
    else:
        states = ((t0, t1, GOOD, "OK: every send dispatched, no errors"),)
    for a, b, colour, label in states:
        p.add(f'<rect x="{sx(a) + 1:.1f}" y="{y + 8}" width="{sx(b) - sx(a) - 2:.1f}" height="18" '
              f'fill="{colour}" fill-opacity="0.18" stroke="{colour}" rx="4"/>')
        p.text((sx(a) + sx(b)) / 2, y + 21, ("✓ " if colour == GOOD else "✕ ") + label, "middle", INK)
    y = lane_y[held_lane]
    _, segs, end = held
    bounds = [a for a, _ in segs] + [end]
    for (a, watts), b in zip(segs, bounds[1:]):
        b = min(b, t1)
        if b - a < 4:
            p.add(f'<rect x="{sx(a):.1f}" y="{y + 4}" width="{max(sx(b) - sx(a), 2):.1f}" height="24" fill="{INK2}"/>')
            continue
        p.add(f'<rect x="{sx(a) + 1:.1f}" y="{y + 4}" width="{sx(b) - sx(a) - 2:.1f}" height="24" fill="{OCPP}" '
              f'fill-opacity="0.85" rx="4"/>')
        p.text((sx(a) + sx(b)) / 2, y + 21, f"{watts / 1000:g} kW", "middle", INK, weight="600")
    minute = math.ceil(t0 / 60) * 60
    while minute <= t1:
        p.text(sx(minute), 312, hms(minute)[:5], "middle")
        minute += 60
    p.save(run["out"], "timing-lanes.svg")


def step_response(run):
    controls, events, power = run["controls"], run["events"], run["power"]
    p = Plot(920, 350, f"LOA-11 run {run['name']}: step response at each scheduled decrease (5 s samples)",
             "Window: 15 s before to 20 s after the Cactus control start. The charger applied steps from the profile it already held.")
    panels = [c for c in controls if c[3] in ("DERC3", "DERC4", "DERC5")]
    width, gap, left0, top, bottom = 262, 30, 44, 112, 286
    ymax = 32000
    for i, (start, end, watts, tag) in enumerate(panels):
        left = left0 + i * (width + gap)
        right = left + width
        t0, t1 = start - 15, start + 20
        sx = lambda t, l=left, r=right, a=t0, b=t1: l + (t - a) / (b - a) * (r - l)
        sy = lambda w: bottom - min(w, ymax) / ymax * (bottom - top)
        for kw in (0, 10, 20, 30):
            y = sy(kw * 1000)
            p.add(f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID if kw else AXIS}"/>')
            if i == 0:
                p.text(left - 6, y + 4, f"{kw}", "end")
        for off in (-10, 0, 10, 20):
            x = sx(start + off)
            p.text(x, bottom + 16, f"{off:+d} s" if off else "0 s", "middle")
        x0 = sx(start)
        p.add(f'<line x1="{x0:.1f}" x2="{x0:.1f}" y1="{top}" y2="{bottom}" stroke="{INK2}" stroke-dasharray="2 3"/>')
        p.text(left, top - 36, f"{tag}: to {watts / 1000:g} kW at {hms(start)}", fill=INK, weight="600")
        csip_pts = sample(lambda t: csip_limit(t, controls, run["default_from"]), t0, t1, 0.05)
        p.add(f'<path d="{step_path(csip_pts, sx, sy)}" fill="none" stroke="{CSIP}" stroke-width="2"/>')
        ocpp_pts = sample(lambda t: ocpp_limit(t, events), t0, t1, 0.05)
        p.add(f'<path d="{step_path(ocpp_pts, sx, sy)}" fill="none" stroke="{OCPP}" stroke-width="2" '
              f'stroke-dasharray="6 3"/>')
        # The time from which the charger's limit stays at the new level (a later profile can briefly undo it).
        ocpp_step = None
        for t, v in ocpp_pts:
            if v is not None and v <= watts:
                ocpp_step = ocpp_step if ocpp_step is not None else t
            else:
                ocpp_step = None
        before = [(t, w) for t, w in power if t < start][-1]
        pw = [before] + [(t, w) for t, w in power if t0 <= t <= t1 and t >= before[0]]
        clipped = [(max(t, t0), w) for t, w in pw]
        p.add(f'<path d="{step_path(clipped + [(t1, clipped[-1][1])], sx, sy)}" fill="none" stroke="{POWER}" '
              f'stroke-width="2"/>')
        for t, w in pw:
            if t >= t0:
                p.add(f'<circle cx="{sx(t):.1f}" cy="{sy(w):.1f}" r="3" fill="{POWER}" stroke="{SURFACE}"/>')
        first = next((t, w) for t, w in power if t > start and w <= watts * 1.05 + 100)
        first_step = next(t for t, v in ocpp_pts if v is not None and v <= watts)
        note = (f" (first {first_step - start:+.1f} s, then live sends raised it)" if ocpp_step - first_step > 0.5 else "")
        p.text(left, top - 21, f"OCPP step {ocpp_step - start:+.1f} s{note}", fill=INK2, size=11)
        p.text(left, top - 7, f"First 5 s sample at new level {first[0] - start:+.1f} s", fill=INK2, size=11)
    lx, ly = left0, 336
    for colour, dash, label in ((CSIP, "", "CSIP-AUS control"), (OCPP, "6 3", "OCPP limit on charger"),
                                (POWER, "", "Charger power")):
        p.add(f'<line x1="{lx}" x2="{lx + 22}" y1="{ly}" y2="{ly}" stroke="{colour}" stroke-width="2" '
              f'stroke-dasharray="{dash}"/>')
        p.text(lx + 28, ly + 4, label, fill=INK)
        lx += 28 + 6.5 * len(label) + 32
    p.save(run["out"], "step-response.svg")


def main():
    for name, cfg in RUNS.items():
        data = HERE / "data" / name
        sends = load_sends(data)
        run = {"name": name, "cfg": cfg, "out": HERE / "charts" / name, "controls": csip_controls(data),
               "events": schedule_events(load_profiles(data), sends), "sends": sends, "power": load_power(data),
               "default_from": ts(cfg["default_from"])}
        overview(run)
        timing(run)
        step_response(run)


if __name__ == "__main__":
    main()
