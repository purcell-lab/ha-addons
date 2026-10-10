# OCPP 1.6 smart-charging validation

Prepared 10 October 2026. This is a separate, staged App; it has not been
installed or connected to live Home Assistant.

## Local acceptance

The pinned native simulator connects only to a loopback mock CSMS using
`ocpp1.6` and `SIM-16-MICROOCPP-01`. The test authorises one connector 1
transaction and uses real OCPP requests and responses, not direct assignment
of the simulator's power limits.

| Check | Tested behaviour |
|---|---|
| Protocol and identity | 1.6 BootNotification, correct test identity, CSMS identity mutation rejected |
| Capability advertisement | SmartCharging and Power units reported |
| Unsupported units | Ampere profile not accepted by this power-only callback |
| TxDefaultProfile | Initial 4,200 W limit applied |
| TxProfile | Six scheduled periods applied within the same transaction |
| Zero-power period | No StopTransaction; energy holds steady; next period resumes |
| MeterValues | On-wire samples contain each requested power plateau, including zero |
| ChargePointMaxProfile | 5,000 W station ceiling constrains a 7,000 W TxProfile |
| GetCompositeSchedule | Effective schedule reflects the station ceiling |
| ClearChargingProfile | Falls back to default, then factory limit after clearing |
| validTo expiry | Temporary cap expires without another control command |
| Stop | StopTransaction with preserved energy and zero final power/current |
| Connector 2 | Idle with zero energy |
| Restart disconnected | No fallback connection; power zero |

Example native readings from the stepped TxProfile:

| Limit | Measured power | Register |
|---:|---:|---:|
| 4,200 W | 4,190 W | 2 Wh |
| 7,000 W | 6,993 W | 8 Wh |
| 11,000 W | 10,997 W | 17 Wh |
| 4,200 W | 4,197 W | 27 Wh |
| 0 W | 0 W | 30 Wh |
| 7,000 W | 7,000 W | 32 Wh |

Small differences below the cap are the simulator's intentional variation.
Exact Wh depends on scheduling. The native regression uses four-second
periods and one-second metering; runtime defaults remain ten-second metering.

The expiry test initially failed: the pinned evaluator did not schedule a
recalculation for `validTo` when a final period had no next boundary.
A small downstream correction adds that boundary and treats it as expired.
This is documented in UPSTREAM.md rather than attributed to unmodified upstream.

Fifteen focused option/persistence/Ingress/fixture tests cover disconnected default,
safe namespace, explicit isolation acknowledgement, URL restrictions, state
retention, no silent endpoint rebinding and the actual nginx peer ACL.
The existing 2.0.1 App directory and workflow are unchanged.

## Plugfest-style schedule acceptance

Based on the charging-only concepts in *Open-source CSIP-AUS to OCPP
demonstration*, 30 July 2026: import-limit clipping, household-load clipping
and restoration. This is a **synthetic 35-minute representative window**, not
the briefing's full 24-hour plan or a transcription of its OCPP 2.1 ampere/V2G
example. Every row represents five minutes; native CI accelerates each to
four seconds (75x), retaining watt limits and scaling expected energy.

| Phase | Desired EV W | Site import cap W | Other household load W | Expected EV W |
|---|---:|---:|---:|---:|
| Normal charging | 11,000 | 13,000 | 2,000 | 11,000 |
| Import-limit clip | 11,000 | 9,000 | 2,000 | 7,000 |
| Import-limit restored | 11,000 | 13,000 | 2,000 | 11,000 |
| Household-load clip | 11,000 | 13,000 | 10,000 | 3,000 |
| No import headroom | 11,000 | 13,000 | 13,000 | 0 |
| Household-load restored | 11,000 | 13,000 | 2,000 | 11,000 |
| Scheduled pause | 0 | 13,000 | 2,000 | 0 |

The fixture uses `min(desired, max(0, site_cap - other_load), 11000)`.
This deliberately simple **test-side calculation is not an HAEO optimiser,
CSIP-AUS client, or production envelope translator**. Negative/V2G inputs and
inconsistent expected headroom are rejected by fixture tests. There is no
ampere conversion or electrical-topology equivalence claim.

The existing native harness sends exactly **one** connector-1 Absolute
TxProfile with the current integer transaction ID. It then:

- Checks each HTTP power plateau within 12 W below its ceiling, never above.
- Requires a matching OCPP MeterValues sample **inside that period's timestamp
  window**, with connector, transaction, W and Wh units verified. A matching
  reading from an earlier phase cannot satisfy the check.
- Checks unchanged transaction ID, no StopTransaction during pauses, steady
  paused energy, monotonic on-wire energy and idle connector 2.
- Integrates the schedule between the first/last included meter timestamps
  and compares that integral with the register delta.
- Counts profile sends, proving the charger executes transitions without
  per-period SetChargingProfile commands.
- Clears the profile before the existing unplug/final-zero acceptance checks.

Local native run on 10 October: measured **44 Wh**, expected **44.102 Wh**
over offsets 1.203–25.803 seconds. Whole-schedule energy is 3,583.333 Wh at
normal speed, or 47.778 Wh accelerated; the measured interval excludes the
unsampled beginning/end, so those whole-schedule values are not its comparator.
Energy tolerance is `2 Wh + 11000 W × 1 s / 3600 + 12 W × elapsed / 3600`,
about 5.14 Wh: integer register rounding, a one-second timing allowance, and
bounded power variation. This is a simulator regression tolerance, not a
meter-accuracy or billing certification. CI prints its own actual observations.

No live HA readings, ODE/SEP2 ingestion, HAEO optimisation, schedule-change
deduplication, 24-hour endurance, OCPP 2.1, or V2G acceptance is claimed.
The one-profile send count does **not** test a production five-minute
reoptimisation loop or its “material change” resend policy.

## Reproduce

```sh
python3 -m unittest discover -s microocpp_simulator16/tests -v
docker build --build-arg BUILD_ARCH=amd64 --build-arg BUILD_VERSION=0.1.0 \
  -t microocpp16:test microocpp_simulator16
docker build -t microocpp16:smoke -f microocpp_simulator16/tests/Dockerfile.smoke .
docker run --rm --network none microocpp16:smoke
```

CI executes the native image and smoke tests on both amd64 and aarch64.
It does not publish an image, modify HA or connect to an external CSMS.
For a prepared local source build, run
`python3 microocpp_simulator16/tests/smart_charging.py /path/to/native/tree`.
Only the test environment needs the Python `websockets` package.

## Outstanding live acceptance

- Approve merge and disconnected App installation separately.
- Verify the App's authenticated Ingress UI and 1.6 labels.
- Establish an isolated HA OCPP 1.6 test entry and unique device identity.
- Compare the same bounded TxProfile against simulator and HA meter readings.
- Confirm pause retains the transaction and final stop clears HA power.
- Track HA's known cumulative-versus-session-energy classification separately.

Recurring schedules, multi-connector load allocation, sustained offline
operation, profile persistence across a restart, and full conformance are
not claimed as validated. Neither V2G nor 2.0.1 smart charging is provided.
