# CitrineOS: full Plugfest demonstration plan

Status: staged development and acceptance target, not a declaration of live capability.
Scope agreed with Mark on 11 October 2026: demonstrate the complete proposed
CSIP-AUS-to-EV charging and V2G path using CitrineOS and move the existing EVerest
V2G simulator. Mark subsequently confirmed: use that simulator first and defer
physical chargers. Physical-device enrolment and multi-vendor testing are not
gates for this first simulator demonstration.
BSV and settlement are excluded.

## What “full” means

The target is the full demonstration described in the circulated Plugfest PDF:
network envelope, site coordination, scheduled charging and discharge, feedback,
fault handling and reproducible evidence. It does not mean every optional OCPP
feature, OCA certification, AS 5438 conformance, or production readiness.

The circulated PDF makes OCPP 2.1 bidirectional charging primary. The earlier
Markdown scope treated V2G as a stretch goal; use this acceptance plan to remove
that ambiguity without rewriting or recirculating the historical proposal.
The ODE/HAEO consultation remains a consultation, not a commitment by maintainers
to deliver the demonstration.

## Architecture

```text
Independent CSIP-AUS / SEP2 test server
                |
       Open Dynamic Export
   schedules + current limits + freshness
                |
   Home Assistant: site coordination
     |                   |
   HAEO optimiser        | secondary inverter path
     |                   +---- SunSpec Modbus test device
     |
   guarded schedule adapter
     | version-specific profile, session ID, validity, owner
   CitrineOS CSMS
     | OCPP 2.1
   existing EVerest V2G EVSE + simulated EV
     |
   measured power, import/export energy, transaction events
     +---- CitrineOS ---- Home Assistant ---- evidence recorder
```

CitrineOS replaces the OCPP central-system leg for the selected test devices,
not ODE, the SEP2 server, Home Assistant or HAEO. Home Assistant remains the
coordinating platform. Only one component may own active charging profiles;
the custom component's separate solar/load-control loop must not compete with HAEO.

