# Changelog

## 0.12.0

- OCPP 2.1 charging needs that arrive before the transaction
  ([ha-addons#106](https://github.com/purcell-lab/ha-addons/issues/106)):
  source patch `0007-ocpp21-charging-needs-before-transaction.patch`.
  An ISO 15118-20 EV states its needs before TransactionEvent `Started`, and
  upstream's Rejected made the station end the session
  (`ReqEnergyTransferRejected`). Now, under OCPP 2.1:
  - needs without a transaction are stored on the EVSE, answered
    `NoChargingProfile`, and linked to the transaction when it starts;
  - V2X needs and the 2.1 modes are answered `NoChargingProfile` (no
    schedule follows), not Accepted;
  - Rejected is kept for unusable needs; AC parameters no longer match the
    2.1 DC modes.

  OCPP 2.0.1 is unchanged.
- `ChargingNeeds` stores `v2xChargingParameters`, `controlMode` and
  `mobilityNeedsMode` (new migration). Role `ha_reader` can read the three
  columns.
- CI: the native EVerest V2G trial runs with `ev_charging_needs` on. It
  checks that the needs are answered `NoChargingProfile` and stored on the
  transaction. It then runs the test profile at a -5 kW setpoint:
  allow_discharge, charge_by (0 W), allow_discharge.

## 0.11.1

- Memory diagnostics for the upstream server's out-of-memory crashes
  ([ha-addons#80](https://github.com/purcell-lab/ha-addons/issues/80)): a
  timestamped memory line every minute, one heap snapshot in `/data/heap` near
  the 768 MB heap limit (only the newest is kept), and a timestamp on the exit
  line. The heap limit is unchanged.
- Source patch `0006-ocpp-empty-station-identity.patch`: a websocket upgrade
  whose URL has no station identity (it ends in `/`) is refused with 404.
  Upstream accepted it and created a station with an empty name, which broke
  Home Assistant discovery and coincided with the 25 October crashes.

## 0.11.0

- OCPP 2.1 smart charging with a local EMS and local generation on the
  command station (`command_control_enabled`, OCPP 2.1):
  - TxProfile periods may use the operation modes `ExternalLimits`,
    `ExternalSetpoint` and `LocalLoadBalancing` (limit and discharge limit, no
    setpoint: the station or local EMS chooses the power);
  - `LocalGeneration` profiles (EVSE 0 or 1, ids 9100 to 9199, up to a day,
    charging limits only), set and cleared whatever the station's transactions.
- EMS limits: source patch `0004-ocpp2-charging-limits.patch` stores the
  station's `NotifyChargingLimit` and `ClearedChargingLimit` in a new
  `ChargingLimits` table ([ha-addons#87](https://github.com/purcell-lab/ha-addons/issues/87));
  `GET /lab/charging-limits` lists them and `ha_reader` may read them.
  `/lab/control-policy` gains `local_energy`.
- Source patch `0005-ocpp2-route-schema-definitions.patch`: OCPP 2.1 message
  routes validate against the 2.1 schema definitions. Upstream resolved every
  route's nested definitions to the OCPP 2.0.1 ones, so a 2.1 SetChargingProfile
  with purpose `LocalGeneration` or `PriorityCharging` was refused with 400
  ([ha-addons#95](https://github.com/purcell-lab/ha-addons/issues/95)).
- CI: a scripted OCPP 2.1 station on the Plugfest listener reports and clears an
  EMS limit and receives a LocalGeneration profile through the gateway
  (`TEST_EMS`).

## 0.10.0

- OCPP 2.1 DER control (lab, opt-in): `der_commands_enabled` (default
  `false`, needs `command_control_enabled`). Source patch
  `0003-ocpp21-der-control.patch` adds the DER schemas, the
  `smartcharging/setDERControl`, `getDERControl` and `clearDERControl` routes
  (OCPP 2.1 only) and handlers for the station's `ReportDERControl`,
  `NotifyDERStartStop` and `NotifyDERAlarm`, which upstream v2.1.0 answered
  with a FormatViolation. The gateway sends them to the command station only,
  online on OCPP 2.1, within lab bounds for `LimitMaxDischarge`,
  `FixedPFInject`, `FixedPFAbsorb` and `FixedVar`; a GetDERControl also returns
  the station's reports. `GET /lab/der-events` lists the station's last 20 DER
  messages, and `ha_reader` may read exactly those three actions in
  `OCPPMessages`. `lab-controller` gets the three routes only with the option on.
- Patch tests cover a patch that changes several upstream files; the upstream
  route list fixture includes the three DER routes. CI runs upstream's tests for
  the new handlers and endpoints, and the EVerest V2G trial sets, reads and
  clears a LimitMaxDischarge 50 % control during the session.
- Version 0.9.0 is skipped: it stays reserved for the LocalGeneration and EMS
  limits work.

## 0.8.0

- CitrineOS **v2.1.0**, built from source. The image no longer starts from
  upstream's published v2.0.1 image: it fetches citrineos-core at the v2.1.0
  commit (`4fd7599b91c2fb6e6065e7c9b94be69880cced27`, checked), applies the
  App's source patches with `git apply` (the build fails if one does not
  apply cleanly) and builds as upstream's `deploy.Dockerfile` does, on
  digest-pinned `node:24.16.0` images, natively for amd64 and aarch64.
- Prebuilt image: GitHub Actions builds that Dockerfile and publishes
  `ghcr.io/purcell-lab/{arch}-citrineos-server:<version>`
  (`citrineos-server-publish.yml`, approval-gated, see `RELEASE.md`), and
  Home Assistant pulls it instead of building on the host. PR CI still builds
  and tests the image from source. No new features: the gateway, operator
  routes, Plugfest listeners, pricing and metering SetVariables behave as in
  0.7.7.
- The 0.7.4 to 0.7.7 fixes are source patches now (`patches/`), replacing the
  compiled-JS patchers (`rootfs/patch-*.mjs`): OCPP 2.1 charging needs
  (`DC_BPT`, `DC_ACDP`, `DC_ACDP_BPT`, and needs with only
  `v2xChargingParameters`) and `allowedEnergyTransfer` in Accepted OCPP 2.1
  AuthorizeResponses, with the same behaviour. The reconnect patch (#67) is
  gone: v2.1.0 deregisters a closing connection before it frees the
  station's slot. CI's Plugfest reconnect probe still checks it.
- Authorisation follows v2.1.0. `rbac-rules.json` and the OIDC settings are
  replaced by `auth.mode` `jwt` (set explicitly: upstream defaults to
  `localDev`, which serves a token-minting `/dev/token`) and a roles seed
  file the App writes at each start from the gateway's route lists. Each
  internal role (`lab-reader`, `lab-controller`, `lab-operator`,
  `lab-reporter`) gets exactly the routes it had. v2.1.0 permissions don't
  name an OCPP version, so the gateway's existing version checks are now the
  only thing that scopes a role to an OCPP version.
- Operator UI schema (`metadata-operator.json`) regenerated from v2.1.0:
  `LatestStatusNotifications` is dropped upstream (a connector has a
  `LatestStatusNotification` relationship instead); `NetworkAlerts`,
  `NetworkAlertOccurrences` and `WebsocketEvents` are readable, without
  the connection's remote address. `ha_reader` (`metadata.json`) is
  unchanged. Use the Operator UI App 0.2.0 (built from v2.1.0) with it.
- Simulator provisioning looks up the station-level `SecurityCtrlr` with
  `evseDatabaseId IS NULL` (v2.1.0 keys components by EVSE too).
- v2.1.0 defaults kept and documented: Calls time out after 20 s, a Call not
  sent within 40 s is dropped, at most 5 pending Calls per station, network
  alerts on, weekly `WebsocketEvents` partitions provisioned at each start.

## 0.7.7

- Operator commands may send SetVariables for metering variables only:
  `SampledDataCtrlr` TxStartedMeasurands, TxUpdatedMeasurands,
  TxUpdatedInterval, TxEndedMeasurands, TxEndedInterval, and
  `AlignedDataCtrlr` Measurands, Interval, TxEndedMeasurands,
  TxEndedInterval (1-10 entries, attribute type Actual, no EVSE, connector or
  instance; intervals 0-86400 s; measurands a comma list of measurand
  names). ChargeSim (Plugfest, 23 October 2026) sends power only when asked
  over OCPP, so without this the lab couldn't measure its charging during a
  Cactus run. Every other SetVariables stays refused.

## 0.7.6

- OCPP 2.1 V2X charging needs that carry only `v2xChargingParameters` are
  accepted. Upstream requires `acChargingParameters` for AC needs, and the
  0.7.4 patch covered only the DC modes, so OCTT's AC V2X needs
  (`AC_BPT`, or AC with V2X parameters) were Rejected. The charging needs
  patch now also accepts any needs with `v2xChargingParameters`, stores them
  and sends no automatic profile (the lab's TxProfile keeps control). AC and
  `DC` needs without V2X parameters keep upstream's behaviour.

## 0.7.5

- Accepted OCPP 2.1 AuthorizeResponses carry `allowedEnergyTransfer`.
  Upstream v2.0.1 never sets it, and OCPP 2.1 treats an omitted list as
  charging only, so no session it authorised could be bidirectional: OCTT
  (OCA, Plugfest) reported the field missing and rejected every
  CentralSetpoint TxProfile. A build-time patch to the upstream handler
  (`rootfs/patch-allowed-energy.mjs`, same exact-build guard) adds the lab's
  modes (`DC`, `DC_BPT`, `AC_single_phase`, `AC_two_phase`,
  `AC_three_phase`, `AC_BPT`) to every Accepted 2.1 AuthorizeResponse that
  doesn't set the field already. Other statuses and OCPP 2.0.1 are
  unchanged. CI checks the image is patched.

## 0.7.4

- OCPP 2.1 charging needs are accepted. Upstream v2.0.1 matches DC needs only
  when `requestedEnergyTransfer` is exactly `DC`, so an ISO 15118-20 EV asking
  for bidirectional DC (`DC_BPT`, also `DC_ACDP`, `DC_ACDP_BPT`) was always
  answered Rejected, and a station then refuses the EV's energy transfer
  (Trialog's ComboCS4M-SW ended its transaction with
  `ReqEnergyTransferRejected`). A build-time patch to the upstream handler
  (`rootfs/patch-charging-needs.mjs`, same exact-build guard as the reconnect
  patch) matches those modes like `DC`. For a mode that is not an OCPP 2.0.1
  mode it stores the charging needs, answers Accepted and sends no automatic
  TxProfile: the lab's own TxProfile sets the V2X operation mode, and an
  automatic one would stack above it. Needs without an active transaction or
  without charging parameters are still Rejected; AC and `DC` needs are
  unchanged. CI checks the image is patched.

## 0.7.3

- Home Assistant can learn each station's power rating. CitrineOS stores a
  station's device model only from NotifyReport, and upstream asks for one
  only on a Pending boot, so stations accepted at once never reported EVSE
  `Power` (on the Green the V2G station had six device-model rows, OCPP 1.6
  stations none). New option `device_model_reports` (default `true`): when an
  OCPP 2.1 or 2.0.1 station of tenant 1 comes online on any listener,
  including Plugfest 8083, the gateway sends it one GetBaseReport
  `FullInventory` (`/ocpp/2.1|2.0.1/reporting/getBaseReport`, the station's
  protocol). At most three stations per 30 s check, not again within
  10 minutes of the last request; never OCPP 1.6. The requests use a new
  internal role, `lab-reporter`, which CitrineOS's role rules permit on
  these two routes only; callers cannot send them, and command and Operator
  UI permissions are unchanged. `/lab/status` adds `device_model_reports`.
- `ha_reader` can read `VariableAttributes`, `Variables` and
  `VariableCharacteristics` for rating variables only (`Power` and the
  discharge power names in the documentation; never a password, secret or
  key variable), `Components`, and `ChargingNeeds`, with upstream's
  relationship names. The Operator UI schema carries the same `ha_reader`
  permissions; `build_operator_metadata.py` now checks that each `ha_reader`
  relationship matches upstream's exactly. See "Device model and charging
  needs" for the columns and the upstream limits: one `maxLimit` per
  variable for all stations, and no rows for ISO 15118-20 `DC_BPT` charging
  needs, which CitrineOS v2.0.1 rejects.

## 0.7.2

- Six more Plugfest listeners, on ports 8100 to 8105, so each charging
  station under test can have its own endpoint
  (`ws://<host>:8100/<station-id>` ... `ws://<host>:8105/<station-id>`).
  They are identical to 8083: OCPP 2.1/2.0.1/1.6, the same
  `plugfest_stations` Basic Auth or `plugfest_open_admission`, tenant 1, and
  only with `plugfest_enabled`. Each is closed until its host port is set on
  the Network tab. A port does not restrict which identity connects on it.
  CI boots a provisioned station on 8100 (2.0.1) and 8105 (1.6), refuses an
  unknown one on 8105, and admits an open-admission station on 8103. A unit
  test checks that no listener takes a port the App uses itself (8080, 8088,
  8091, 8092).

## 0.7.1

- Stale transactions no longer block every start. A station that loses its
  transaction state (on the Green, an EVerest App update recreated the V2G
  simulator mid-session) never ends its transaction, so CitrineOS kept it
  active and the gateway refused each later start as another active session.
  With scoped commands on, the gateway now sends OCPP 2.x
  GetTransactionStatus for each transaction CitrineOS holds active for the
  command station: when the station comes online, every 5 minutes, and at
  once after it refuses a start for an active transaction (the 409 then says
  to retry). Upstream's response handler closes a transaction the station
  reports not ongoing with no queued messages, and leaves an ongoing one as
  it is. `POST /lab/reconcile-transactions` (command token) runs the check on
  demand and returns each station answer and the transactions still active.
  `/lab/control-policy` adds `transaction_reconcile`; existing keys are
  unchanged. CitrineOS's role rules grant the command role the two
  GetTransactionStatus routes, which callers cannot send through the gateway.
  OCPP 1.6 has no equivalent, so 1.6 transactions are not checked. CI
  recreates the V2G station mid-transaction and expects the stale
  transaction closed before the charge/discharge trial.

## 0.7.0

Includes the unreleased 0.6.3 changes below.

- Dynamic pricing (lab, opt-in): `price_commands_enabled` (default `false`,
  needs `command_control_enabled`) and `price_currency` (default `AUD`). With
  the command token:
  - an OCPP 2.1 `setChargingProfile` may carry one `absolutePriceSchedule`
    or `priceLevelSchedule` (bounded: 288 rule stacks or 100 levels, 48 h,
    `price_currency`); every other profile bound is unchanged;
  - `/ocpp/2.1|2.0.1/transactions/costUpdated` sends CostUpdated with
    California Pricing `customData` (current and next price, text) for the
    command station's active transaction;
  - `/ocpp/2.1/transactions/setDefaultTariff` sends an energy-only tariff to
    the command station or a provisioned Plugfest station online on 2.1, and
    returns the station's reply or CALLERROR unchanged.
  `/lab/control-policy` adds `price_commands` (`{"enabled": false}` when off);
  existing keys are unchanged. CitrineOS's role rules grant the command role
  the price routes only when both flags are on. With price commands on,
  CitrineOS's own CostUpdated every 60 s (zero from its lab tariff) is moved
  to about 24.8 days, so it no longer overwrites the price on the station.
  See "Dynamic pricing (lab)" in the documentation.
- A refused profile that carries a price schedule says why (flag off, not
  OCPP 2.1, or outside the bounds).

## 0.6.3

- Station replies no longer stop after a quick reconnect (#67). On the
  Green, an EVerest station reconnected after `Pong not received from
  server!`; CitrineOS then stored all its messages but answered none
  (Heartbeat, StatusNotification and TransactionEvent timed out on the
  station, TransactionEvent Started was stored three times), while
  RequestStartTransaction still reached it. Upstream v2.0.1 deregisters the
  old connection in the background, and that deregistration removed the
  RabbitMQ bindings the new connection had just added. The image build now
  patches the upstream connection handler so a reconnect waits until the old
  connection has finished closing (`patch-reconnect.mjs`; the build fails on
  any other upstream file). CI checks the image is patched and reconnects a
  station nine times, each time expecting replies to BootNotification and
  Heartbeat.
- Less log noise (#30): startup seeds a zero-cost lab tariff on tenant-1
  connectors and an unpublished lab Location on tenant-1 stations that have
  none, so upstream stops logging `Tariff not found for connector N` every
  minute and `does not have a locationId` at each transaction start.
  Stations and connectors first seen after a start get them at the next
  start. The remaining upstream warnings are listed in the documentation.
  (A deliberate stop already exits 0 since 0.5.2.)

## 0.6.2

- Read-only station configuration for the OCPP 1.6 command station:
  `POST /lab/station-configuration` (command token) sends GetConfiguration
  for a fixed set of standard metering and smart-charging keys, waits up to
  8 s for the station's reply (CitrineOS posts it to a one-time loopback
  callback) and returns only the requested keys. It shows whether a physical
  charger accepts watt or amp schedules; a DC charger on the Green kept
  advertising 25 kW under 0 W profiles. CitrineOS's role rules grant the
  command role this one route when scoped commands are on.

## 0.6.1

- Startup no longer fails when Hasura takes longer than 10 s to apply the
  metadata. With `operator_ui_enabled` the full upstream schema took 10 s on a
  busy Home Assistant Green: Hasura stored it, but the 10 s request timeout
  had already failed the start ("Laboratory startup failed"), three times in a
  row. The metadata request now allows 120 s; other requests keep 10 s.
- Scoped commands on OCPP 2.0.1 and 1.6 now work. 0.6.0 accepted those
  routes at the gateway, but CitrineOS's role rules (`rbac-rules.json`, baked
  into the image) granted the command role only the 2.1 routes, so CitrineOS
  refused them ("Authentication or authorization failed"). The App now writes
  the rules at every start from the gateway's own route list: the command role
  gets exactly the scoped command routes when `command_control_enabled` is on,
  and none when it is off. Reader and Operator UI rules are unchanged. Route
  changes no longer need a rebuild of the rules file.

## 0.6.0

- Scoped commands for a physical charger (opt-in): with
  `command_real_stations_enabled`, `command_station_id` may be any OCPP
  identity on the Plugfest listener (8083, provisioned password or
  `plugfest_open_admission`). Still one configured station and the same
  bounds. Needs `plugfest_enabled`; cannot be combined with
  `profile_simulator_enabled`. `/lab/control-policy` then reports
  `real_devices_enabled: true`.
- Scoped commands also accept OCPP 2.0.1 routes (`/ocpp/2.0.1/...`) for a
  station that negotiated 2.0.1, with charging-only periods. The route's
  version must match the station's protocol. The policy adds `protocols` and
  `commands_by_protocol`, and keeps `protocol`/`commands` (2.1) for older
  clients.
- Scoped commands also accept OCPP 1.6 routes for a 1.6 station:
  `remoteStartTransaction`, `remoteStopTransaction` (integer transaction
  ID), `setChargingProfile` (`csChargingProfiles`, whole-watt charging-only
  periods) and `clearChargingProfile` by `id`.
- Transaction IDs accept the OCPP identifierString characters
  (`* - _ = : + | @ .`) that physical chargers use.

## 0.5.3

- Scoped lab SetChargingProfile: the limit per period is now 25 kW for
  charging and for V2G discharge (`max_import_w` and `max_export_w` 25000,
  were 11000), so a 3-phase 32 A AC simulator (about 22 kW) can be limited
  across its whole range (purcell-lab/ha-addons#55).

## 0.5.2

- Scoped lab SetChargingProfile (#39): a period may carry `numberPhases`
  (1 or 3) and, with `numberPhases: 1`, `phaseToUse` (1 to 3). A period is
  either a V2G `CentralSetpoint` period (as before) or an AC charging-only
  period: `operationMode` absent or `ChargingOnly`, with no `setpoint` or
  `dischargeLimit`. libocpp assumes 3 phases when `numberPhases` is absent,
  so a single-phase AC charger received a third of a watt limit.
- A deliberate stop exits 0, so Supervisor shows the App as stopped, not in
  error (#30).

## 0.5.1

- Plugfest listener (8083) also accepts OCPP 1.6. Upstream picks the first
  protocol in the listener's list that the station offers, in the order
  2.1, 2.0.1, 1.6.
- New `plugfest_open_admission` (default `false`, needs `plugfest_enabled`):
  8083 runs Security Profile 0 and admits any station identity without
  credentials, like the internal 8082 listener but on the publishable port.
  `plugfest_stations` may then be empty. The server logs a warning at start.
- `/lab/status` reports `plugfest_open_admission` and `plugfest_protocols`.
- `tests/plugfest_probe.py` checks a 1.6 boot with Basic Auth, 2.1
  preference, and open admission on 2.1, 2.0.1 and 1.6.

## 0.5.0

- Operator UI scope for the new CitrineOS Operator UI App, off by default:
  - `operator_ui_enabled` with a separate `operator_token`: GraphQL through the
    gateway as Hasura role `operator_ro`, using `metadata-operator.json`
    (upstream's full v2.0.1 schema, select-only, tenant-filtered; password and
    key variables, OCPI credential profiles and webhook subscriptions hidden).
    The `ha_reader` permissions used by CitrineOS-HA are unchanged.
  - `operator_commands_enabled`: a fixed set of OCPP 2.0.1/2.1 operational
    commands to any online tenant-1 station on the matching version, through a
    separate upstream RBAC role `lab-operator`. Credential, certificate,
    firmware, network-profile, SetVariables, data-transfer and file-upload
    commands are never allowed.
- `tests/operator_probe.py` (`TEST_OPERATOR=1`, in CI) checks the scope end to
  end, including a Reset delivered to an online OCPP 2.0.1 station.

## 0.4.0 (staged, not accepted for deployment)

- Add opt-in enrolment for the existing `SIM-EV-EVEREST-V2G-01` simulator.
- Offer OCPP 2.1 alongside the existing 2.0.1 listener.
- Separate command credentials from read access; allow only bounded simulator
  start/stop, transaction profiles and post-closure exact-profile cleanup.
- Check observed 2.1 protocol and active transaction before dispatch.
- Retain read-only Hasura, no host ports, no real-device enrolment and no
  automatic load controller.
- Add the full Plugfest demonstration acceptance plan. HA controls, integration
  testing, fail-safe enforcement and the complete envelope path remain gates.
- Offer aarch64 (for example a Home Assistant Green) alongside amd64 for the
  server and its private dependencies (broker, database and Hasura 0.1.1).
  The pinned upstream server index already includes arm64. jq is taken per
  architecture with its published checksum, and the database moves to the
  multi-arch `imresamu/postgis:16-3.5-bullseye` build of the same PostgreSQL
  16.9 / PostGIS 3.5.2 / bullseye versions, so existing data is compatible.
- Add an opt-in Plugfest listener (`plugfest_enabled`, port 8083): OCPP
  2.1/2.0.1 Security Profile 1 for provisioned external charging stations
  (`plugfest_stations`, per-station passwords; unknown stations refused).
  `8083/tcp` is the only port the App declares, unpublished until a host port
  is set. Startup revokes the Basic Auth password of any station no longer
  provisioned. CI connects a station: Accepted boot; wrong password, unknown
  identity and a removed station refused.
- Add opt-in `open_admission_enabled`: an unauthenticated internal listener on
  port 8082 accepting any station identity over OCPP 2.1/2.0.1. Off by default;
  port 8081 authentication is unchanged. See DOCS.md for the impersonation risk.
- Add `command_station_id` to select the one `SIM-EV-` station scoped commands
  may target (default `SIM-EV-EVEREST-V2G-01`).

## 0.1.0

- Stage an amd64, manual-boot, disconnected-only CitrineOS package.
- Pin upstream server release image by digest and client source by commit.
- Add compiled route-contract, pinned-client and packaging safety checks.
- Block runtime activation pending client compatibility and full-stack gates.
# 0.2.0

- Add explicitly enabled isolated server mode with private dependency Apps.
- Add native JWT authentication, read-only gateway and restricted Hasura discovery.
- Retain disconnected default, manual boot, no host ports and zero charger listeners.
- Add bounded stack, authentication, persistence and logical-restore tests.
# 0.3.0

- Add opt-in, private Security Profile 1 listener for one dedicated MicroOCPP identity.
- Provision only the test station, boot acceptance, password and synthetic token.
- Expose read-only boot, metering and transaction events for acceptance checks.
- Test native registration, power, energy and closure without existing chargers.
