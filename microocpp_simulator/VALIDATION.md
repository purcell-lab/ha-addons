# OCPP 2.0.1 App validation

Updated 10 October 2026. Version 0.1.2 is installed on the isolated Home
Assistant OCPP 2.0.1 test entry. Version 0.1.3 is a staged post-stop metering
correction. No version is an OCPP certification claim.

## Completed in the development sandbox

- Native C++ release build from the pinned source and submodules.
- Fourteen focused Python/Ingress tests: disconnected default, test identity,
  explicit acknowledgement, URL restrictions, 2.0.1 credential seeding,
  record preservation, safe ready-state reset, rebinding refusal, corrupt
  state refusal, unbound 2.0.1 transaction protection and actual nginx
  peer/mutation restrictions.
- Loopback mock-CSMS test requiring the `ocpp2.0.1` WebSocket subprotocol.
- OCPP 2.0.1 BootNotification, Authorize and Started/Updated/Ended
  TransactionEvent messages.
- Positive imported energy and sampled positive power in transaction events.
- HTTP API transaction ID equals the OCPP 2.0.1 string ID.
- CSMS attempt to change the station identity is not accepted.
- `SetChargingProfile` returns an explicit protocol error, not false success.
- SIGTERM cleanup and restart with networking disabled, without a fallback
  connection to the public echo server.
- Ingress-relative UI API URL replaces upstream hard-coded localhost.
- Git whitespace validation.
- Version 0.1.1 regression checks reject missing legacy-connector diagnostics
  during the native lifecycle, disconnected restart and App entrypoint test.
  Both EVSE meter APIs must show zero power after disconnected restart.
- Version 0.1.1 serves exactly one HTML Content-Type, with matching HTML
  bodies for gzip and identity encoding. It no longer serves the UI as a
  downloadable gzip file. Native HTTP regression tests cover both variants.
- The two upstream 1.6 UI headings now identify the fixed 2.0.1 mode.
- Local Chromium desktop (1280×900) and mobile (390×844) checks through an
  nginx proxy with an ingress-style path rendered the Status page without
  downloads or JavaScript errors. Meter requests used the prefixed API path
  and returned 200; both EVSEs showed zero readings. Opening the connection
  page showed an empty backend and SIM test identity. This disposable fixture
  trusted loopback only; production ingress configuration was not relaxed.
  These checks do not replace browser acceptance on the live HA installation.

## Version 0.1.2 browser power-flow regression

The earlier native smoke test set all four plug/ready flags directly. It did
not catch that both browser forms omitted `evsePlugged`. The new adaptation
sets both cable ends from the single UI Plugged control, without weakening
the native power model. Focused tests assert both payloads and fail closed
on changed upstream context or double application.

QA inventory and results:

- Status plug, EV Ready, EVSE Ready: exercised through real Chromium clicks,
  followed by a test RFID through Connectors > Transaction Options.
- Plug/ready without authorization: zero power, not a fabricated charge.
- Clicking the status badge: remains server-reported Available.
- Authorized connector 1: visible power about 11,000 W and increasing Wh.
- Normal 2.0.1 Occupied status: blue non-error styling, raw status retained.
- Connector EVSE Options: independently verified both plug flags become
  true and then false; both readiness flags stayed false and no power flowed.
- Connector 2: remained unplugged, not ready, zero power and zero energy.
- Stop: real UI Unplugged and both Not Ready controls restored Available
  and zero W/A/V; transaction ended and the native process exited cleanly.
- Desktop 1280×900 and mobile 390×844: controls and readings visible,
  mobile main content width 390 px with no horizontal overflow after the
  existing layout transition completes. No JavaScript page errors.

The final isolated browser run used one transaction at 02:20:43–02:21:07 UTC
on 10 October 2026. The mock central system received:

| Event | Timestamp UTC | Import register | Import power |
|---|---|---:|---:|
| Started | 02:20:43.413 | 0 Wh | 0 W |
| Updated | 02:20:53.483 | 30 Wh | 11005.78809 W |
| Updated | 02:21:03.576 | 61 Wh | 10993.68164 W |
| Ended | 02:21:07.776 | 74 Wh | 10993.68164 W |

This proves browser controls → native metering → OCPP 2.0.1 mock receiver.
It does **not** prove the live HA central-system sensor mapping.

**Version 0.1.2 final-sample limitation:** the Ended event contains the most recent
nonzero power value while the simulator subsequently reads zero. Consumers
must not infer ongoing charging solely from that retained sample. Verify
HA's ended-transaction/power handling in the live acceptance test; no
post-stop zero MeterValues guarantee is made here.

Version 0.1.3 addresses this ordering defect at sample time. Its regression
first failed against 0.1.2 with a nonzero final power sample (~10,998 W).
After correction it checks zero power/current/voltage in actual
`Transaction.End` samples for unplug, local tag withdrawal and remote stop,
without dropping the final energy register. It also tests readiness
pause/resume, no stopped energy growth, successive cumulative registers and
an untouched second connector. Live 0.1.3 acceptance remains pending.

The 0.1.2 live HA test subsequently achieved approximately 11 kW and
0.330 kWh session energy. Closure cleared the transaction but retained
nonzero power. See METERING_INVESTIGATION.md for that evidence and the
separate cumulative-energy classification defect.

An initial local fixture overlapped a native smoke invocation because its
launcher PID differed from its child PID. That contaminated run was discarded.
Both fixtures now refuse to start on an occupied native API port. The final
browser run above was isolated, with one transaction and an Ended event.

## CI and deployment gates

The PR workflow builds both native `amd64` and `aarch64` images, then runs
the same mock-CSMS test in a container with `--network none`; only loopback
is available. It does not publish images, deploy, restart HA or create
real settlements. Refer to the PR checks for current results.

Version 0.1.1 installation and running state were verified through Supervisor.
Live direct MCP API probes received nginx HTTP 403 from peer 172.30.32.1,
which is not the permitted Supervisor Ingress peer. The ACL remains intact.
Browser rendering through actual Ingress was reported by the operator.
The isolated test entry negotiated 2.0.1 and completed initial setup.
The live bounded positive-power test passed with operator UI controls.
The approved MCP surface cannot proxy the simulator's mutating API, and a Supervisor ingress
session request was Unauthorized. No ACL bypass or broader credentials were
used. The operator must use authenticated Open Web UI for the live controls.
Version 0.1.3 installation needs separate approval.

## Reproduce

```sh
python3 -m unittest discover -s microocpp_simulator/tests -v
docker build --build-arg BUILD_ARCH=amd64 --build-arg BUILD_VERSION=0.1.3 \
  -t microocpp:test microocpp_simulator
docker build -t microocpp:smoke -f microocpp_simulator/tests/Dockerfile.smoke .
docker run --rm --network none microocpp:smoke
```

The smoke image adds the test-only `websockets` Python dependency.
No mock CSMS or test dependency is added to the runtime App image.

For browser QA, run `python3 microocpp_simulator/tests/ui_fixture.py
/path/to/prepared/native/tree` with the test-only `websockets` dependency.
It serves the real UI on loopback port 8000 and accepts only the `SIM-*`
fixture station at a loopback mock CSMS. Operate the DOCS.md procedure, stop
the UI transaction, then send SIGTERM to the fixture's Python PID to print
the received events. The fixture always stops after 180 seconds. Never run
this alongside the native smoke test or point it at Home Assistant.
