# CitrineOS isolated laboratory

**New controlled path: NO-GO for activation.** Merged source is not a deployed
release. The current EVerest runtime does not reliably honour 0 W profiles; keep
command controls off until the documented gates pass. Read the
[full implementation, build and test handover](../docs/citrine-everest-handover.md)
before preparing an update.

This App runs pinned CitrineOS **v2.1.0**, not an OCPP protocol version. The
image builds it from source at the release commit
(`4fd7599b91c2fb6e6065e7c9b94be69880cced27`) with this App's source patches
(`patches/`, see "Upstream changes in this App"). The image is built in
GitHub Actions for amd64 and aarch64 and published to GHCR
(`ghcr.io/purcell-lab/{arch}-citrineos-server`); Home Assistant pulls it and
does not build on the host. See `RELEASE.md`.
Its companion Apps provide dedicated PostgreSQL/PostGIS, RabbitMQ and Hasura.
Nothing binds a host port. No OCPP listener is enabled by default.
Existing physical chargers, simulators, Home Assistant OCPP entries and payments
are not used or redirected.

## Installation

Install `citrineos_database`, `citrineos_broker`, `citrineos_hasura` and
`citrineos_server` from this repository. Keep manual boot and automatic updates off.
Use the actual Supervisor-discovered hostnames, not guessed IP addresses.

Generate four distinct 32-byte random values encoded as 64 lowercase hexadecimal
characters for database, broker, Hasura admin and gateway credentials. Enter them
only in the corresponding App options. Do not commit them or include them in logs.
The server uses all four; Hasura uses database and Hasura credentials; the other
Apps use only their own password. Supervisor administrators can read options.
Backups therefore contain secrets and must be protected.

Start the database, broker and Hasura first. Configure the server's dependency
hostnames and change `mode` from `disconnected` to `isolated`, then start it.
The server waits for its dedicated dependencies, applies pinned migrations and
partition provisioning, starts the upstream server and installs the lab's
read-only Hasura metadata. Failed readiness fails startup rather than reporting
an empty healthy system.

The compatibility lock retains the **historical** initial client assessment.
The current runtime and authentication evidence comes from the isolated-stack CI.
The old installed HA client is not automatically updated or configured by this App.

## Access and security boundary

The internal gateway listens on port 8080. `/health/ready` is an unprivileged
readiness check. All other supported routes require `Authorization: Bearer TOKEN`:

- `GET /lab/status`: release, read-only mode and zero-listener status.
- `GET /commands/tariff?tenantId=1`: authenticated, tenant-scoped upstream read.
- `POST /v1/graphql`: Hasura discovery through role `ha_reader`, fixed tenant 1.

