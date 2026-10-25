# EVerest DC V2G Test Charger

## Staged CitrineOS migration

Version 0.1.4 adds `csms_basic_auth_password`, an optional provisioned
32-character lowercase hexadecimal test credential. Set the same credential
in the dedicated CitrineOS station record through the isolated server options.
Do not paste it into issues, logs, URLs or evidence bundles. An empty option
keeps the original locally generated password; supplying a value never replaces
that original file.

Changing the CSMS still requires an explicit `archive_and_rebind` operation.
First verify that no transaction is active, stop the App, preserve the prior
options and state, and obtain migration approval. Archive old state rather than
delete it. Clear `archive_and_rebind` after the single migration so it does not
archive again on the next restart. Do not restore old transaction state onto a
different CSMS. No real charger or BSV integration is included.

The full demonstration scope and outstanding acceptance gates are in
[`ocpp-plugfest: plugfest-lab/ACCEPTANCE.md`](https://github.com/purcell-lab/ocpp-plugfest/blob/main/plugfest-lab/ACCEPTANCE.md).
The new image must be published through the approved release workflow before
installation. A staged manifest is not proof that its image is available.

A simulated bidirectional DC charging station built from
[EVerest](https://everest.github.io/latest/how-to-guides/getting-started/get-started-sw.html)
**2026.10.0-rc1** (a release candidate, compiled from source; 0.1.13 and
earlier used the 2025.10.0 demo image), with one EVSE, one CCS2 connector
and a simulated EV. The charger and the EV talk **ISO 15118-20 with the
DC_BPT (bidirectional power transfer) service over mutual TLS 1.3**, so a
central system (CSMS) can both charge and discharge the vehicle.

The station offers **OCPP 2.1 first and falls back to OCPP 2.0.1** when the
CSMS only supports 2.0.1. The Status page shows the negotiated version.
From 0.2.0 EVerest's OCPPmulti module runs OCPP (it replaces OCPP201).

| Negotiated | What the CSMS can do |
|---|---|
| `ocpp2.1` | Charge and discharge. Send a TxProfile in W with `operationMode: CentralSetpoint` and a signed `setpoint` (negative is discharge, V2G export to the grid). Send DER controls (SetDERControl, GetDERControl, ClearDERControl); the station accepts, reports and records them but does not apply them to power (see DER control). |
| `ocpp2.0.1` | **Charging only.** OCPP 2.0.1 has no discharge or setpoint fields, so the station only applies charging limits. No DER messages. |

This is a test tool, not a physical charger. It sits beside the AC
**EVerest OCPP 2.1 Test Charger** App and does not replace it.

## Scope

- DC charging and discharging between the simulated charger and EV, using
  the ISO 15118-20 Dynamic control mode. Power, voltage and energy come
  from EVerest's DC supply simulator, not from real hardware.
- OCPP over `ws://` with Security Profile 1. No TLS to the CSMS.
- OCPP 2.1 DER control messages are accepted, reported and shown, never
  applied to power.
- No Plug and Charge. The test PKI only secures the ISO 15118 link inside
  the App.
- Negotiating `ocpp2.1` and passing the tests in VALIDATION.md proves the
  messages tested there. It does not prove OCPP 2.1 or ISO 15118-20
  conformance, and a CSMS receiving a reply is not proof that it accepted
  or acted on it.

## Safe first start

1. Install the App after the PR is merged. Keep `csms_url` empty.
2. Start it manually and open the web UI. It should show **Disconnected (no
   CSMS URL)** and EVSE state **Unplugged**. The first start generates the
   test PKI (a few seconds).
3. Prepare a separate **test** CSMS endpoint. Exclude every `SIM-` device
   from physical charger automations, driver registration and BSV
   settlement. The App cannot enforce those exclusions in another
   integration.
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

From 0.1.1, state created only by disconnected starts never reached any
CSMS, so the first connected start moves it to `/data/archive-<time>/` and
binds without the extra step. The App logs `First connection: state from
disconnected starts moved to archive-<time>/`. Unbound state from 0.1.0
still needs `archive_and_rebind` once.

## Options

| Option | Default | Meaning |
|---|---|---|
| `csms_url` | Empty | OCPP base URL without the station ID. `ws://` on an explicit port, no credentials, query or `%` encoding. |
| `charge_point_id` | `SIM-EV-EVEREST-V2G-01` | Required `SIM-EV-` namespace, up to 36 suffix characters. Also the Basic Auth user. |
| `ocpp_version` | `2.1` | `2.1` offers `ocpp2.1, ocpp2.0.1`. `2.0.1` offers only `ocpp2.0.1`. |
| `max_power_kw` | `25` | Charger rating in both directions, 3 to 25 kW. Also the default composite limit and the DER nameplate. The simulated battery is at 380 V, so 25 kW is 66 A DC. Upstream's simulated board allows only 11.04 kW discharge and 22.08 kW charge by default; the App sets its limits to the rating (`caps_max_current_A`, up to 109 A per phase). |
| `acknowledge_test_isolation` | `false` | Operator assertion that the endpoint and downstream automations are test-only. Required for a nonempty `csms_url`. |
| `archive_and_rebind` | `false` | One-start operator action to archive state and allow a new binding. |
| `ha_control` | `false` | Starts the Home Assistant control bridge (see Home Assistant control). |
| `tx_sample_interval_s` | `5` | Seconds between transaction MeterValues samples sent to the CSMS (`SampledDataTxUpdatedInterval`), 1 to 60. Change it in the App configuration and restart; no rebuild. |

**Basic Auth.** Security Profile 1 sends a random 32-character password,
generated once in `/data/basic-auth-password`. The App never logs or shows
it. Use a test CSMS that does not require Basic Auth (HA OCPP does not).

## Using the simulated EV

The Status page has three controls. They only drive EVerest's EV simulator;
the UI cannot send OCPP messages, choose direction or set power. Direction
and power come only from the CSMS.

- **Plug in**: the EV runs SLAC, opens the ISO 15118-20 TLS session, offers
  DC_BPT and waits for authorisation. Start the transaction from the CSMS
  with RequestStartTransaction within 55 s: from 0.2.0 (EVerest 2026.10)
  the charger stops an ISO 15118-20 authorisation wait after 55 s
  (V2G_SECC_Ongoing_Performance_Time); 0.1.10 to 0.1.13 waited 3 minutes,
  earlier versions 60 s. A later start is handled by the EV watchdog below.
  Cable check and pre-charge take about 15 s.
- **EV stop session**: the EV ends the ISO 15118 session and unplugs.
- **Unplug now**: immediate unplug, which ends any transaction.

Live readings refresh every second and show state, direction, signed power
(negative is discharge), meter import and export energy, DC voltage and
current, and the rated power. Green means import (charging) and blue means
export (discharge, V2G); every value also carries a +/- sign, an arrow icon
and a text label, so colour is never the only cue. A bidirectional bar and a
two-minute trend show power against the rated limit. The discovery self-test
panel is at the bottom of the page.

The charger sends OCPP transaction meter samples to the CSMS every
`tx_sample_interval_s` seconds (`SampledDataTxUpdatedInterval`, default 5
from 0.1.7; earlier versions sent one every second, which outran CitrineOS
on the Green over long sessions).

Each plug-in starts a fresh EV ISO 15118 stack. In upstream PyEvJosev, a
failed discovery leaves the EV stack idle without returning, so every
later plug-in did nothing until a restart. The App patches the module
(UPSTREAM.md): a new plug-in replaces a stack that is still running and
logs `ha-everest: EV ISO 15118 stack stopped (replaced by a new plug-in)`;
other EV stack errors are logged the same way and the next plug-in
retries. The Status page and the HA
status object count these restarts as `ev_stack_restarts`.

**EV watchdog.** If the EV's ISO 15118 session ends before charging, the
EV gives up for the rest of that plug-in and logs `maximum number of SDP
retry cycles (1) is now reached`; the charger keeps the connector in
`Preparing` at 0 W and a new plug-in is refused. The usual cause is no
authorisation within 55 s (3 minutes up to 0.1.13): the charger then fails
the session. 5 s after that line the App unplugs the EV, waits 10 s and plugs
it in again, as you would by hand, so a later RequestStartTransaction
still charges. It logs `EV watchdog: ...` and never acts while power flows,
while unplugged, or when an EV command from the UI or HA came at about the
same time. After 3
re-plugs without a session that delivers power it stops and asks for a
manual unplug and plug-in. A transaction that had already started ends
with the unplug; start a new one. The Status page shows a notice, and the
status object reports `ev_session` (`ok`, `gave_up` or `recovering`) and
`ev_last_recovery`.

## Discovery diagnostics

About 3 s after the charger's SDP server starts, the App runs a discovery
self-test across the private link and logs one line, for example:

```
Discovery self-test PASSED: unicast=reply multicast=reply v2g0=[in:request,out:response] v2g1=[out:request,in:response] (at start)
```

- **multicast** sends an SDP request to `ff02::1` via `v2g1`, as the
  simulated EV does. It runs first.
- **unicast** sends the same request from `v2g1` to the charger's
  link-local address on `v2g0`, the path CI's firewall probe uses.
- **v2g0** and **v2g1** list the SDP frames a packet counter saw on each end
  (`in` or `out`, request or response). A request seen leaving `v2g1` but
  never arriving on `v2g0` points at the link; a request arriving on `v2g0`
  without a response points at the SDP server or the firewall. The counter
  needs a raw packet socket; where the runtime refuses one, it shows
  `capture-unavailable` and the two results still stand.

The charger (libiso15118) opens a session for every request it answers
and ignores later requests until that session ends. After each reply the
self-test connects to the offered TCP port and sends an invalid header, so
the charger closes the session and the next plug-in is not blocked. A
test whose session could not be released fails with
`session-release=failed`. On request, the self-test runs only while the
simulated EV is unplugged.

If the simulated EV is unplugged while the charger waits for
authorisation, upstream libiso15118 never ends that charger session and
ignores every later discovery request. The App detects this, logs
`ha-everest: the charger is ignoring discovery ... Restart the App to clear
it.`, adds `charger=ignoring-discovery(restart the App)` to the self-test
line, and sets `charger_ignoring_discovery` on the HA status object.
Authorise or stop the session from the CSMS before unplugging to avoid it.

The line ends with `unscoped-multicast-via=<interface>`: the interface
a request to `ff02::1` would leave by if the sender did not choose one,
read from the routing table without sending anything. Upstream Josev did
not choose one, and on Home Assistant OS this is `eth0`, which is why
0.1.0 and 0.1.1's EV never reached the charger there. 0.1.2 patches the EV to send
on `v2g1`, and the firewall drops SDP that would leave by any other
interface (counter `SDP kept on the private link`).

On failure the App also logs `Discovery diagnostics:` with the full
snapshot. The Status page's Discovery self-test panel shows the latest
result, a Run self-test button and the snapshot: link state and sysctls,
IPv6 addresses (with tentative and duplicate flags), multicast groups
joined on each end, UDP listeners on port 15118, and packet counters for
every firewall rule, including `dropped by policy`. The self-test sends two
SDP requests on the private link only and changes nothing.

## Home Assistant control

With `ha_control: true` the App runs an outbound-only bridge to Home
Assistant Core, so an HA MCP client or automation can operate it without
the Ingress UI. It opens no port and adds no inbound path.

- **Status object** `sensor.<charge_point_id>_v2g_app` (for example
  `sensor.sim_ev_everest_v2g_01_v2g_app`): EVSE state as the state, with
  attributes for the negotiated OCPP version, direction, power, energy,
  `ev_stack_restarts`, `ev_session`, `ev_last_recovery` and the last
  self-test summary. Refreshed every
  30 s and after each command. It is a plain state object, not a
  registered entity, and disappears from the state list after an HA
  restart until the bridge republishes it.
- **Commands** arrive as HA event `everest_v2g_command` with data
  `{"charge_point_id": "<id>", "command": "<name>"}`. `<name>` is one of
  `plugin`, `stop`, `unplug`, `selftest` or `diagnostics`. Other IDs are
  ignored; other names are refused. At most one command each 2 s.
- **Results** are fired as event `everest_v2g_command_result` with the
  command, `ok` and the App's reply.

From an HA MCP client: fire `everest_v2g_command` with the event tool,
then read the status object. The bridge reuses the same three EV
controls and the self-test as the Status page; it cannot send OCPP
messages, change options, or set direction or power.

`homeassistant_api: true` in the manifest gives the App a Supervisor
token for Core's API whether or not `ha_control` is on. With it off the
token is unused. The bridge calls only the WebSocket event subscription,
`POST /api/states/<status object>` and `POST /api/events/everest_v2g_command_result`.

## Charging and discharging profiles

Send a TxProfile in W after the session reaches **Charging** (see the
limitations). A working OCPP 2.1 example, 20 s per step:

```json
{"startPeriod": 0,  "limit": 11000, "dischargeLimit": -11000, "setpoint": 6000,  "operationMode": "CentralSetpoint"},
{"startPeriod": 20, "limit": 11000, "dischargeLimit": -11000, "setpoint": -5000, "operationMode": "CentralSetpoint"},
{"startPeriod": 40, "limit": 11000, "dischargeLimit": -11000, "setpoint": 3000,  "operationMode": "CentralSetpoint"}
```

This measured +6,000 W, then -5,000 W (export), then +3,000 W, in CI and
live from Home Assistant. With the HA OCPP integration, pass the whole
profile through `ocpp.set_charge_rate` (it is sent unchanged to EVSE 1):

```yaml
action: ocpp.set_charge_rate
data:
  devid: SIM-EV-EVEREST-V2G-01
  conn_id: 1
  custom_profile:
    id: 210301
    stackLevel: 0
    chargingProfilePurpose: TxProfile
    chargingProfileKind: Absolute
    transactionId: "<current transaction id>"
    chargingSchedule:
      - id: 1
        chargingRateUnit: W
        startSchedule: "2026-10-10T21:30:35Z"
        chargingSchedulePeriod:
          - {startPeriod: 0, limit: 11000, dischargeLimit: -11000, setpoint: 6000, operationMode: CentralSetpoint}
          - {startPeriod: 20, limit: 11000, dischargeLimit: -11000, setpoint: -5000, operationMode: CentralSetpoint}
          - {startPeriod: 40, limit: 11000, dischargeLimit: -11000, setpoint: 3000, operationMode: CentralSetpoint}
```

The transaction id is in the charger's Transaction Id sensor. HA raises an
error if the station does not reply `Accepted`. During export, HA's import
power sensor shows a negative value; use the export energy register for
exported energy. The
**Last received charging profile** panel shows the newest
SetChargingProfile of any purpose, with its purpose, id and stack level, and the station's
reply, and **Effective limit** shows EVerest's composite schedule for EVSE
1, including limit, discharge limit and setpoint. A ChargingStationMaxProfile
on EVSE 0 is merged into that composite by libocpp.

### Known EVerest limitations

These are upstream behaviours, found in testing on EVerest 2025.10.0 and
recorded in VALIDATION.md. The App does not hide them. 0.2.0 runs EVerest
2026.10.0-rc1: its CI acceptance run repeats the TxProfile steps
(charge, 0 W, discharge, reversals) and they must still pass, but the other
items have not been re-measured on 2026.10 yet; treat them as possible.

- **Charging-only periods do not limit discharge.** OCPP201 in EVerest
  2025.10.0 turns `limit` into an import limit and `setpoint` into a
  setpoint, but sends no export limit, so a period without a setpoint
  leaves discharge unbounded: a charging-only 0 W limit after a discharge
  setpoint kept exporting. To hold the EV at 0 W, send a CentralSetpoint
  period with `setpoint: 0` (honoured since 0.1.8), for example
  `{"limit": 11000, "dischargeLimit": -11000, "setpoint": 0, "operationMode": "CentralSetpoint"}`.
- **Small charging setpoints are rounded down to 0 W.** A charging
  setpoint below about 1.4 kW (the simulated board's 6 A minimum on one
  phase) gives 0 W. Before 0.1.8 it, and a 0 W setpoint, left the EV at its
  previous power.
- **Give every period a setpoint.** EVerest applies the first setpoint
  before its period starts and keeps the last one after it ends, so a
  period without a setpoint inherits a neighbour's.
- **Send profiles after Charging starts.** A profile that arrives during
  pre-charge or the switch to charging can be held at 0 W.
- **Direction changes show a short transient.** For one to two seconds after
  a direction change the simulator can report power above the rating
  (13.5 kW was seen once). Energy totals stay within 10 per cent of the
  integrated power.
- **Station-level limits come through EVSE 1 only.** libocpp reports the
  EVSE 0 composite as per-phase shares, and EVerest 2025.10.0 reads the L1
  share as the total, which capped every target at a third of the rating.
  The App therefore applies OCPP limits through EVSE 1, whose composite
  already includes station-level profiles. OCPP201 (up to 0.1.13) computed
  the EVSE 0 composite every 10 s and warned `Can not apply external limits!
  No evse energy sink configured for evse_id: 0`, which 0.1.10 to 0.1.13
  dropped from the log. OCPPmulti (0.2.0) warns once at start (`No evse
  energy sink configured for evse_id 0, composite schedules for it are not
  applied as external limits`); that line is expected.

### Power rating in the device model

A CSMS learns the rating from GetBaseReport (CitrineOS-HA from 0.7.2 asks
when the station comes online). EVerest builds the EVSE component itself
(2025.10.0 and 2026.10.0-rc1): EVSE 1 `Power` reports only an `Actual`
attribute and a `maxLimit` taken from the simulated board's AC limits (from
0.2.0 the per-phase allowance x 3 x 230 V, 75,210 W at 25 kW; 88,320 W up
to 0.1.13), not `max_power_kw`, and the App cannot change it. The
App therefore adds `Power` to the `ChargingStation` component, from
`max_power_kw`: `MaxSet` = rating in W (charging), `MinSet` = minus the
rating (discharge, negative as in OCPP 2.1), and the same values as
`maxLimit` and `minLimit`. Read the per-station `MaxSet`/`MinSet`
attributes: CitrineOS v2.0.1 keeps a single `maxLimit` per variable name for
all stations, and within this station's report EVSE `Power` comes later
and overwrites it. The DER nameplate (`DCDERCtrlr` `MaxW`, `MaxVA`,
`MaxChargeRateW`, see DER control) carries the rating too.

### EV charging needs

The station sends no NotifyEVChargingNeeds, by design. EVerest's
ISO 15118-20 module (Evse15118D20) publishes the EV's needs on its
`extensions` interface, and the OCPP module (OCPP201, OCPPmulti from 0.2.0)
sends them only when its `extensions_15118` requirement is connected to it
(with an EVSE mapping on the ISO 15118 module); the App does not connect
it. CitrineOS v2.0.1
accepts charging needs only for AC with `acChargingParameters` or DC with
`dcChargingParameters`. For ISO 15118-20 EVerest sends `DC_BPT` (or `DC`)
with `v2xChargingParameters` only, so CitrineOS answers Rejected and stores
nothing, and libocpp v0.30.3 on OCPP 2.1 then stops the transaction
(`ReqEnergyTransferRejected`, K18.FR.23). On OCPP 2.0.1 the message is not
valid 2.0.1. Connecting it would end every V2G session; it needs CitrineOS
support for `v2xChargingParameters` first (UPSTREAM.md). The EV's
discharge limits (Josev: 66 A, 25 kW) are therefore not reported over OCPP.

### CSMS requirements

The station asks the CSMS for the certificate status of the ISO 15118
chain. The CSMS must answer GetCertificateStatus with a valid
`status` field (for example `Failed`). libocpp in EVerest 2025.10.0 aborted
the station process on a reply without one; this has not been re-checked on
2026.10.0-rc1, so keep answering with a status.

## Dynamic pricing

The station shows prices; it never changes charging because of them. From
0.1.11 the device model enables costs and tariffs in Australian dollars:

| Device-model variable | Value |
|---|---|
| `TariffCostCtrlr` `Available` (instances `Tariff` and `Cost`) | `true` (ReadOnly, so set in the generated device model) |
| `TariffCostCtrlr` `Enabled` (instances `Tariff` and `Cost`) | `true` |
| `TariffCostCtrlr` `Currency` | `AUD` |
| `TariffCostCtrlr` `NumberOfDecimalsForCostValues` | `4` |
| `CustomizationCtrlr` `CustomImplementationEnabled` (instance `org.openchargealliance.costmsg`, California Pricing) | `true` |

The device model is rebuilt on every start, so a CSMS SetVariables change
to these lasts until the next restart.

What works (libocpp v0.30.3 and EVerest 2026.10.0-rc1, OCPP 2.1 and 2.0.1;
the CI acceptance run checks the items below on both):

- **CostUpdated** is accepted during a transaction. With California Pricing
  `customData` (vendor `org.openchargealliance.costmsg`) the station also
  reads the current and next-period prices and the price text. The
  **Price** panel on the Status page shows the latest one: total cost,
  current price per kWh (and per hour, if sent), next-period price and its
  start time, the price text and the cost timestamp. Example:

  ```json
  {"totalCost": 1.23, "transactionId": "<transaction id>",
   "customData": {"vendorId": "org.openchargealliance.costmsg", "state": "Charging",
                  "chargingPrice": {"kWhPrice": 0.2512},
                  "nextPeriod": {"atTime": "2026-10-18T05:30:00Z", "chargingPrice": {"kWhPrice": 0.31}},
                  "priceText": "0.2512 AUD/kWh now, 0.31 AUD/kWh from 15:30"}}
  ```

  A `totalCost` in a TransactionEventResponse is shown the same way, and an
  `updatedPersonalMessage` sent with it becomes the price text. Prices
  are kept to 4 decimals and cut off, not rounded, beyond that (EVerest's
  conversion).
- **Price schedules in charging profiles** (`absolutePriceSchedule`,
  `priceLevelSchedule`, ISO 15118-2 `salesTariff`) are accepted and stored
  with the profile, but EVerest does not act on them. The **Price** panel
  shows the first 6 intervals of the schedule in the last received
  charging profile (start time, duration, energy price or price level) and
  how many there are. A profile over 8 KiB (a 48 h price schedule is about
  13 KiB) is shown under **Last received charging profile** without its
  price information, so the power setpoint schedule stays readable; the
  note above it names what was left out and the full size.
- **OCPP 2.1 tariffs are not implemented.** libocpp (v0.30.3, and still in
  EVerest 2026.10.0-rc1) answers SetDefaultTariff, GetTariffs, ClearTariffs
  and ChangeTransactionTariff with the CALLERROR `NotImplemented`, whatever
  the device model says.

**Recent pricing messages** on the Status page (and `pricing` in
`/api/profiles`) lists the last ten CostUpdated and tariff requests with
the station's reply: `Replied` for CostUpdated (its response has no
status), `CallError` with the reason for the tariff messages. They are
listed apart from the profile requests, so frequent cost updates never push
a profile out of view. `/api/status` carries the parsed `session_cost`, and
`/api/profiles` the `price_schedules` of the latest profile. Each profile
event also carries its own `price_schedules`, and `omitted` lists the price
keys left out of an oversized `payload`.

