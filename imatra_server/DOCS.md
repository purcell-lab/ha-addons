# Imatra ISO 15118-2 Lab

The [Imatra](https://github.com/Chargetronic/imatra.iso15118_server) cloud
ISO 15118-2 server (Chargetronic, Apache-2.0) as one App, for lab work with
simulators. The station hardware stays simple; the server runs the
ISO 15118-2 AC session (EIM), DIN 70121 state of charge read-out and PWM, and
accepts operator current limits through its API.

Not for the Home Assistant Green until approved. Upstream caps its services at
about 1.2 GB together; CI records the actual use of this App.

## What is inside

One container, built in GitHub Actions from the pinned upstream source
(v0.1.0) and published to GitHub's container registry, so Home Assistant only
downloads it. Nothing from upstream is stored in this repository; it holds the
build and start-up scaffolding, and the image carries the upstream LICENSE,
NOTICE and PATENTS.md.

| Service | Listens on |
|---|---|
| Gateway (Caddy): `/v1` and `/health` | 8080 (published only if you set a host port) |
| Device broker (Mosquitto), MQTT with mutual TLS | 8883 (published only if you set a host port) |
| Broker listener for the services | 127.0.0.1:1883 |
| Postgres 16, Valkey 8, operator API, engine, relay, projector | 127.0.0.1 only |

The broker is internal to this App. Devices log in with certificates only
(the certificate CN is the user name), so the Home Assistant Mosquitto App is
not used and is not changed.

Other Apps reach the API at `http://<repo>-imatra-server:8080` on the
internal network without publishing a port.

## Configuration

| Option | Meaning |
|---|---|
| `operator_api_key` | Required, 16 or more characters. Send it as `X-API-Key` on every `/v1` request. |
| `broker_dns` | Name in the broker certificate. Empty: the container host name. Devices must connect by this name. |
| `broker_ips` | IP addresses to add to the broker certificate. |
| `devices` | Lab devices: `id` (lowercase, digits, `-`), `type` (default `station`), `rules` (a JSON object, see upstream `docs/rules.md`). |
| `evse_max_current_a`, `evse_phases`, `evse_nominal_voltage_v` | Station defaults (32 A, 3 phases, 230 V). |

For each device the App issues a certificate from its own CA to
`/share/imatra/devices/<id>.pem` (certificate and key in one file) and copies
the CA to `/share/imatra/ca.crt`. These are lab test keys: do not use them on
a public network. The App also publishes the device's registry entry
(`bound`), again only when the type or rules change. Removing a device from
the list does not revoke it.

Internal passwords are generated once and kept in `/data`. They are never
shown in the log.

## Operator limits

```bash
curl -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
  -X POST http://<host>:8080/v1/devices/dev-01/limit \
  -d '{"limit_a": 10, "duration_s": 600}'
```

Every limit needs a duration. The server refuses limits below 6 A (the
IEC 61851 minimum) and above the station limit. `DELETE` on the same path
cancels it. See upstream `docs/operator.md` for sessions, activations and the
event feed.

## Not included yet

- ISO 15118-20, DC, bidirectional charging and Plug & Charge (not in Imatra).
- The Imatra test harness. It is PolyForm Internal Use 1.0.0 (no
  distribution), so it is never bundled or published here. CI fetches and
  builds it at run time only.

## Licences and patents

The server is Apache-2.0; its LICENSE, NOTICE and PATENTS.md are in
`/usr/share/doc/imatra/` in the image. Chargetronic states that running the
server is free; its patents (FI 20246111 A1, EP 4711188 A1) concern station
equipment and adapters. See upstream
[PATENTS.md](https://github.com/Chargetronic/imatra.iso15118_server/blob/main/PATENTS.md).
