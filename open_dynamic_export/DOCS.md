# Open Dynamic Export

[Open Dynamic Export](https://opendynamicexport.com/) (ODE) controls solar
export and generation: CSIP-AUS dynamic connections, fixed or zero export,
and negative feed-in. This App runs ODE v0.20.0 on Home Assistant, with
its web UI in the sidebar through Ingress.

**It can curtail real inverters.** It starts manually, and nothing is
controlled until your configuration sets `"inverterControl": {"enabled": true}`.
Test with control disabled first.

## Configure

ODE reads one `config.json`
([reference](https://opendynamicexport.com/configuration/)). Provide it
one of two ways:

1. **`config` option:** paste the JSON into the App's Configuration tab.
2. **File:** leave `config` empty and put `config.json` in this App's
   folder, `/addon_configs/<prefix>_open_dynamic_export/` (for example
   with the File editor or Samba App).

The option wins when both exist. Invalid JSON stops the App with a clear
log message; ODE validates the content itself at start.

A minimal fixed export limit, with control off:

```json
{
  "setpoints": { "fixed": { "exportLimitWatts": 5000 } },
  "inverters": [
    { "type": "sunspec", "connection": { "type": "tcp", "ip": "192.168.1.6", "port": 502 }, "unitId": 1 }
  ],
  "inverterControl": { "enabled": false },
  "meter": {
    "type": "sunspec", "connection": { "type": "tcp", "ip": "192.168.1.6", "port": 502 },
    "unitId": 240, "location": "feedin"
  }
}
```

MQTT inverters and meters (for example published by Home Assistant
automations through the Mosquitto App) use `"type": "mqtt"` with
`mqtt://core-mosquitto`; see the ODE documentation.

### Options

| Option | Default | Meaning |
|---|---|---|
| `config` | empty | ODE `config.json` content; empty means use the file |
| `sep2_cert_file`, `sep2_key_file` | `sep2-cert.pem`, `sep2-key.pem` | CSIP-AUS device certificate and key file names in this App's folder |
| `sep2_pen` | `62223` | CSIP-AUS Private Enterprise Number (upstream default) |
| `timezone` | `Australia/Brisbane` | IANA time zone for schedules and logs |
| `log_level` | `info` | ODE debug-file log level |
| `influxdb_host` | empty | Optional InfluxDB 2 host for history charts |
| `influxdb_port`, `influxdb_org`, `influxdb_bucket`, `influxdb_token` | | InfluxDB settings; the token is required with a host |

Without InfluxDB the history charts on the UI show errors; control is
unaffected.

### CSIP-AUS

Put the certificate and key your network provider issues in this App's
folder under the configured names, then restart the App. They are copied
into the App's private data directory (key mode 600). Without them,
CSIP-AUS setpoints do not connect.

## Access

- **Ingress (default):** *Open Web UI* or the **Dynamic Export** sidebar
  entry, behind Home Assistant login.
- **LAN port (off):** ODE's UI and API have no authentication. Set a host
  port for `3000/tcp` on the Network tab only if you need direct access
  (for example from another system) on a trusted network.

## Data and logs

Configuration and certificates live in the App's data and are included in
App backups. ODE's rotating debug log files (up to about 1.1 GB) are kept
in temporary storage, not backed up; the App log shows ODE's console
output.

## Install size and source

Home Assistant pulls a prebuilt image
(`ghcr.io/purcell-lab/{arch}-open-dynamic-export`, amd64 and aarch64)
built in GitHub Actions from the pinned upstream commit; see `UPSTREAM.md`
and `RELEASE.md`.
