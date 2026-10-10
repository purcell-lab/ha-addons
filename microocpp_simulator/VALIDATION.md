# OCPP 2.0.1 App validation

Prepared 10 October 2026. This is a staged implementation, not a live
Home Assistant deployment or an OCPP certification claim.

## Completed in the development sandbox

- Native C++ release build from the pinned source and submodules.
- Eleven focused Python/Ingress tests: disconnected default, test identity,
  explicit acknowledgement, URL restrictions, 2.0.1 credential seeding,
  record preservation, safe ready-state reset, rebinding refusal, corrupt
  state refusal and actual nginx peer/mutation restrictions.
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

## CI and deployment gates

The PR workflow builds both native `amd64` and `aarch64` images, then runs
the same mock-CSMS test in a container with `--network none`; only loopback
is available. It does not publish images, deploy, restart HA or create
real settlements. Refer to the PR checks for current results.

Actual HA Supervisor installation, browser rendering through real Ingress,
phone usability, host resource use and interoperability with the installed
HA OCPP integration remain acceptance gates. Test namespace exclusions
must be verified before entering a backend URL.

## Reproduce

```sh
python3 -m unittest discover -s microocpp_simulator/tests -v
docker build --build-arg BUILD_ARCH=amd64 --build-arg BUILD_VERSION=0.1.0 \
  -t microocpp:test microocpp_simulator
docker build -t microocpp:smoke -f microocpp_simulator/tests/Dockerfile.smoke .
docker run --rm --network none microocpp:smoke
```

The smoke image adds the test-only `websockets` Python dependency.
No mock CSMS or test dependency is added to the runtime App image.
