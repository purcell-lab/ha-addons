# Imatra Test Harness (internal use)

One simulated ISO 15118-2 device for the Imatra ISO 15118-2 Lab App: the
Imatra test station and the Josev test EV, joined by a virtual V2G link inside
this App. Use it to exercise Imatra and the Imatra OCPP Bridge (and CitrineOS)
without hardware. It is simulated only: it proves nothing about physical
charging control.

## Licence first

The [Imatra test harness](https://github.com/Chargetronic/imatra.test_harness)
is licensed under PolyForm Internal Use 1.0.0 and "may not be distributed".
Patent FI 20246111: no licence is granted for EVSE, devices or vehicles.

This repository holds scaffolding only. The App image holds no harness code.
On start, and only when `accept_licence` is `true`, the App downloads the
harness at a pinned commit from GitHub, checks its SHA-256 and keeps it in this
App's `/data`. The Supervisor builds the image on your host. Do not push or
share the built image or `/data`.

## Set up

1. In the Imatra ISO 15118-2 Lab App, add the device to `devices`
   (`id: harness-01`, `type: station`, `rules: {"topology":"integrated"}`) and
   restart it. It issues `/share/imatra/devices/harness-01.pem`.
2. Optional: add `harness-01` to the Imatra OCPP Bridge `devices` and restart
   it. CitrineOS then sees `IMATRA-harness-01`.
3. Install this App, read the licence, set `accept_licence: true`, start.

## Options

| Option | Default | Meaning |
|---|---|---|
| `accept_licence` | `false` | Must be `true`, or the App will not start |
| `device_id` | `harness-01` | Device registered on the Imatra App |
| `server_host` | (derived) | Imatra App host; default `<repo hash>-imatra-server` |
| `broker_name` | (= host) | Name in the broker certificate, if `broker_dns` is set (e.g. `imatra.purcell.id.au`). Mapped to the server App in this App's `/etc/hosts` only |
| `replug_s` | `30` | Station replug interval (s) |
| `ev_pause_s` | `20` | Pause between EV sessions (s) |

## How it runs

- A veth pair `v2g0` (station, `fd15:118::10`) and `v2g1` (EV, `fd15:118::20`)
  inside this App's own network namespace. This needs `NET_ADMIN`; the App has
  no host network and no ports.
- The station connects to the Imatra broker on 8883 with mutual TLS (own PKI
  mode). The EV runs without TLS, because own PKI mode has no V2G signer.
- No SLAC, PLC, control pilot or meter: the link is virtual.

Memory: roughly 150 to 250 MB (Java for the EXI codec plus two Python processes).
