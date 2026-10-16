# Plugfest lab: system setup and build process

How the **Green** CSMS test box was built for the October 2026 OCA Plugfest,
how each App image is built and published, and how to rebuild or verify any
part of it. Test results are in [README.md](README.md).

Contents:
1. [System overview](#1-system-overview)
2. [Host: Home Assistant Green](#2-host-home-assistant-green)
3. [App store repositories](#3-app-store-repositories)
4. [Integrations (HACS)](#4-integrations-hacs)
5. [CitrineOS lab stack](#5-citrineos-lab-stack)
6. [Charging station simulators](#6-charging-station-simulators)
7. [Build process](#7-build-process)
8. [Publish process](#8-publish-process)
9. [Local tests](#9-local-tests)
10. [Rebuild checklist](#10-rebuild-checklist)

Secrets aren't recorded here. Generate every token and password fresh, and
keep them outside the repository. The values used in the 16 October test
must be rotated.

## 1. System overview

```
Home Assistant Green (HA OS, aarch64), LAN 192.168.86.90
│
├─ HA Core 2026.10.1
│   ├─ HACS 2.0.5
│   │   ├─ CitrineOS HA (citrine_ha)      purcell-lab/CitrineOS-HA-Integration
│   │   ├─ OCPP (ocpp) v0.12.1            lbbrhzn/ocpp, central system on 19002
│   │   └─ HA-MCP Custom Component v2.2.2 (MCP access for remote operation)
│   └─ Supervisor
│       ├─ store 7fbee41d = purcell-lab/ha-addons            (main)
│       └─ store 31ac84d3 = purcell-lab/ha-addons#claude/green-e2e
│
├─ CitrineOS lab stack (store 31ac84d3, built locally on the Green)
│   database 0.1.1 ─ broker 0.1.1 ─ hasura 0.1.1 ─ server 0.4.0
│       8080 gateway · 8081 SP1 simulators · 8082 SP0 open admission
│       8083 SP1 Plugfest (host port published only during a slot)
│
├─ Charging-station simulators
│   EVerest V2G 0.1.6 (31ac84d3, prebuilt GHCR)  → CitrineOS 8083 via LAN IP
│   EVerest AC  0.1.1 (31ac84d3, prebuilt GHCR)  → CitrineOS 8082
│   MicroOCPP 1.6 0.1.1 (7fbee41d, local build)  → HA OCPP 19002
│   MicroOCPP 2.0.1 0.1.3 (7fbee41d, local build) — stopped (#38)
│
└─ Open Dynamic Export 0.1.0 (7fbee41d, prebuilt GHCR; ODE v0.20.0)
    offline test configuration, inverter control disabled
```

**Why a branch store.** The aarch64 builds of the CitrineOS Apps (PR #34)
and the Plugfest listener (`claude/plugfest-sp1`) aren't on main yet. On
main the CitrineOS Apps are amd64-only, so the Green's main store shows them
as unavailable. `claude/green-e2e` is main + PR #34 + `claude/plugfest-sp1`.
Once those merge, install everything from the main store and remove the
branch store.

## 2. Host: Home Assistant Green

| Item | Value |
|---|---|
| Hardware | Home Assistant Green (aarch64, 4 GB RAM) |
| OS | Home Assistant OS, Core 2026.10.1, time zone Australia/Brisbane |
| Network | Ethernet, LAN address 192.168.86.90. At the venue, use Ethernet on the venue LAN. |
| Memory in use | CitrineOS stack about 0.5 GB, ODE about 295 MB, V2G up to 370 MB, AC 120 MB, MicroOCPP about 10 MB each |

Setup steps:
1. Onboard HA OS and create the admin user.
2. Install **HACS**: run the "Get HACS" App once, restart, then add the
   HACS integration.
3. Install the **HA-MCP** custom component through HACS. It is optional, but
   it is how this lab was operated remotely: App lifecycle, options, logs
   and service calls.

## 3. App store repositories

Settings → Apps → App store → ⋮ → Repositories:

| Store slug | URL | Use |
|---|---|---|
| `7fbee41d` | `https://github.com/purcell-lab/ha-addons` | main: MicroOCPP Apps, Open Dynamic Export |
| `31ac84d3` | `https://github.com/purcell-lab/ha-addons#claude/green-e2e` | CitrineOS stack, EVerest AC and V2G |

- The `#branch` suffix tracks a branch. Supervisor names the store by a hash
  of the URL, so App slugs become `<store>_<folder>`, for example
  `31ac84d3_citrineos_server`.
- Container hostnames replace `_` with `-`, for example
  `31ac84d3-citrineos-server`.
- After pushing to a tracked branch, reload the store with **Check for
  updates**. A changed version then shows as an update. A local-build App
  whose source changed without a version bump needs **Rebuild**.

## 4. Integrations (HACS)

### CitrineOS HA (`citrine_ha`)

1. HACS → ⋮ → Custom repositories → `purcell-lab/CitrineOS-HA-Integration`
   (Integration), then download and restart.
2. Add the integration, with gateway URL `http://31ac84d3-citrineos-server:8080`
   and the server's `api_token`. The entry on the Green is "CitrineOS Green
   Lab".
3. Options: `api_profile: v2_scoped_lab_control`, `read_only: false`,
   `command_token` (the server's), `scan_interval: 5`.
4. Entities are created for the server's `command_station_id` only.
   - After changing it, restart the server, wait about 60 s, then reload the
     entry (#40).
   - Lab services: `citrine_ha.lab_schedule`, `sync_discovery_now`;
     buttons Start charging, Stop transaction, and Clear test profile after
     closure.

### OCPP (`ocpp`, lbbrhzn) as a second CSMS

1. Install it through HACS (v0.12.1) and add the integration.
   - Central system port **19002**.
   - The entry is named `sim_lab_16`, which keeps test chargers apart from
     production ones.
2. Stations connect to `ws://172.30.32.1:19002`, the HA Core address on the
   Supervisor network.
3. Options: set **`meter_interval`** below its 60 s default (for example
   5 s) before profile tests. At 60 s, short steps are invisible (#42).
4. Every `SIM-` device must be excluded from real charging and energy
   automations.

## 5. CitrineOS lab stack

Install from store `31ac84d3`, in this order: **database → broker → Hasura
→ server**. Keep boot `manual` and auto-update off for each App. On the
Green each is built locally by Supervisor (no `image:` key), taking about 70
to 90 s per App.

### Secrets

Generate distinct values, never reused across Apps or stations:

```sh
python3 -c "import secrets;print(secrets.token_hex(32))"      # database, broker, hasura, api_token, command_token
python3 -c "import secrets;print(secrets.token_hex(16))"      # Plugfest/V2G station password (32 hex)
```

Vendor Plugfest passwords must be 16 to 40 printable ASCII characters, with
no spaces. `secrets.token_urlsafe(24)` gives 32 characters.

### Options

| App | Options |
|---|---|
| `citrineos_database` | `password` (the database secret) |
| `citrineos_broker` | `password` (the broker secret) |
| `citrineos_hasura` | `database_host: 31ac84d3-citrineos-database`, `database_password`, `admin_secret` (the Hasura secret) |
| `citrineos_server` | see below |

`citrineos_server` 0.4.0 (green-e2e build):

```yaml
mode: isolated                      # 'disconnected' until all secrets are set
database_host: 31ac84d3-citrineos-database
broker_host: 31ac84d3-citrineos-broker
hasura_host: 31ac84d3-citrineos-hasura
database_password: <db>             # same as database App
broker_password: <broker>           # same as broker App
hasura_secret: <hasura>             # same as hasura App
api_token: <64 hex>                 # gateway Bearer for CitrineOS-HA
simulator_enabled: false            # SIM-CITRINE-LAB-01 on 8081 (not used)
profile_simulator_enabled: false
command_control_enabled: true       # scoped lab commands
command_token: <64 hex>
command_station_id: SIM-EV-EVEREST-V2G-03   # one station at a time (#40)
open_admission_enabled: true        # 8082, internal only, for the AC simulator
plugfest_enabled: true              # 8083 SP1 listener
plugfest_stations:
  - id: SIM-EV-EVEREST-V2G-03
    password: <32 hex>              # also set in the V2G App
```

| Port | Listener | Exposure |
|---|---|---|
| 8080 | Gateway (Bearer `api_token`; commands also need `command_token`) | Internal |
| 8081 | SP1, provisioned simulators | Internal |
| 8082 | SP0 open admission | **Internal only, never published** |
| 8083 | SP1 Plugfest: provisioned `plugfest_stations` only, unknown IDs rejected | Host port `8083` **only during a slot** |
| 8091 | JWKS | Internal |

Start-up and checks:
1. Start the database, broker and Hasura, then the server. Server start-up
   takes about 60 s.
2. Check `/lab/status` on the gateway: listeners, and `plugfest_stations`
   (IDs only).
3. Publish 8083 only for a test or slot: in the App's Network tab, or with
   `network {"8083/tcp": 8083}`, then restart. Afterwards set it to `null`
   and restart. Never port-forward it to the internet.
4. On each start the seed provisions every Plugfest station (station row,
   Boots `Accepted`, `SecurityCtrlr.BasicAuthPassword`). It also revokes the
   password of any station removed from the list.
5. Stop in this order: server, Hasura, broker, database.

## 6. Charging station simulators

Each simulator starts disconnected. The first connected start binds its URL
and identity to the App's data. EVerest Apps change that only with
`archive_and_rebind: true` for one start; MicroOCPP Apps can't change it
without a data reset (#29).

| App (store) | Image | Options used |
|---|---|---|
| `everest_v2g_simulator` 0.1.6 (31ac84d3) | `ghcr.io/purcell-lab/aarch64-everest-v2g-simulator:0.1.6` | `csms_url: ws://192.168.86.90:8083`, `charge_point_id: SIM-EV-EVEREST-V2G-03`, `ocpp_version: "2.1"`, `max_power_kw: 11`, `ha_control: true`, `csms_basic_auth_password: <32 hex>`, `acknowledge_test_isolation: true` |
| `everest_simulator` 0.1.1 (31ac84d3) | `ghcr.io/purcell-lab/aarch64-everest-simulator:0.1.1` | `csms_url: ws://31ac84d3-citrineos-server:8082`, `charge_point_id: SIM-EV-EVEREST-G1`, `ocpp_version: "2.1"`, `phases: "1"`, `max_current_a: 32`, `acknowledge_test_isolation: true` |
| `microocpp_simulator16` 0.1.1 (7fbee41d) | local build | `backend_url: ws://172.30.32.1:19002`, `charge_point_id: SIM-16-MICROOCPP-01`, `acknowledge_test_isolation: true` |
| `microocpp_simulator` 0.1.3 (7fbee41d) | local build | `backend_url: ws://31ac84d3-citrineos-server:8082`, `charge_point_id: SIM-MICROOCPP-G1`. **Doesn't connect** (hostname DNS, #38) |

Notes:
- **V2G uses the LAN address**, not the internal hostname, so the test goes
  through the published 8083 port exactly as a vendor charger would. It
  needs `privileged: NET_ADMIN` for its isolated v2g0/v2g1 link, and its
  start-up discovery self-test must report PASSED.
- **MicroOCPP needs an IP address**, not a hostname (#38). The HA Core IP
  `172.30.32.1` is stable; other App IPs change on restart.
- **Driving the simulators** (all through Ingress or HA):

| Simulator | Plug in / unplug | Start |
|---|---|---|
| V2G | HA event `everest_v2g_command` `{"charge_point_id": …, "command": "plugin"\|"stop"\|"unplug"}` | Within about 60 s of plug-in (#33) |
| AC | `POST /api/ev/{plugin,pause,resume,unplug}` with header `X-HA-EVerest: 1` | — |
| MicroOCPP | `POST /api/connector/1/evse` `{"evPlugged","evsePlugged","evReady","evseReady"}` | — |

### Open Dynamic Export (`open_dynamic_export` 0.1.0, store 7fbee41d)

Released from main on 16 October (PR #36, publish run 38887442611, tag
`open_dynamic_export-v0.1.0`). It packages upstream ODE v0.20.0 (commit
`bc807abb`), which is the latest upstream release and main as of 16 October.
Image: `ghcr.io/purcell-lab/aarch64-open-dynamic-export:0.1.0`, pulled, not
built on the device.

On the Green it runs the **offline test configuration** used by CI:

```json
{
  "setpoints": { "fixed": { "exportLimitWatts": 5000 } },
  "inverters": [
    { "type": "sunspec", "connection": { "type": "tcp", "ip": "127.0.0.1", "port": 1502 }, "unitId": 1 }
  ],
  "inverterControl": { "enabled": false },
  "meter": {
    "type": "sunspec", "connection": { "type": "tcp", "ip": "127.0.0.1", "port": 1502 },
    "unitId": 240, "location": "feedin"
  }
}
```

- Pass it as the `config` option (a JSON string), or put it in
  `/addon_configs/7fbee41d_open_dynamic_export/config.json`.
- Nothing listens on `127.0.0.1:1502`, so no device is contacted. The log
  shows `ECONNREFUSED` on every poll, which is expected.
- **Check:** `GET /api/coordinator/status` (Ingress) reports
  `"running": true`, active limit `opModExpLimW` 5000 from `fixed`, and
  `inverterConfiguration: null` (no commands sent).
- Without a configuration the App refuses to start. The log says "No
  configuration", and Supervisor shows the App in error. This is by
  design.
- The UI is behind Ingress: *Open Web UI*, or enable "Show in sidebar"
  (Dynamic Export). LAN port `3000/tcp` stays unset, because the upstream UI
  and API have no authentication.
- For real use, replace the inverter and meter with real devices. Keep
  `inverterControl.enabled: false` until readings are confirmed. For
  CSIP-AUS, add `sep2-cert.pem` and `sep2-key.pem` to the App's folder.
- It is separate from the community ODE App (Stuart0411) on the main box.

## 7. Build process

### How Supervisor gets an image

| App | Image source | Architectures |
|---|---|---|
| everest_simulator, everest_v2g_simulator | `image: ghcr.io/purcell-lab/{arch}-…`: Supervisor **pulls** the published image | V2G 0.1.6: aarch64 + amd64. AC 0.1.1: aarch64 + amd64 |
| citrineos_database, broker, hasura, server, simulator | No `image:`: Supervisor **builds** the Dockerfile on the device | aarch64 + amd64 on PR #34 / green-e2e; amd64 only on main |
| microocpp_simulator, microocpp_simulator16 | Built locally on main. PR #35 adds `image:` (`{arch}-microocpp-simulator[16]`) to skip the on-device compile. | aarch64 + amd64 |
| open_dynamic_export | `image: ghcr.io/purcell-lab/{arch}-open-dynamic-export`: Supervisor **pulls** (0.1.0 published) | aarch64 + amd64 |

### EVerest images

The upstream EVerest demo image is about 4.3 GB per architecture, almost all
of it build tree. It is reduced in two steps.

1. **Shared runtime** `everest_runtime/` is a build input, not an App.
   - It starts from `ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase@sha256:9165d093…`.
   - It copies the manager, libraries, `share/everest`, the demo certs,
     Josev and the union of both Apps' modules onto
     `debian:bookworm-slim@sha256:7c7b2c96…`.
   - It strips every ELF file and ends in `FROM scratch`.
   - Published as `ghcr.io/purcell-lab/everest-runtime:<VERSION>`, with a
     multi-arch index over `-amd64` and `-aarch64` tags.
   - The Apps pin `2025.10.0-1@sha256:ad99f273…`.
   - **2025.10.0-2** (PR #34, unpublished) also:
     - keeps only shared libraries in the DT_NEEDED closure, found with
       `readelf`;
     - empties `share/everest/www`, which the manager requires to exist;
     - drops data for unused modules.
     `EXPECTED_DIFFERENCES` lists these intended changes, so the
     identical-files gate (`image_tree_compare.py --expected`) still passes.
2. **App images** copy only their own `MODULES` from the runtime onto the
   same pinned Debian base, and add nginx, mosquitto, Python and the App's
   `rootfs/`.
   - **V2G 0.1.6** replaces the 184 MB `openjdk-17-jre-headless` with a
     **jlink** runtime of about 50 MB. Its modules are `java.base`,
     `java.compiler`, `java.desktop`, `java.management`, `java.naming`,
     `java.rmi`, `java.sql`, `java.xml` and `jdk.unsupported`.
   - Its JVM flags are built in with `--add-options`: `-Xms16m -Xmx128m
     -XX:MaxMetaspaceSize=64m -XX:+UseSerialGC -XX:TieredStopAtLevel=1
     -Xss512k`. A `/usr/bin/java` symlink points to it.
   - Python dependencies for Josev install with `pip --require-hashes`.

Build locally without publishing:

```sh
docker build --build-arg RUNTIME_VERSION="$(cat everest_runtime/VERSION)" -t everest-runtime:local everest_runtime
sh .github/scripts/everest_identical_files.sh everest-runtime:local amd64
docker build --build-arg BUILD_ARCH=amd64 -t v2g:test everest_v2g_simulator
CHECKS=full sh everest_v2g_simulator/tests/ci_image_checks.sh v2g:test
```

### CitrineOS images

| App | Base (digest-pinned) |
|---|---|
| server | `ghcr.io/citrineos/citrineos-server:v2.0.1@sha256:15316dff…` (multi-arch; arm64 manifest recorded in `compatibility-lock.json`) with the `launch.mjs` wrapper |
| database | main: `postgis/postgis:16-3.5@…` (amd64 only). PR #34: `imresamu/postgis:16-3.5-bullseye@sha256:3ffaa98c…` (same PostgreSQL 16.9 / PostGIS 3.5.2, multi-arch) |
| broker | `rabbitmq:3.13.7-management@…` + jq 1.8.1 |
| hasura | `hasura/graphql-engine:v2.40.3@…` + gosu |

- jq is downloaded with `ADD --checksum=sha256:…` and chosen per
  architecture through `FROM jq-${TARGETARCH}` stages.
- `citrineos_server/tests/test_packaging.py` checks digest pins, checksums,
  privileges and ports.

### MicroOCPP images

- Two stages on `alpine:3.22`.
- Build stage: clone MicroOcppSimulator at
  `2cb07cdbe53954a694a29336ab31eac2d2b48673`, run `prepare_source.py`
  (patches), then a CMake build of `mo_simulator`.
- Runtime stage: nginx + python3 + `app.py`.
- On-device builds on the Green take several minutes, which is why PR #35
  moves them to GitHub.

### Open Dynamic Export image

- `node:24-alpine3.22`, pinned by index digest, for both stages.
- Build stage:
  - fetches upstream commit `bc807abbc4c58be3294257ee76f0348dc87c4945`
    (v0.20.0) and checks it after the fetch;
  - applies our `ingress.patch`, so the UI works under
    `/api/hassio_ingress/<token>/` with relative assets;
  - then runs `pnpm install --frozen-lockfile`, the build, and a prune.
- Runtime stage: our launcher `rootfs/opt/ode-ha/run.mjs`.
  - It validates the options and writes `config.json` (mode 600).
  - It copies the CSIP-AUS certificate and key privately.
  - It runs the upstream server and forwards signals.
  - ODE's rotating debug logs go to `/tmp`.
- `open_dynamic_export/tests/ci_image_checks.sh` is shared by PR CI and the
  publish gate. It checks:
  - the packaged commit, licence and patch;
  - that assets are relative;
  - that the App fails closed without a configuration;
  - that an offline start reaches `running`;
  - that `config.json` is mode 600;
  - that SIGTERM shuts it down cleanly.
- To move to a newer upstream release, change `ODE_COMMIT` and the App
  version, check that the patch still applies, and republish.

## 8. Publish process

Every published image comes from a GitHub Actions workflow on `ubuntu-24.04`
(amd64) and `ubuntu-24.04-arm` (aarch64) runners.
- Workflows log in to GHCR with `GITHUB_TOKEN`.
- They **refuse to overwrite** an existing version, push only the version
  tag (never `latest`) and attach build provenance.
- No PR workflow publishes.

| Image | Workflow | How to start |
|---|---|---|
| `everest-runtime` | `everest-runtime-publish.yml` | Push tag `everest_runtime-v$(cat everest_runtime/VERSION)` |
| `{arch}-everest-simulator` | `everest-publish.yml` | Push tag `everest_simulator-v<version>` |
| `{arch}-everest-v2g-simulator` | `everest-v2g-publish.yml` | **Run workflow** with `version` + `target` (commit SHA), or a tag |
| `{arch}-microocpp-simulator[16]` | `microocpp-publish.yml` (PR #35) | Run workflow with `app`, `version` and `target`, or a tag |
| `{arch}-open-dynamic-export` | `ode-publish.yml` | **Run workflow** with `version` + `target`, or a tag (0.1.0: run 38887442611) |

**Release sequence.** Each step is a separate approval.
1. Bump `version` in the App's `config.yaml` (and CHANGELOG), and open the PR.
   PR CI must pass: unit tests, image build and `ci_image_checks.sh`.
2. Publish from the reviewed PR head. **Run workflow** with that version and
   commit SHA. It builds and checks both architectures, pushes, then the
   `tag` job creates `<app>-v<version>` on the same SHA. This is
   publish-then-tag, because a tag pushed with the workflow token wouldn't
   trigger the workflow. If only the tag job fails, use *Re-run failed
   jobs*.
3. Check that a **new** GHCR package can be pulled anonymously. If not,
   make it public (Package settings → Change visibility). The ODE packages
   were public from the first push.
   - A publish workflow must be on main before it can be run manually. For
     a new App, merge its publish workflow first (as #43 did for ODE).
4. Re-run the PR checks until the `published-image` gate is green. It runs
   `docker manifest inspect` anonymously for both architectures.
5. Merge. Then in HA: Check for updates, update, and restart the App.

**Runtime release.**
1. Push the runtime tag.
2. Make `everest-runtime` public.
3. Pin `ARG EVEREST_RUNTIME=ghcr.io/purcell-lab/everest-runtime:<v>@sha256:<index digest>`
   in both EVerest Dockerfiles; the run summary prints the line.
4. Empty `EXPECTED_DIFFERENCES`.
5. Release new App versions.

A published version is never replaced. Fix forward with a version bump.

Verify a published image:

```sh
docker manifest inspect ghcr.io/purcell-lab/aarch64-everest-v2g-simulator:0.1.6
gh attestation verify oci://ghcr.io/purcell-lab/aarch64-everest-v2g-simulator:0.1.6 --owner purcell-lab
```

## 9. Local tests

```sh
pip install PyYAML==6.0.2        # Node 24; nginx, openssl for EVerest tests
python -m unittest discover -s citrineos_server/tests -p test_packaging.py -v
python -m unittest discover -s citrineos_server/tests -p test_v2g_readiness.py -v
node --test citrineos_server/tests/*.test.mjs
python -m unittest discover -s everest_simulator/tests -v
python -m unittest discover -s everest_v2g_simulator/tests -v
python -m unittest discover -s microocpp_simulator/tests -v
python -m unittest discover -s microocpp_simulator16/tests -v
python .github/scripts/test_image_tree_compare.py
git diff --check
```

**Container stack tests.** Build the `citrine-*:test` images first, as in
`.github/workflows/citrineos.yml`. The harnesses use fixed `lab-*`
container names, so run only one at a time.

| Command | Covers |
|---|---|
| `TEST_NATIVE_SIMULATOR=1 python3 citrineos_server/tests/stack_smoke.py` | MicroOCPP baseline |
| `TEST_V2G_SIMULATOR=1 python3 citrineos_server/tests/stack_smoke.py` | HA client → CitrineOS → EVerest V2G |
| `TEST_PLUGFEST=1 python3 citrineos_server/tests/stack_smoke.py` | 8083: accepted boot, wrong password, unknown ID, revocation (plugfest-sp1) |

Charts for new test runs: add `data/<run>.json`, then
`python3 make_charts.py`.

## 10. Rebuild checklist

1. HA OS on the Green. Then HACS, the HA-MCP component, CitrineOS HA and
   OCPP (v0.12.1) through HACS.
2. Add both App stores (section 3).
3. Generate fresh secrets. Install and configure database, broker, Hasura and
   server, then start them in that order.
4. Add the CitrineOS HA entry (`v2_scoped_lab_control`). Add the OCPP entry
   on 19002 with a short `meter_interval`.
5. Install the simulators (section 6). Start each disconnected, then set the
   URL and identity.
6. For V2G on 8083: add its ID and password to `plugfest_stations`, publish
   host port 8083, and restart the server.
7. Optional: install Open Dynamic Export from the main store with the
   offline test configuration (section 6), then start it and check the
   coordinator status.
8. Run the three tests in [README.md](README.md). Then remove the 8083 host
   port and stop the simulators.
9. At the event, replace the simulator entries in `plugfest_stations` with
   the vendors' IDs and passwords, and follow `docs/plugfest-runbook.md`.
