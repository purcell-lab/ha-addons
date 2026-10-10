# Validation record, 0.1.0

## Evidence levels

| Level | Status |
|---|---|
| Unit tests (options, binding, device model, log parsing, log filter, UI service) | Pass locally; CI runs them on every PR |
| nginx peer ACL and POST allowlist (real nginx) | Pass locally in Debian 12; CI |
| End-to-end acceptance against a mock CSMS | Pass locally in a Debian 12 root with the extracted, stripped EVerest runtime (amd64). CI repeats it in the built image on amd64 and aarch64 |
| Container image build | **CI only.** Not built locally (no Docker in the authoring sandbox) |
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

## Findings during development

- `ChargingStationSupplyPhases: 1` made libocpp leave every profile out of
  the composite schedule. The App keeps the upstream value (3); a unit test
  guards this.
- Watt profiles without `numberPhases` are treated as 3-phase (see DOCS).
- The upstream `controller` admin panel listens on all interfaces; it is
  replaced by a stub.
- The demo build is coverage-instrumented and logs composite schedules
  every interval; both are handled in `app.py`.

## Not claimed

OCPP 2.1 conformance beyond the messages above, ISO 15118, V2G or
bidirectional power, TLS, Security Profiles 2 and 3, physical-charger
behaviour, and BSV settlement are out of scope.
