# CitrineOS Operator UI

The CitrineOS **Operator UI** (the CSMS management web app that ships with
CitrineOS v2.1.0) for the isolated CitrineOS lab, in the Home Assistant
sidebar through Ingress. It shows charging stations, connectors, status,
transactions, meter values, locations and OCPP message logs, and can send a
fixed set of operational commands.

It needs the **CitrineOS Isolated Lab** App 0.8.0 or later (CitrineOS v2.1.0), with its
operator scope turned on. It never talks to the database or Hasura
directly: everything goes through the lab server's gateway.

## Set up

1. In the **CitrineOS Isolated Lab** App, generate a token and set:
   ```yaml
   operator_ui_enabled: true
   operator_token: <64 hex characters, distinct from every other secret>
   operator_commands_enabled: false   # true for phase 2 commands
   ```
   Generate the token with `python3 -c "import secrets;print(secrets.token_hex(32))"`,
   then restart the server.
2. In this App, set:
   ```yaml
   gateway_url: http://<store>-citrineos-server:8080   # e.g. http://31ac84d3-citrineos-server:8080
   operator_token: <the same token>
   commands_enabled: false
   ```
3. Start the App and open **CitrineOS** in the sidebar (or *Open Web UI*).

Without a valid `gateway_url` and `operator_token` the App refuses to start
and says why in its log.

## What it can do

**Read-only data (phase 1).** All GraphQL reads run in Hasura as the role
`operator_ro`: upstream's full schema, tenant 1 only, select permission
only. Edits, creates and deletes in the UI (for example *Add Charging
Station* or editing a location) fail with a permission error, by design.
Station Basic Auth passwords and other password or key variables, OCPI
credential profiles and webhook subscriptions are hidden.

**Commands (phase 2).** With `commands_enabled: true` here **and**
`operator_commands_enabled: true` on the server, the UI's buttons can send:

| Area | Commands |
|---|---|
| EV driver | RequestStartTransaction, RequestStopTransaction, UnlockConnector, ClearCache |
| Configuration | Reset, ChangeAvailability, TriggerMessage |
| Reporting and monitoring | GetBaseReport, GetVariables, GetTransactionStatus, SetVariables (metering variables only, server 0.7.7) |
| Smart charging | SetChargingProfile, ClearChargingProfile, GetChargingProfiles, GetCompositeSchedule |

to any station of tenant 1, OCPP 2.0.1 or 2.1, only while it is online on
that version. SetVariables may only set the metering variables of
`SampledDataCtrlr` (TxStarted/TxUpdated/TxEnded measurands, TxUpdated and
TxEnded intervals) and `AlignedDataCtrlr` (Measurands, Interval, TxEnded
measurands and interval), no EVSE or instance. The gateway refuses
everything else, including any other SetVariables, certificate, firmware, network-profile, data-transfer, log and diagnostics
requests. Each command is logged by the server.

## Security

- The UI is reachable only through Home Assistant Ingress (behind HA login).
  The App's proxy accepts connections only from the Supervisor's Ingress
  peer, and no port is published.
- The operator token stays in the App. The browser never receives a token or
  secret; the proxy adds the token to each forwarded request.
- The UI's own login is not used: Home Assistant authenticates the operator.
  The v2.1.0 UI asks CitrineOS which pages and buttons the user may use
  (`/permissions/user`); the App's proxy answers that itself with "not
  enforcing", so the UI shows everything, as the v2.0.1 UI did, and the
  server's gateway still refuses what the operator scope does not allow.
  CitrineOS's development login (`/dev/token`, `/dev/roles`) is answered
  with 404 and never forwarded.
- No Hasura admin secret, database password or broker credential is given to
  this App.

## Limitations

- **No live updates.** GraphQL subscriptions are off; pages refresh on
  navigation. Reload a page to see new data.
- **Maps.** Location maps and address search need a Google Maps API key,
  which this App does not configure. The map area shows an error; the rest
  of the UI is unaffected.
- **Server actions.** File upload and storage features need cloud storage
  (S3 or GCS) and stay disabled; the browser console shows
  `Error: Unauthenticated` for those calls. This is expected.
- **Help video.** The welcome dialog's video is not shipped upstream and
  does not load. Close the dialog.
- The UI shows controls (edit, delete, add) that the read-only role refuses.
- **Network alerts.** The v2.1.0 UI adds a Network Alerts page (station
  connectivity, connector status, OCPP call failures), read-only like the
  rest. The server's websocket connection log is readable without the
  station's remote IP address.

## Resources

About 150 to 200 MB of memory. Prebuilt for aarch64
(`ghcr.io/purcell-lab/{arch}-citrineos-operator-ui`); Home Assistant pulls
the image. amd64 hosts add the store entry
`https://github.com/purcell-lab/ha-addons#local-build` instead and build it on the host.
