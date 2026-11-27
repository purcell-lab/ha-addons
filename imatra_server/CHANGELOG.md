# Changelog

## 0.1.0

- First release. Imatra ISO 15118-2 server v0.1.0 (commit `c007614`, with the replug fix for Chargetronic/imatra.iso15118_server#15) built
  from source in GitHub Actions and published as a prebuilt image: one container with its own Postgres 16, Valkey 8 and
  Mosquitto. Services listen on 127.0.0.1; only the gateway (8080) and the
  device broker (8883, mutual TLS) can be published.
- Lab devices from the options: certificates in `/share/imatra/devices/` and
  a bound registry entry for each.
- CI runs the App end to end with the Imatra test harness station and EV,
  fetched at run time and never bundled. The same end to end gates every
  published image.
