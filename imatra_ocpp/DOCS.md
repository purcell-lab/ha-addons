# Imatra OCPP Bridge

Puts OCPP in the control path of the
[Imatra ISO 15118-2 Lab](../imatra_server/DOCS.md). Each Imatra device becomes
one OCPP charging station towards a CSMS such as CitrineOS:

```
CitrineOS <-- OCPP 2.1 / 2.0.1 --> this App <-- /v1 API + event feed --> Imatra App <-- MQTT/mTLS --> station <-- ISO 15118-2 --> EV
```

Source: [purcell-lab/imatra-ocpp](https://github.com/purcell-lab/imatra-ocpp)
(Apache-2.0), installed at a pinned commit when the App is built.

## Setup

1. Install and start the Imatra ISO 15118-2 Lab App with its devices.
2. For CitrineOS, enable `open_admission_enabled` on the CitrineOS App
   (internal listener 8082, any station identity, OCPP 2.1 or 2.0.1).
3. Set this App's options and start it.

| Option | Meaning |
|---|---|
| `csms_url` | CSMS address without the station id, e.g. `ws://<repo>-citrineos-server:8082`. The station id is added: `<csms_url>/<prefix><device id>`. |
| `csms_password` | Basic Auth password (user = station id). Empty for open admission. |
| `imatra_url` | Empty: the Imatra App in this repository (`http://<repo>-imatra-server:8080`). |
| `imatra_api_key` | The Imatra App's `operator_api_key`. |
| `devices` | Imatra device ids to bridge. Empty: all. |
| `station_id_prefix` | Default `IMATRA-`, so `dev-01` is station `IMATRA-dev-01`. |
| `confirm_timeout_s` | How long to wait for the device to confirm a limit before answering Rejected (default 10 s). |
| `default_duration_s` | Limit duration when a profile sets none (default 3600 s). Re-sent while the profile is valid. |
| `voltage_v`, `phases` | For profiles in W: A = W / (V x phases). |

## Behaviour

- SetChargingProfile (TxProfile, TxDefaultProfile, ChargingStationMaxProfile):
  Accepted only once the device confirmed the limit. Below 6 A, including
  0 A, Rejected `BelowMinimum`. Above the station limit, clamped. OCPP 2.1:
  `ChargingOnly` only.
- Outside a session, TxDefaultProfile and ChargingStationMaxProfile are
  stored and applied at plug-in.
- One plug-in session is one OCPP transaction (TransactionEvent Started,
  Updated with power, Ended with energy).
- Remote start and stop and Reset are rejected: Imatra starts on plug-in (EIM).
- No ports are opened. Not for the Home Assistant Green until approved.
