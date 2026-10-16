# Handover: EVerest build process, runtime image and 0.1.1 / 0.1.3 releases

Status at 2026-10-11 (AEST). PR #17 merged into main. AC 0.1.1 and V2G 0.1.3
are published and running on the HA host. Docs PR #15 (TxProfile runs 1 to
3) was merged just before PR #17 (`a9516a4`, then `85e2263`) without a
conflict, so no rebase is needed. The V2G `VALIDATION.md` on main holds both
those runs and the 0.1.3 entry.

## Bottom line

- **No more 4.3 GB downloads.** App builds no longer pull the 4.3 GB
  upstream EVerest image. They copy a 44 MB pinned runtime image,
  `ghcr.io/purcell-lab/everest-runtime:2025.10.0-1`, built once from that
  upstream image.
- **The released files did not change.** Apps built from the runtime image
  match the earlier releases (AC 0.1.0, V2G 0.1.2) file for file under the
  EVerest, licence, App code and Python package paths.
- **CI image jobs are 2 to 3 times faster.** AC went from 6.5 to 8 min to
  2.4 to 2.5 min, and V2G from 7 to 12 min to 4.1 to 4.2 min. Pull
  requests now run minimum viable checks; releases keep the full gate.
- **amd64 and aarch64.** CI, publication and `config.yaml` cover both
  again from V2G 0.1.6 (a Home Assistant Green test host is aarch64).
  Between `1509f8b` and its revert they covered amd64 only.
- **Live on HA,** V2G 0.1.3 passed the start-up self-test, OCPP 2.1 and a
  three-step TxProfile run. AC 0.1.1 booted and connected.
- **Probable cause found for the 5-minute first-transaction delay.** HA's
  OCPP integration does not answer `SecurityEventNotification` or
  `GetCertificateStatus`, and EVerest sends queued messages in series.
  This is not fixed.

## Why the build changed

The upstream `ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase`
image is about 4.3 GB compressed per architecture. Registry layer data shows
two compile layers of about 2.7 GB and 0.7 GB, holding the build tree,
sources and toolchain. The Apps use 30 MB (AC) and 45 MB (V2G) of it,
compressed.

| Image (amd64, compressed) | Total | EVerest files | Rest |
|---|---|---|---|
| Upstream demo image | 4.28 GB | | |
| V2G 0.1.2 | 192 MB | 45 MB | 117 MB Debian packages (mostly OpenJDK 17 for Josev), 29 MB base |
| AC 0.1.0 | 97 MB | 30 MB | 38 MB packages, 29 MB base |
| Runtime 2025.10.0-1 | 44 MB | 44 MB (153 MB uncompressed) | none, `FROM scratch` |

HA never downloaded the 4.3 GB image. CI and every release did, once for
each architecture.

## Build process, end to end

### 1. Runtime image (`everest_runtime/`)

`everest_runtime/Dockerfile`, published by `everest-runtime-publish.yml`,
is built in three stages:

1. `FROM` the upstream demo image, pinned by digest
   `sha256:9165d093…92756`. This stage collects the EVerest licence and the
   licence and notice files of the CPM dependencies from `/ext/cache/cpm`.
2. A Debian 12 slim stage, pinned by digest. It copies `manager`, `lib/*.so*`
   with `lib/everest`, `share/everest`, the demo certificates (AC only),
   Josev (V2G only) and the union of both Apps' modules. It then strips
   every ELF file with `strip --strip-unneeded`, exactly as the Apps did
   before.
3. `FROM scratch` with only `/opt/everest` and `/usr/share/doc/everest`,
   labelled with the upstream digest.

`VERSION` holds the runtime version (`2025.10.0-1`). `REFERENCE` names the
App releases that the identical-file check compares against.

### 2. App images

Both App Dockerfiles take `ARG EVEREST_RUNTIME`, pinned by digest:

```
ghcr.io/purcell-lab/everest-runtime:2025.10.0-1@sha256:ad99f273e062f09c58fa030cd938df1d612ccbe04b65d1201864b4a72a8e455f
```

A short selection stage copies that App's `MODULES` (V2G also removes
`__pycache__`). The final Debian stage is unchanged: runtime packages,
`rootfs/`, `UPSTREAM.md`, the controller stub and `patch_josev.py` (V2G).

### 3. Pull request CI

| Workflow | Jobs |
|---|---|
| `everest.yml`, `everest-v2g.yml` | `changes` (skips images for documentation-only changes), `focused-tests` (unit tests), `image` (amd64, `CHECKS=minimal`), `published-image` (merge gate) |
| `everest-runtime.yml` | `compare-tool` (unit tests of the comparison tool), `identical-files` (amd64) |

`.github/scripts/everest_runtime.sh` uses the pinned runtime when it is
pinned and pullable and the PR does not change `everest_runtime/`.
Otherwise it builds the runtime locally first, which pulls the 4.3 GB image.

The `published-image` gate requires the App version and the runtime to be
public on GHCR and pinned by digest.

