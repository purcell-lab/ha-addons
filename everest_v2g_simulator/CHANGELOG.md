# Changelog

## 0.1.8 (unreleased)

- 0 W setpoints are honoured. The simulated DC supply now has a 0 A minimum
  current (upstream default 1 A at 200 V), so EvseManager no longer sees a
  200 W minimum above a 0 W target and keeps the previous current. Before,
  a 0 W setpoint left the EV at its previous power, and after a discharge
  that power reappeared as charging. The acceptance run now steps
  +6,000, 0, -5,000, 0 and +3,000 W.
- Still upstream: a charging-only period (no `setpoint` or
  `dischargeLimit`) does not bound discharge, because EVerest 2025.10.0
  OCPP201 sends no export limit. Use CentralSetpoint periods (DOCS.md).

## 0.1.7

- `tx_sample_interval_s` option (default 5 s) and a profile panel that
  shows the newest SetChargingProfile of any purpose.

## 0.1.6 (unreleased)

- Offer and publish aarch64 images again alongside amd64, for example for a
  Home Assistant Green test host.
- Replace the full OpenJDK 17 JRE package (about 184 MB) with a jlink
  runtime of only the modules Josev's EXI codec uses (about 50 MB), with a
  fixed small heap (-Xmx128m, serial GC). The codec JVM's resident memory
  drops from about 158 MB to about 92 MB; EXI encoding is byte-identical.

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