The **Live readings** show the price now and the next price with its start
time. All times on the Status page are in the browser's time zone, with the
zone shown (AEDT in Canberra in October); the API keeps UTC.

Enabling Tariff and Cost does not change authorisation, transactions or
smart charging: libocpp uses these variables only when it handles
CostUpdated and the cost fields of a TransactionEventResponse, and passes
the result to EVerest's session cost.

## DER control (OCPP 2.1)

From 0.2.0 the station implements OCPP 2.1 DER control (functional block R,
libocpp in EVerest 2026.10.0-rc1) for EVSE 1, whenever `ocpp2.1` is
negotiated. It is a test target for a CSMS's DER messages: the station
answers, stores and reports DER controls, and the Status page shows the
active ones, but **no DER control changes charging or discharging power**.
Use TxProfile setpoints for power.

What a CSMS can send:

| Message | Station reply |
|---|---|
| SetDERControl | `Accepted` for any of the 22 OCPP 2.1 control types (`EnterService`, `FreqDroop`, `FreqWatt`, `FixedPFAbsorb`, `FixedPFInject`, `FixedVar`, `Gradients`, `HFMustTrip`, `HFMayTrip`, `HVMustTrip`, `HVMomCess`, `HVMayTrip`, `LimitMaxDischarge`, `LFMustTrip`, `LVMustTrip`, `LVMomCess`, `LVMayTrip`, `PowerMonitoringMustTrip`, `VoltVar`, `VoltWatt`, `WattPF`, `WattVar`), with `supersededIds` when it replaces a lower-priority control of the same type. `Rejected` with reason `InvalidValue` when the control field does not match `controlType` (`ControlFieldMismatch`), a default control has `startTime` or `duration`, or `EnterService` or `Gradients` is not a default. When a scheduled control starts or ends, the station sends NotifyDERStartStop (`started` true or false); a control whose `startTime` has already passed starts at once. |
| GetDERControl | `Accepted`, then a ReportDERControl with the matching controls (by `isDefault`, `controlType`, `controlId`) and the same `requestId`; `NotFound` when nothing matches. |
| ClearDERControl | `Accepted` or `NotFound`, by `controlId`, or by `controlType`; with neither, every control with the given `isDefault` (always `Accepted`). |

