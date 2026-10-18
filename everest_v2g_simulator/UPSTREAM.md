# Upstream sources and licences

This App repackages binaries from the EVerest project. It does not modify
EVerest source code. All EVerest components are Apache-2.0 licensed.

## Pinned inputs

| Input | Pin |
|---|---|
| EVerest demo manager image | `ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase@sha256:9165d0937323ae61ee2e496f68f3c4a465ed9099740e489df1f0161265492756` (multi-arch index) |
| everest-demo repository | [EVerest/everest-demo](https://github.com/EVerest/everest-demo) at `686e370d6ed6460211b06e34a4cdf9438a22e81e` (`TAG=2025.10.0-single-phase`) |
| everest-core | 2025.10.0, commit `c86cd9c0ada60b5797f574fd484eae4d8330017d` (built inside the demo image) |
| libocpp | v0.30.3, commit `1c6fb7c5fd92b4651648bcf3a6c8f32b58b935dc` (everest-core `dependencies.yaml`) |
| everest-framework | v0.24.0, commit `059e95ca6cdd23f318259a87480c0b1f48d0cf72` |
| libiso15118 | v0.9.0, commit `a792d07039475375faf56813ce46f52728032d80` |
| Josev (PyEvJosev EV simulator) | As vendored in the demo image under `libexec/everest/3rd_party/josev` |
| Josev Python dependencies | Hash-pinned wheels in `requirements-josev.txt` (installed with `--require-hashes --only-binary`) |
| Runtime base | `debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587` (same Debian 12 ABI as the demo build) |

Up to 0.1.10 this table gave `a68f6735…` as the libocpp
commit and `23a1414…` as the everest-framework commit. Those are the demo
build's CPM cache directory keys (`/ext/cache/cpm/libocpp/a68f6735…`, as in
everest-demo's `enable_ocpp_logging.patch`), not git commits. The versions
above are the tags pinned by everest-core 2025.10.0.

The getting-started guide this App follows is
[EVerest: Get started with software](https://everest.github.io/latest/how-to-guides/getting-started/get-started-sw.html).
The module set follows upstream's `config-sil-dc-d20.yaml` (ISO 15118-20 DC)
combined with the OCPP 2.0.1/2.1 wiring of `config-sil-ocpp201.yaml`.

## What is copied

Only `/ext/dist` runtime content from the demo image: `bin/manager`, shared
libraries, the module directories listed in the Dockerfile `MODULES`
argument, `share/everest` and the vendored Josev tree. **No certificates or
keys are copied**; each install generates its own test PKI. Binaries are
stripped. The upstream admin-panel `controller` is replaced by a stub.

## Upstream configuration needed for V2G

- PyEvJosev `supported_d20_energy_services: "DC_BPT,DC"`. Josev selects the
  first listed service; the default order selects plain DC and the session
  then reports that export is not supported.
- A vehicle certificate is required for the TLS 1.3 session. The demo
  image's cached certificates lack it, hence the generated PKI.
- `ChargePointModel` must stay within 20 characters; a longer value aborts
  the OCPP201 module at start.
- EnergyManager `switch_3ph1ph_while_charging_mode: Both` with a 1 s
  hysteresis, and a per-phase grid allowance that carries the full rating on
  one phase. The simulated board reports a 6 A three-phase AC minimum
  (4.14 kW). Without the one-phase fallback, EnergyManager enforces 0 W for
  any charging target below it, even on this DC EVSE.
- OCPP energy sink on EVSE 1 only (see DOCS, station-level limits).

## Local patches

`patch_josev.py` runs at image build and edits four files; `patch_yeti.py`
patches one binary.

Josev `iso15118/evcc/controller/simulator.py` (2025.9.0, bundled with
EVerest 2025.10.0): the simulated EV's ISO 15118-20 BPT discharge limits are
hard-coded at 25 A and 11 kW in charge parameter discovery and the dynamic
DC loop. With the DC supply at its 200 V default minimum, discharge stopped
at 5 kW. The patch sets 66 A and 25 kW (25 kW at the App's 380 V).

Josev `iso15118/evcc/states/iso15118_20_states.py` (2025.9.0): the EV
gives up 60 s after the first Ongoing AuthorizationRes, and PyEvJosev
allows one SDP retry cycle, so the EV starts no new session in that
plug-in. A RequestStartTransaction about 60 s after plug-in then left the
transaction at 0 W. The charger (libiso15118 v0.9.0) answers Ongoing for
3 minutes (`TIMEOUT_EIM_ONGOING`); the patch makes the EV wait 190 s, so
the charger decides. Only the Authorization state used the shared ongoing
timeout; the patch requires exactly those two uses.

`YetiSimulator` binary (everest-core 2025.10.0, prebuilt): the simulated
board reports 32 A import and 16 A export per phase, which EvseManager uses
for DC too, capping the charger at 22.08 kW charging and 11.04 kW
discharging. Configuration can only lower these. `patch_yeti.py` raises both
to 128 A: a three-float `.rodata` block on amd64, two `movi` instructions on
arm64 (an `fmov` immediate cannot exceed 31.0). It accepts only the exact
SHA-256 and original bytes of each architecture's binary, and the image
checks run it with `--check`. The App's per-phase setting (up to 109 A for
25 kW) is the limit that applies.

Josev `iso15118/evcc/transport/udp_client.py`: upstream computes the
interface index but leaves `IPV6_MULTICAST_IF` commented out, so the EV's
SDP request to `FF02::1` leaves by the kernel's first multicast route. That
is the private link only when no other interface exists. The patch sets
the option, so requests always leave by `v2g1`.


`PyEvJosev/module.py` from everest-core 2025.10.0. Upstream runs one Josev
EVCC per plug-in with `asyncio.run()`. After `SDPFailedError` Josev logs
the error and keeps waiting, so `asyncio.run()` never returns and no later
plug-in starts an EV stack; other errors end the loop, which catches only
KeyboardInterrupt. The patch runs each EVCC on its own event loop, lets
`start_charging` (a new plug-in) cancel a stack that is still running,
logs every stop, publishes `v2g_session_finished` and clears the plug-in
event before each run. The build fails if either upstream anchor changes,
and the image checks assert the marker.

## Upstream behaviours to report

Candidate upstream issues, with reproduction in `tests/acceptance.py` and
VALIDATION.md:

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
9. Josev's UDP client does not set `IPV6_MULTICAST_IF`, so SDP leaves by
   the first multicast route instead of the configured interface (Local
   patches).
7. libiso15118 v0.9.0 `TbdController` creates a session for each answered
   SDP request and ignores all later requests until it ends. A session
   whose peer never connects never ends, so one stray SDP request blocks
   discovery until the module restarts.
8. The same controller never ends a session whose EV left before session
   end (for example unplugged while waiting for authorisation): with the
   connection closed, `Session::poll` returns before handling any event.
   Discovery is then ignored until the App restarts. The App reports it.
10. Josev waits only 60 s for authorisation, the charger 3 minutes, and
    PyEvJosev hard-codes one SDP retry cycle, so a session that ends before
    charging leaves EvManager waiting with the plug-in refused (Local
    patches; the App's EV watchdog re-plugs).
11. OCPP201 applies every composite from libocpp's
    `get_all_composite_schedules`, which always includes EVSE 0, and warns
    each interval when EVSE 0 has no energy sink. There is no option to
    skip EVSE 0 (see item 3 for why it has no sink here).
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

## Licences

The image carries `/usr/share/doc/everest/EVerest-LICENSE` and the
licence/notice files of every CPM-fetched dependency under
`/usr/share/doc/everest/third_party/`. Josev is Apache-2.0. Debian packages
carry their own copyright files under `/usr/share/doc/`. The Java runtime
under `/opt/java` is a jlink image of Debian's OpenJDK 17 (GPLv2 with the
Classpath Exception); its module legal notices are in `/opt/java/legal/`
and Debian's copyright file is `/usr/share/doc/openjdk-17/copyright`.
