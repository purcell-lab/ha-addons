# CitrineOS and EVerest: implementation, build and test handover

Prepared 11 October 2026, Australia/Brisbane. This brief covers the coordinated
Home Assistant Apps and CitrineOS HA-client work, including the older open
MicroOCPP and comparison PRs. Mark authorised merging the open PRs; that is
source consolidation, not permission to publish images, update Apps, restart HA,
rebind the simulator or activate controls.

## Executive decision

**Source may be consolidated; the new controlled CitrineOS-to-EVerest path is
NO-GO for live activation.** The native test demonstrates registration,
charging, discharge, both energy registers and explicit stop/closure, but a
0 W profile leaves the simulated EV charging at 3,000 W. The native acceptance
test remains red; it has not been skipped, weakened or converted to an expected
pass. [Native evidence](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637)

Two later runs tracked discharge correctly after an earlier -5,000 W request
produced -1,111.11 W. Its cause remains unresolved; passing repeats do not
establish reliability. Profile expiry and communication-loss safe states are
also unproven. [Earlier failure](https://github.com/purcell-lab/ha-addons/actions/runs/38101004161)
[Repeat](https://github.com/purcell-lab/ha-addons/actions/runs/38101772800)

The intended first deployment target is the existing EVerest V2G simulator.
Physical chargers, multi-vendor hardware testing and BSV settlement are excluded
from this tranche. The full demonstration still requires the CSIP-AUS/ODE and
HAEO schedule bridge, fault handling and evidence dashboard.
[Acceptance scope](https://github.com/purcell-lab/ha-addons/pull/18)

## Repository and PR inventory

“All PRs” in this handover means the six open PRs discovered in the two
repositories below, not unrelated BSV or other project repositories. The PR
links are the authoritative merge records; older PR descriptions may retain
historical “staged” or “do not merge” wording.

| Repository / PR | Purpose | Important qualification |
|---|---|---|
| [ha-addons #4](https://github.com/purcell-lab/ha-addons/pull/4) | MicroOCPP final zero-power samples and cumulative-energy investigation | Fixes simulator sampling, not HA's sticky energy-classification heuristic |
| [ha-addons #13](https://github.com/purcell-lab/ha-addons/pull/13) | Exact CitrineOS release-versus-next component comparison | No production pin change; green means comparison completed |
| [ha-addons #15](https://github.com/purcell-lab/ha-addons/pull/15) | Live HA OCPP/EVerest TxProfile evidence | Different CSMS path from the CitrineOS native trial |
| [ha-addons #17](https://github.com/purcell-lab/ha-addons/pull/17) | Shared EVerest runtime and reduced PR build work | File equivalence is not behavioural or V2G safety equivalence |
| [ha-addons #18](https://github.com/purcell-lab/ha-addons/pull/18) | Guarded CitrineOS controls, admission, telemetry and native tests | Known failed zero-power acceptance; no live activation |
| [CitrineOS-HA-Integration #2](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2) | HA manual controls, schedules and telemetry | Existing read-only entries remain read-only |

### Source, published images and installed state are different

The runtime work already published EVerest V2G **0.1.3**. The new optional
CitrineOS credential and export-measurand changes originally reused that version;
this handover reserves **0.1.4, unreleased**, to avoid suggesting the published
0.1.3 image contains different functional code.
[Published V2G 0.1.3](https://github.com/purcell-lab/ha-addons/actions/runs/38101003167)
[Functional changes](https://github.com/purcell-lab/ha-addons/pull/18)

The Citrine server App source is 0.4.0 and HA-client source is 0.3.0. These
versions do not identify the OCPP protocol: the server is pinned to upstream
CitrineOS v2.0.1 while this selected simulator path negotiates OCPP 2.1.
[Server changes](https://github.com/purcell-lab/ha-addons/pull/18)
[Client changes](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2)

No fresh HA inventory or live control test was performed for this merge/handover.
The parallel runtime handover records AC 0.1.1 and V2G 0.1.3 installed on
branch-tracking App repositories; treat those as recorded observations, not a
new live verification by this brief. Its historical statement that #17 was
already merged conflicted with GitHub's initially open PR state, so use the
actual GitHub merge record rather than that sentence.
[Runtime workstream](https://github.com/purcell-lab/ha-addons/pull/17)

## Architecture and ownership

```text
Independent CSIP-AUS/SEP2 test feed
    → Open Dynamic Export
    → Home Assistant site coordination + HAEO
    → guarded schedule adapter [not yet implemented for this full path]
    → CitrineOS protected gateway
        → native command API → broker → OCPP 2.1
        → existing EVerest V2G EVSE + simulated EV
    ← transaction events, signed power and import/export energy
    ← CitrineOS database → read-only Hasura → HA client
```

HA is the coordinating EMS; CitrineOS is the CSMS, not the optimiser or a
replacement for ODE. There must be one owner of active charging schedules.
The client's inherited load/solar controller and MQTT intent publisher remain
disabled in the scoped manual-control profile.
[Design and implementation](https://github.com/purcell-lab/ha-addons/pull/18)
[Client ownership guards](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2)

### Components and security boundary

| Component | Responsibility / boundary |
|---|---|
| `citrineos_database` | Dedicated PostgreSQL/PostGIS and `/data/pgdata`; never a household/shared production database |
| `citrineos_broker` | Dedicated RabbitMQ, persistent `/data/mnesia`; management plugin disabled |
| `citrineos_hasura` | Explicit read-only `ha_reader` role and tenant-filtered columns |
| `citrineos_server` | Pinned server, migrations, protected gateway and optional simulator admission |
| `everest_v2g_simulator` | Private simulated EV/EVSE link, SLAC, ISO 15118-20 DC_BPT, meter and OCPP client |
| `custom_components/citrine_ha` | Reader discovery plus separate opt-in command credential; HA entities and schedule service |

These boundaries are implemented in the
[App PR](https://github.com/purcell-lab/ha-addons/pull/18) and
[HA-client PR](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2).
Supervisor's shared container network is not a dedicated network firewall.
Security Profile 1 is cleartext Basic authentication confined to that trusted
network; it is not TLS and must not be exposed to the LAN or internet.
[App security documentation](https://github.com/purcell-lab/ha-addons/pull/18)

### Scoped command contract

- **Station:** `SIM-EV-EVEREST-V2G-01`, tenant 1, EVSE 1, observed `ocpp2.1`.
- **Routes:** RequestStartTransaction, RequestStopTransaction,
  SetChargingProfile and exact-profile ClearChargingProfile only.
- **Bounds:** ±11,000 W, at most ten periods and 600 seconds, explicit
  CentralSetpoint and discharge/import bounds.
- **Binding:** freshly observed active transaction; no numeric/string-ID,
  protocol, units or profile-purpose fallback.
- **Cleanup:** clear exact profile only after no active transaction remains.
- **Credentials:** distinct reader and command values; Hasura never receives
  user-selected admin privileges.

The exact allowlist is in `citrineos_server/rootfs/control-policy.mjs`; client
validation is in `custom_components/citrine_ha/lab_control.py`.
[App contract](https://github.com/purcell-lab/ha-addons/pull/18)
[Client contract](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2)

## HA control surface

The new profile is `v2_scoped_lab_control`. Existing `v2_hasura_read_only`
entries stay read-only; installing source does not opt an entry into commands.
[HA-client PR](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2)

- **Buttons:** Start charging, Stop transaction, Apply requested power,
  Request zero power, Clear test profile after closure.
- **Number:** requested signed power, -11,000 to +11,000 W; changing it stages
  a value and does not issue a command.
- **Service:** `citrine_ha.lab_schedule`, selected by entry ID, resolves the
  actual transaction and submits bounded periods.
- **Sensors:** signed power, imported/exported meter registers, transaction
  ID, observed protocol, connector state and command-dispatch state.

These are implemented controls, not proof of live HA entity acceptance.
The Request zero power button must not be treated as a safe stop with the
current runtime. Explicit stop closes the transaction; that is not equivalent
to holding an active session at zero.
[Client PR](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2)
[Zero versus stop evidence](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637)

Power becomes unknown after 45 seconds without a fresh meter frame, never
fabricated zero. Energy readings are cumulative registers, not session deltas.
Dispatch, station acceptance and measured response are separate evidence states;
an HTTP success remains `dispatched_awaiting_station_evidence`.
[Telemetry semantics](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2)

## Reproducible build process

### Prerequisites and pins

Use a disposable Linux Docker runner, sufficient disk for initial image pulls,
Git, Node 24 and Python 3.14 for HA-client tests. The development sandbox used
for this work had no Docker executable; actual native containers ran in GitHub
Actions, not in the user's HA installation.
[Client CI](https://github.com/purcell-lab/CitrineOS-HA-Integration/actions/runs/38100890975)
[Native CI](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637)

| Item | Reviewed pin |
|---|---|
| CitrineOS release source | `1a83638c31eebdb1dd8d6cdb0f5b8a9f142a1372` |
| CitrineOS release image | `ghcr.io/citrineos/citrineos-server:v2.0.1@sha256:15316dff5f661714e2fddfa2f25baebea4c11d8d6aa2a9bb254a98159da58378` |
| Comparison-only next source | `19ef2b452f8dc1e5bcd97cd3c1aac072c821f588` |
| EVerest runtime | `ghcr.io/purcell-lab/everest-runtime:2025.10.0-1@sha256:ad99f273e062f09c58fa030cd938df1d612ccbe04b65d1201864b4a72a8e455f` |
| Last fully observed native client source | `67174d9920fa39f7b23f934f743a19cf42fe879c` |
| Last fully observed native App source, before consolidation | `ee3a56020d3e5f507656b14ed8b3f7eb8260db7c` |

Pins come from the [comparison PR](https://github.com/purcell-lab/ha-addons/pull/13),
[runtime PR](https://github.com/purcell-lab/ha-addons/pull/17) and
[native test](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637).
After consolidation, record the new main SHA separately; old test results do
not automatically certify every new merge combination.

### Shared EVerest runtime

The one-time runtime build extracts installed binaries, libraries, module
resources, Josev and licences from the digest-pinned upstream demo image.
App builds copy only their selected modules from the much smaller runtime.
Normal builds should not repeatedly pull the upstream build toolchain image.
[Runtime design](https://github.com/purcell-lab/ha-addons/pull/17)

`everest_runtime/Dockerfile` and `VERSION` govern runtime rebuilding.
`.github/scripts/everest_runtime.sh` resolves the pinned public runtime, or
requests a local runtime build when the runtime source changed or is unavailable.
The identical-file tool compares types, modes, owners and content/link targets
against `everest_runtime/REFERENCE`, with documented Python-bytecode equivalence
handling. A file-equivalence pass is not an interoperability pass.
[Runtime build and verification](https://github.com/purcell-lab/ha-addons/pull/17)

Consolidated EVerest CI targets amd64, matching the recorded HA host.
Previously published runtime/App releases include aarch64, but that historical
publication does not establish ongoing aarch64 support for new changes.
[Architecture change](https://github.com/purcell-lab/ha-addons/pull/17)

### Build without publication

From the Apps repository, in a disposable Docker environment:

```sh
for app in database broker hasura server simulator; do
  docker build -t "citrine-${app}:test" "citrineos_${app}"
done

version=$(sed -n 's/^version: "\(.*\)"$/\1/p' everest_v2g_simulator/config.yaml)
docker build --build-arg BUILD_ARCH=amd64 \
  --build-arg BUILD_VERSION="$version" \
  -t citrine-v2g:test everest_v2g_simulator

# Required directory name for Dockerfile.client:
git clone https://github.com/purcell-lab/CitrineOS-HA-Integration.git citrine-client
git -C citrine-client checkout 67174d9920fa39f7b23f934f743a19cf42fe879c
docker build -f citrineos_server/tests/Dockerfile.client \
  -t citrine-client:test .
```

This mirrors the [native workflow](https://github.com/purcell-lab/ha-addons/pull/18).
Do not run multiple stack harnesses concurrently on one Docker host: they use
fixed `lab-*` container names and the `citrine-ci` network.

### Publication is a separate operation

Release workflows are tag-triggered, check immutable versions and publish with
provenance. Runtime tags are `everest_runtime-v<VERSION>`; V2G tags are
`everest_v2g_simulator-v<version>`; AC tags are
`everest_simulator-v<version>`.
[Release process](https://github.com/purcell-lab/ha-addons/pull/17)

Do not push those tags as part of this handover. Never overwrite published
0.1.3. New V2G 0.1.4 source requires a separately approved publication, passing
release checks and verified anonymous image pull before installation.
Its `published-image` check should fail while the image does not exist; that
failure must remain visible, not be disabled to make the merge look green.

## Testing process

### Fast changed-area checks

Apps repository:

```sh
python -m unittest discover -s citrineos_server/tests -p test_packaging.py -v
python -m unittest discover -s citrineos_server/tests -p test_v2g_readiness.py -v
node --test citrineos_server/tests/*.test.mjs
python -m unittest discover -s citrineos_simulator/tests -v
python -m unittest discover -s everest_v2g_simulator/tests -v
python -m unittest discover -s microocpp_simulator/tests -v
python -m unittest discover -s citrineos_comparison -p test_harness.py -v
git diff --check
```

Real nginx, openssl and PyYAML are needed for the complete focused environment.
A local skip is not a CI pass. The workflows define the authoritative dependency
setup. [Apps CI and tests](https://github.com/purcell-lab/ha-addons/pull/18)
[MicroOCPP checks](https://github.com/purcell-lab/ha-addons/pull/4)

HA-client repository, Python 3.14 virtual environment:

```sh
python -m pip install homeassistant==2026.10.0 pytest==8.4.2 \
  pytest-asyncio==1.2.0 graphql-core==3.2.6

# Point to actual checked-out source, not credentials or HA endpoints.
export CITRINE_SERVER_SOURCE=/path/to/pinned/citrineos-core
export CITRINE_APP_SOURCE=/path/to/ha-addons
python -m pytest tests -q --ignore=tests/test_allocator.py
python -m compileall -q custom_components
git -c core.whitespace=cr-at-eol diff --check
```

The three pre-existing allocator failures are compared against the exact upstream
baseline in `.github/workflows/compatibility.yml`; they are not claimed to pass.
Missing source environment variables can skip cross-repository checks, so verify
the test summary rather than relying only on exit code.
[Client workflow](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2)

### Container and integration checks

```sh
# Dedicated MicroOCPP/Citrine baseline: auth, discovery, persistence,
# logical restore, 2.0.1 registration, power, energy and closure.
TEST_NATIVE_SIMULATOR=1 python3 citrineos_server/tests/stack_smoke.py

# Actual HA API client → CitrineOS → EVerest, in disposable containers.
# This is expected to remain red until the known zero-power defect is fixed.
TEST_V2G_SIMULATOR=1 python3 citrineos_server/tests/stack_smoke.py

# App packaging and runtime acceptance: minimum viable PR path.
CHECKS=minimal sh everest_v2g_simulator/tests/ci_image_checks.sh citrine-v2g:test

# Full release gate: do not substitute the minimal path for a release.
CHECKS=full sh everest_v2g_simulator/tests/ci_image_checks.sh citrine-v2g:test
```

The native harness creates an internal Docker network, generates disposable
credentials, verifies negative authorization controls, then runs the bounded
schedule and cleanup. Credentials travel via private files/stdin and are
redacted from evidence; no live HA secrets are used.
[Native harness](https://github.com/purcell-lab/ha-addons/pull/18)

The V2G container requires NET_ADMIN solely for its private virtual EV/EVSE link
and namespace firewall. Do not give it host networking, the Docker socket or
physical charger access to make a test pass.
[Simulator isolation](https://github.com/purcell-lab/ha-addons/pull/17)

### Evidence levels

| Level | What it proves | What it does not prove |
|---|---|---|
| Unit / contract tests | Validators, entity fixtures, timing format, telemetry parsing | Live HA registration or real station execution |
| Pinned component comparison | Route/schema/query compatibility at exact revisions | Full CSMS startup or deployment readiness |
| Private-stack CI | Auth, migrations, persistence and logical database restore | Full Supervisor disaster recovery |
| Native V2G test | Actual API client, actual CSMS, actual simulator runtime | Installed HA Core entity operation, physical EV behaviour or certification |
| Live HA test | The specific installed versions and route tested | Another CSMS path, future builds or all optional protocol functions |

These distinctions are deliberate in the [comparison](https://github.com/purcell-lab/ha-addons/pull/13),
[client](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2) and
[native integration](https://github.com/purcell-lab/ha-addons/pull/18) work.

## Test record and measured results

| Evidence | Result / interpretation |
|---|---|
| [Client run 38100890975](https://github.com/purcell-lab/CitrineOS-HA-Integration/actions/runs/38100890975) | 73 focused/controller-regression tests passed; allocator baseline tracked separately |
| [Private stack 38102326634](https://github.com/purcell-lab/ha-addons/actions/runs/38102326634) | Passed |
| [Native run 38101004161](https://github.com/purcell-lab/ha-addons/actions/runs/38101004161) | Accepted profile; discharge mean -1,111.11 W against -5,000 W |
| [Native repeat 38101772800](https://github.com/purcell-lab/ha-addons/actions/runs/38101772800) | +6/-5/+3 kW passed; zero failed; export register absent from client |
| [Native final 38102326637](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637) | Both energy registers corrected; explicit stop/closure passed; overall failed on zero |
| [App image run 38102326657](https://github.com/purcell-lab/ha-addons/actions/runs/38102326657) | Earlier two-architecture packaging/runtime checks passed; not a zero-power acceptance pass |
| [Pinned comparison 38054245248](https://github.com/purcell-lab/ha-addons/actions/runs/38054245248) | Completed; next does not restore legacy HA `/data` compatibility |

Final native test transaction: `a3792d1d-5565-4aec-9116-ca214e95fc45`.
Each period lasted 30 seconds, with stable-window tolerance the greater of
3% or 50 W. [Final native evidence](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637)

| Request | Measured mean | Result |
|---|---:|---|
| +6,000 W | +6,000 W | Pass |
| -5,000 W | -5,000 W | Pass |
| +3,000 W | +3,000 W | Pass |
| 0 W | +3,000 W | **Fail** |

All measurements in this table are from the
[final native run](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637).
The profile was accepted and its effective composite requested zero; power did
not follow it. Explicit RequestStopTransaction subsequently produced zero and
closed the exact transaction.
[Acceptance and closure evidence](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637)

| Measurement | Value |
|---|---:|
| Start dispatch → measured charging | 17.447 s |
| Profile dispatch → EVSE Accepted | 0.132 s |
| Stop dispatch → observed closure and zero | 2.712 s |
| Schedule-window imported energy | 103.29 Wh metered / 106.66 Wh integrated |
| Schedule-window exported energy | 40.59 Wh metered / 39.19 Wh integrated |
| Final cumulative import/export registers | 0.160667 / 0.040586 kWh |

These are application-level observations from one isolated run, including
polling, not latency guarantees. Energy-window increments and final cumulative
registers have different meanings.
[Timestamp and meter evidence](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637)

### Defects corrected during this work

- **Timestamp mismatch:** emit milliseconds rather than Python's default
  microseconds; test the actual gateway validator across repositories.
- **Startup readiness:** wait for an explicitly passed discovery self-test;
  idle state alone is insufficient, and a null self-test means pending.
- **Missing export energy:** request both registers and signed power in
  Started, Updated and Ended lists, preserving other configured measurands.
- **Evidence loss:** retain raw samples/effective limits and record tracking
  failures while proceeding to bounded stop/closure checks.

These corrections are in [client #2](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2)
and [App #18](https://github.com/purcell-lab/ha-addons/pull/18).

## Open defects and next implementation sequence

| Priority | Item | Acceptance before activation |
|---|---|---|
| P0 | Zero-power profile leaves charging at previous power | Measured zero in an active session, no silent conversion into session termination |
| P0 | Expiry and communication-loss local safety unproven | Independently interrupt planner, HA, CSMS and EVSE link; measure safe state and recovery |
| P1 | Intermittent discharge and transition overshoot | Repeated bounded reversal runs with voltage/current, limits and meter timing; explain failures |
| P1 | Live HA controls not installed/validated | Fresh inventory, protected rollback, exact simulator binding, entity/button/service tests |
| P1 | CSIP-AUS/ODE/HAEO adapter incomplete | Import/export/load clips, timestamps, stale inputs, ownership, feasible plan and replacement semantics |
| P2 | HA OCPP energy classification | Separate fix/test for zero-start cumulative register heuristic; do not confuse with native Citrine telemetry |
| P2 | First-event delay on HA OCPP path | Correlate unanswered security/certificate messages and queue delays; not established as a Citrine failure |
| P2 | Receipt of profile-clear response | Observe charger response separately from the existing HTTP dispatch acknowledgement |

The first three items follow the [native evidence](https://github.com/purcell-lab/ha-addons/actions/runs/38102326637);
energy classification is documented in [MicroOCPP #4](https://github.com/purcell-lab/ha-addons/pull/4),
and HA OCPP delay/transients are recorded in the [runtime handover](https://github.com/purcell-lab/ha-addons/pull/17).
Do not fix a simulator defect by loosening the power tolerance or hiding red CI.

Recommended sequence: reproduce/fix the runtime zero and reversal behaviour;
prove local fallback; validate the installed HA profile; implement the envelope
and HAEO adapter; then build the demo dashboard and deterministic evidence bundle.
Physical chargers remain a later, separately approved stage.

## Deployment and rollback runbook

This section is preparation, not an instruction to execute deployment now.
Use the established HA remote-management runbook and discovered MCP operations;
never guess endpoints or print webhook URLs, credentials or private keys.
[Canonical HA runbook](https://github.com/purcell-lab/ha-config/blob/main/docs/skills/ha-remote-management-runbook.md)

Before deployment:

1. Resolve all P0 gates and rerun the native trial on exact intended release pins.
2. Verify a published, immutable 0.1.4-or-later image and matching source/manifest.
3. Read live App slugs, versions, repository branches, options and HA entry state.
4. Confirm the existing simulator and both CSMS records have no active transaction.
5. Preserve the old endpoint, identity, generated credential, options and data.
6. Obtain approval for the exact publication/install/rebind/restart operations.
7. Create and verify a fresh protected backup; logical CI restore is not proof
   of full Supervisor restore.

Migration, once separately approved:

1. Keep command controls off and client read-only.
2. Stop the existing simulator; use its explicit archive-and-rebind workflow.
3. Provision the distinct test credential at both ends without exposing it.
4. Repoint only the approved simulator, never the physical central system.
5. Start dependencies before the server, then the simulator.
6. Verify identity, negotiated 2.1, accepted boot, idle state and fresh telemetry.
7. Enable the explicit manual-control profile only after the safety gates pass.
8. Run a bounded trial with measured stop, transaction closure and preserved logs.

Rollback means disabling commands and restoring the preserved simulator binding
and compatible component/App versions, not deleting the database or credentials.
Stop stack components in order server, Hasura, broker, database; start
dependencies before server. Reconcile active transaction records before retrying
an uncertain command, and never clear a live discharge profile as a stop shortcut.
[App procedures](https://github.com/purcell-lab/ha-addons/pull/18)
[Client procedures](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/2)

## Evidence and handover checklist

- Record exact source commits, image digests, architecture, config version and
  whether the environment is unit fixture, CI container or installed HA.
- Preserve raw received profile, station reply, effective schedule, meter trace,
  both energy counters, transaction events and timing.
- Keep the sanitized native JSON `v2g-integration-evidence.json` from the workflow.
- Check all open PRs in the two scoped repositories after consolidation.
- Keep native acceptance failure and unpublished-image status visible.
- Do not equate merged source, built image, published release and activated system.
- Do not claim OCA certification, AS 5438 compliance, Plug & Charge or physical
  interoperability from these simulator tests.

The authoritative evidence links and limitations are retained above so a new
maintainer can resume without guessing the last successful or failed step.