The device model has the DER component (GetBaseReport, GetVariables):
`DCDERCtrlr` on EVSE 1 with `Available` and `Enabled` `true`
(`Enabled` is ReadWrite: `false` stops the station passing the active set
on, until the next restart), `ModesSupported` (the 22 types), `MaxW`,
`MaxVA` and `MaxChargeRateW` (the rating, `max_power_kw`), and
`InverterManufacturer` `purcell-lab`, `InverterModel` `EVerest-SIL-DC-V2G`.

What the simulator does with them: libocpp keeps the controls in the core
database (`/data/everest/ocpp201/cp.db`, so they survive restarts and
upgrades until cleared) and computes the active set. EVerest's OCPPmulti
module passes that set, on every change and every 60 s
(`GridSupportHeartbeatS`), to the App's `HaGridSupport` module, which
records it and forwards it unchanged to EVerest's ISO 15118-20 charger
module (Evse15118D20). The **DER control** panel on the Status page shows
the declared types, the active controls (type, id, priority, start and
duration, for example `50 % of rated discharge power`) and the last ten
DER requests with the station's replies; `/api/status` carries `der` and
`/api/profiles` `der`.

Limits:

- **Not applied to power.** Evse15118D20 relays only curve controls
  (`VoltVar`, `WattVar`, `WattPF`), and only to an EV in an ISO 15118-20 AC
  DER session (`AC_DER_IEC` or `AC_DER_SAE`), at the next session. This
  charger is DC and the simulated EV (Josev) has no DER support, so a
  `LimitMaxDischarge` of 50 % does not reduce discharge.
