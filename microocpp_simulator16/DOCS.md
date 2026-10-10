# MicroOCPP 1.6 Smart Charging

A separate Home Assistant App for OCPP 1.6J smart-charging experiments.
It does not upgrade, replace or reconfigure the OCPP 2.0.1 simulator App.
The App has its own slug, container and `/data` volume, starts disconnected,
and requires a `SIM-16-` identity.

## Capabilities and limits

- Two simulated connectors, with connector 1 used for acceptance testing.
- Native OCPP 1.6 `SetChargingProfile`, `ClearChargingProfile` and
  `GetCompositeSchedule`; no 2.0.1 translation shim.
- `TxProfile`, `TxDefaultProfile` and `ChargePointMaxProfile` tested in watts.
- Time-stepped profile increases/decreases and zero-power pause/resume
  without ending the transaction.
- Power ceiling approximately 11 kW. The existing simulator's threshold
  below 720 W pauses output; this is a simplified model, not an accurate
  three-phase AC minimum-current implementation.
- **Watt profiles only.** The existing native `setSmartChargingPowerOutput`
  callback declares power support, not current support. Ampere profiles are
  rejected. Do not assume HA's current sliders can drive this simulator.
- No V2G, ISO 15118, real hardware, certification claim, public-network TLS
  or payment functionality. This is a charging-only protocol test fixture.

The simulator varies power slightly below the cap. The downstream patch
prevents its original random variation from exceeding the requested ceiling.
Meter values refresh at sample time so a stopped simulator reports zero
power/current without wiping the energy register.

## Install and connect safely

1. After approval and merge, install **MicroOCPP 1.6 Smart Charging**.
2. Leave `backend_url` empty and start manually. Verify Open Web UI says
   OCPP 1.6 and is disconnected.
3. Prepare a separate test CSMS endpoint/HA OCPP entry pinned to 1.6.
   Select a verified free endpoint and a unique HA charger name such as
   `microocpp16`; do not reuse the 2.0.1 station identity or data.
4. Confirm test devices are excluded from physical charger and energy-control
   automations.
5. Configure the verified `ws://test-host:port[/base-path]`, without the CPID;
   retain `SIM-16-MICROOCPP-01` or another unique `SIM-16-` identity, and set
   `acknowledge_test_isolation: true`. Restart this App only.
6. Confirm `ocpp1.6` negotiation, BootNotification and smart-charging
   capabilities at the test CSMS.

| Option | Default | Meaning |
|---|---|---|
| `backend_url` | Empty | Credential-free WS test endpoint with explicit port; empty disconnects. |
| `charge_point_id` | `SIM-16-MICROOCPP-01` | Required isolated 1.6 test namespace. |
| `acknowledge_test_isolation` | false | Required before connecting. |

The first endpoint and identity are bound to the App data. Pausing preserves
this binding and existing records. Rebinding requires a deliberate data
archive/reset, not an automatic migration. Restart preserves profiles and
protocol records, but resets all plug/readiness flags. Simulated energy is
in memory and resets on process restart.

Ingress-only access and the strict Supervisor peer ACL are unchanged from
the existing App. No host ports, hardware, Docker socket or HA token are
requested. Do not weaken the ACL to make a direct MCP proxy call work.

## Bounded live test

Use connector 1 and a dedicated test token. Set Plugged and both Ready
controls, then authorise a transaction through the test CSMS or simulator.
Wait for the real OCPP 1.6 integer transaction ID before applying a TxProfile.

Send `SetChargingProfile` to connector 1 with purpose `TxProfile`, the active
`transactionId`, and `chargingRateUnit: W`. Use an absolute schedule whose
start is in the near future, or account correctly for the transaction start
when using a relative schedule.

Suggested one-minute test: 4.2 → 7 → 11 → 4.2 → 0 → 7 kW, ten seconds each.
This is a stepped ceiling, not continuous slew-rate control. Watch both the
simulator and central-system power/energy; the zero step should pause energy
growth without a StopTransaction. Unplug at the end and confirm closure.

Profiles are sent by the CSMS, not by changing the UI's displayed max-power
field. Verify GetCompositeSchedule and measured response; an Accepted reply
alone is not sufficient.

## Metering caveat

The existing HA integration can classify a zero-start cumulative register as
session-only energy and leave the cumulative sensor stale. This App does not
fix those HA semantics. Compare raw MeterValues and session deltas, especially
on second/subsequent sessions. Never seed fake energy to avoid that heuristic.

See [VALIDATION.md](VALIDATION.md) for tested scope and remaining live gates,
and [UPSTREAM.md](UPSTREAM.md) for licensing and pinned-source provenance.
