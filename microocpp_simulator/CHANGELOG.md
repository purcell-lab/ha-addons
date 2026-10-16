# Changelog

## 0.1.5

- Resolve CSMS hostnames through the Supervisor DNS (#38): Mongoose has its own
  resolver, which defaulted to public `8.8.8.8` and could not find
  Supervisor App hostnames such as `<repo>-citrineos-server`. The launcher now
  passes the first IPv4 `nameserver` from `/etc/resolv.conf`.
- New `archive_and_rebind` option (#29): moves `mo_store` and the destination
  binding into `/data/archive-<UTC timestamp>/`, then binds the configured
  destination. Nothing is deleted.

## 0.1.4

- Home Assistant now pulls a prebuilt image
  (`ghcr.io/purcell-lab/{arch}-microocpp-simulator`, amd64 and aarch64) built and
  checked in GitHub Actions, instead of compiling MicroOcppSimulator on the
  host (the on-device compile took about 15 minutes on an aarch64 Home
  Assistant Green). No functional change from 0.1.3.
- Publication is approval-gated (`RELEASE.md`); PR CI runs the same image
  checks as the publish gate.

## 0.1.3 and earlier

See `DOCS.md` for the per-version notes.