- **The capability is the App's declaration.** EVerest enables DER only
  when a device declares a DER capability, and no upstream module declares
  one (Evse15118D20 does not). Wired directly, every SetDERControl on this
  DC station would be answered `NotSupported`. `HaGridSupport` (App code,
  not EVerest) declares a DC capability with all 22 types and the rating
  as nameplate, for testing a CSMS; it is not a measured inverter
  capability.
- **No DER alarms.** NotifyDERAlarm is sent only for grid events an EV
  reports in an AC DER session, which never happens here.
- **OCPP 2.0.1** has no DER messages.
- **Release candidate.** DER control is new in EVerest 2026.10.0-rc1.
  Passing the CI scenario (VALIDATION.md) proves those messages; it is not
  OCPP 2.1 conformance.

## Upgrading from 0.1.x

0.2.0 keeps `/data`: the identity binding, the Basic Auth password, the
test PKI and the core database. On the first start, libocpp migrates the
core database from schema 6 (EVerest 2025.10.0) to 7 (adds the DER
controls table); it does this itself when it opens the database. Before
that, the App copies the old file once to
`/data/everest/ocpp201/cp-schema6.db.bak` and logs it. The device model
database is rebuilt on every start, as before.

Rolling back to 0.1.13: EVerest 2025.10.0 cannot open a schema 7 core
database (it has no step back from 7), so OCPP would not start. Set
`archive_and_rebind: true` for the first 0.1.13 start (state is moved to
`/data/archive-<time>/`, never deleted), then set it back to `false`.

