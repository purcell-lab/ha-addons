# CitrineOS dedicated MicroOCPP test charger

Separate App and persistent state, fixed identity `SIM-CITRINE-LAB-01`. This is a
copy of the existing pinned MicroOCPP 2.0.1 package with isolated destination and
credential guards. It does not modify or repoint the existing MicroOCPP Apps.
Its Ingress interface retains the existing simulator controls.

Set the backend to `ws://<discovered-citrineos-server-hostname>:8081`, enter the
dedicated generated simulator password, and acknowledge test isolation. It is
disconnected by default. Startup forces both connectors unplugged/not ready.
No host port is published.

The server uses native OCPP Security Profile 1 with HTTP Basic authentication;
unknown station admission is disabled. This is cleartext on the trusted private
Supervisor network, not TLS or internet-safe charging access. No physical
charger identity is admitted. Never reuse this credential outside the lab.

Use connector 1 only, with test token `SIM-CITRINE-TEST`. Enable plug and both
readiness controls, start a transaction, observe power and energy, then unplug.
An independent App watchdog ends simulated charging after 180 seconds from first
positive power even if the orchestration client disappears. This is a synthetic
meter, not a real EV or revenue meter. The normal test is less than one minute.

Server read-only GraphQL exposes boot status, transaction events and meter samples.
Do not equate a simulator UI state with a persisted server transaction: require
the matching transaction ID, `Ended` event, `isActive=false` and an end timestamp.

Stop the simulator App to disconnect it. Disable `simulator_enabled` and restart
only the CitrineOS server to remove its listener. Keep all other chargers and
simulator connections unchanged.

Focused integration testing lives in `citrineos_server/tests/simulator_trial.py`
and runs the real MicroOCPP image against pinned CitrineOS and private dependencies.
The upstream source, licence and retained patches are described in `UPSTREAM.md`.
