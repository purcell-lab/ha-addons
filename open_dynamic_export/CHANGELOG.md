# Changelog

## 0.1.1

- CSIP-AUS `rampTms` is now applied in hundredths of a second, as the
  standard defines, instead of seconds (upstream pull request #138,
  cherry-picked as `ramp-tms.patch`).
- Without InfluxDB, the UI's history requests no longer print an
  "InfluxDB isn't available" stack trace in the App log; they get HTTP 503
  (`influxdb-quiet.patch`).

## 0.1.0

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
