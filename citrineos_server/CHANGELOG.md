# Changelog

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
