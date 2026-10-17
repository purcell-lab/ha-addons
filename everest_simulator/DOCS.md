# EVerest OCPP 2.1 Test Charger

A simulated AC charging station built from [EVerest](https://everest.github.io/latest/how-to-guides/getting-started/get-started-sw.html)
2025.10.0, with one EVSE, one Type 2 connector and a simulated EV. It
offers **OCPP 2.1 first and falls back to OCPP 2.0.1** when the central
system (CSMS) only supports 2.0.1. The CSMS chooses the version during the
WebSocket handshake; the Status page shows which one was negotiated.

This is a test tool, not a physical charger. Scope of this release:

- AC charging only (IEC 61851 simulation). No ISO 15118, no V2G or
  bidirectional power, no Plug and Charge. `max_current_export_A` is 0.
- OCPP over `ws://` with Security Profile 1. No TLS.
- Smart charging is upstream libocpp behaviour: the App does not change how
  profiles are accepted or combined.
- OCPP 2.1 support is what libocpp 2025.10.0 implements. Negotiating
  `ocpp2.1` proves the handshake and the 2.0.1-compatible messages tested
  below, not conformance with every 2.1 feature.

## Safe first start

1. Install the App after the PR is merged. Keep `csms_url` empty.
2. Start it manually and open the web UI. It should show
   **Disconnected (no CSMS URL)** and EVSE state **Unplugged**.
3. Prepare a separate **test** CSMS endpoint (for example a dedicated HA OCPP
   central system on its own port). Exclude every `SIM-` device from real
   charger automations, driver registration and BSV settlement. The App
   cannot enforce those exclusions in another integration.
4. Set `csms_url` to `ws://test-host:port[/base-path]` without the station
   ID, set a unique `SIM-EV-` charge-point ID and
   `acknowledge_test_isolation: true`. Restart the App.
5. Confirm BootNotification and the negotiated version in the test CSMS and
   on the Status page.

An empty `csms_url` always disables the connection. The station then points
at a closed loopback port (`ws://127.0.0.1:9`), so the App log shows
`connection refused` retries; nothing leaves the container.

The first connected start binds the URL and charge-point ID to this App's
data. Changing either later is refused until you set `archive_and_rebind:
true` for one start (state is moved to `/data/archive-<time>/`, never
deleted), then set it back to `false`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `csms_url` | Empty | OCPP base URL without the station ID. `ws://` on an explicit port, no credentials, query or `%` encoding. |
| `charge_point_id` | `SIM-EV-EVEREST-01` | Required `SIM-EV-` namespace, up to 36 suffix characters. Also the Basic Auth user. |
| `ocpp_version` | `2.1` | `2.1` offers `ocpp2.1, ocpp2.0.1`. `2.0.1` offers only `ocpp2.0.1`. |
| `phases` | `1` | Phases the simulated EV draws. Typical Australian homes are single-phase. |
| `max_current_a` | `32` | EVSE and EV current limit, 6 to 32 A. Also the default composite limit. |
| `tx_sample_interval_s` | `5` | Seconds between transaction MeterValues samples sent to the CSMS (`SampledDataTxUpdatedInterval`), 1 to 60. Change it in the App configuration and restart; no rebuild. |
| `acknowledge_test_isolation` | `false` | Operator assertion that the endpoint and downstream automations are test-only. Required for a nonempty `csms_url`. |
| `archive_and_rebind` | `false` | One-start operator action to archive state and allow a new binding. |

**Basic Auth.** Security Profile 1 sends a random 32-character password,
generated once in `/data/basic-auth-password`. The App never logs or shows
it. Use a test CSMS that does not require Basic Auth (HA OCPP does not), or
treat a CSMS that does as out of scope for this release.

## Using the simulated EV

The Status page has four controls. They only drive EVerest's car simulator;
the UI cannot send OCPP messages or charging profiles.

- **Plug in**: the EV connects and waits for authorisation (`AuthRequired`).
  Start charging from the CSMS with RequestStartTransaction.
- **EV pause / EV resume**: the EV stops or restarts drawing power. The
  transaction stays open.
- **Stop and unplug**: the EV unplugs, which ends any transaction.

Remote stop (RequestStopTransaction) ends the transaction and power falls
to 0 W; then use **Stop and unplug**.

## Charging profiles

The **Last received charging profile** panel shows the latest
SetChargingProfile of any purpose (TxProfile, TxDefaultProfile,
ChargingStationMaxProfile, ChargingStationExternalConstraints), with its
purpose, id and stack level, from the CSMS message log, its receipt time (UTC), and the station's actual reply
(`Accepted` or `Rejected`, with reason). **Recent profile requests** lists the
last ten SetChargingProfile and ClearChargingProfile requests. **Effective
limit** is EVerest's composite schedule for EVSE 1.

**Watt profiles on a single-phase EV: set `numberPhases: 1`.** libocpp
assumes 3 phases when a period has no `numberPhases`, so a 7,360 W period
becomes 10.67 A per phase, and anything below 4,140 W falls under the 6 A
minimum and pauses charging. Amp-based profiles are not affected.

**Watt profiles on a 3-phase station: set `numberPhases: 3`.** From 0.1.3
EVerest takes its composite schedule in amps, so a 3-phase watt limit is
applied in full (25 kW is 32 A per phase). Earlier versions applied a third
of it, and limits below about 12.4 kW paused charging.

Measured power is a few per cent below a watt limit because the simulated
supply sits slightly below 230 V. The current follows the limit exactly.

**Transaction samples.** The station sends a TransactionEvent with
MeterValues every `tx_sample_interval_s` seconds while charging (default 5
from 0.1.4; 0.1.2 and 0.1.3 sent one every second, earlier versions every
10 s). On the Green, CitrineOS stored about one TransactionEvent every 2 s,
so 1 s samples built a queue over a long session and delayed the Ended event
by minutes.

## Security boundaries

The UI uses Home Assistant Ingress authentication. nginx on port 8099
accepts only the Supervisor Ingress peer (`172.30.32.2`), checked on the
actual connection, not a forwarded header. Everything else (UI service,
MQTT broker) listens on loopback only. The upstream EVerest admin panel is
not shipped. Only four fixed EV-simulator POST endpoints exist; all other
paths are read-only. No host ports, host networking, hardware access, HA API
token or Docker socket are requested. Do not add a port mapping or widen the
ACL to make direct probes pass; use **Open Web UI**.

## Storage

All state is in the App's `/data`: OCPP message logs
(`everest/ocpp_logs`, rotated at 1 MiB, 3 files), the core database with
transactions and installed charging profiles (`everest/ocpp201/cp.db`,
kept across restarts), and the generated EVerest configuration. The device
model is rebuilt from the options on every start.

## Install size

Home Assistant pulls a prebuilt image for its architecture
(`ghcr.io/purcell-lab/{arch}-everest-simulator`, about 310 to 340 MB) rather
than building locally from EVerest's 4.3 GB build image. The image is
published only through the approval-gated tag process in `RELEASE.md`.
