# MicroOCPP Simulator

A native **OCPP 2.0.1 JSON** simulated charging station with two EVSEs, each
with one connector (shown as connectors 1 and 2 in the upstream UI).
It runs independently of your browser. This first App release deliberately
uses MicroOCPP's limited 2.0.1 implementation. It does not provide full
2.0.1 smart charging, V2G, TLS or wallet/payment functions.

## Safe first start

1. Install the App from this repository after the PR is merged.
2. Keep `backend_url` empty. Start manually and open the web UI.
3. Verify the interface works while the OCPP connection stays disconnected.
4. Prepare a separate **test** CSMS endpoint/HA OCPP entry. Confirm all
   `SIM-*` devices are excluded from real charger automations, driver
   registration and BSV settlement. The App cannot enforce those exclusions
   in another integration.
5. Set `backend_url` to the verified `ws://test-host:port[/base-path]`, without
   the station ID. Use `homeassistant` only when that is the confirmed
   reachable HA OCPP server. Do not guess the port or reuse the real CPID.
6. Set a unique `SIM-` charge-point ID and
   `acknowledge_test_isolation: true`. Restart the App.
7. Confirm the negotiated protocol and BootNotification in the test CSMS.
   In the simulator UI set the connector plug/ready controls and present a
   dedicated test RFID token accepted by the test CSMS.

An empty backend always disables the connection, including after an earlier
configured run. No public echo endpoint, real station identity or live host
address is built into the App.

## Options

| Option | Default | Meaning |
|---|---|---|
| `backend_url` | Empty | OCPP base URL, without appended CPID. Initial release accepts only credential-free `ws` on an explicit port. |
| `charge_point_id` | `SIM-MICROOCPP-01` | Required `SIM-` namespace, up to 40 suffix characters. |
| `acknowledge_test_isolation` | `false` | Operator assertion that the endpoint and downstream automations are test-only. Required for a nonempty backend. |
| `archive_and_rebind` | `false` | Move existing simulator state into a timestamped archive, then bind the configured destination. |

Use only on an isolated trusted test network. There is **no TLS or Basic Auth
support in this packaging release**; do not send real RFID identifiers or
use it across an untrusted/public network. TLS validation and secret handling
need a separate reviewed increment rather than an insecure skip-verify flag.

The UI uses Home Assistant Ingress authentication. Port 8000 is loopback-only;
port 8099 accepts only the Supervisor Ingress peer. No host ports, host
networking, hardware access, HA API token or Docker socket are requested.
Do not add an external port mapping or disable protection mode.

An API probe made directly from another App can receive `403 Forbidden`.
The ACL checks the actual peer, not an `X-Forwarded-For` header. Use Home
Assistant's **Open Web UI** for the browser acceptance check; a denied
direct probe does not establish that authenticated browser Ingress is broken.
Do not allow the container gateway or whole App subnet just to make such
probes pass.

Version 0.1.1 guards the upstream 1.6-only dummy error-code and smart-charging
setup hooks in 2.0.1 mode. Those hooks looked for legacy Connector objects
that the 2.0.1 EVSE model does not create, producing a misleading
`connector with connectorId 1 does not exist` startup error. This correction
does not add smart charging or simulated fault reporting.

Version 0.1.1 also corrects the Web UI response type. Version 0.1.0 supplied
conflicting `application/gzip` and `text/html` headers, which can make a
browser download `download.gz` instead of displaying the page. The corrected
server sends one HTML content type and negotiates gzip encoding separately.
Do not bypass an insecure-download warning to open the UI.

## UI and configuration boundaries

Version 0.1.2 fixes the single **Plugged/Unplugged** UI control to set both
simulated cable ends. Previously it left the EVSE end unplugged, so power
remained zero even with the EV and EVSE marked Ready. Both the Status card
and Connector EVSE Options use the corrected payload. The status badge
is now read-only; clicking it cannot fabricate a local Charging status.
OCPP 2.0.1 **Occupied** now has non-error styling. It means the connector
is occupied, not necessarily transferring energy; use the power reading
and transaction data to determine whether energy is flowing.

### Bounded connector 1 power-flow check

Use an isolated test central system and an accepted test token only.
Keep connector 2 unplugged and not ready.

1. In **Status**, use Connector 1's controls to select **Plugged**,
   EV **Ready** and EVSE **Ready**.
2. In **Connectors**, fetch Connector 1's transaction data, expand
   **Transaction Options**, enter your test `idTag`, then select
   **Update Transaction**. The test central system must accept this token.
3. Return to **Status**. Expect simulated power around 11,000 W and
   increasing Wh after authorization. This is simulated energy, not a
   physical charger measurement.
4. In the central system, compare `Power.Active.Import` and
   `Energy.Active.Import.Register`. Account for W/kW and Wh/kWh units
   and the configured sample interval (ten seconds by default).
