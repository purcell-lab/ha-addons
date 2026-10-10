# Validation record, 0.1.2

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

## Discovery diagnostics and recovery (0.1.1 and 0.1.2)

- Every image run (`ci_image_checks.sh`) requires `Discovery self-test
  PASSED: unicast=reply multicast=reply` in the offline App log, and an
  `/api/diagnostics` snapshot with addresses on both link ends, an SDP
  listener and a nonzero `private V2G link` firewall counter.
- Acceptance scenario `recovery` blocks SDP into `v2g0`, plugs in and
  waits for Josev's `SDPRequest was not successful`, with no SDP request
  reaching the charger. After unblocking, unplug and plug-in, the patched
  module must replace the idle stack (`ev_stack_restarts` 1) and the fresh
  stack must complete discovery, TLS and ISO 15118-20 session setup. The self-test then passes again.
- CI also showed that the charger ignores SDP requests while a session it
  answered is still open, and such a session never ends if no TCP
  connection follows. The self-test therefore releases each session it
  opens (DOCS.md, Discovery diagnostics).
- Unplugging the EV while the charger waited for authorisation left the
  charger ignoring discovery (`Ignoring sdp request message because a
  session is already created and running`). The `recovery` scenario now
  requires the App to report this and the self-test to show the requests
  arriving on `v2g0` without a reply. This is a plausible cause of the HA
  OS symptom after a Preparing session was unplugged, but not of the very
  first failure there, which had no `Got SDP request` line.
- Field finding that led to 0.1.1: on Home Assistant OS the EV's SDP
  requests timed out although the SDP server had started on `v2g0` and
  link-local addresses were present; the same image passed in CI. The
  0.1.0 EV stack then idled, so later plug-ins did nothing.
- Cause, established with 0.1.1 on HA OS (2026-10-10): the start-up
  self-test passed on both paths, yet the simulated EV's requests still
  timed out. Upstream Josev sends to `FF02::1` without choosing an
  interface (its `IPV6_MULTICAST_IF` line is commented out), so the kernel
  uses the first multicast route. CI's acceptance container has no network,
  so that is the private link; on HA OS it is `eth0` on the Supervisor
  network. Reproduced in a network namespace with a second interface: the
  unscoped request left by that interface, and with the interface set it
  went from `v2g1` to `v2g0`. 0.1.2 patches Josev to use `v2g1`, drops any
  SDP that would leave by another interface, and CI repeats `recovery`
  with a bridge network attached (an `eth0`, as on HA OS).
- Live on HA OS with 0.1.2 (2026-10-11), driven only through the HA MCP:
  the start-up self-test passed with `unscoped-multicast-via=eth0`; an
  `everest_v2g_command` plug-in reached discovery in 3 s, then TLS, session
  setup and DC_BPT; after RequestStartTransaction from `sim_lab_v2g` the
  session charged at 11,000 W. HA's charge-control switch stayed `off` (the
  HA OCPP 2.1 status gap), so turning it off sent no stop; unplugging ended
  the transaction (TxStopPoints EVConnected). The self-test afterwards
  passed and the charger was not ignoring discovery.
- Second session on HA OS with 0.1.2 (2026-10-11 06:30): plug-in reached
  discovery in 2.6 s, DC_BPT, then 11,000 W after RequestStartTransaction.
  An `everest_v2g_command` `stop` ended it from the EV side; HA's
  transaction opened at 06:30:37 and closed at 06:31:48 on time. Meter
  start 0.451 kWh and final register 0.613 kWh give about 0.16 kWh, which
  fits 52 s at 11 kW (HA's session-energy sensor showed the register). The
  self-test afterwards passed. The first session's transaction reached HA
  only at 06:19:37, when the App logged a dropped OCPP message after
  retries; that delay, not the switch state alone, explains why HA could
  not stop it. Its cause is not established.
- TxProfile from HA on HA OS with 0.1.2 (2026-10-11 07:30 AEST): during a
  live session (transaction `f4a603c2-9ee8-448e-ae9f-e970c5d7b76d`), HA's
  `ocpp.set_charge_rate` with `custom_profile` sent the CI profile (id
  210301, Absolute, 20 s per step, CentralSetpoint) to EVSE 1. HA raised no
  error, so the station replied `Accepted`. Power from the App's status
  object, relative to `startSchedule`:

  | Setpoint | Observed | HA meter energy | Expected |
  |---|---|---|---|
  | +6,000 W | +6,000 W from -3 s (first setpoint applies early) | 33.3 Wh import, 0.6 to 20.6 s | 33.3 Wh |
  | -5,000 W (export) | -1,111 W at 22 s, -5,000 W from 27 s | 26.9 Wh export register | 27.8 Wh |
  | +3,000 W | +3,000 W from 47 s | 25.0 Wh import over 29.5 s | 24.6 Wh |

  The status object polls every 5 s, so these times are upper bounds on
  the response. HA's import power sensor showed -5.0 kW during export and
  its export power sensor stayed `unknown`; the export energy register
  counted correctly. Turning off `switch.charger5_charge_control` sent
  RequestStopTransaction: power reached 0 W and HA closed the transaction
  within 2 s. After unplug the self-test passed. This shows receipt,
  acceptance and execution of one 2.1 TxProfile through HA; it is not a
  conformance result.
- Repeat (2026-10-11 08:12 AEST, transaction
  `c227697d-9167-4e59-a2ae-76acb8741653`, profile 210302): the same
  result. +6,000 W from 0 s (33.3 Wh import, 33.5 Wh expected), -5,000 W
  by 24.5 s, +3,000 W by 44.7 s (22.5 Wh over 27.8 s, 23.2 Wh expected).
  HA's stop closed the transaction within 2 s and the self-test passed.
  One status sample at the start of charging read 24,750 W, above the
  11 kW rating; HA's meter showed 11.0 kW. The documented transient
  (13.5 kW) is at a direction change; this one was at the start of
  charging and larger. Cause not established.
- CI flake (PR #16, amd64, 2026-10-11): in `v2g21` the station accepted the
  profile but the first +6,000 W step never applied (11,000 W throughout);
  the -5,000 W and +3,000 W steps applied on time. A re-run passed. Not
  yet reproduced on HA OS; cause not established.

## Not claimed

OCPP 2.1 or ISO 15118-20 conformance beyond the messages above, AC
bidirectional power, Plug and Charge, TLS to the CSMS, Security Profiles 2
and 3, real vehicle or charger behaviour, grid-code compliance, and BSV
settlement are out of scope.
