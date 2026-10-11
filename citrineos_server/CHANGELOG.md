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