## Security boundaries

The UI uses Home Assistant Ingress authentication. nginx on port 8099
accepts only the Supervisor Ingress peer (`172.30.32.2`), checked on the
actual connection, not a forwarded header. The UI service and MQTT broker
listen on loopback only. Only three fixed EV-simulator POST endpoints and
the discovery self-test exist; all other paths are read-only. No host
ports, host networking, hardware access, Supervisor API or Docker socket
are requested. The Core API token serves only the opt-in control bridge
(Home Assistant control). Do not add a
port mapping or widen the ACL to make direct probes pass; use **Open Web
UI**.

**Why this App needs NET_ADMIN.** ISO 15118 discovery (SDP) is IPv6
link-local multicast, which loopback cannot carry. On start the App
creates a private veth pair (`v2g0` for the charger, `v2g1` for the EV)
inside its own container network namespace. Nothing is bridged to the host
or the LAN. The same capability loads an nftables policy that **drops all
inbound traffic** on the Home Assistant network interface except Ingress
from the Supervisor and replies to the App's own outbound OCPP connection.
Outbound, it drops ISO 15118 discovery (UDP 15118) on every interface
except the private link and loopback.
The upstream SDP server binds every interface, so this policy is the
boundary for TCP and defence in depth for UDP. If either step fails, the
App logs `V2G isolation setup failed` and starts no EVerest process.

