#!/usr/bin/env python3
"""Charts for the LOA-11 report, built from data/ with the standard library only.

python3 make_charts.py   # writes charts/*.svg
"""
import csv
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
OUT = HERE / "charts"
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


def csip_controls():
    """(start, end, watts, tag) from the raw DERControl and DefaultDERControl XML."""
    text = (DATA / "csip-aus-derc.xml").read_text()
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


DEFAULT_FROM = ts("2026-10-17T03:07:59.491998+00:00")  # DefaultDERControl first served (opModImpLimW 0)


def csip_limit(t, controls):
    if t < DEFAULT_FROM:
        return None
    for i, (start, end, watts, _) in enumerate(controls):
        # Consecutive controls are created about 0.1 s apart, so each ends a fraction of a second
        # before the next begins. Draw that sub-second default gap as part of the earlier control.
        nxt = controls[i + 1][0] if i + 1 < len(controls) else end
        if start <= t < (nxt if 0 < nxt - end < 1 else end):
            return watts
    return 0


def load_profiles():
    rows = json.loads((DATA / "ocpp-charging-profiles.json").read_text())["profiles"]
    out = []
    for row in rows:
        sched = row["request"]["chargingProfile"]["chargingSchedule"][0]
        out.append((ts(row["received"]), ts(sched["startSchedule"]),
                    [(p["startPeriod"], p["limit"]) for p in sched["chargingSchedulePeriod"]], sched["duration"]))
    return out


def load_sends():
    with open(DATA / "bridge-sends.csv") as f:
        return [(ts(r["time_aest"]), int(r["limit_w"]) if r["limit_w"] else None, r["result"], r["note"])
                for r in csv.DictReader(f)]


def load_power():
    with open(DATA / "charger-power.csv") as f:
        return [(ts(r["time_aest"]), int(r["power_w"])) for r in csv.DictReader(f)]


def ocpp_limit(t, profiles, sends):
    """Limit the charger's TxProfile set at time t (newest accepted profile wins)."""
    best = None
    for received, start, periods, duration in profiles:
        if received <= t and (best is None or received > best[0]):
            best = (received, start, periods, duration)
    early = [s for s in sends if s[2] == "accepted" and s[0] <= t and s[1] is not None]
    if early and (best is None or early[-1][0] > best[0]) and early[-1][0] < profiles[0][0]:
        return early[-1][1]
    if best is None:
        return early[-1][1] if early else None
    _, start, periods, duration = best
    offset = t - start
    if offset >= duration:
        return None
    limit = periods[0][1]
    for start_period, value in periods:
        if offset >= start_period:
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

    def save(self, name):
        OUT.mkdir(exist_ok=True)
        (OUT / name).write_text("\n".join(self.parts + ["</svg>"]) + "\n")


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