Minimum viable checks (`CHECKS=minimal`):

- **AC:** no V2G modules; offline start and OCPP 2.1 charging; offline
  entrypoint; listeners; clean shutdown.
- **V2G:**
  - Packaging: DC V2G modules present and no private keys.
  - Session: one OCPP 2.1 V2G session with the TxProfile steps.
  - Isolation: fails closed without NET_ADMIN.
  - Discovery: the start-up self-test passes on an IPv6 network that
    reproduces the HA OS route (`unscoped-multicast-via=eth0`, now asserted).
  - Firewall and shutdown: diagnostics, nftables rules, listeners, the
    firewall probe with a negative control, and clean shutdown.

### 4. Releases (tag only; each tag needs approval)

| Tag | Workflow | Gate |
|---|---|---|
| `everest_runtime-v<VERSION>` | `everest-runtime-publish.yml` | No overwrite, build, identical-file check, push `<VERSION>-amd64`, index `<VERSION>`, provenance |
| `everest_simulator-v<version>` | `everest-publish.yml` | Runtime pinned and public, no overwrite, build, full `ci_image_checks.sh`, push, provenance |
| `everest_v2g_simulator-v<version>` | `everest-v2g-publish.yml` | As above, with the full V2G gate (offline, recovery on IPv6 eth0, v2g21, fallback, pinned 2.0.1) |

### 5. Deployment on HA

The installed Apps come from repository copies that track branches, not
main:

| Installed slug | HA repository | Branch |
|---|---|---|
| `01723051_everest_v2g_simulator` | 01723051 | `feat/everest-v2g-diagnostics` |
| `08aef286_everest_simulator` | 08aef286 | `feat/everest-ghcr-image` |

Both branches were already merged into main. For this release they were
fast-forwarded to `1509f8b`, then updated through the HA MCP (store
`check_updates`, then `update`). Installed identities, options and `/data`
were kept. Side effect: those copies now also list the CitrineOS Apps from
main as available, not installed.

The main copy (7fbee41d) now offers the same versions. Moving the installed
Apps to it means reinstalling and needs separate approval.

## Releases

| Image | Digest | Commit |
|---|---|---|
| `everest-runtime:2025.10.0-1` (index, amd64 and arm64) | `sha256:ad99f273e062f09c58fa030cd938df1d612ccbe04b65d1201864b4a72a8e455f` | 4ba14d2 |
| `amd64-everest-simulator:0.1.1` | `sha256:4bc0dce016ad728c61f0d8ab445b4d14f5c9e4df8aba57c7d482c94c7cccc309` | f490c7b |
| `aarch64-everest-simulator:0.1.1` | `sha256:ceb254d6dda2f74214f19166cb545b7a79c826fa397dc43780d607e258c5360c` | f490c7b |
| `amd64-everest-v2g-simulator:0.1.3` | `sha256:6275b998182913f550bde8f924cd0ea1153be0b1129fea638b6eb15e62eea77f` | f490c7b |
| `aarch64-everest-v2g-simulator:0.1.3` | `sha256:fc6417bff64dfeaa73012ab9b4a5dad6c960245050e9d66b1ebfca5fc023cca5` | f490c7b |

Publish runs:

