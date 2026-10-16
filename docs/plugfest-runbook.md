# Plugfest runbook: CitrineOS on the Home Assistant Green

OCPP 2.0.1 & 2.1 Plugfest, October 2026. Purcell is a **CSMS** under test.
The CSMS is the CitrineOS Isolated Lab App on the Home Assistant Green,
plugged into the venue LAN. Stations connect with Security Profile 1
(Basic Auth over `ws://`) to the opt-in Plugfest listener (port 8083).

## Slots (Purcell row)

| Slot | Charging station | Notes |
|---|---|---|
| 1 | OCTT (DNV) | Conformance tool acting as a station; ask which security profile its test cases need |
| 2 | EVX Australia | Venue LAN |
| 5 | EVSE | Venue LAN |
| 6 | Trialog | Venue LAN |
| 7 | AS Jade - CS (online) | **Online**: cannot reach a LAN-only CSMS; needs a separately agreed TLS path, or reschedule. Do not port-forward 8083 |
| 10 | Starcharge | Venue LAN |

## Before the event

1. Install the CitrineOS stack on the Green (database, broker, Hasura,
   server; aarch64 support from the aarch64 PR). Fresh generated secrets.
2. Ask each vendor for its **station identity** (OCPP `chargingStation`
   id) and OCPP version. Generate one password per station, 16 to 40
   printable characters, for example
   `python3 -c "import secrets;print(secrets.token_urlsafe(24))"`.
3. Server options: `mode: isolated`, the dependency hosts and secrets,
   `plugfest_enabled: true`, and `plugfest_stations` with one
   `{id, password}` entry per vendor station. Keep
   `command_control_enabled: false` unless a simulator command test is
   planned.
4. Rehearse on a home network: set a host port for `8083/tcp` (for example
   `8083`), connect a test station with Basic Auth to
   `ws://<green-ip>:8083/<id>`, check its BootNotification is Accepted, then
   remove the host port again.

## At the venue

1. Connect the Green by Ethernet. Note its venue IP (Settings → System →
   Network) and, if possible, ask for a DHCP reservation.
2. Start database, broker, Hasura, then the server; check `/lab/status`
   lists the expected `plugfest_stations`.
3. Keep the `8083/tcp` host port empty between slots.

## Each slot

1. Set the `8083/tcp` host port; restart the server App.
2. Give the vendor: URL `ws://<green-ip>:8083/` (the station appends its
   identity), its identity and its password. Nothing else is shared.
3. Run the agreed test cases. Record supported and unsupported features,
   message traces and the transaction evidence (TransactionEvents and
   MeterValues through the read-only discovery endpoint).
4. After the slot: clear the `8083/tcp` host port and restart the server
   App. Remove the vendor's entry from `plugfest_stations` if it will not
   return; on restart its password is revoked in the database.

## After the event

1. Set `plugfest_enabled: false`, clear `plugfest_stations` and the host
   port, and restart the server.
2. Export the evidence, then reset or archive the dedicated database.
   Passwords of stations no longer listed are revoked at each restart; the
   station records and their message history stay until the reset.
3. Treat every Plugfest password as public; none is reused.

## Not covered

- Security Profile 2/3 (TLS, client certificates). OCTT test cases may need
  them; agree the scope with DNV beforehand.
- Internet-facing access for the online slot.
- Control of real stations through the Home Assistant command path, which
  stays limited to `SIM-EV-` simulators.
