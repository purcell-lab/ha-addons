# Changelog

## 0.1.4 (unreleased)

- Add an optional provisioned Basic Authentication password for an isolated CSMS.
- Preserve the original generated password for rollback; never include the
  supplied password in returned settings or status.
- Keep the existing explicit archive-and-rebind requirement. No migration runs
  merely by upgrading the App.
- Prebuilt images require separately approved publication before installation.
- Request import/export energy and signed power in OCPP transaction frames.

## 0.1.3 (released 2026-10-11)

- Rebuilt from the shared EVerest runtime image
  `ghcr.io/purcell-lab/everest-runtime:2025.10.0-1`. No functional change:
  the identical-file release gate found 0 differences against 0.1.2 under
  the EVerest, licence, App code and Python paths.
- From the next release, only amd64 images are built and offered.