- [Runtime publish](https://github.com/purcell-lab/ha-addons/actions/runs/38098456995)
- [AC 0.1.1 publish](https://github.com/purcell-lab/ha-addons/actions/runs/38101003191)
- [V2G 0.1.3 publish](https://github.com/purcell-lab/ha-addons/actions/runs/38101003167)

These were the last aarch64 releases before `1509f8b` made the build
amd64 only. Its revert restores aarch64; V2G 0.1.6 is the first release
published for both architectures again.

## Evidence

### Identical files

`.github/scripts/image_tree_compare.py` exports both images and compares
type, mode, owner, and SHA-256 content or link target for every path.
Timestamps are not compared. Paths under `/opt/everest`,
`/usr/share/doc/everest`, `/opt/ha-everest` and `/usr/local/lib/python3.11`
must match exactly.

Two refinements were needed during this PR:

1. **`.pyc` source timestamp.** The first run matched every EVerest file,
   but `.pyc` files differed because their header records the checkout
   time. The check now drops only that 4-byte field of timestamp-based
   `.pyc` files.
2. **pip-compiled `.pyc` encoding.** 71 V2G `.pyc` files compiled by pip
   still differed, because marshal output is not byte-reproducible. A
   differing pair now passes only if the image's own Python 3.11 loads both
   and the code objects are equal.

Release gate result (runtime publish run, both architectures):

| App | Strict paths (files) | Strict differences | Notes |
|---|---|---|---|
| AC 0.1.1 vs 0.1.0, amd64 | 365 (282) | 0 | 6 information-only (apt logs, ldconfig cache, `group-`) |
| AC 0.1.1 vs 0.1.0, aarch64 | 365 (282) | 0 | as above |
| V2G 0.1.3 vs 0.1.2, amd64 | 746 (619) | 0 | 71 `.pyc` code-equal; 8 information-only, including the Java `cacerts` keystore |
| V2G 0.1.3 vs 0.1.2, aarch64 | 742 (615) | 0 | as above |

This proves file identity with the earlier releases, not behaviour.

### CI timings

| Job | Before (4.3 GB pull, full checks) | After (pinned runtime, minimal checks) |
|---|---|---|
| AC image, amd64 | 6.5 to 8 min | [2.5 min](https://github.com/purcell-lab/ha-addons/actions/runs/38098894325) |
| V2G image, amd64 | 7 to 12 min | [4.2 min](https://github.com/purcell-lab/ha-addons/actions/runs/38099906870) |

After the change, the App build step takes 14 to 18 s; the rest is tests.
Before, freeing runner disk took 0.4 to 1.4 min and the runtime build or
pull took 1.9 to 2.8 min. A PR that changes `everest_runtime/` still takes
the long path by design.

### Live on HA (2026-10-11, amd64, HA OS 18.3)

**V2G 0.1.3** (`01723051_everest_v2g_simulator`, `SIM-EV-EVEREST-V2G-01`,
CSMS `ws://172.30.32.1:19004`):

- **Start-up:** the self-test passed with `unscoped-multicast-via=eth0`, and
  OCPP connected with `ocpp2.1`.
- **Session start:** `everest_v2g_command` `plugin` led to AuthRequired.
  `switch.charger5_charge_control` on led to Preparing, then Charging at
  11,000 W.
- **Transaction reached HA after 258 s:** transaction
  `c158555a-8d3c-4e93-b490-df249f235cef` appeared in HA at 11:44:17, six
  seconds after the last unanswered `SecurityEventNotification` timed out.
- **TxProfile 210304** via `ocpp.set_charge_rate` (CentralSetpoint, 20 s
  steps; `startSchedule` 01:44:36Z):

| Step target | Settled value | Interim sample before settling |
|---|---|---|
| +6,000 W | 6,000 W (applied about 3 s before `startSchedule`) | none |
| −5,000 W | −5,000 W after 5 to 7 s | −1,111 W |
| +3,000 W | 3,000 W after 5 to 7 s | 13,500 W |

- **Session end:** charge control off led to Finished, then `unplug` led to
  Unplugged and idle.

**AC 0.1.1** (`08aef286_everest_simulator`, `SIM-EV-EVEREST-01`, CSMS
`ws://172.30.32.1:19003`): booted, connected with `ocpp2.0.1` because that
CSMS offers only 2.0.1 (same as 0.1.0 earlier that day), BootNotification
answered, Unplugged and idle. No charging session was run on HA for AC.

## Open items

1. **First-transaction delay (probable cause, not fixed).** EVerest queues
   OCPP calls in series. HA's OCPP integration does not answer
   `SecurityEventNotification` or `GetCertificateStatus`, so each one waits
   for its timeout and retries. Between the start of the session and the
   transaction reaching HA, the App logged five
   `SecurityEventNotification` timeouts and one `GetCertificateStatus`
   timeout. Options:
   - Raise this upstream with the HA OCPP integration.
   - Reduce the security events the simulator emits.
   - Shorten `MessageTimeout` for the lab.
2. **Transition transients.** One interim sample per step change (−1,111 W,
   13,500 W; earlier 24,750 W). The settled values are exact. Not
   characterised.
3. **TxProfile CI flake.** One aarch64 run read +11,000 W for the −5,000 W
   step. CI is amd64 only now, but the same class was seen before on amd64.
4. **Installed Apps track old branches.** Moving them to the main
   repository copy needs approval.

## How to

- **Release an App:** bump `version` in `config.yaml`, pass PR CI, and with
  approval push `everest_<app>-v<version>`. Then deploy by fast-forwarding
  the branch HA tracks and updating through the HA MCP.
- **Move to a new EVerest release** (for example 2025.12.1):
  1. Change the upstream image and digest in `everest_runtime/Dockerfile`
     and bump `VERSION` (for example `2025.12.1-1`).
  2. Expect differences against `REFERENCE`. Review them, then update
     `REFERENCE` or make the check informational for that change.
  3. Publish the runtime with approval, then pin it and release new App
     versions.
- **Drop an architecture:** remove its runner from the matrices in the five
  EVerest workflows, the runtime index command, both `config.yaml` arch
  lists and the `published-image` loops (see `1509f8b`).
- **Rebuild only the runtime:** bump `VERSION`. Tags never overwrite.

## Rules that still apply

- **Approvals:** no merge, install, HA restart, connection, tag push or
  image publication without explicit approval.
- **App isolation:** Apps start disconnected, boot manually and are
  Ingress-only, with the Supervisor peer ACL `allow 172.30.32.2; deny all;`.
- **Simulator identities:** use `SIM-EV-` identities only. Simulators are
  excluded from physical charger automations and BSV settlement. Never use
  the physical `central` system.
- **Scope claims:** receipt is not acceptance, and testing is not
  conformance.
