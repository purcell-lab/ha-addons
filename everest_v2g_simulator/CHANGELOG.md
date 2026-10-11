# Changelog

## 0.1.4 (unreleased)

- Add an optional provisioned Basic Authentication password for an isolated CSMS.
- Preserve the original generated password for rollback; never include the
  supplied password in returned settings or status.
- Keep the existing explicit archive-and-rebind requirement. No migration runs
  merely by upgrading the App.
- Prebuilt images require separately approved publication before installation.
- Request import/export energy and signed power in OCPP transaction frames.
- Version 0.1.3 is already published with the shared runtime packaging; these
  functional changes must not overwrite that release.
