# Changelog

## 0.1.0 (unreleased)

- First release: Open Dynamic Export v0.20.0 (commit `bc807abb`) built from
  the pinned upstream source with a small Ingress patch, on a pinned
  `node:24-alpine3.22` base, for amd64 and aarch64.
- Web UI through Home Assistant Ingress; the unauthenticated LAN port is off
  by default.
- `config.json` from the `config` option or from this App's
  `/addon_configs` folder; CSIP-AUS certificate and key from the same
  folder; optional InfluxDB 2.
- Manual start; inverter control stays off unless the configuration
  enables it.
