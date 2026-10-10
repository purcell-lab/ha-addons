# Validation record, 0.1.0

## Evidence levels

| Level | Status |
|---|---|
| Unit tests (options, ratings, OCPP string limits, binding, device model, EVerest wiring, test PKI with openssl, firewall ruleset, link-local parsing, isolation setup fail-closed, log parsing, UI service) | Pass locally; CI runs them on every PR |
| nginx peer ACL and POST allowlist (real nginx) | Pass locally in Debian 12; CI |
| End-to-end acceptance against a mock CSMS | Pass locally (Debian 12 root, amd64, own network namespace) and in the built image in CI on amd64 and aarch64 ([run 38044772282](https://github.com/purcell-lab/ha-addons/actions/runs/38044772282)) |
| Container image, fail-closed without NET_ADMIN, listener check, external firewall probe with negative control | Pass in CI on amd64 and aarch64 ([run 38044772282](https://github.com/purcell-lab/ha-addons/actions/runs/38044772282)), with real nftables. Images: amd64 559 MB, aarch64 585 MB. Local runs used a test stub for `nft` because the sandbox kernel has no nf_tables |
| Home Assistant install, HA OCPP CSMS, Ingress in a browser | **Not done.** Needs explicit approval and an isolated test central system. Whether HA's App network gives the veth pair IPv6 link-local addresses is unverified until then; if it does not, the App fails closed with a clear log line |

## End-to-end acceptance (tests/acceptance.py)

Mock CSMS on loopback, real App entrypoint (veth pair, nftables, test PKI,
mosquitto, EVerest manager, UI service, nginx). Local run on 2026-10-10:

| Scenario | App offers | CSMS accepts | Negotiated | Result |
|---|---|---|---|---|
| offline | n/a (`csms_url` empty) | n/a | no connection attempt reached the CSMS; PKI generated | Pass |
| v2g21 | `ocpp2.1, ocpp2.0.1` | `ocpp2.1, ocpp2.0.1` | `ocpp2.1` | Pass |
| fallback | `ocpp2.1, ocpp2.0.1` | `ocpp2.0.1` only | `ocpp2.0.1` | Pass |
| pinned201 | `ocpp2.0.1` | `ocpp2.1, ocpp2.0.1` | `ocpp2.0.1` | Pass |

**v2g21** checks: WebSocket path `/<charge_point_id>` and Basic Auth user;
EV plug-in, SLAC, ISO 15118-20 session; the log evidence `Selected DC_BPT
service parameters`, `Client supports TLS1.3: Change verify mode to
SSL_VERIFY_PEER` and `Handshake complete!`; RequestStartTransaction to
TransactionEvent `Started`; then a CentralSetpoint TxProfile in W, 20 s per
step, sent 10 s after steady Charging. Step means use samples from 6 s into
each step to 2 s before its end, tolerance 3 per cent or 50 W.

| Setpoint | Measured mean |
|---|---|
| +6,000 W | +6,000 W |
| -5,000 W (export) | -5,000 W |
| +3,000 W | +3,000 W |

Energy: import 57.0 Wh metered vs 54.7 Wh integrated, export 27.5 Wh
metered vs 26.9 Wh integrated (limit 10 per cent or 5 Wh). The Status page
recorded the TxProfile with reply `Accepted` and the exact periods sent.
RequestStopTransaction gave `Ended`; after unplug, a fresh session charged
at the 11,000 W default; the App exited with code 0.

**fallback** checks: under `ocpp2.0.1`, a 4,000 W charging limit gave a
4,000 W mean, and no sample showed discharge.

## Firewall evidence (CI)

Result in [run 38044772282](https://github.com/purcell-lab/ha-addons/actions/runs/38044772282): from a second container, SDP `silent` and TCP 8099 and 50000
`dropped` on both 172.31.250.2 and fd00:2026:10::2; after deleting the
table, TCP 8099 `connected`; the private-link SDP probe got a `reply`.

On a user-defined Docker network with IPv4 and IPv6, a second container
probes the App: an SDP request to UDP 15118 gets no reply, and TCP 8099
(where nginx listens on every address) and 50000 time out (dropped, not
refused). The negative control deletes the App's nftables table, after
which TCP 8099 connects, so the drop came from the policy. The positive
control inside the App gets an SDP response on the private `v2g0` link. A
separate run without NET_ADMIN must log `V2G isolation setup failed`, start
no EVerest process and exit non-zero.

Local finding: even without the firewall, the upstream SDP server answered
only on its configured interface (`v2g0`), not from another network
namespace on global or link-local addresses.

## Findings during development

- PyEvJosev's default service order selects plain DC; `DC_BPT,DC` is needed
  for export.
- The demo image certificates lack a vehicle certificate; the App generates
  a per-install PKI.
- libocpp aborts on a GetCertificateStatus reply without `status`, and
  OCPP201 aborts on a `ChargePointModel` longer than 20 characters.
- EnergyManager enforced 0 W for charging targets below the simulated
  board's 4.14 kW three-phase AC minimum. This was the cause of a 4 kW limit
  being ignored and of charging failing after a discharge. One-phase
  fallback fixed both.
- The EVSE 0 composite was applied as a total although it carries per-phase
  shares, capping targets at a third of the rating. Fixed by applying OCPP
  limits through EVSE 1 only; a 9 kW ChargingStationMaxProfile still
  appeared in EVSE 1's composite (`limit: 9000`).
- A 0 W setpoint left the EV at 6,000 W, and a 1,000 W setpoint after a
  -5,000 W discharge gave +5,000 W (previous magnitude, now charging).
  Upstream EvseManager returns early when the minimum exceeds the maximum.
  Documented, not worked around.
- A one-second 13.5 kW sample appeared at a direction change.
- Re-plugging within about 4 s of unplug, while the previous TLS session
  was still closing, prevented a new discovery; the test waits 15 s.

## Not claimed

OCPP 2.1 or ISO 15118-20 conformance beyond the messages above, AC
bidirectional power, Plug and Charge, TLS to the CSMS, Security Profiles 2
and 3, real vehicle or charger behaviour, grid-code compliance, and BSV
settlement are out of scope.
