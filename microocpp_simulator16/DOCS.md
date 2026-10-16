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
| `archive_and_rebind` | false | Archive existing state, then bind the configured destination. |

The first endpoint and identity are bound to the App data. Pausing preserves
this binding and existing records. Rebinding is never automatic.
Set `archive_and_rebind: true` and the new destination together to rebind:
on start the App moves `mo_store` and `test-identity.json` into
`/data/archive-<UTC timestamp>/` (never deleted), then binds the new destination.
Set the option back to `false` afterwards; each start with it `true` archives again. Restart preserves profiles and
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

### Plugfest-style schedule

The automated acceptance suite also runs one seven-period TxProfile:
11 → 7 → 11 → 3 → 0 → 11 → 0 kW. It represents import-limit and
household-load clipping, restoration and pause, adapted to this App's
charging-only watt interface. Five-minute fixture windows run at four
seconds each in CI. It checks timestamp-matched OCPP power and integrated
energy, not just profile acceptance.

This is not the full CSIP-AUS/HAEO/OCPP 2.1 demonstration and does not support
its negative-power V2G periods. See [VALIDATION.md](VALIDATION.md) for the
explicit fixture inputs, timing, energy tolerances and live-test exclusions.

## Metering caveat

The existing HA integration can classify a zero-start cumulative register as
session-only energy and leave the cumulative sensor stale. This App does not
fix those HA semantics. Compare raw MeterValues and session deltas, especially
on second/subsequent sessions. Never seed fake energy to avoid that heuristic.

See [VALIDATION.md](VALIDATION.md) for tested scope and remaining live gates,
and [UPSTREAM.md](UPSTREAM.md) for licensing and pinned-source provenance.

## Received TxProfile on Status

Version 0.1.1 adds a read-only, automatically refreshed JSON panel for each
connector on the Status page. Copy JSON copies the full received
`SetChargingProfile` payload with two-space indentation. No profile-editing
or sending controls are added.

The panel captures the latest **received TxProfile** via MicroOcpp's public
request observer. It is not an active-profile view: receipt does not prove
acceptance, and a rejected request replaces the previous diagnostic record.
The timestamp is the simulator host's UTC clock at receipt. Acceptance is
explicitly not recorded. Use measured power and the CSMS response to verify
operation.

Records remain visible after a transaction ends or a profile is cleared, but
reset when the simulator restarts. No earlier profiles can be recovered after
installing this version. The next received TxProfile populates the panel.
TxDefaultProfile and ChargePointMaxProfile do not replace it.

Each connector retains at most one payload, limited to 4 KiB of serialized JSON.
Larger requests show a diagnostic-size warning instead of partial JSON; native
OCPP processing is unchanged. An API failure hides the last payload and retries,
rather than presenting stale data as freshly checked. Clipboard-denied browsers
select the JSON for manual copying. All content is rendered as text.

The endpoint is GET-only at `/api/connector/{1|2}/txprofile` behind the existing
Home Assistant Ingress boundary. No extra port, network permission or HA access
is introduced. This feature applies only to the OCPP 1.6 App.
