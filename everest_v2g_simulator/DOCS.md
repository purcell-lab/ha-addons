# EVerest DC V2G Test Charger

A simulated bidirectional DC charging station built from
[EVerest](https://everest.github.io/latest/how-to-guides/getting-started/get-started-sw.html)
2025.10.0, with one EVSE, one CCS2 connector and a simulated EV. The charger
and the EV talk **ISO 15118-20 with the DC_BPT (bidirectional power
transfer) service over mutual TLS 1.3**, so a central system (CSMS) can both
charge and discharge the vehicle.

The station offers **OCPP 2.1 first and falls back to OCPP 2.0.1** when the
CSMS only supports 2.0.1. The Status page shows the negotiated version.

| Negotiated | What the CSMS can do |
|---|---|
| `ocpp2.1` | Charge and discharge. Send a TxProfile in W with `operationMode: CentralSetpoint` and a signed `setpoint` (negative is discharge, V2G export to the grid). |
| `ocpp2.0.1` | **Charging only.** OCPP 2.0.1 has no discharge or setpoint fields, so the station only applies charging limits. |

This is a test tool, not a physical charger. It sits beside the AC
**EVerest OCPP 2.1 Test Charger** App and does not replace it.

## Scope

- DC charging and discharging between the simulated charger and EV, using
  the ISO 15118-20 Dynamic control mode. Power, voltage and energy come
  from EVerest's DC supply simulator, not from real hardware.
- OCPP over `ws://` with Security Profile 1. No TLS to the CSMS.
- No Plug and Charge. The test PKI only secures the ISO 15118 link inside
  the App.
- Negotiating `ocpp2.1` and passing the tests in VALIDATION.md proves the
  messages tested there. It does not prove OCPP 2.1 or ISO 15118-20
  conformance, and a CSMS receiving a reply is not proof that it accepted
  or acted on it.

## Safe first start

1. Install the App after the PR is merged. Keep `csms_url` empty.
2. Start it manually and open the web UI. It should show **Disconnected (no
   CSMS URL)** and EVSE state **Unplugged**. The first start generates the
   test PKI (a few seconds).
3. Prepare a separate **test** CSMS endpoint. Exclude every `SIM-` device
   from physical charger automations, driver registration and BSV
   settlement. The App cannot enforce those exclusions in another
   integration.
4. Set `csms_url` to `ws://test-host:port[/base-path]` without the station
   ID, set a unique `SIM-EV-` charge-point ID and
   `acknowledge_test_isolation: true`. Restart the App.
5. Confirm BootNotification and the negotiated version in the test CSMS and
   on the Status page.

An empty `csms_url` always disables the connection. The station then points
at a closed loopback port (`ws://127.0.0.1:9`), so the App log shows
`connection refused` retries; nothing leaves the container.

The first connected start binds the URL and charge-point ID to this App's
data. Changing either later is refused until you set `archive_and_rebind:
true` for one start (state is moved to `/data/archive-<time>/`, never
deleted), then set it back to `false`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `csms_url` | Empty | OCPP base URL without the station ID. `ws://` on an explicit port, no credentials, query or `%` encoding. |
| `charge_point_id` | `SIM-EV-EVEREST-V2G-01` | Required `SIM-EV-` namespace, up to 36 suffix characters. Also the Basic Auth user. |
| `ocpp_version` | `2.1` | `2.1` offers `ocpp2.1, ocpp2.0.1`. `2.0.1` offers only `ocpp2.0.1`. |
| `max_power_kw` | `11` | Charger rating in both directions, 3 to 11 kW. Also the default composite limit. The simulated board's AC export capability (16 A on three phases) sets the 11 kW ceiling. |
| `acknowledge_test_isolation` | `false` | Operator assertion that the endpoint and downstream automations are test-only. Required for a nonempty `csms_url`. |
| `archive_and_rebind` | `false` | One-start operator action to archive state and allow a new binding. |

**Basic Auth.** Security Profile 1 sends a random 32-character password,
generated once in `/data/basic-auth-password`. The App never logs or shows
it. Use a test CSMS that does not require Basic Auth (HA OCPP does not).

## Using the simulated EV

The Status page has three controls. They only drive EVerest's EV simulator;
the UI cannot send OCPP messages, choose direction or set power. Direction
and power come only from the CSMS.

- **Plug in**: the EV runs SLAC, opens the ISO 15118-20 TLS session, offers
  DC_BPT and waits for authorisation. Start the transaction from the CSMS
  with RequestStartTransaction. Cable check and pre-charge take about 15 s.
- **EV stop session**: the EV ends the ISO 15118 session and unplugs.
- **Unplug now**: immediate unplug, which ends any transaction.

Live readings show direction, signed power (negative is discharge), meter
import and export energy, DC voltage and current, and the rated power.

## Charging and discharging profiles

Send a TxProfile in W after the session reaches **Charging** (see the
limitations). A working OCPP 2.1 example, 20 s per step:

```json
{"startPeriod": 0,  "limit": 11000, "dischargeLimit": -11000, "setpoint": 6000,  "operationMode": "CentralSetpoint"},
{"startPeriod": 20, "limit": 11000, "dischargeLimit": -11000, "setpoint": -5000, "operationMode": "CentralSetpoint"},
{"startPeriod": 40, "limit": 11000, "dischargeLimit": -11000, "setpoint": 3000,  "operationMode": "CentralSetpoint"}
```

This measured +6,000 W, then -5,000 W (export), then +3,000 W. The
**Last received TxProfile** panel shows the profile and the station's
reply, and **Effective limit** shows EVerest's composite schedule for EVSE
1, including limit, discharge limit and setpoint. A ChargingStationMaxProfile
on EVSE 0 is merged into that composite by libocpp.

### Known EVerest 2025.10.0 limitations

These are upstream behaviours, found in testing and recorded in
VALIDATION.md. The App does not hide them.

- **0 W and small charging setpoints are not honoured.** A 0 W setpoint,
  or a charging setpoint below about 1.4 kW (the simulated board's 6 A
  minimum on one phase), leaves the EV at its previous power. After a
  discharge, that previous power reappears as charging. To stop power flow,
  end the transaction (RequestStopTransaction).
- **Give every period a setpoint.** EVerest applies the first setpoint
  before its period starts and keeps the last one after it ends, so a
  period without a setpoint inherits a neighbour's.
- **Send profiles after Charging starts.** A profile that arrives during
  pre-charge or the switch to charging can be held at 0 W.
- **Direction changes show a short transient.** For one to two seconds after
  a direction change the simulator can report power above the rating
  (13.5 kW was seen once). Energy totals stay within 10 per cent of the
  integrated power.
- **Station-level limits come through EVSE 1 only.** libocpp reports the
  EVSE 0 composite as per-phase shares, and EVerest 2025.10.0 reads the L1
  share as the total, which capped every target at a third of the rating.
  The App therefore applies OCPP limits through EVSE 1, whose composite
  already includes station-level profiles.

### CSMS requirements

The station asks the CSMS for the certificate status of the ISO 15118
chain. The CSMS must answer GetCertificateStatus with a valid
`status` field (for example `Failed`). libocpp 2025.10.0 aborts the station
process on a reply without one.

## Security boundaries

The UI uses Home Assistant Ingress authentication. nginx on port 8099
accepts only the Supervisor Ingress peer (`172.30.32.2`), checked on the
actual connection, not a forwarded header. The UI service and MQTT broker
listen on loopback only. Only three fixed EV-simulator POST endpoints
exist; all other paths are read-only. No host ports, host networking,
hardware access, HA API token or Docker socket are requested. Do not add a
port mapping or widen the ACL to make direct probes pass; use **Open Web
UI**.

**Why this App needs NET_ADMIN.** ISO 15118 discovery (SDP) is IPv6
link-local multicast, which loopback cannot carry. On start the App
creates a private veth pair (`v2g0` for the charger, `v2g1` for the EV)
inside its own container network namespace. Nothing is bridged to the host
or the LAN. The same capability loads an nftables policy that **drops all
inbound traffic** on the Home Assistant network interface except Ingress
from the Supervisor and replies to the App's own outbound OCPP connection.
The upstream SDP server binds every interface, so this policy is the
boundary for TCP and defence in depth for UDP. If either step fails, the
App logs `V2G isolation setup failed` and starts no EVerest process.

NET_ADMIN lowers the App's Home Assistant security rating. It does not give
host networking, raw sockets or access to other containers.

**Test PKI.** ISO 15118-20 needs mutual TLS 1.3, so the charger and EV need
certificates. No keys ship in the image. Each install generates its own
chain under a random key password in `/data/pki` (Josev's
`create_certs.sh`), and renews the 60-day leaf certificates on start when
they have under 7 days left. The chain is test-only and is never trusted by
real vehicles or chargers.

## Storage

All state is in the App's `/data`: OCPP message logs
(`everest/ocpp_logs`, rotated at 1 MiB, 3 files), the core database with
transactions and installed charging profiles (`everest/ocpp201/cp.db`),
the test PKI (`pki/`) and the generated EVerest configuration. The device
model is rebuilt from the options on every start.

## Install size

Home Assistant pulls a prebuilt image for its architecture
(`ghcr.io/purcell-lab/{arch}-everest-v2g-simulator`, about 560 MB on amd64
and 585 MB on aarch64, of which the Java runtime for the EV simulator is
about 184 MB) rather than building locally from EVerest's 4.3 GB build
image. The image is published only through the approval-gated tag process
in `RELEASE.md`.
