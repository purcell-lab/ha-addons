# Changelog

## 0.1.4 (unreleased)

- Home Assistant now pulls a prebuilt image
  (`ghcr.io/purcell-lab/{arch}-microocpp-simulator`, amd64 and aarch64) built and
  checked in GitHub Actions, instead of compiling MicroOcppSimulator on the
  host (the on-device compile took over 20 minutes on an aarch64 Home
  Assistant Green). No functional change from 0.1.3.
- Publication is approval-gated (`RELEASE.md`); PR CI runs the same image
  checks as the publish gate.

## 0.1.3 and earlier

See `DOCS.md` for the per-version notes.
