# CitrineOS isolated laboratory

**New controlled path: NO-GO for activation.** Merged source is not a deployed
release. The current EVerest runtime does not reliably honour 0 W profiles; keep
command controls off until the documented gates pass. Read the
[full implementation, build and test handover](../docs/citrine-everest-handover.md)
before preparing an update.

This App runs pinned CitrineOS **v2.0.1**, not an OCPP protocol version.
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

Other paths and methods are denied. GraphQL has no mutation permissions; its four
tables expose only the staged HA client's explicit discovery fields. Caller
authentication, role and tenant headers are never forwarded to dependencies.

The upstream API binds loopback port 8088 and uses its actual OIDC/JWT provider,
not local authentication bypass. The gateway signs 60-second internal JWTs with
an in-memory RSA key and role `lab-reader`; its loopback JWKS endpoint is port 8091.
RBAC permits only tariff reads for that role. Restart rotates the internal key.
Scoped commands use role `lab-controller`. At every start the App writes
CitrineOS's RBAC rules (`rbac-rules.json`) from the gateway's command route
list: with `command_control_enabled`, `lab-controller` may POST exactly the
scoped start, stop, profile and clear routes for OCPP 2.1, 2.0.1 and 1.6;
without it, none. The gateway still applies every check first.
The bearer gateway is a lab credential bridge, not an interactive identity provider.

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

**Reconnect patch (#67).** The image build patches one upstream file,
`@citrineos/ocpp/dist/src/transport/network-connection/websocket-network-connection.js`
(`rootfs/patch-reconnect.mjs`). Upstream v2.0.1 closes a station's old
connection in the background: it frees the station's connection slot at once,
then deregisters the station from the message router, which unbinds the
station's RabbitMQ bindings. A station that reconnected at once (EVerest does
after `Pong not received from server!`) registered its bindings in the
meantime, and the old deregistration then removed them: CitrineOS stored
every message from the station, but no reply (CALLRESULT) reached it, while
commands to the station still worked. With the patch a new connection waits
until an earlier connection of the same identity has finished closing. The
build fails unless the file is the exact v2.0.1 build, and CI checks that the
image is patched (`node /opt/citrine-ha/patch-reconnect.mjs --check`). If a
station shows the old symptom on an unpatched version, restart only the
station (one clean connection).

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

Upstream log lines that remain and need no action:

- `Active Transaction not found on charging station {} evse {} <station> 1`:
  a clock-aligned MeterValues (15 min by default) for an EVSE with no
  transaction.
- `(sequelize) Warning: Unknown attributes (chargingSchedule,transactionId)
  passed to defaults option of findOrCreate` on each SetChargingProfile.
- `MaxListenersExceededWarning: 11 connected listeners added to
  [RabbitMQConnectionManager]` at start: one listener per upstream module.

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
[server release](https://github.com/citrineos/citrineos-core/releases/tag/v2.0.1),
[deployment architecture](https://github.com/citrineos/citrineos-core/blob/v2.0.1/docker-compose.yml),
[HA-client compatibility PR](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/1).
# Staged Plugfest control extension

The 0.4.0 changes are a development draft. They add opt-in OCPP 2.1 admission
and a separate, narrowly scoped command credential for the existing EVerest V2G
simulator only. All command controls remain off by default; Hasura remains
read-only. Do not enable this draft until the full gateway, HA-client,
local-fallback and Citrine/EVerest integration gates pass.

See [the full Plugfest acceptance plan](../docs/citrine-plugfest-acceptance.md)
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

- The station connects on the Plugfest listener (8083), so `plugfest_enabled`
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
- With `plugfest_open_admission`, anyone who can reach port 8083 can connect
  as the command station's identity. Use a provisioned password for anything
  but an isolated test network.

## Operator UI scope (opt-in)

For the **CitrineOS Operator UI** App. Off unless `operator_ui_enabled: true`.

| Option | Meaning |
|---|---|
| `operator_ui_enabled` | Accept `operator_token` at the gateway (8080) for GraphQL as the read-only Hasura role `operator_ro`, and apply `metadata-operator.json` (upstream's full schema) on start |
| `operator_token` | 64 hex characters, distinct from every other secret; the same value goes in the Operator UI App |
| `operator_commands_enabled` | Also allow the fixed operator command set (see the Operator UI App's DOCS) to any online tenant-1 station on the matching OCPP version |

The operator role can read everything the UI needs but cannot insert,
update or delete. BasicAuthPassword and other password or key variables,
OCPI credential profiles and webhook subscriptions are not readable. The
`ha_reader` role used by CitrineOS-HA is unchanged. Every operator command
is logged as `Operator command <action> to <station> (<protocol>)`.

`tools/build_operator_metadata.py` regenerates `metadata-operator.json`
from the pinned upstream release.

## Plugfest listener (opt-in, external charging stations)

For an OCPP Plugfest where this server is the CSMS under test, external
charging stations on the venue network need to connect. `plugfest_enabled`
(default `false`) adds listener `citrine-plugfest` on port 8083:

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

Port 8083 is the only port this App declares, and it is closed until you
set a host port for `8083/tcp` on the App's Network tab. Vendors then use
`ws://<host-ip>:<host-port>/<station-id>` with Basic Auth user `<station-id>`.

Read this before enabling it:

- Security Profile 1 is cleartext: passwords and OCPP traffic can be read
  by anyone on the same network. Use it only on the Plugfest network, only
  during test slots, and with passwords made for the event.
- Do not expose port 8083 to the internet (no port forward); an online
  test partner needs a separate TLS (Security Profile 2) path.
- Command and control of a real station by the HA path needs
  `command_real_stations_enabled` and that station as `command_station_id`;
  otherwise use the test partner's agreed procedure.

### Open admission on 8083 (opt-in, unauthenticated)

`plugfest_open_admission: true` (default `false`, needs `plugfest_enabled`)
switches 8083 to Security Profile 0: any station identity connects, with no
password, on 2.1, 2.0.1 or 1.6, and registers at BootNotification. Any
Authorization header is ignored. `plugfest_stations` may then be empty.
Anyone who can reach the port can register a station or take over an
identity that is already connected, so use it only on an isolated test
network, only while a host port is published, and switch it off again
afterwards. The server logs a warning at start while it is on.

See [the Plugfest runbook](../docs/plugfest-runbook.md).
