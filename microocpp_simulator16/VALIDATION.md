# OCPP 1.6 smart-charging validation

Prepared 10 October 2026. This is a separate, staged App; it has not been
installed or connected to live Home Assistant.

## Local acceptance

The pinned native simulator connects only to a loopback mock CSMS using
`ocpp1.6` and `SIM-16-MICROOCPP-01`. The test authorises one connector 1
transaction and uses real OCPP requests and responses, not direct assignment
of the simulator's power limits.

| Check | Tested behaviour |
|---|---|
| Protocol and identity | 1.6 BootNotification, correct test identity, CSMS identity mutation rejected |
| Capability advertisement | SmartCharging and Power units reported |
| Unsupported units | Ampere profile not accepted by this power-only callback |
| TxDefaultProfile | Initial 4,200 W limit applied |
| TxProfile | Six scheduled periods applied within the same transaction |
| Zero-power period | No StopTransaction; energy holds steady; next period resumes |
| MeterValues | On-wire samples contain each requested power plateau, including zero |
| ChargePointMaxProfile | 5,000 W station ceiling constrains a 7,000 W TxProfile |
| GetCompositeSchedule | Effective schedule reflects the station ceiling |
| ClearChargingProfile | Falls back to default, then factory limit after clearing |
| validTo expiry | Temporary cap expires without another control command |
| Stop | StopTransaction with preserved energy and zero final power/current |
| Connector 2 | Idle with zero energy |
| Restart disconnected | No fallback connection; power zero |

Example native readings from the stepped TxProfile:

| Limit | Measured power | Register |
|---:|---:|---:|
| 4,200 W | 4,190 W | 2 Wh |
| 7,000 W | 6,993 W | 8 Wh |
| 11,000 W | 10,997 W | 17 Wh |
| 4,200 W | 4,197 W | 27 Wh |
| 0 W | 0 W | 30 Wh |
| 7,000 W | 7,000 W | 32 Wh |

Small differences below the cap are the simulator's intentional variation.
Exact Wh depends on scheduling. The native regression uses four-second
periods and one-second metering; runtime defaults remain ten-second metering.

The expiry test initially failed: the pinned evaluator did not schedule a
recalculation for `validTo` when a final period had no next boundary.
A small downstream correction adds that boundary and treats it as expired.
This is documented in UPSTREAM.md rather than attributed to unmodified upstream.

Twelve focused option/persistence/Ingress tests cover disconnected default,
safe namespace, explicit isolation acknowledgement, URL restrictions, state
retention, no silent endpoint rebinding and the actual nginx peer ACL.
The existing 2.0.1 App directory and workflow are unchanged.

## Reproduce

```sh
python3 -m unittest discover -s microocpp_simulator16/tests -v
docker build --build-arg BUILD_ARCH=amd64 --build-arg BUILD_VERSION=0.1.0 \
  -t microocpp16:test microocpp_simulator16
docker build -t microocpp16:smoke -f microocpp_simulator16/tests/Dockerfile.smoke .
docker run --rm --network none microocpp16:smoke
```

CI executes the native image and smoke tests on both amd64 and aarch64.
It does not publish an image, modify HA or connect to an external CSMS.
For a prepared local source build, run
`python3 microocpp_simulator16/tests/smart_charging.py /path/to/native/tree`.
Only the test environment needs the Python `websockets` package.

## Outstanding live acceptance

- Approve merge and disconnected App installation separately.
- Verify the App's authenticated Ingress UI and 1.6 labels.
- Establish an isolated HA OCPP 1.6 test entry and unique device identity.
- Compare the same bounded TxProfile against simulator and HA meter readings.
- Confirm pause retains the transaction and final stop clears HA power.
- Track HA's known cumulative-versus-session-energy classification separately.

Recurring schedules, multi-connector load allocation, sustained offline
operation, profile persistence across a restart, and full conformance are
not claimed as validated. Neither V2G nor 2.0.1 smart charging is provided.