def overview(controls, profiles, sends, power):
    t0, t1 = ts("2026-10-17T03:07:40+00:00"), ts("2026-10-17T03:19:20+00:00")
    p = Plot(920, 440, "LOA-11: CSIP-AUS import limit, OCPP TxProfile limit and charger power",
             "SIM-EV-EVEREST-G1, 3-phase 32 A AC (max about 22 kW). Times AEST, 17 Oct 2026.")
    left, right, top, bottom = 64, 900, 64, 380
    ymax = 30000
    sx = lambda t: left + (t - t0) / (t1 - t0) * (right - left)
    sy = lambda w: bottom - min(w, ymax) / ymax * (bottom - top)
    lock0, lock1 = ts("2026-10-17T13:09:13.29+10:00"), ts("2026-10-17T13:16:00.70+10:00")
    p.add(f'<rect x="{sx(lock0):.1f}" y="{top}" width="{sx(lock1) - sx(lock0):.1f}" height="{bottom - top}" '
          f'fill="{CRITICAL}" fill-opacity="0.07"/>')
    p.text((sx(lock0) + sx(lock1)) / 2, sy(27000), "Integration locked after CitrineOS HTTP 500: no profiles sent",
           "middle", CRITICAL)
    for kw in range(0, 31, 5):
        y = sy(kw * 1000)
        p.add(f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID if kw else AXIS}"/>')
        p.text(left - 8, y + 4, f"{kw}", "end")
    p.text(16, top - 6, "kW", fill=INK2)
    minute = ts("2026-10-17T03:08:00+00:00")
    while minute <= t1:
        x = sx(minute)
        p.add(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{bottom}" y2="{bottom + 5}" stroke="{AXIS}"/>')
        p.text(x, bottom + 18, hms(minute)[:5], "middle")
        minute += 60
    y = sy(CAP_W)
    p.add(f'<line x1="{left}" x2="{right}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK2}" stroke-dasharray="4 4"/>')
    p.text(right - 4, y - 5, "Bridge cap 25 kW", "end")
    csip_pts = sample(lambda t: csip_limit(t, controls), t0, t1)
    p.add(f'<path d="{step_path(csip_pts, sx, sy)}" fill="none" stroke="{CSIP}" stroke-width="2"/>')
    ocpp_pts = sample(lambda t: ocpp_limit(t, profiles, sends), t0, t1)
    p.add(f'<path d="{step_path(ocpp_pts, sx, sy)}" fill="none" stroke="{OCPP}" stroke-width="2" '
          f'stroke-dasharray="6 3"/>')
    pw = [(t, w) for t, w in power if t0 <= t <= t1]
    hold = []
    for i, (t, w) in enumerate(pw):
        hold.append((t, w))
    p.add(f'<path d="{step_path(hold + [(t1, pw[-1][1])], sx, sy)}" fill="none" stroke="{POWER}" '
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
    p.save("limits-and-power.svg")


def timing(controls, profiles, sends):
    t0, t1 = ts("2026-10-17T03:07:40+00:00"), ts("2026-10-17T03:19:20+00:00")
    p = Plot(920, 330, "LOA-11 timing: CSIP-AUS controls, bridge sends and the schedule held by the charger",
             "Each lane on the same clock (AEST). The 13:09:11 profile carried every remaining step through the lock.")
    left, right = 200, 900
    sx = lambda t: left + (t - t0) / (t1 - t0) * (right - left)
    lanes = ["CSIP-AUS controls", "Bridge sends", "Integration state", "Charger schedule (13:09:11)"]
    lane_y = {name: 72 + i * 56 for i, name in enumerate(lanes)}
    for name, y in lane_y.items():
        p.text(16, y + 18, name, fill=INK, weight="600")
        p.add(f'<line x1="{left}" x2="{right}" y1="{y + 36}" y2="{y + 36}" stroke="{GRID}"/>')
    for start, *_ in controls:
        p.add(f'<line x1="{sx(start):.1f}" x2="{sx(start):.1f}" y1="64" y2="292" stroke="{AXIS}" '
              f'stroke-dasharray="2 3"/>')
    y = lane_y["CSIP-AUS controls"]
    p.add(f'<rect x="{sx(DEFAULT_FROM):.1f}" y="{y + 4}" width="{sx(t1) - sx(DEFAULT_FROM):.1f}" height="24" '
          f'fill="none" stroke="{CSIP}" stroke-dasharray="3 3" rx="4"/>')
    p.text(sx(DEFAULT_FROM) + 4, y + 21, "Default 0 W", fill=INK)
    for start, end, watts, tag in controls:
        p.add(f'<rect x="{sx(start) + 1:.1f}" y="{y + 4}" width="{sx(end) - sx(start) - 2:.1f}" height="24" '
              f'fill="{CSIP}" rx="4"/>')
        p.text((sx(start) + sx(end)) / 2, y + 21, f"{tag} {watts / 1000:g} kW", "middle", "#ffffff", weight="600")
    y = lane_y["Bridge sends"]
    for t, watts, result, _ in sends:
        x = sx(t)
        if result == "accepted":
            p.add(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y + 6}" y2="{y + 28}" stroke="{OCPP}" stroke-width="2"/>')
        else:
            p.add(f'<path d="M{x - 6:.1f},{y + 8}L{x + 6:.1f},{y + 26}M{x + 6:.1f},{y + 8}L{x - 6:.1f},{y + 26}" '
                  f'stroke="{CRITICAL}" stroke-width="2.5"/>')
            p.text(x + 10, y + 21, "HTTP 500 at 13:09:13", fill=CRITICAL)
    p.text(sx(ts("2026-10-17T13:09:06+10:00")), y + 46, "13 sends at 1 s (ODE ramp)", "middle")
    y = lane_y["Integration state"]
    lock0, lock1 = ts("2026-10-17T13:09:13.29+10:00"), ts("2026-10-17T13:16:00.70+10:00")
    for a, b, colour, label in ((t0, lock0, GOOD, "OK"), (lock0, lock1, CRITICAL, "Locked: outcome unknown"),
                                (lock1, t1, GOOD, "OK after reload")):
        p.add(f'<rect x="{sx(a) + 1:.1f}" y="{y + 8}" width="{sx(b) - sx(a) - 2:.1f}" height="18" '
              f'fill="{colour}" fill-opacity="0.18" stroke="{colour}" rx="4"/>')
        p.text((sx(a) + sx(b)) / 2, y + 21, ("✓ " if colour == GOOD else "✕ ") + label, "middle", INK)
    y = lane_y["Charger schedule (13:09:11)"]
    received, start, periods, duration = next(pr for pr in profiles if abs(pr[0] - ts("2026-10-17T03:09:12.775Z")) < 0.01)
    bounds = [start + sp for sp, _ in periods] + [start + duration]
    for (sp, watts), a, b in zip(periods, bounds, bounds[1:]):
        b = min(b, t1)
        p.add(f'<rect x="{sx(a) + 1:.1f}" y="{y + 4}" width="{sx(b) - sx(a) - 2:.1f}" height="24" fill="{OCPP}" '
              f'fill-opacity="0.85" rx="4"/>')
        p.text((sx(a) + sx(b)) / 2, y + 21, f"{watts / 1000:g} kW", "middle", INK, weight="600")
    minute = ts("2026-10-17T03:08:00+00:00")
    while minute <= t1:
        p.text(sx(minute), 312, hms(minute)[:5], "middle")
        minute += 60
    p.save("timing-lanes.svg")


def step_response(controls, profiles, sends, power):
    p = Plot(920, 350, "Step response at each scheduled decrease (5 s samples)",
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
        csip_pts = sample(lambda t: csip_limit(t, controls), t0, t1, 0.05)
        p.add(f'<path d="{step_path(csip_pts, sx, sy)}" fill="none" stroke="{CSIP}" stroke-width="2"/>')
        ocpp_pts = sample(lambda t: ocpp_limit(t, profiles, sends), t0, t1, 0.05)
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
        note = f" (first {first_step - start:+.1f} s, undone for 1 s)" if ocpp_step - first_step > 0.5 else ""
        p.text(left, top - 21, f"OCPP step {ocpp_step - start:+.1f} s{note}", fill=INK2, size=11)
        p.text(left, top - 7, f"First 5 s sample at new level {first[0] - start:+.1f} s", fill=INK2, size=11)
    lx, ly = left0, 336
    for colour, dash, label in ((CSIP, "", "CSIP-AUS control"), (OCPP, "6 3", "OCPP limit on charger"),
                                (POWER, "", "Charger power")):
        p.add(f'<line x1="{lx}" x2="{lx + 22}" y1="{ly}" y2="{ly}" stroke="{colour}" stroke-width="2" '
              f'stroke-dasharray="{dash}"/>')
        p.text(lx + 28, ly + 4, label, fill=INK)
        lx += 28 + 6.5 * len(label) + 32
    p.save("step-response.svg")


def main():
    controls, profiles, sends, power = csip_controls(), load_profiles(), load_sends(), load_power()
    overview(controls, profiles, sends, power)
    timing(controls, profiles, sends)
    step_response(controls, profiles, sends, power)


if __name__ == "__main__":
    main()