NET_ADMIN lowers the App's Home Assistant security rating. It does not give
host networking or access to other containers.

**Test PKI.** ISO 15118-20 needs mutual TLS 1.3, so the charger and EV need
certificates. No keys ship in the image. Each install generates its own
chain under a random key password in `/data/pki` (Josev's
`create_certs.sh`), and renews the 60-day leaf certificates on start when
they have under 7 days left. The chain is test-only and is never trusted by
real vehicles or chargers.

## Storage

All state is in the App's `/data`: OCPP message logs
(`everest/ocpp_logs`, rotated at 1 MiB, 3 files), the core database with
transactions, installed charging profiles and DER controls
(`everest/ocpp201/cp.db`), the test PKI (`pki/`) and the generated EVerest
configuration. The device model is rebuilt from the options on every start.
The DER panel's copy of the active set (`/run/ha-everest/der.json`) is not
kept across restarts.

## Install size

Home Assistant pulls a prebuilt image for its architecture
(`ghcr.io/purcell-lab/{arch}-everest-v2g-simulator`) rather than building
locally from EVerest's 4.3 GB build image. From 0.1.6 the Java runtime for
the EV simulator's EXI codec is a 50 MB jlink image instead of the 184 MB
OpenJDK package, so the image is about 135 MB smaller than 0.1.5 (about
560 MB on amd64 and 585 MB on aarch64). The 0.2.0 image, on the
from-source EVerest 2026.10.0-rc1 runtime, has not been measured yet
(VALIDATION.md records it once published). The image is published only through the approval-gated tag process
in `RELEASE.md`.
