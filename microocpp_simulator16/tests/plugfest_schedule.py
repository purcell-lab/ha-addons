"""Synthetic charging-only adaptation of the Plugfest brief, not HAEO/CSIP.

Seven five-minute windows are accelerated to four seconds for native CI.
Inputs/outputs use W; this is not the brief's OCPP 2.1/A/V2G payload.
"""

WINDOWS = (
    ("normal charging", 11000, 13000, 2000, 11000),
    ("import-limit clip", 11000, 9000, 2000, 7000),
    ("import-limit restored", 11000, 13000, 2000, 11000),
    ("household-load clip", 11000, 13000, 10000, 3000),
    ("no import headroom", 11000, 13000, 13000, 0),
    ("household-load restored", 11000, 13000, 2000, 11000),
    ("scheduled pause", 0, 13000, 2000, 0),
)


def schedule(period_seconds=300, windows=WINDOWS):
    """Test fixture only: EV headroom = site import cap minus other load."""
    if not isinstance(period_seconds, int) or period_seconds <= 0:
        raise ValueError("period_seconds must be a positive integer")
    periods = []
    for i, (_, desired, site_cap, other_load, expected) in enumerate(windows):
        if min(desired, site_cap, other_load, expected) < 0:
            raise ValueError("charging-only fixture: V2G/negative values unsupported")
        limit = min(desired, max(0, site_cap - other_load), 11000)
        if limit != expected:
            raise ValueError("fixture expectation differs from available EV headroom")
        periods.append({"startPeriod": i * period_seconds, "limit": limit})
    return {"chargingRateUnit": "W", "duration": len(windows) * period_seconds,
            "chargingSchedulePeriod": periods}


def expected_wh(periods, start, end, duration):
    """Exact piecewise-constant integral over a bounded schedule interval."""
    if not 0 <= start <= end <= duration:
        raise ValueError("energy interval outside the schedule")
    return sum(
        p["limit"] * max(0, min(end, periods[i + 1]["startPeriod"]
                               if i + 1 < len(periods) else duration)
                         - max(start, p["startPeriod"])) / 3600
        for i, p in enumerate(periods)
    )