CitrineOS exposes separate message and data interfaces, while its operator UI
uses Hasura for reads and REST for commands. These interfaces must remain distinct
in our HA adapter. [CitrineOS server architecture](https://github.com/citrineos/citrineos-core)

OCPP library support is not proof of complete end-to-end functionality:
EVerest describes its OCPP 2.1 work as ongoing, initially focused on smart charging
and bidirectional power transfer. Each capability below therefore needs evidence
from our pinned server, simulator, client and payloads. [EVerest libocpp](https://github.com/EVerest/libocpp)

## Current baseline and gaps

Read-only live check on 11 October 2026, approximately 09:48 AEST:

- CitrineOS server App 0.3.0 is started in isolated mode.
- The CitrineOS HA entry is loaded; no control-profile change was made.
- EVerest V2G App 0.1.2 is started, configured for 2.1 with an 11 kW rating,
  and still targets its existing HA OCPP central system.
- Its HA bridge reported `Unplugged`. That is not sufficient by itself to prove
  that both central systems have no outstanding transaction; check again before migration.
- No live command, credential change, rebind, publication, deployment or restart
  was performed during this preparation.

Earlier accepted baseline: the isolated CitrineOS/MicroOCPP test exercised
registration, approximately 11 kW charging, energy accumulation and transaction
closure under 2.0.1. That is a foundation, not evidence of the full V2G or
envelope path. [Dedicated simulator validation](https://github.com/purcell-lab/ha-addons/pull/14#issuecomment-6102037606)

The installed client was deliberately validated as read-only.
Enabling control requires client changes and matching server permissions,
not simply changing a boolean. [Read-only client validation](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/1#issuecomment-6102196159)

## Acceptance matrix

All rows are required for the proposed simulator demonstration unless marked
secondary, comparison or deferred. “Planned” means no complete CitrineOS
end-to-end proof is claimed. Simulator acceptance must be labelled as such;
it does not establish physical-device or multi-vendor interoperability.

| ID | Demonstration | Evidence required | Present status |
|---|---|---|---|
| P01 | Identity, security and protocol negotiation | Exact station identity, approved credential, observed `ocpp2.1`, accepted boot; wrong password and unknown identity refused | MicroOCPP 2.0.1 baseline only; V2G migration pending |
| P02 | Start and stop through HA | Operator action, dispatched OCPP ID, charger reply, `Started` / `Ended`, final idle and measured zero | New controlled HA profile pending |
| P03 | Multi-step charging and V2G | +6 kW, -5 kW, +3 kW, then zero, one exact transaction; power and both energy registers agree | Scoped 2.1 server policy staged; Citrine/EVerest integration proof pending |
| P04 | Current and scheduled envelopes | Independent test-feed `opModImpLimW`, `opModExpLimW`, `opModLoadLimW`, validity, source and freshness captured | Live feed and mappings to be checked |
| P05 | HAEO constrained plan | Solver input/output captures including EV, residual load, PV, storage and price; feasible plan within site limits | Citrine schedule adapter pending |
| P06 | Import, export and load clips | Tighten each limit separately; show which constraint binds and measured response; restore safely | Planned |
| P07 | Material schedule update | Correlated replacement `TxProfile`, exact active transaction, correct precedence, old schedule no longer governing | Planned |
| P08 | Zero, suspend and resume | Explicit zero power, no unintended direction change, then deliberate resume under current limits | Planned |
| P09 | Failure and stale-data handling | Separate loss of CSIP feed, planner, HA, CSMS and EVSE link; verify local safe state and recovery | Not implemented/accepted |
| P10 | Telemetry and closure | Fresh signed power; separate monotonic import/export Wh; timestamps, complete transaction and zero after stop | HA telemetry work pending; inherited final-power-sample issue remains |
| P11 | Charging-only fallback | Explicit separate 2.0.1 run with positive limits; negative/setpoint-only 2.1 intent rejected before dispatch | Baseline charging exists; deliberate fallback test pending |
| P12 | Secondary SunSpec path | Real SunSpec model discovery and constrained setpoint/readback on an isolated test target | Target and permission not yet identified |
| P13 | Charger-vendor interoperability (deferred) | Later repeat core matrix against independent approved charger-side implementations; record unsupported features | Explicitly deferred by Mark; not a simulator-demo gate |
| P14 | Dashboard and evidence bundle | Envelope, requested plan, accepted profile, actual power, energy, state, timing and raw sanitised JSON | Planned |
| P15 | Soak and restart recovery | Repeat schedule updates and an agreed long-duration run; no stale session/profile reuse or unsafe default rebound | Planned after bounded tests |
| P16 | Optional 1.6 comparison | Charging-only version-specific profile on a separate test route; no V2G claim | Not part of this first controlled Citrine path |

Native OCPP 2.1 DER/grid-support modes, certificate lifecycle, Plug & Charge
contract provisioning, reservations, firmware updates, OCPI and billing are not
silently included. They require separate scenarios if selected. ISO 15118-20
DC_BPT evidence inside the simulator must not be relabelled as successful
end-to-end Plug & Charge.

## Metering and envelope rules

Use one published convention: EV power is positive while importing energy into
the EV and negative while exporting energy from it. Preserve raw measurands and
their units alongside the normalised value. Unknown or stale values are not zero.

Keep the energy counters separate. Do not derive net energy first and then
attempt to reconstruct the direction-specific totals. Record whether a value
comes from the EVSE meter, its OCPP payload, the CSMS database or an HA calculation.

Site import/export limits constrain the point of connection, not merely the EV.
With site-import-positive power, the test oracle must check:

```text
P_site = P_other_load + P_EV + P_battery_charge - P_generation
-site_export_limit <= P_site <= site_import_limit
```

The treatment of `opModLoadLimW` needs an explicit, verified mapping to the
applicable controllable-load aggregation. Do not subtract “house residual” from
it by assumption. Clamp EV capability and site headroom consistently; if no
feasible plan exists, declare the constraint conflict and enter the selected
safe state rather than silently violating a limit.

For V2G, use a version-valid 2.1 schedule with `CentralSetpoint`, a positive import
ceiling, a negative discharge floor, and a signed `setpoint` in every period.
A positive charging `limit` alone is a ceiling, not proof that the EV will track
an exact requested power. Do not forward a 1.6 payload unchanged to 2.x or
convert W to A without the measured/declared phase and voltage basis.

## Bounded first test

Only the existing `SIM-EV-EVEREST-V2G-01` simulator is eligible in the staged
command policy. Its server policy caps import and export at 11,000 W, each
profile at 600 seconds and 10 periods. These are test bounds, not a claim that
the longer Plugfest horizon is already implemented.

Proposed first measurement sequence, after readiness and local fail-safe gates:

| Relative time | Requested power | Observe |
|---|---:|---|
| 0–60 s | +6,000 W | Stable charging and import energy |
| 60–120 s | -5,000 W | Stable discharge and export energy |
| 120–180 s | +3,000 W | Safe direction reversal back to charging |
| 180–240 s | 0 W | Verified zero before stop |
| After 240 s | Stop transaction | `Ended`, zero, idle; then clear exact test profile |

Resolve and bind the actual transaction ID after `Started`. For a profile sent
after the transaction starts, use an explicit future absolute start time or
account correctly for transaction-relative schedule offsets. Do not assume
a Relative profile begins when the HTTP request arrives.

Never clear a profile during discharge as a shortcut to stopping. The staged
gateway permits profile cleanup only after no active transaction is evidenced.
Finite profile duration is not itself a watchdog: expiration can restore a
nonzero default. A tested local fallback and a bounded operator stop path are
required before the trial is activated.

Proposed simulator acceptance tolerance: stable-window mean power within the
greater of 3% or 50 W; integrated power versus energy-register increments within
the greater of 10% or 5 Wh. Agree hardware tolerances separately. Sample arrival,
settling time and meter location must be explicit rather than hidden by averaging.

## Latency, safety and evidence

Record these events separately:

1. CSIP event published, effective and received.
2. ODE current/schedule publication.
3. HAEO solve started and completed.
4. Adapter generated and dispatched the profile.
5. CitrineOS accepted the API request for dispatch.
6. EVSE replied `Accepted` or rejected the OCPP call.
7. Measured power reached the required band.
8. Transaction ended and measured power returned to zero.

An HTTP success is not a charger acknowledgement. A charger acknowledgement
is not proof of power tracking. On a timeout after dispatch, record outcome
unknown and reconcile by message/session ID; do not automatically resend or
change protocol, units or profile purpose until something accepts it.

The circulated proposal's 5-second read/write, 30-second limit response and
15-second communication-loss targets are demonstration targets to investigate,
not verified limits or a statement of current standards compliance. Test the
failure location independently: HA cannot send a stop through a disconnected
CSMS-to-EVSE link. Local behaviour must be configured and measured.

Evidence bundle: pinned commits and image digests, test configuration without
credentials, capability/device inventory, raw input envelope, solver inputs and
outputs, generated/received profiles, correlated OCPP request/reply IDs, metered
power and energy, event timing, pass/fail thresholds, failures and rollback result.
No Basic Auth values, JWTs, private keys or sensitive customer identifiers.

## Coordinated implementation sequence

### C1: isolated server and simulator admission

Current staged changes: separate read/command credentials; optional existing-V2G
admission; explicit 2.1 start/stop and bounded signed TxProfiles; exact station,
tenant, observed protocol and transaction checks; no real-device enrolment;
optional provisioned simulator credential with original-password preservation.
Controls remain disabled by default.

Before merging: test the actual authenticated gateway and upstream schema routes,
reader-write rejection, incorrect station/tenant, protocol downgrade, stale and
foreign transaction, unknown dispatch result and unchanged MicroOCPP baseline.
Publish the new simulator image only with separate approval and verify both
architecture manifests before installing it.

### C2: HA manual control, telemetry and event correlation

Add a separate explicit controlled API profile. Preserve read-only mode and
reader credentials. Expose only permitted controls for each enrolled station.
Remove optimistic capability inference, misleading placeholder telemetry and
silent mutating-request fallbacks in this new profile.

Provide start/stop, a signed power request, validated schedule submission and
exact-profile cleanup, with command status separate from observed device state.
Add fresh power and import/export energy sensors. Keep the inherited automatic
site controller disabled until HAEO ownership and safety policy are configured.
Do not present destructive/security/firmware operations as generic “full control”.

### C3: site envelope and HAEO schedule bridge

Implement unit/sign/capability mapping, timestamp validation, stale-input policy,
material-change detection, profile ownership, correct transaction binding and
bounded horizon updates. Cover all three envelope clips and infeasible cases.
Replace the initial 600-second test guard with a separately reviewed horizon
policy only after expiry, supersession and fallback are proven.

### C4: fault handling, demo dashboard and evidence

Implement independent local safe-state behaviour; test input staleness,
disconnection, restart and recovery. Show requested versus accepted versus
measured power, without a false “success” badge. Produce the downloadable
evidence bundle and a deterministic 30-minute demonstration script.

### C5: secondary protocol and deferred physical devices

Keep the secondary SunSpec test as a separate workstream. Physical charger
enrolment and independent-device repetition are explicitly deferred and must
not delay C1–C4 or cause an additional simulator instance to be created.

When Mark reopens physical testing, enroll each charger-side device using its
exact identity, protocol, transport security, capability and approved power
envelope before repeating the core tests.
The private App-only listener is not yet a real-device LAN endpoint. Do not
publish it externally or remove authentication to make hardware connect.

## Migration and release gates

- Recheck that the existing simulator and its old CSMS have no active transaction.
- Preserve the old endpoint, options, generated credential and recorded state.
- Stop the simulator once; perform its explicit archive-and-rebind workflow.
  Do not delete historical state or replay old transactions to the new CSMS.
- Provision a separate test credential in both ends without displaying it.
- Verify `ocpp2.1` negotiation, accepted boot and idle readings before enabling commands.
- Keep all physical charger connections and unrelated simulator instances unchanged.
- Obtain approval for the exact PRs, image publication, App updates/restarts and
  any Core restart. Migration selection is not permission to issue physical V2G commands.
- A failed security, identity, local fallback, telemetry or closure gate is a
  deployment blocker, not a warning.

No physical-device information is needed to continue the simulator work.
When physical testing resumes, request make/model, station ID, supported
protocol, network reachability/security, and permitted charging/discharging
power and energy bounds. Do not request credentials in chat.

## Demonstration script

| Segment | Content |
|---|---|
| 0–5 min | Architecture, exact software/protocol versions, station capabilities and baseline |
| 5–12 min | Start, multi-step charge/discharge, measured power and separate energy counters |
| 12–20 min | Network import/export/load clips, HAEO replanning, profile replacement and recovery |
| 20–25 min | Loss-of-input / communication test, observed safe state, controlled recovery |
| 25–30 min | Stop/closure, available secondary-protocol evidence, simulator limitations and evidence export |

Prepare the long-duration soak evidence before claiming that coverage in the
live walk-through. Multi-vendor hardware evidence is deferred. A short simulator
demo must not be presented as proof of a 24-hour run or physical interoperability.
