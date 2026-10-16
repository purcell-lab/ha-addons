# Upstream sources and licences

This App repackages binaries from the EVerest project. It does not modify
EVerest source code. All EVerest components are Apache-2.0 licensed.

## Pinned inputs

| Input | Pin |
|---|---|
| EVerest demo manager image | `ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase@sha256:9165d0937323ae61ee2e496f68f3c4a465ed9099740e489df1f0161265492756` (multi-arch index) |
| everest-demo repository | [EVerest/everest-demo](https://github.com/EVerest/everest-demo) at `686e370d6ed6460211b06e34a4cdf9438a22e81e` (`TAG=2025.10.0-single-phase`) |
| everest-core | 2025.10.0 (built inside the demo image) |
| libocpp | `a68f6735ebee194bd543386bbf4dbe2f678df268` |
| everest-framework | `23a1414f35f0b4bfcaf260340e3c7ca674214095` |
| Josev (PyEvJosev EV simulator) | As vendored in the demo image under `libexec/everest/3rd_party/josev` |
| Josev Python dependencies | Hash-pinned wheels in `requirements-josev.txt` (installed with `--require-hashes --only-binary`) |
| Runtime base | `debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587` (same Debian 12 ABI as the demo build) |

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

`patch_josev.py` runs at image build and edits two files.

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

## Licences

The image carries `/usr/share/doc/everest/EVerest-LICENSE` and the
licence/notice files of every CPM-fetched dependency under
`/usr/share/doc/everest/third_party/`. Josev is Apache-2.0. Debian packages
carry their own copyright files under `/usr/share/doc/`. The Java runtime
under `/opt/java` is a jlink image of Debian's OpenJDK 17 (GPLv2 with the
Classpath Exception); its module legal notices are in `/opt/java/legal/`
and Debian's copyright file is `/usr/share/doc/openjdk-17/copyright`.
