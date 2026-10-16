"""Render TxProfile response charts (SVG, standard library only).

Each data/*.json record holds the profile the CSMS sent (seconds from
profile start, watts; null marks the end), the charging station's own
power samples ("cs") and the power the CSMS recorded from MeterValues
("csms"), as local HH:MM:SS[.fff] times. CSMS values and "events" station
series are held until the next change; "samples" station series are point
reads and are drawn as markers only. Run from this folder:

    python3 make_charts.py
"""
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 760, 380
L, R, T, B = 70, 20, 50, 60  # plot margins


def seconds(t, start):
    clock = datetime.strptime(t.split(".")[0], "%H:%M:%S")
    frac = float("0." + t.split(".")[1]) if "." in t else 0.0
    moment = start.replace(hour=clock.hour, minute=clock.minute, second=clock.second, microsecond=0)
    return (moment - start).total_seconds() + frac


def step_points(points, until):
    """Hold each sample until the next one (a sample-and-hold trace)."""
    out = []
    for i, (x, y) in enumerate(points):
        nxt = points[i + 1][0] if i + 1 < len(points) else until
        out += [(x, y), (nxt, y)]
    return out


def chart(record, title, path):
    start = datetime.fromisoformat(record["profile_start"])
    sent = record["sent"]
    end = sent[-1][0]
    cs = [(seconds(t, start), w) for t, w in record["cs"]]
    csms = [(seconds(t, start), w) for t, w in record["csms"]]
    x0 = min([0] + [x for x, _ in cs + csms]) - 5
    x1 = max([end] + [x for x, _ in cs + csms]) + 10
    ys = [w for _, w in sent if w is not None] + [w for _, w in cs + csms]
    y0 = min(0, min(ys)) - 1000
    y1 = max(ys) + 1000

    def px(x):
        return L + (x - x0) / (x1 - x0) * (W - L - R)

    def py(y):
        return T + (y1 - y) / (y1 - y0) * (H - T - B)

    def poly(points, cls):
        d = " ".join(f"{px(x):.1f},{py(y):.1f}" for x, y in points)
        return f'<polyline class="{cls}" points="{d}"/>'

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
           'font-family="system-ui,sans-serif" font-size="12">',
           '<style>.grid{stroke:#ddd}.axis{stroke:#555}.sent{fill:none;stroke:#1f6feb;stroke-width:2.5;'
           'stroke-dasharray:7 4}.cs{fill:none;stroke:#2da44e;stroke-width:2}.csms{fill:none;stroke:#cf222e;'
           'stroke-width:2}.dot-cs{fill:#2da44e}.dot-csms{fill:#cf222e}text{fill:#24292f}</style>',
           '<rect width="100%" height="100%" fill="#fff"/>',
           f'<text x="{W / 2}" y="22" text-anchor="middle" font-size="15" font-weight="600">{title}</text>']
    step = 2000 if y1 - y0 < 20000 else 4000
    y = (int(y0) // step) * step
    while y <= y1:
        if y >= y0:
            svg.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{py(y):.1f}" y2="{py(y):.1f}"/>')
            svg.append(f'<text x="{L - 6}" y="{py(y) + 4:.1f}" text-anchor="end">{y / 1000:g}</text>')
        y += step
    xt = 0
    while xt <= x1:
        if xt >= x0:
            svg.append(f'<line class="grid" x1="{px(xt):.1f}" x2="{px(xt):.1f}" y1="{T}" y2="{H - B}"/>')
            svg.append(f'<text x="{px(xt):.1f}" y="{H - B + 16}" text-anchor="middle">{xt}</text>')
        xt += 30
    svg.append(f'<line class="axis" x1="{L}" x2="{W - R}" y1="{py(0):.1f}" y2="{py(0):.1f}"/>')
    svg.append(f'<text x="{(L + W - R) / 2}" y="{H - 22}" text-anchor="middle">seconds from profile start '
               f'({start:%Y-%m-%d %H:%M:%S} AEST)</text>')
    svg.append(f'<text transform="translate(18 {(T + H - B) / 2}) rotate(-90)" text-anchor="middle">'
               'power kW (negative = discharge)</text>')
    sent_pts = [(x, w) for x, w in sent if w is not None]
    svg.append(poly(step_points(sent_pts, end), "sent"))
    if record.get("cs_mode") == "events":
        svg.append(poly(step_points(cs, x1), "cs"))
    svg.append(poly(step_points(csms, x1), "csms"))
    for x, w in cs:
        svg.append(f'<circle class="dot-cs" cx="{px(x):.1f}" cy="{py(w):.1f}" r="3.5"/>')
    for x, w in csms:
        svg.append(f'<circle class="dot-csms" cx="{px(x):.1f}" cy="{py(w):.1f}" r="3.5"/>')
    legend = [("sent", "TxProfile sent by CSMS"), ("cs", "CS measured (station)" if record.get("cs_mode") == "events"
               else "CS measured (point samples)"),
              ("csms", "CSMS recorded (MeterValues)")]
    for i, (cls, label) in enumerate(legend):
        lx = L + 10 + i * 220
        svg.append(f'<line class="{cls}" x1="{lx}" x2="{lx + 28}" y1="38" y2="38"/>')
        svg.append(f'<text x="{lx + 34}" y="42">{label}</text>')
    svg.append("</svg>")
    path.write_text("\n".join(svg) + "\n")


CHARTS = [
    ("v2g.json", "V2G DC BPT: SIM-EV-EVEREST-V2G-03 via CitrineOS 8083 (SP1)", "v2g-txprofile.svg"),
    ("ac.json", "AC: SIM-EV-EVEREST-G1 via CitrineOS 8082", "ac-txprofile.svg"),
    ("microocpp16.json", "OCPP 1.6: SIM-16-MICROOCPP-01 via HA OCPP central", "microocpp16-txprofile.svg"),
]

if __name__ == "__main__":
    (HERE / "charts").mkdir(exist_ok=True)
    for data, title, out in CHARTS:
        chart(json.loads((HERE / "data" / data).read_text()), title, HERE / "charts" / out)
        print("wrote charts/" + out)
