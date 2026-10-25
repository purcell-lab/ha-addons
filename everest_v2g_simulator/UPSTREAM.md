# Upstream sources and licences

This App packages binaries built from the EVerest project's source. It does
not modify EVerest source code; the build-time patches below edit installed
Python files of the simulated EV. All EVerest components are Apache-2.0
licensed. The App adds one EVerest module of its own, `HaGridSupport`
(below), which is App code, not part of EVerest.

## Pinned inputs

From 0.2.0 (EVerest 2026.10.0-rc1, compiled from source):

| Input | Pin |
|---|---|
| everest-core | [EVerest/everest-core](https://github.com/EVerest/everest-core) tag `2026.10.0-rc1`, commit `f45ba0d0827f29d53d516fec98960f2528460802` (2026-10-22), checked by the build. A release candidate. libocpp (OCPP 1.6/2.0.1/2.1 with DER control), everest-framework, libiso15118 and the other EVerest libraries are in this tree. |
| Build image | `ghcr.io/everest/everest-ci/build-kit-base:v1.6.0@sha256:ca9da7d85c09295cbbfb75167b28eb2f17488a1e4dbca12892f3f848e9bf2f2f` (multi-arch index; the everest-ci ref everest-core's CI uses, `ref_everest_ci: v1.6.0`). Debian 12, GCC 12, Boost 1.74. |
| Build | `everest_runtime_source/Dockerfile`: CMake Release, `EVEREST_INCLUDE_MODULES` = `everest_runtime_source/MODULES`, tests, applications, run scripts, Rust and JavaScript off, then `install/strip`. CPM fetches the third-party dependencies at the versions in everest-core's `dependencies.yaml`. |
| Runtime image | `ghcr.io/purcell-lab/everest-runtime:2026.10.0-rc1-1`, extracted by `everest_runtime/Dockerfile` (unchanged), index `sha256:49a1d5acf22b5368d2d92dac4d5818bb0d6266f4dfcc49817aac4b137f32efa7` (published 2026-10-25 by [run 40174763359](https://github.com/purcell-lab/ha-addons/actions/runs/40174763359) from `4086cdf`, tag `everest_runtime_source-v2026.10.0-rc1-1`). Pinned by digest in the App Dockerfile. |
| Josev (PyEvJosev EV simulator) | [EVerest/ext-switchev-iso15118](https://github.com/EVerest/ext-switchev-iso15118) at `1b3ea741ea7954bbe4288742446f33653ecb7849` (everest-core `dependencies.yaml`), installed under `libexec/everest/3rd_party/josev` |
| Josev Python dependencies | Hash-pinned wheels in `requirements-josev.txt` (installed with `--require-hashes --only-binary`) |
| Runtime base | `debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587` (same Debian 12 ABI as the build image) |

Up to 0.1.13 the runtime was an extract of the everest-demo manager image
`ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase@sha256:9165d0937323ae61ee2e496f68f3c4a465ed9099740e489df1f0161265492756`
([EVerest/everest-demo](https://github.com/EVerest/everest-demo) at
`686e370d6ed6460211b06e34a4cdf9438a22e81e`): everest-core 2025.10.0
(`c86cd9c0ada60b5797f574fd484eae4d8330017d`), libocpp v0.30.3
(`1c6fb7c5fd92b4651648bcf3a6c8f32b58b935dc`), everest-framework v0.24.0
(`059e95ca6cdd23f318259a87480c0b1f48d0cf72`), libiso15118 v0.9.0
(`a792d07039475375faf56813ce46f52728032d80`) and the Josev vendored there
(2025.9.0). Up to 0.1.10 this file gave `a68f6735…` and `23a1414…` as the
libocpp and everest-framework commits; those were the demo build's CPM
cache directory keys, not git commits.

The getting-started guide this App follows is
[EVerest: Get started with software](https://everest.github.io/latest/how-to-guides/getting-started/get-started-sw.html).
The module set follows upstream's `config-sil-dc-d20.yaml` (ISO 15118-20 DC)
combined with the OCPPmulti wiring of `config-sil-ocpp-multi.yaml`.

## What is copied

Only the installed tree (`/ext/dist`): `bin/manager`, the shared libraries
the shipped binaries load, the module directories listed in the Dockerfile
`MODULES` argument, `share/everest` (libocpp's component configs and
database migrations are under `share/everest/modules/OCPP201`, which
OCPPmulti reads) and the Josev tree. **No certificates or keys are
copied**; each install generates its own test PKI. Binaries are stripped.
EVerest 2026.10's manager no longer starts the admin-panel `controller`
(0.1.x replaced it with a stub).

## App module: HaGridSupport

`rootfs/opt/everest/libexec/everest/modules/HaGridSupport` (Python, using
EVerest's everestpy) provides the `grid_support` interface on EVSE 1.
OCPPmulti enables its DER device-model component and libocpp accepts a DER
control only for types a `grid_support` provider declares in a capability.
Evse15118D20 provides `grid_support` but declares no capability ("This
module does not publish DER capability"), and no other EVerest module
provides it. HaGridSupport declares a DC capability (all 22 OCPP 2.1 types,
the rating as nameplate), writes each active directive set to
`/run/ha-everest/der.json` for the Status page, forwards the set to
Evse15118D20's `grid_support` (its `relay`) and passes that module's alarms
on. It applies nothing to power.

## Upstream configuration needed for V2G

- PyEvJosev `supported_d20_energy_services: "DC_BPT,DC"`. Josev selects the
  first listed service; the default order selects plain DC and the session
  then reports that export is not supported.
- A vehicle certificate is required for the TLS 1.3 session. The demo
  image's cached certificates lacked it, hence the generated PKI (the
  from-source build installs no certificates at all).
- `ChargePointModel` must stay within 20 characters; a longer value aborted
  the OCPP201 module at start (2025.10.0; kept for OCPPmulti).
- EnergyManager `switch_3ph1ph_while_charging_mode: Both` with a 1 s
  hysteresis, and a per-phase grid allowance that carries the full rating on
  one phase. The simulated board reports a 6 A three-phase AC minimum
  (4.14 kW). Without the one-phase fallback, EnergyManager enforces 0 W for
  any charging target below it, even on this DC EVSE.
- YetiSimulator `caps_max_current_A` = the per-phase allowance (up to
  109 A for 25 kW). The board reports 32 A import and 16 A export per phase
  by default, and EvseManager uses the board's capabilities as the EVSE's
  own limit for DC too (EvseManager 2026.10 has no `max_current_import_A`
  or `max_current_export_A`), which capped the charger at 22.08 kW charging
  and 11.04 kW discharging. Up to 0.1.13 the 2025.10.0 binary had no such
  option and `patch_yeti.py` raised both limits to 128 A in the binary.
- OCPPmulti `Mode: Only2`; the offered versions come from InternalCtrlr
  `SupportedOcppVersions`. libocpp 2026.10 has no InternalCtrlr
  `ChargePointId` (SecurityCtrlr `Identity` is the identity) and imports the
  `NetworkConnectionProfiles` list into the `NetworkConfiguration_1`
  component at boot.
- OCPPmulti `grid_support` connected to HaGridSupport (EVSE 1 mapping);
  `GridSupportHeartbeatS: 60`.
- OCPP energy sink on EVSE 1 only (see DOCS, station-level limits).

## Local patches

`patch_josev.py` runs at image build, edits three installed Python files of
the simulated EV and checks a fourth. The build fails if an upstream anchor
changes, and the image checks assert each marker.

`PyEvJosev/module.py` (everest-core 2026.10.0-rc1). Upstream runs one Josev
EVCC per plug-in with `asyncio.run()` (it now clears the plug-in event
before each run and shares one EXI codec). After `SDPFailedError` Josev
logs the error and keeps waiting, so `asyncio.run()` never returns and no
later plug-in starts an EV stack; other errors end the loop, which catches
only KeyboardInterrupt. The patch runs each EVCC on its own event loop
(with upstream's shared codec), lets `start_charging` (a new plug-in)
cancel a stack that is still running, logs every stop and publishes
`v2g_session_finished`.

Josev `iso15118/evcc/controller/simulator.py` (2025.9.0, unchanged at
`1b3ea741` in this respect): the simulated EV's ISO 15118-20 BPT discharge
limits are hard-coded at 25 A and 11 kW in charge parameter discovery and
the dynamic DC loop (the new EvManager discharge settings reach only DIN
SPEC 70121 and ISO 15118-2). With the DC supply at its 200 V default
minimum, discharge stopped at 5 kW. The patch sets 66 A and 25 kW (25 kW at
the App's 380 V).

Josev `iso15118/evcc/states/iso15118_20_states.py`: the EV gives up 60 s
after the first Ongoing AuthorizationRes, and PyEvJosev allows one SDP
retry cycle, so the EV starts no new session in that plug-in. The patch
makes the EV wait 190 s, so the charger always decides: Evse15118D20
(2026.10) fails an EIM wait after 55 s (V2G_SECC_Ongoing_Performance_Time,
[V2G20-2102]); libiso15118 v0.9.0 (up to 0.1.13) after 3 minutes. Only the
Authorization state uses the shared ongoing timeout; the patch requires
exactly those two uses.

Josev `iso15118/evcc/transport/udp_client.py`: patched up to 0.1.13 to set
`IPV6_MULTICAST_IF`, so SDP to `FF02::1` leaves by the configured interface
(`v2g1`) and not the kernel's first multicast route (eth0 on HA OS). Josev
`1b3ea741` sets it upstream; the build now only checks that line.

## Upstream behaviours to report

Candidate upstream issues, with reproduction in `tests/acceptance.py` and
VALIDATION.md. Items 1 to 14 were found on EVerest 2025.10.0 (0.1.x);
except where an item says otherwise they have not been re-checked on
2026.10.0-rc1 (the release gate's acceptance scenarios cover 1, 2, 6, 7, 8,
10 and 12 again):

1. `Market::resample` (EnergyManager) only considers periods with a
   setpoint, so setpoints leak into neighbouring periods without one.
2. In ISO 15118-20 Dynamic mode, EvseManager returns early when the
   minimum charge power exceeds the maximum (for example a 0 W limit), so
   the EV keeps its previous target.
3. The EVSE 0 composite schedule's `limit` is an L1 share when
   `limit_L2`/`limit_L3` are present, but the OCPP201 module applies it as
   the total.
4. EnergyManager applies the board's AC minimum current to a DC EVSE.
5. libocpp aborts on a GetCertificateStatus reply without `status`.
6. PyEvJosev never starts a new EV stack after a failed discovery
   (Local patches).
9. Josev's UDP client did not set `IPV6_MULTICAST_IF`, so SDP left by
   the first multicast route instead of the configured interface. **Fixed
   upstream** (Josev `1b3ea741`, EVerest 2026.10.0-rc1).
7. libiso15118 v0.9.0 `TbdController` creates a session for each answered
   SDP request and ignores all later requests until it ends. A session
   whose peer never connects never ends, so one stray SDP request blocks
   discovery until the module restarts.
8. The same controller never ends a session whose EV left before session
   end (for example unplugged while waiting for authorisation): with the
   connection closed, `Session::poll` returns before handling any event.
   Discovery is then ignored until the App restarts. The App reports it.
10. PyEvJosev hard-codes one SDP retry cycle, so a session that ends
    before charging (Josev waits 60 s for authorisation; the charger 55 s
    from 2026.10, 3 minutes before) leaves EvManager waiting with the
    plug-in refused (Local patches; the App's EV watchdog re-plugs).
11. OCPP201 applies every composite from libocpp's
    `get_all_composite_schedules`, which always includes EVSE 0, and warns
    each interval when EVSE 0 has no energy sink. There is no option to
    skip EVSE 0 (see item 3 for why it has no sink here). OCPPmulti
    (2026.10) warns once at start instead.
12. EvseManager has two writers of the DC supply target in the ISO 15118-20
    dynamic loop: on new limits, `enforce_limits` re-applies the previous
    target (`apply_new_target_voltage_current`), while the loop handler
    applies the new one from another thread, both through
    `powersupply_DC_set` (on a reversal, two `Set mode` lines 0.3 ms
    apart). When the stale write lands last nothing corrects it: the handler
    sees its target unchanged, and `enforce_limits` acts again only when the
    limits, target voltage or measured voltage (over 1 V) change. Charging
    runs at the EV's maximum voltage (EvManager default 900 V) and
    discharging at the supply minimum (380 V). With the EV maximum at 380 V
    a +6 kW to -5 kW reversal stayed at -6 kW; at 382 V the reversals
    tracked but an 11 kW to 6 kW step stayed at 11 kW. So charging stays at
    900 V, which passes the same trials, and purcell-lab/ha-addons#70 cannot
    be fixed by configuration.
13. OCPP201 2025.10.0 builds the EVSE component in its own device model
    storage: EVSE `Power` has no `MaxSet` attribute, and its `maxLimit` is
    the board's capabilities (`max_current_A_import x 230 V x
    max_phase_count_import`, as published by the board, before EvseManager's
    `max_current_import_A`), not the configured rating. That component
    shadows any EVSE file in `component_config` (the composed storage merges
    the EVEREST storage first). `update_hw_capabilities` notes "TODO: update
    EVSE.Power maxLimit value". The App reports its rating on
    `ChargingStation` `Power` instead (DOCS, Power rating). In 2026.10 the
    EverestDeviceModelStorage (ocpp_module_common, used by OCPPmulti) still
    sets only `maxLimit`, from the board's capabilities.
14. ISO 15118-20 charging needs: EVerest sends NotifyEVChargingNeeds with
    `v2xChargingParameters` only. CitrineOS v2.0.1 rejects them (it handles
    only AC/DC parameters, and its ChargingNeeds table has no V2X column),
    and libocpp stops an OCPP 2.1 transaction whose -20 needs are rejected.
    The App therefore leaves OCPP201 `extensions_15118` unconnected (DOCS,
    EV charging needs). Needed upstream: CitrineOS support for
    `v2xChargingParameters`/`DC_BPT` (store them, answer Accepted or
    NoChargingProfile without sending its own profile).
15. OCPP 2.1 DER control on a DC EVSE (2026.10.0-rc1): OCPPmulti creates
    `DCDERCtrlr` for an EVSE with a `grid_support` connection, but
    `ModesSupported` stays empty until a provider publishes a capability,
    and libocpp then answers every SetDERControl `NotSupported`. No
    EVerest module publishes one (Evse15118D20 provides `grid_support`
    without a capability and relays only curve directives, only to AC DER
    sessions). So upstream wiring alone gives no usable DER control on a DC
    station; the App declares a capability itself (HaGridSupport above).
    Needed upstream: a capability source for DC (for example from the DC
    power supply or EvseManager's BPT settings) and a DC path for the
    directives.
16. V2X operation modes (2026.10.0-rc1): EverestDeviceModelStorage builds
    each EVSE's `V2XChargingCtrlr` `SupportedOperationModes` as
    `ChargingOnly,Idle` ("TODO: Update dynamically operation mode"), even on
    a DC_BPT EVSE, and libocpp then rejects every OCPP 2.1 profile period
    with `operationMode` `CentralSetpoint` (Q09.FR.01,
    `ChargingSchedulePeriodOperationModeNotInSupportedList`).
    `update_supported_operation_modes` exists but nothing calls it.
    HaGridSupport writes the list through OCPPmulti's `set_variables`
    (DOCS, DER control is unaffected).

## Licences

The image carries `/usr/share/doc/everest/EVerest-LICENSE` and the
licence/notice files of every CPM-fetched dependency under
`/usr/share/doc/everest/third_party/`. Josev is Apache-2.0. Debian packages
carry their own copyright files under `/usr/share/doc/`. The Java runtime
under `/opt/java` is a jlink image of Debian's OpenJDK 17 (GPLv2 with the
Classpath Exception); its module legal notices are in `/opt/java/legal/`
and Debian's copyright file is `/usr/share/doc/openjdk-17/copyright`.