Other paths and methods are denied. GraphQL has no mutation permissions; its
tables expose only the HA client's explicit discovery fields, and the device
model tables only power-rating variables (see "Device model and charging
needs"). Caller
authentication, role and tenant headers are never forwarded to dependencies.

The upstream API binds loopback port 8088 and uses its JWT provider
(`auth.mode` `jwt`), not local authentication bypass. The App sets the mode
explicitly: CitrineOS v2.1.0 defaults to `localDev`, which serves a
token-minting `/dev/token` route; with `jwt` no `/dev` route exists, and the
gateway never forwards `/dev` or `/permissions`. The gateway signs 60-second
internal JWTs (RS256, key ID `lab`, claims `roles` and `tenant_id` 1) with an
in-memory RSA key; its loopback JWKS endpoint is port 8091. Restart rotates the
internal key.

CitrineOS checks one permission per route, named from the route
(`ocpp.<eventGroup>.<action>` for an OCPP route, `commands.tariff.get` for the
tariff read), and reads the roles that hold them from a roles seed file. At
every start the App writes that file (`roles-seed.json` in the upstream app
folder, root-owned, read-only to CitrineOS, which re-reads it every 60 s) from
the gateway's route lists:

| Role | Used for | May call |
| --- | --- | --- |
| `lab-reader` | gateway reads | the tariff read |
| `lab-controller` | scoped commands | the tariff read; with `command_control_enabled`, exactly the scoped start, stop, profile and clear routes for OCPP 2.1, 2.0.1 and 1.6, the OCPP 1.6 configuration read and GetTransactionStatus; with `price_commands_enabled` too, the price routes; with `der_commands_enabled` too, the three DER routes |
| `lab-operator` | Operator UI commands | the operator command set (below) |
| `lab-reporter` | device model reports | GetBaseReport, when `device_model_reports` is on |

These are the routes each role had with CitrineOS v2.0.1. A v2.1.0 permission
no longer names an OCPP version, so it also covers the same action on the other
versions (for the operator role, the OCPP 1.6 forms of its actions): the
gateway's own checks, which already required the route's version to match the
station's, are what scope a role to an OCPP version, and they run before every
request. The bearer gateway is a lab credential bridge, not an interactive
identity provider.

No HA/Supervisor API token, Docker socket, host network, device or privileged mount
is granted. Server and Hasura processes run as UID 1000 after root-only startup
preparation. Database and broker use upstream privilege-dropping entrypoints.
RabbitMQ's management plugin is disabled.

**Isolation is not a dedicated network firewall.** HA Apps share Supervisor's
container network. Other trusted Apps can reach dependency ports, but need the
distinct credentials. No ports are published to the LAN or internet. This is
single-tenant laboratory packaging, not a production multi-tenant service.

## Data and rollback

Database state is stored in its own `/data/pgdata`; broker state in `/data/mnesia`.
Hasura metadata is stored in the dedicated database. Server runtime files are in
its own `/data/assets`. An upgrade never enables database sync, alter or force.
Only the upstream versioned migration path is used.

Stop in order: server, Hasura, broker, database. Start dependencies before server.
Stopping these four Apps is the rollback for this first installation and leaves
all existing charging systems alone. Do not uninstall or clear data as recovery.
Credential rotation and server upgrades require coordinated review.

CI checks a logical `pg_dump`/`pg_restore` into a disposable second database and
server restart persistence. This does not claim that a full Supervisor disaster
restore has been tested. Take a protected HA backup before deployment.

## Upstream changes in this App

**Source build and patches.** The image build fetches CitrineOS at the pinned
commit (and checks it), applies each file in `patches/` with `git apply`
(checked first: a patch that does not apply cleanly fails the build), then
builds and deploys the server as upstream's `apps/ocpp-server/deploy.Dockerfile`
does, on digest-pinned `node:24.16.0` images, natively on each architecture.
The build fails if a runtime file the launcher uses is missing or a patch is not
in the compiled output. The pinned source licence, commit and patches are in
`/usr/share/doc/citrineos-core` in the image. CI applies the patches to the
pinned commit, compiles them and runs upstream's tests for both handlers, and
the App's own tests run the patched TypeScript with fakes.

**Charging needs patch (OCPP 2.1)**
(`patches/0001-ocpp21-charging-needs.patch`,
`packages/ocpp/src/handlers/requests/2/notify-ev-charging-needs-request-ocpp-2-handler.ts`).
Upstream accepts DC charging needs only when `requestedEnergyTransfer` is
exactly `DC`, so an OCPP 2.1 EV asking for bidirectional DC (`DC_BPT`) is
answered Rejected and the station refuses the energy transfer
(`ReqEnergyTransferRejected`). With the patch the 2.1 DC modes (`DC_BPT`,
`DC_ACDP`, `DC_ACDP_BPT`) match like `DC`, and needs with
`v2xChargingParameters` (for example OCTT's `AC_BPT`) match whatever the mode;
for a mode that is not an OCPP 2.0.1 mode, or any needs with
`v2xChargingParameters`, CitrineOS stores the needs, answers Accepted and sends
no automatic profile, so the lab's TxProfile (CentralSetpoint, discharge) stays
in control. AC and `DC` needs without V2X parameters keep upstream's behaviour.

**allowedEnergyTransfer patch (OCPP 2.1)**
(`patches/0002-ocpp21-allowed-energy-transfer.patch`,
`packages/ocpp/src/handlers/requests/2/authorize-request-ocpp-21-handler.ts`).
OCPP 2.1 AuthorizeResponse lists the energy transfer modes the EV may choose
(`allowedEnergyTransfer`); when it is omitted the station treats the session as
charging only. Upstream never sets it, so a bidirectional (CentralSetpoint
discharge) session could not be negotiated. With the patch every Accepted OCPP
2.1 AuthorizeResponse lists `DC`, `DC_BPT`, `AC_single_phase`, `AC_two_phase`,
`AC_three_phase` and `AC_BPT`, unless the response already has a list. Other
statuses and OCPP 2.0.1 are unchanged.

**DER control patch (OCPP 2.1)** (`patches/0003-ocpp21-der-control.patch`).
Upstream v2.1.0 knows the OCPP 2.1 DER actions by name only: it has no schemas,
routes or handlers for them, so a station's `ReportDERControl`,
`NotifyDERStartStop` or `NotifyDERAlarm` is answered with a FormatViolation
CALLERROR and nothing can send `SetDERControl`, `GetDERControl` or
`ClearDERControl`. The patch adds the six actions' schemas to the OCPP 2.1
schema records, the three OCPP 2.1 routes under `smartcharging`, handlers that
acknowledge the three station messages (with the empty response the schema
defines; CitrineOS keeps every message in `OCPPMessages`) and handlers that log
the station's status for the three CSMS requests. No database change. The
gateway decides who may use the routes (see DER control below).

**Reconnect (#67), fixed upstream.** CitrineOS v2.0.1 freed a closing
station's connection slot before it deregistered the station from the message
router, so a station that reconnected at once (EVerest does after `Pong not
received from server!`) lost its reply bindings; 0.6.x to 0.7.x patched this.
v2.1.0 deregisters first and only then releases the slot (an immediate
reconnect is refused until then, and the station retries), so the patch is
gone. CI's Plugfest probe still reconnects one station nine times and checks
every BootNotification and Heartbeat is answered.

**CitrineOS v2.1.0 defaults the App keeps.** A Call waits up to 20 s for the
station's reply (`maxCallLengthSeconds`); a Call that has not reached the
station within 40 s is dropped (`staleCallMaxAgeSeconds`); at most 5 Calls per
station are pending at once (`maxPendingCallsPerStation`), and a further one is
not sent. The gateway's own waits are shorter (4 s to send, 8 s for a reply),
and its automatic requests (transaction checks, device model reports) go one
at a time. Network alerts (station connectivity, connector
status, OCPP call failures) are on and appear in the Operator UI tables
`NetworkAlerts` and `NetworkAlertOccurrences`. Connection events go to
`WebsocketEvents`, partitioned by week like `OCPPMessages`: each start
provisions four weeks ahead and never drops a partition.

**Lab tariff and location (#30).** When any charger listener is on, startup
adds a zero-cost tariff (`HA-LAB-ZERO`, EUR 0 per kWh; upstream already
reports cost 0 without one) to every tenant-1 connector without a tariff, and
the lab Location `Home Assistant lab` (not published upstream) to every
tenant-1 station without a location. Upstream then no longer logs `Tariff not
found for connector N` every minute of a transaction, or `does not have a
locationId` at each transaction start. Existing tariffs and locations are not
changed. A station or connector first seen after this start (open admission,
Plugfest stations' connectors from their status reports) is covered at the
next start and logs these lines until then.

**Stale transactions.** CitrineOS keeps a transaction active until the
station sends TransactionEvent Ended. A station that loses its transaction
state (an App update recreates the simulator container mid-session) never
does, and the gateway would then refuse every start. With
`command_control_enabled` the gateway sends OCPP 2.x GetTransactionStatus for
each transaction CitrineOS holds active for the command station: when the
station comes online, every 5 minutes, and at once after it refuses a start
for an active transaction (retry a few seconds later). Upstream closes a
transaction the station reports not ongoing with no queued messages
(`isActive` false; the end time stays empty). `POST
/lab/reconcile-transactions` with the command token runs the check on demand
and returns the station's answers and the transactions still active. The
gateway log shows each check (`Transaction status check (...)`). OCPP 1.6 has
no GetTransactionStatus, so a stale 1.6 transaction still needs the station's
StopTransaction.

Upstream log lines that remain and need no action:

- `Active Transaction not found on charging station {} evse {} <station> 1`:
  a clock-aligned MeterValues (15 min by default) for an EVSE with no
  transaction.
- `(sequelize) Warning: Unknown attributes (chargingSchedule,transactionId)
  passed to defaults option of findOrCreate` on each SetChargingProfile.
- `MaxListenersExceededWarning: 11 connected listeners added to
  [RabbitMQConnectionManager]` at start: one listener per upstream module.

## Device model and charging needs

Home Assistant reads each station's power rating from CitrineOS's device
model, and per session the EV's needs, through role `ha_reader`.

**Device model reports** (option `device_model_reports`, default `true`).
CitrineOS stores a station's device model only from NotifyReport, which a
station sends when asked. Upstream asks (GetBaseReport) only when it
answers a BootNotification Pending, so stations it accepts at once never
report, and EVSE `Power` stayed unknown. When any OCPP 2.1 or 2.0.1 station
of tenant 1 comes online, on any listener including Plugfest 8083, the
gateway sends it one GetBaseReport `FullInventory` through upstream
(`/ocpp/2.1/reporting/getBaseReport` or `/ocpp/2.0.1/reporting/getBaseReport`,
matching the station's protocol). GetBaseReport is a read-only request; the
station answers with NotifyReport messages that CitrineOS stores. The check
runs every 30 s beside startup, at most three stations per check. A station
that comes online again within 10 minutes of its last request is not asked
again; a request CitrineOS could not send is retried on up to three checks.
OCPP 1.6 stations are never asked (no device model). The gateway log shows
`Device model report requested from <identity> (<protocol>): <status>.`
The requests use the internal role `lab-reporter`, which the roles seed
permits GetBaseReport only; callers cannot send them through
the gateway, and no command or Operator UI permission changes. Set
`device_model_reports: false` to send none.

**Tables for `ha_reader`** (tenant 1, read-only, at most 501 rows):

| Table | Columns | Rows |
|---|---|---|
| `VariableAttributes` | `id stationId evseDatabaseId componentId variableId type value updatedAt` | rating variables only |
| `Variables` | `id name instance` | rating variables only |
| `VariableCharacteristics` | `id variableId maxLimit minLimit unit` | rating variables only |
| `Components` | `id name instance evseDatabaseId` | all |
| `ChargingNeeds` | `id evseId transactionDatabaseId acChargingParameters dcChargingParameters requestedEnergyTransfer departureTime createdAt updatedAt` | all |

Rating variables are those named `Power`, `DischargePower`,
`MaxDischargePower`, `PowerDischarge` or `V2XMaxDischargePower`, or matching
`%discharge%power%` (case-insensitive); any name containing `password`,
`secret` or `key` is excluded as in the Operator UI scope, so
`BasicAuthPassword` is never readable. Object relationships use upstream's
names: `VariableAttributes.Variable`, `.Component`, `.ChargingStation`;
`Variables.VariableCharacteristic`; `VariableCharacteristics.Variable`;
`ChargingNeeds.Evse`, `.Transaction`. `VariableAttributes.evseDatabaseId`
refers to upstream's `EvseTypes` (the device-model EVSE), which `ha_reader`
cannot read; use the `Component` (name `EVSE`) instead.

Upstream data model limits, which the App does not change:

- CitrineOS keeps one `Variables` row per name and instance, and one
  `VariableCharacteristics` row per variable, for all stations. `maxLimit`
  of `Power` is therefore whatever the station that reported last sent.
  Per-station values are `VariableAttributes` rows (`stationId`, `type`
  `Actual`, `MaxSet` or `MinSet`), when the station reports them.
- `ChargingNeeds` rows come only from NotifyEVChargingNeeds that CitrineOS
  accepts: AC with `acChargingParameters`, or `DC`, `DC_BPT`, `DC_ACDP` or
  `DC_ACDP_BPT` with `dcChargingParameters`, during an active transaction
  (the 2.1 modes need the charging needs patch below). The table has no
  column for `v2xChargingParameters`, so those are not stored. For AC and
  `DC` needs CitrineOS itself sends the station a TxProfile computed from the
  EV's maxima (not bounded by the lab policy); a physical ISO 15118-2 station
  on the Plugfest listener can get such a profile. For the 2.1 modes it sends
  none.

## Deliberate limits

An optional dedicated simulator test is described below. TxProfile, V2G, operator
UI, OCPI, external CA and BSV settlement are not enabled. The Hasura endpoint works through the read-only
gateway; raw Hasura admin credentials must not be supplied to a user-facing client.

## Optional dedicated simulator

Set `simulator_enabled=true` with a distinct generated 40-hex
`simulator_password` to enable internal port 8081, OCPP 2.0.1 only, native Security
Profile 1, fixed tenant 1 and unknown-station rejection. No host port is published.
Startup provisions only `SIM-CITRINE-LAB-01`, Accepted boot status and the synthetic
`C17E0001` token. It refuses provisioning if any different station is in
this dedicated database. Parameters are bound through PostgreSQL, never SQL
interpolated or exposed in an HTTP SQL endpoint.

Security Profile 1 is cleartext Basic authentication, confined to the trusted
Supervisor network. It is not TLS and must not be exposed to the LAN or internet.
(The separate, opt-in Plugfest listener below is the only listener that can be
published on a LAN, deliberately and temporarily.)
The opt-in setup is for the separately installed `citrineos_simulator` App only.
No existing charger or simulator identity is reused.

Read-only discovery additionally exposes `Boots`, `TransactionEvents` and
`MeterValues`, with explicit columns and tenant filters. This is lab observability,
not a change to the HA client's still-staged compatibility work.

Upstream references:
[server release](https://github.com/citrineos/citrineos-core/releases/tag/v2.1.0),
[deployment architecture](https://github.com/citrineos/citrineos-core/blob/v2.1.0/docker-compose.yml),
[HA-client compatibility PR](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/1).
# Staged Plugfest control extension

The 0.4.0 changes are a development draft. They add opt-in OCPP 2.1 admission
and a separate, narrowly scoped command credential for the existing EVerest V2G
simulator only. All command controls remain off by default; Hasura remains
read-only. Do not enable this draft until the full gateway, HA-client,
local-fallback and Citrine/EVerest integration gates pass.

See [the full Plugfest acceptance plan](https://github.com/purcell-lab/ocpp-plugfest/blob/main/plugfest-lab/ACCEPTANCE.md)
for the proposed end-to-end scope, migration procedure and remaining work.
The previous isolated/read-only instructions below describe the installed
baseline, not proof that the new controlled profile is ready.

## Open station admission (opt-in, unauthenticated)

`open_admission_enabled` (default `false`) adds a second internal listener on
port 8082 that accepts **any** charging-station identity over OCPP 2.1 or
2.0.1, with no password: `allowUnknownChargingStations` and
`ignoreAuthenticationHeaders` are both on, Security Profile 0, fixed tenant 1.
New stations are created at their first BootNotification and accepted.
Port 8081 and its provisioned Basic Auth identities are unchanged.

Read this before enabling it:

- Any App on the Supervisor network can register under any identity on 8082,
  including an identity that 8081 authenticates, such as `SIM-CITRINE-LAB-01`
  or the command station. Identity on this listener is not proof of who
  connected. No host port is published, so it is not reachable from the LAN.
- While it is enabled, startup no longer refuses a database containing other
  stations; it still provisions only the configured simulator records.
- Disable the option and restart only the server to remove the listener.
  Stations it registered remain in the dedicated database as history.

Use it for simulators that cannot be given a provisioned password, for example
EVerest V2G 0.1.3: set its `csms_url` to `ws://<server-hostname>:8082` and a
distinct `SIM-EV-` identity. The App's own generated Basic Auth header is
ignored on this listener.

`command_station_id` (default `SIM-EV-EVEREST-V2G-01`) selects the single
station that scoped commands may target. It must be a `SIM-EV-` identity
unless `command_real_stations_enabled` is on (below). The existing gates
still apply: online, tenant 1, exact active transaction and bounded profiles.
Commands may be enabled with either `profile_simulator_enabled` or
`open_admission_enabled`; they still need the separate command credential.

Scoped commands speak OCPP 2.1 (`/ocpp/2.1/...`), OCPP 2.0.1
(`/ocpp/2.0.1/...`) or OCPP 1.6 (`/ocpp/1.6/...`). The route's version must
be the protocol the station negotiated; there is no fallback between
versions. On 2.0.1 a profile period is charging-only (`limit`, optional
`numberPhases`/`phaseToUse`): 2.0.1 has no `operationMode`, `setpoint` or
`dischargeLimit`.

OCPP 1.6 uses its own messages with the same bounds:

| Command | Route | Payload |
|---|---|---|
| Start | `/ocpp/1.6/evdriver/remoteStartTransaction` | `{"connectorId": 1, "idTag": "C17E0001"}` |
| Stop | `/ocpp/1.6/evdriver/remoteStopTransaction` | `{"transactionId": <integer>}` |
| Profile | `/ocpp/1.6/smartcharging/setChargingProfile` | `connectorId` 1 and `csChargingProfiles`: a TxProfile on the active integer `transactionId`, one W schedule, periods of `startPeriod`, a whole-watt `limit` and optional `numberPhases` 1 or 3 |
| Clear | `/ocpp/1.6/smartcharging/clearChargingProfile` | `{"id": <profile id>}`, after the transaction has closed |

Many 1.6 chargers accept only amps (`ChargingScheduleAllowedChargingRateUnit`
= `Current`). Those reject a W profile, and the HA integration reports the
rejection; amp profiles are not enabled here. `/lab/control-policy`
lists the routes per protocol (`protocols`, `commands_by_protocol`) and still
reports the original 2.1 `protocol` and `commands` for older clients.

### Physical command station (opt-in)

`command_real_stations_enabled: true` (default `false`) lets
`command_station_id` be any OCPP identity (up to 48 of
`A-Z a-z 0-9 . _ ~ * + -`), so the HA bridge can limit a physical charger.
It is still exactly one station, chosen in the options, and every other
bound is unchanged: TxProfile only, an active transaction on that station
is required, at most 600 s and 10 periods, 25 kW import and export, and
clear only after the transaction has closed.

- The station connects on the Plugfest listeners (8083 and 8100 to 8105), so `plugfest_enabled`
  is required: with a provisioned password in `plugfest_stations`, or with
  `plugfest_open_admission` for no authentication.
- `profile_simulator_enabled` cannot be on at the same time, because it
  would provision the same identity with the lab simulator credential.
- `/lab/control-policy` reports `real_devices_enabled: true`. CitrineOS-HA
  0.3.4 and earlier refuse such a policy; use a version that supports
  physical stations.
- The station may use OCPP 2.1, 2.0.1 or 1.6. On 2.0.1 and 1.6 profiles are
  charging-only.
- On OCPP 1.6, `POST /lab/station-configuration` with the command token and
  `{"key": ["ChargingScheduleAllowedChargingRateUnit"]}` reads the station's
  configuration (GetConfiguration) and returns its reply, for example whether
  it accepts watt (`Power`) or amp (`Current`) schedules. Only these standard,
  non-secret keys can be read: `SupportedFeatureProfiles`,
  `NumberOfConnectors`, `GetConfigurationMaxKeys`, `MeterValuesSampledData`,
  `MeterValueSampleInterval`, `StopTransactionOnEVSideDisconnect`,
  `ChargingScheduleAllowedChargingRateUnit`, `ChargingScheduleMaxPeriods`,
  `ChargeProfileMaxStackLevel`, `MaxChargingProfilesInstalled` and
  `ConnectorSwitch3to1PhaseSupported`. Nothing is written to the station.

Before you command a real charger:

- A profile ends 600 s after it starts. If HA stops sending, the charger
  returns to its own default limit, so set a conservative default on the
  charger itself (TxDefaultProfile or ChargingStationMaxProfile).
- Watt limits on a single-phase charger need `numberPhases: 1`; libocpp-based
  chargers assume 3 phases otherwise.
- With `plugfest_open_admission`, anyone who can reach ports 8083 and 8100 to 8105 can connect
  as the command station's identity. Use a provisioned password for anything
  but an isolated test network.

## Dynamic pricing (lab)

Off unless `price_commands_enabled: true` (default `false`; needs
`command_control_enabled`). `price_currency` (default `AUD`, three capital
letters) is the only currency the gateway accepts. Prices are information
for the station: they never change the power bounds above. All three use the
command token and `?identifier=<station>&tenantId=1`, like the scoped
commands.

| Feature | Route | Target |
|---|---|---|
| B: price schedule in a charging profile | the OCPP 2.1 `smartcharging/setChargingProfile` route | the command station |
| C: CostUpdated | `/ocpp/2.1/transactions/costUpdated`, `/ocpp/2.0.1/transactions/costUpdated` | the command station, online on that version, with that active transaction |
| D: SetDefaultTariff | `/ocpp/2.1/transactions/setDefaultTariff` | a `tariff_stations` entry online on OCPP 2.1 |

- **B.** `chargingProfile.chargingSchedule[0]` may carry one of
  `absolutePriceSchedule` or `priceLevelSchedule` (OCPP 2.1 only); every
  other profile bound is unchanged. `absolutePriceSchedule`: `timeAnchor`,
  `priceScheduleID`, `currency` = `price_currency`, `language` `en`,
  `priceAlgorithm` `urn:iso:std:iso:15118:-20:PriceAlgorithm:1-Power`,
  1 to 288 `priceRuleStacks` (`duration` > 0 s, 1 to 8 `priceRule` of
  `energyFee` and `powerRangeStart` `{"value": 0, "exponent": 0}`), optional
  `priceScheduleDescription` (160 characters), `minimumCost` and
  `maximumCost`. A RationalNumber has an integer `value` from -32768 to 32767
  and an `exponent` from -3 to 3. No tax, overstay or additional-service
  rules. `priceLevelSchedule`: `timeAnchor`, `priceScheduleId`,
  `numberOfPriceLevels` 1 to 10, 1 to 100 entries of `duration` > 0 s and
  `priceLevel` below `numberOfPriceLevels`. Either schedule covers at most
  48 h (172800 s). A refused priced profile says whether the flag, the OCPP
  version or the bounds were the cause.
- **C.** `{"totalCost": 0..10000, "transactionId": "<active>", "customData":
  {"vendorId": "org.openchargealliance.costmsg", "chargingPrice": {"kWhPrice": n,
  "hourPrice"?: n, "flatFee"?: n}, "nextPeriod"?: {"atTime": "<date-time>",
  "chargingPrice": {"kWhPrice": n}}, "priceText"?: "<255 characters>"}}`
  (California Pricing). Prices are AUD per kWh including GST, -5 to 20. The
  reply is CitrineOS's dispatch confirmation, as for the scoped commands.
- **D.** `{"evseId": n, "tariff": {...}}`: `tariffId` (up to 60 printable
  characters, not `HA-LAB-ZERO`), `currency` = `price_currency`, optional
  `description` (up to 3 of `{"format": "UTF8", "language": "en", "content":
  "<255 characters>"}`), optional `validFrom`, and `energy` with 1 to 96
  `prices` of `priceKwh` (excluding GST, -5 to 20) and optional `conditions`
  (`startTimeOfDay`/`endTimeOfDay` `HH:MM`, `dayOfWeek`,
  `validFromDate`/`validToDate` `YYYY-MM-DD`, `minPower`/`maxPower` in W,
  negative for export), and optional `taxRates` `[{"type": "GST", "tax": 10}]`.
  No charging-time, idle, fixed, reservation or minimum/maximum cost
  components. `tariff_stations` is the command station plus every
  `plugfest_stations` identity while `plugfest_enabled` is on; the `SIM-EV-`
  rule does not apply, since a tariff is information, not control. The
  gateway waits up to 8 s and returns the station's reply unchanged: the
  SetDefaultTariffResponse (`{"status": "Accepted"}`, `Rejected`, ...) or, for a
  CALLERROR, CitrineOS's error object (for example
  `{"_errorCode": "NotImplemented", ...}`). 504 when the station does not
  answer. CitrineOS stores an accepted tariff in its Tariffs table by
  `tariffId`; connectors keep the lab tariff.

`/lab/control-policy` reports `price_commands` (`{"enabled": false}` when
off) with the currency, the limits, the routes and `tariff_stations`. The
existing keys are unchanged. The command role in the CitrineOS roles seed gets
the three price routes only while both flags are on.

CitrineOS itself sends a CostUpdated from its Tariffs table (zero for the lab
tariff) every 60 s of a transaction, which would replace the price shown by
C. With price commands on, the App sets CitrineOS's
`transactions.costUpdatedInterval` to 2147483 s (about 24.8 days, the longest
interval Node.js can schedule), so those messages stop in practice. Upstream
requires either that interval or `sendCostUpdatedOnMeterValue`, which would
put a zero `totalCost` into every TransactionEventResponse instead. CitrineOS
still fills `totalCost` in the TransactionEventResponse that ends a
transaction (zero with the lab tariff), and 0 for a 2.1 transaction cancelled
before any energy was delivered.

## DER control (lab)

Off unless `der_commands_enabled: true` (default `false`; needs
`command_control_enabled`). OCPP 2.1 DER control of the command station only,
which must be online on OCPP 2.1. The three routes use the command token and
`?identifier=<command station>&tenantId=1`, like the scoped commands, and
answer with the station's reply (or CitrineOS's CALLERROR) unchanged.

| Route | Body |
|---|---|
| `POST /ocpp/2.1/smartcharging/setDERControl` | `isDefault`, `controlId` (1 to 36 of `A-Za-z0-9._:-`), `controlType` and its one control |
| `POST /ocpp/2.1/smartcharging/getDERControl` | `requestId`, optional `isDefault`, `controlType`, `controlId` |
| `POST /ocpp/2.1/smartcharging/clearDERControl` | `isDefault`, optional `controlType`, `controlId` |
| `GET /lab/der-events` | none (api or command token): the station's last 20 DER messages, newest first |

- **Set**: four control types, each with `priority` (integer, 0 or more) and
  optional `startTime` and `duration` (1 to 86400 s):
  `LimitMaxDischarge` with `limitMaxDischarge.pctMaxDischargePower` 0 to 100
  (no `powerMonitoringMustTrip` curve); `FixedPFInject` and `FixedPFAbsorb`
  with `displacement` above 0 and at most 1 and `excitation`; `FixedVar` with
  `setpoint` -100 to 100 and `unit` `PctMaxW`, `PctMaxVar` or `PctVarAvail`.
  Curves, trip settings, `EnterService`, `FreqDroop` and `Gradients` are
  refused (400), as is any other key or `customData`.
- **Get**: after an Accepted status the gateway waits up to 5 s for the
  station's `ReportDERControl` messages with that `requestId` (until one has
  no `tbc`) and returns them as `reports`, oldest first.
- **Events**: `ReportDERControl`, `NotifyDERStartStop` and `NotifyDERAlarm`
  from `OCPPMessages`. Home Assistant's `ha_reader` role may read only these
  three station messages there (20 rows, the payload but not the raw frame).
- `/lab/control-policy` lists the routes, control types and limits as
  `der_commands`, and `/lab/status` shows `der_commands`.

A DER control is information for the station's own DER function. The gateway
does not change any charging profile or power bound because of it.

## Operator UI scope (opt-in)

For the **CitrineOS Operator UI** App. Off unless `operator_ui_enabled: true`.

| Option | Meaning |
|---|---|
| `operator_ui_enabled` | Accept `operator_token` at the gateway (8080) for GraphQL as the read-only Hasura role `operator_ro`, and apply `metadata-operator.json` (upstream's full schema) on start |
| `operator_token` | 64 hex characters, distinct from every other secret; the same value goes in the Operator UI App |
| `operator_commands_enabled` | Also allow the fixed operator command set (see the Operator UI App's DOCS) to any online tenant-1 station on the matching OCPP version |

The operator role can read everything the UI needs but cannot insert,
update or delete. BasicAuthPassword and other password or key variables,
OCPI credential profiles, webhook subscriptions and the remote (IP) address of
connection events (`WebsocketEvents`) are not readable. The
`ha_reader` role used by CitrineOS-HA is unchanged. Every operator command
is logged as `Operator command <action> to <station> (<protocol>)`.

`tools/build_operator_metadata.py` regenerates `metadata-operator.json`
from the pinned upstream release. The schema is v2.1.0's: the
`LatestStatusNotifications` table is gone (upstream migration
20261015140000; each connector has a `LatestStatusNotification` relationship
instead), and `NetworkAlerts`, `NetworkAlertOccurrences` and `WebsocketEvents`
are new. Use the Operator UI App 0.2.0 or later (built from v2.1.0); 0.1.0
(v2.0.1) shows errors where it reads the old
table.

## Plugfest listener (opt-in, external charging stations)

For an OCPP Plugfest where this server is the CSMS under test, external
charging stations on the venue network need to connect. `plugfest_enabled`
(default `false`) adds listener `citrine-plugfest` on port 8083, and six
identical listeners on ports 8100 to 8105 (`citrine-plugfest-8100` ...
`citrine-plugfest-8105`) so that each station under test can be given its own
endpoint:

- OCPP 2.1, 2.0.1 and 1.6, Security Profile 1 (Basic Auth over `ws://`),
  tenant 1. The server chooses the first of 2.1, 2.0.1, 1.6 that the station
  offers. 1.6 stations use the same Basic Auth password. Scoped commands
  (see above) cover 2.1, 2.0.1 and 1.6; Operator UI commands cover 2.0.1
  and 2.1 only;
- only the identities in `plugfest_stations` are admitted, each with its own
  password; unknown stations and wrong passwords are refused at the
  WebSocket upgrade;
- identities are OCPP station IDs (up to 48 of `A-Z a-z 0-9 . _ ~ * + -`; no
  `:` or `/`), passwords 16 to 40 printable characters, all unique and
  distinct from every other credential. An identity that a simulator option
  already provisions (`SIM-CITRINE-LAB-01` with `simulator_enabled`, the
  command station with `profile_simulator_enabled`) is refused. The scoped HA
  command path only ever targets `command_station_id`: a `SIM-EV-` simulator,
  or a vendor station only when `command_real_stations_enabled` is on. A
  `SIM-EV-` simulator may be listed to rehearse the vendor path;
- stations are provisioned at startup (identity, password, Accepted boot);
  their EVSEs and connectors are created from their own status reports.
- at every startup, Basic Auth passwords of stations that are no longer
  provisioned (removed from `plugfest_stations`, or a disabled simulator)
  are revoked, so a removed station cannot log in again.

Ports 8083 and 8100 to 8105 are the only ports this App declares, and each is closed
until you set a host port for it on the App's Network tab. Vendors then use
`ws://<host>:<host-port>/<station-id>` with Basic Auth user `<station-id>`,
for example one station per port:

| Station under test | Endpoint |
|---|---|
| 1 | `ws://<host>:8100/<station-id>` |
| 2 | `ws://<host>:8101/<station-id>` |
| 3 | `ws://<host>:8102/<station-id>` |
| 4 | `ws://<host>:8103/<station-id>` |
| 5 | `ws://<host>:8104/<station-id>` |
| 6 | `ws://<host>:8105/<station-id>` |

All seven ports admit stations the same way (the `plugfest_stations` list,
or open admission). A port does not restrict which identity connects on it:
it gives each station a separate endpoint, log and firewall rule, not
separate credentials. Close a port again (clear its host port) when its
station's slot ends.

Read this before enabling it:

- Security Profile 1 is cleartext: passwords and OCPP traffic can be read
  by anyone on the same network. Use it only on the Plugfest network, only
  during test slots, and with passwords made for the event.
- Do not expose ports 8083 and 8100 to 8105 to the internet (no port forward); an online
  test partner needs a separate TLS (Security Profile 2) path.
- Command and control of a real station by the HA path needs
  `command_real_stations_enabled` and that station as `command_station_id`;
  otherwise use the test partner's agreed procedure.

### Open admission on 8083 and 8100 to 8105 (opt-in, unauthenticated)

`plugfest_open_admission: true` (default `false`, needs `plugfest_enabled`)
switches 8083 and 8100 to 8105 to Security Profile 0: any station identity connects, with no
password, on 2.1, 2.0.1 or 1.6, and registers at BootNotification. Any
Authorization header is ignored. `plugfest_stations` may then be empty.
Anyone who can reach the port can register a station or take over an
identity that is already connected, so use it only on an isolated test
network, only while a host port is published, and switch it off again
afterwards. The server logs a warning at start while it is on.

See [the Plugfest runbook](https://github.com/purcell-lab/ocpp-plugfest/blob/main/plugfest-lab/RUNBOOK.md).