5. After 30 seconds of positive power, select **Unplugged**, then return
   both readiness controls to **Not Ready**. Confirm zero power locally
   and an ended transaction at the central system. Do not leave a test
   charging indefinitely.

The App's native API still exposes independent plug flags for protocol
testing; the UI deliberately presents one cable control. The upstream
`/api/plugin` shortcut is not used by this UI procedure.

The upstream UI is retained, but network/configuration/reset POST APIs are
blocked. Only connector plug/ready and transaction/RFID actions may be
submitted through the UI; use the App Configuration tab for its endpoint.
Upstream advanced controls outside this scope can show a denied request.
The upstream WebSocket settings page is informational, not an alternate
configuration route.

The station supports two connectors; use connector 1 for the first test.
Do not associate a test token with a production driver or real budget.
On a fresh data directory, sampled import energy, power, current, voltage
and SoC are enabled at transaction start/end and ten-second updates.
The test CSMS may change the device-model sampling settings.

The current build does not implement 2.0.1 `SetChargingProfile`. Its
explicit unsupported response is covered by the smoke test. Do not use
this App as proof of TxProfile execution; that needs the EVerest stage.

## Persistence and restart

Version 0.1.3 refreshes simulated meter values at sampling time, including
the final OCPP transaction sample. Unplug, local stop and remote stop report
zero power/current while preserving accumulated energy. This fixes a 0.1.2
ordering defect where HA retained the last approximately 11 kW reading after
the transaction ended.

The separate stale HA cumulative-energy sensor is **not fixed** by this App
change. HA's zero-start heuristic can interpret the simulator register as
session-only energy. See [METERING_INVESTIGATION.md](METERING_INVESTIGATION.md)
for the verified cause, later-session risk and recommended integration tests.

`/data/mo_store` holds protocol state and configuration. Startup updates only
App-managed keys, retains other records and resets plug/ready booleans to
false. The upstream energy accumulator is in memory, so a process restart
is a metering discontinuity, not an uninterrupted revenue-meter session.
Test CSMS reconciliation of interrupted transactions explicitly.

The first configured endpoint and identity are bound in
`/data/test-identity.json`. Changing either is refused to avoid sending
stored transaction records to another station/backend. An empty backend
pauses networking without deleting this binding.

For a genuinely new test destination, finish or reconcile open test
transactions first. Set `archive_and_rebind: true` and the new destination together to rebind:
on start the App moves `mo_store` and `test-identity.json` into
`/data/archive-<UTC timestamp>/` (never deleted), then binds the new destination.
Set the option back to `false` afterwards; each start with it `true` archives again.
Never erase data simply to hide an unresolved test transaction. No automatic
state deletion or live HA configuration edits are performed.

Both child processes are supervised. A child exit fails the App rather than
leaving a misleading half-running UI; normal shutdown gives both processes
up to eight seconds before forced cleanup. Boot is manual. A CSMS Reset
can stop the App; restart it explicitly during this first testing stage.

## Validation and installation gates

The PR contains focused option/persistence tests, native simulator smoke
tests and separate amd64/aarch64 Docker build checks. No image is pushed
and no App is installed by the workflow.

Before live-host acceptance:

- Confirm the HA version accepts this App manifest and its Ingress peer.
- Build on the actual host architecture; allow time for the C++ dependency build.
- Confirm UI requests stay beneath the Ingress URL, including on a phone.
- Check a full test-only charging lifecycle and sampled transaction meter data.
- Confirm the documented unsupported profile response is not shown as success.
- Stop/start the App and reconcile the explicit metering discontinuity.
- Confirm no test data enters production settlement or control automations.

## Scope and future increments

Keep full 2.0.1 smart charging, V2G, authenticated/TLS OCPP, deterministic metering and fleet
scenarios outside this baseline PR. See [UPSTREAM.md](UPSTREAM.md) for the
pin, source distribution, licensing and exact upstream changes.

## Connection troubleshooting

Mongoose (the simulator's network library) has its own DNS client: it asks
the first IPv4 `nameserver` in `/etc/resolv.conf` for an A record of the
bare CSMS host name and connects to the first address in the answer. Other
Apps resolve through libc instead. With a backend URL set, the App logs
`Connection diagnostics:` lines at start, and each failed attempt logs
`socket error peer <address>:<port>`. Compare:

- `Mongoose connects to <address>` with the CSMS App's IP address (App
  info, or `libc getaddrinfo`). A different or stale address points at DNS.
- `TCP probe <address> port <port>`: `open` means the listener accepts
  connections there; `ECONNREFUSED` means nothing listens on that port at
  that address (listener disabled, or wrong address); `EHOSTUNREACH` or
  `timeout` means the address is not reachable on the Supervisor network.
- `Mongoose-style A query ... failed` means Mongoose cannot reach that
  nameserver; its attempts then end in `DNS timeout` rather than
  `socket error`.
