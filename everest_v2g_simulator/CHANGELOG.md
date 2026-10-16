# Changelog

## 0.1.6 (unreleased)

- Offer and publish aarch64 images again alongside amd64, for example for a
  Home Assistant Green test host. No functional change from 0.1.5.

## 0.1.5 (released 2026-10-11)

- Send OCPP transaction meter samples every second instead of every ten
  seconds, so the CSMS record can time step response and direction changes.
- Status page redesign: icons, a bidirectional power bar and a two-minute
  power trend; live reading chips coloured green for import/charging and blue
  for export/discharge, always with a +/- sign, arrow icon and text label;
  signed, coloured composite schedule values; discovery self-test moved to
  the bottom. Readings refresh every second.
- Accessibility: visible keyboard focus, AA contrast in light and dark themes,
  reduced-motion support and a polite screen-reader announcement only when
  the power direction changes. No new network access; icons are inline SVG
  under the existing Content-Security-Policy.

## 0.1.4 (released 2026-10-11)

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
