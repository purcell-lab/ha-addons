# Changelog

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
