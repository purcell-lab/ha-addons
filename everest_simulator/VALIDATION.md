# Validation record, 0.1.0

## Evidence levels

| Level | Status |
|---|---|
| Unit tests (options, binding, device model, log parsing, log filter, UI service) | Pass locally; CI runs them on every PR |
| nginx peer ACL and POST allowlist (real nginx) | Pass locally in Debian 12; CI |
| End-to-end acceptance against a mock CSMS | Pass locally (Debian 12 root, amd64) and in the built image in CI on amd64 and aarch64 ([run 38035593593](https://github.com/purcell-lab/ha-addons/actions/runs/38035593593)) |
| Container image build | Pass in CI: amd64 308 MB, aarch64 334 MB. No listener outside loopback except Ingress 8099 |
| Home Assistant install, HA OCPP CSMS, Ingress in a browser | **Not done.** Needs explicit approval and an isolated test central system |

## End-to-end acceptance (tests/acceptance.py)

Mock CSMS on loopback, real App entrypoint (mosquitto, EVerest manager, UI
service, nginx). Local run on 2026-10-10:

| Scenario | App offers | CSMS accepts | Negotiated | Result |
|---|---|---|---|---|
| offline | n/a (`csms_url` empty) | n/a | no connection attempt reached the CSMS | Pass |
| ocpp21 | `ocpp2.1, ocpp2.0.1` | `ocpp2.1, ocpp2.0.1` | `ocpp2.1` | Pass |
| fallback | `ocpp2.1, ocpp2.0.1` | `ocpp2.0.1` only | `ocpp2.0.1` | Pass |
| pinned201 | `ocpp2.0.1` | `ocpp2.1, ocpp2.0.1` | `ocpp2.0.1` | Pass |

The charging scenarios check: WebSocket path `/<charge_point_id>`, Basic Auth
user equal to the charge-point ID, EV plug-in to `AuthRequired`,
RequestStartTransaction to TransactionEvent `Started`, and then a stepped
single-phase TxProfile (W, `numberPhases: 1`, 15 s per step):

| Limit | Expected | ocpp2.1 mean | fallback mean |
|---|---|---|---|
| 4,000 W | 17.39 A | 17.36 A, 3,834 W | 17.39 A, 3,846 W |
| 7,360 W | 32.00 A | 32.11 A, 6,894 W | 32.09 A, 6,888 W |
| 0 W | 0 A (paused) | 0.00 A, 0 W | 0.00 A, 0 W |
| 2,000 W | 8.70 A | 8.71 A, 1,969 W | 8.72 A, 1,974 W |
| 7,360 W | 32.00 A | 31.97 A, 6,837 W | 32.02 A, 6,859 W |

Also checked in each charging scenario: the 0 W step did not end the
transaction (one transaction ID, no `Ended`); metered energy matched the
integral of measured power (85.0 vs 85.6 Wh, and 85.0 vs 84.5 Wh); the Status
page recorded the TxProfile with reply `Accepted` and the exact periods sent;
RequestStopTransaction gave TransactionEvent `Ended` and 0 W; unplug returned
to `Unplugged` with 0 A; the App exited with code 0.

CI step means (A) for the same schedule:

| Run | 4,000 W | 7,360 W | 0 W | 2,000 W | 7,360 W | Energy metered vs integrated |
|---|---|---|---|---|---|---|
| amd64 ocpp2.1 | 17.39 | 32.09 | 0.00 | 8.72 | 32.02 | 85.0 vs 85.0 Wh |
| amd64 fallback | 17.39 | 32.07 | 0.00 | 8.72 | 31.99 | 85.0 vs 86.4 Wh |
| aarch64 ocpp2.1 | 17.38 | 32.03 | 0.00 | 8.70 | 32.00 | 86.0 vs 85.5 Wh |
| aarch64 fallback | 17.39 | 32.07 | 0.00 | 8.72 | 31.99 | 85.0 vs 85.1 Wh |

## Findings during development

- `ChargingStationSupplyPhases: 1` made libocpp leave every profile out of
  the composite schedule. The App keeps the upstream value (3); a unit test
  guards this.
- Watt profiles without `numberPhases` are treated as 3-phase (see DOCS).
- The upstream `controller` admin panel listens on all interfaces; it is
  replaced by a stub.
- The demo build is coverage-instrumented and logs composite schedules
  every interval; both are handled in `app.py`.

## 0.1.1: rebuilt from the shared runtime image (2026-10-11)

0.1.1 is 0.1.0 rebuilt from `ghcr.io/purcell-lab/everest-runtime:2025.10.0-1`
(no functional change). Full detail: `everest_runtime/HANDOVER.md`.

- Identical-file release gate against 0.1.0: 365 strict paths on amd64 and
  aarch64, 0 differences.
- Full release gate passed in the
  [publish run](https://github.com/purcell-lab/ha-addons/actions/runs/38101003191).
  The amd64 image is `sha256:4bc0dce016ad728c61f0d8ab445b4d14f5c9e4df8aba57c7d482c94c7cccc309`.
- Live on HA OS 18.3 (amd64): booted and connected to
  `ws://172.30.32.1:19003` with `ocpp2.0.1` (that CSMS offers only 2.0.1,
  as with 0.1.0). The BootNotification was answered, and the App is
  Unplugged and idle. No charging session was run on HA.

## Not claimed

OCPP 2.1 conformance beyond the messages above, ISO 15118, V2G or
bidirectional power, TLS, Security Profiles 2 and 3, physical-charger
behaviour, and BSV settlement are out of scope.
