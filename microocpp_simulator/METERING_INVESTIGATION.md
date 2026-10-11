# Post-stop power and cumulative-energy investigation

10 October 2026. Version 0.1.2 live observations; 0.1.3 proposed correction.
Scope: isolated MicroOCPP simulator and Home Assistant OCPP integration.
No live controls, deployments, sensor overrides or integration edits were
performed during this investigation.

## Post-stop power: simulator sample ordering

The simulator calls `mocpp_loop()` before `Evse::loop()`. OCPP can end a
transaction and take its final sample inside `mocpp_loop()`, while cached
simulated power still contains the previous charging value. The subsequent
simulator loop clears power locally, too late for the final event.

The live test ended at 13:43:12 AEST with Available status, an empty
transaction ID, and final session energy 0.330 kWh. HA retained
11.00600977 kW and 15 A through the repeated 13:43:59 check.

The installed HA `ocppv201.py` only supplies zero for a non-energy measurand
missing from the final `Transaction.End` samples. Since the simulator
explicitly sent nonzero power/current, HA retained them. A heartbeat does
not replace those meter values.

**Correction in 0.1.3:** refresh the meter model whenever a protocol or HTTP
meter getter is sampled. Re-evaluate OCPP charge permission, both plug flags,
both readiness flags and the existing power threshold. Integrate the preceding
powered interval before zeroing power; preserve energy. No fake HA state,
extra transaction, background sender or change to the upstream OCPP core
is introduced.

The regression first reproduced the old nonzero final sample, then passed
unplug, local tag withdrawal and CSMS RequestStopTransaction cases with zero
final power/current/voltage. Readiness pause/resume, stable energy while stopped,
positive energy while charging, and an untouched second connector are covered.

## Stale cumulative energy: HA classification heuristic

The simulator sends `Energy.Active.Import.Register` in its transaction
samples. It is a process-lifetime cumulative register: it carries across
transactions but resets when the simulator process restarts.

The installed HA `chargepoint.py` contains:

```python
if self._metrics[(connector_id, csess.meter_start)].value == 0:
    self._charger_reports_session_energy = True

skip_eair = (
    is_eair
    and self._charger_reports_session_energy
    and is_transaction
)
```

A fresh simulator starts at zero. HA consequently classifies its register
as direct session energy and skips updating the cumulative metric from
transaction samples. The initial zero remains while Energy Session updates.
This is not a Wh/kWh conversion error or an absent measurand.

The flag is initialised False and the inspected implementation only assigns
True thereafter; it is charge-point-wide, not per EVSE. A later session can
therefore also be interpreted as direct session energy despite a nonzero
starting register. This risks overstated later session energy, not merely a
stale display.

Native multi-session regression demonstrates the distinction: one run ended
at 31 Wh, then 37 Wh, then 43 Wh; later starts retained the earlier register.
These are cumulative values, not three independent session amounts. Exact
readings vary slightly with runtime scheduling.

## Recommended separate integration correction

- Do not infer session-only energy solely from a legitimate zero start.
- Represent energy semantics per EVSE/connector: cumulative, session-only or
  not yet established. Prefer an explicit documented configuration or
  evidence-backed device capability over a sticky global heuristic.
- For cumulative mode, publish the register and compute each session from
  its own start/end difference. Preserve session-only device compatibility.
- Test consecutive sessions, a zero initial register, restart reset,
  multi-EVSE mixed behaviour, and stale/offline/out-of-order events.
- Treat a simulator restart as a meter reset, not a lifetime revenue-meter
  continuity guarantee.

Do not work around this by seeding a fabricated nonzero register, summing
already cumulative readings, overriding HA states, or silently forcing all
chargers into cumulative mode.

This PR documents the cumulative-energy cause but does not change HA's
integration or fix that sensor. A separate integration PR and live acceptance
are required. The simulator post-stop correction can be reviewed independently.

## Evidence provenance

Upstream simulator pin: `2cb07cdbe53954a694a29336ab31eac2d2b48673`, plus the
App's exact-context adaptations. Relevant source: `src/main.cpp`,
`src/evse.cpp`, and MicroOCPP `Model/Transactions/TransactionService.cpp`.

The installed HA integration files were reread through the approved read-only
file tool on 10 October rather than trusting older local copies:

| Installed file | SHA-256 | Relevant lines |
|---|---|---|
| `custom_components/ocpp/chargepoint.py` | `4cb66aa66646ec757916f21971f1e751089eb37f58b91b1f9b23632fda465270` | 1698–1700, 1769–1777; initialisation at 410 |
| `custom_components/ocpp/ocppv201.py` | `8813406a1d41d6a95ac4924f846e6b0435b0de052f74aceea53ebd2542924ff0` | 1617–1619, 1625 onwards |

Older saved copies did not match these hashes. The quoted live logic was
verified directly; no private endpoint, token or wallet data is included.
