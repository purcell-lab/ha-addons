# OCPP 2.0.1 App validation

Updated 10 October 2026. Version 0.1.0 was installed and started disconnected
on Home Assistant; version 0.1.1 is a staged startup correction. Neither
version is an OCPP certification claim.

## Completed in the development sandbox

- Native C++ release build from the pinned source and submodules.
- Twelve focused Python/Ingress tests: disconnected default, test identity,
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

## CI and deployment gates

The PR workflow builds both native `amd64` and `aarch64` images, then runs
the same mock-CSMS test in a container with `--network none`; only loopback
is available. It does not publish images, deploy, restart HA or create
real settlements. Refer to the PR checks for current results.

Version 0.1.0 installation and running state were verified through Supervisor.
Live direct MCP API probes received nginx HTTP 403 from peer 172.30.32.1,
which is not the permitted Supervisor Ingress peer. The ACL remains intact.
Browser rendering through actual Ingress, phone usability, the 0.1.1 live
update and interoperability with the installed HA OCPP integration remain
acceptance gates. Test namespace exclusions must be verified before entering
a backend URL.

## Reproduce

```sh
python3 -m unittest discover -s microocpp_simulator/tests -v
docker build --build-arg BUILD_ARCH=amd64 --build-arg BUILD_VERSION=0.1.1 \
  -t microocpp:test microocpp_simulator
docker build -t microocpp:smoke -f microocpp_simulator/tests/Dockerfile.smoke .
docker run --rm --network none microocpp:smoke
```

The smoke image adds the test-only `websockets` Python dependency.
No mock CSMS or test dependency is added to the runtime App image.
