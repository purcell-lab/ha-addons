# CitrineOS compatibility and packaging

This is a staged, disconnected-only Home Assistant App, not an operational
central system. A running App means the packaging guard is running; it does not
mean CitrineOS is ready. Do not add or enable a Citrine HA config entry yet.

## What is packaged

- Upstream CitrineOS server **v2.0.1** pinned by release-image digest.
- Home Assistant amd64 manifest with manual boot.
- Replacement entrypoint that never runs migrations, starts the upstream server
  or connects to a broker. It opens no sockets and has no activation option.
- No host ports, Ingress, Supervisor API, HA API, Docker socket or host mounts.
- Non-root runtime, clean SIGTERM/SIGINT handling and sanitised option errors.

Software release v2.0.1 must not be confused with the OCPP protocol version.
The release exposes OCPP 1.6, 2.0.1 and 2.1 message APIs in its
[pinned API implementation](https://github.com/citrineos/citrineos-core/tree/1a83638c31eebdb1dd8d6cdb0f5b8a9f142a1372/packages/ocpp/src/apis).

## Compatibility result: blocked

The candidate pairing is HA integration 0.2.1, commit
`a98cd336e4197f3875be238bdfe5c4784194efb1`, with server v2.0.1, commit
`1a83638c31eebdb1dd8d6cdb0f5b8a9f142a1372`. The exact image and source locks
are recorded in `compatibility-lock.json`; updating them requires review.

| Area | Finding | Consequence |
| --- | --- | --- |
| Connection validation | Client requires `GET /data/ocpprouter/systemConfig`; reviewed server APIs do not register it | Config flow cannot rely on this pairing |
| REST discovery | All 16 station, connector and transaction fallback paths use legacy `/data` APIs | An empty result may mean incompatible endpoints, not an empty station inventory |
| Authentication | Client discovery catches the base API exception, including authentication failures | A failed permission check may appear as an empty list |
| Smart charging | Primary 1.6, 2.0.1 and 2.1 SetChargingProfile route names align | Route existence does not establish valid payloads, authentication or station acceptance |
| Hasura | Config flow validates the legacy REST ping before Hasura | Adding Hasura alone is not a fix |
| Control safety | Controller starts during entry setup; Off can request zero limits | Leave the HA entry absent/disabled; Off is not read-only |
| Inline schema compilation | With `swagger.exposeMessage=false`, the compiled routing code and upstream server AJV fail on duplicate `MessageQuerystring` IDs | Resolve and retest this configuration before using it; default `true` mode is not tested here |

These findings come from the [pinned client](https://github.com/Stuart0411/CitrineOS-HA-Integration/blob/a98cd336e4197f3875be238bdfe5c4784194efb1/custom_components/citrine_ha/citrine_api.py),
[config flow](https://github.com/Stuart0411/CitrineOS-HA-Integration/blob/a98cd336e4197f3875be238bdfe5c4784194efb1/custom_components/citrine_ha/config_flow.py),
[controller](https://github.com/Stuart0411/CitrineOS-HA-Integration/blob/a98cd336e4197f3875be238bdfe5c4784194efb1/custom_components/citrine_ha/load_controller.py)
and [server registration](https://github.com/citrineos/citrineos-core/blob/1a83638c31eebdb1dd8d6cdb0f5b8a9f142a1372/packages/ocpp/src/apis/register.ts).

## Focused verification

The workflow builds the digest-pinned amd64 image without publishing it.
It tests disconnected startup, absence of listening TCP sockets, stop handling
and rejection of activation options. It imports compiled upstream API classes,
registers their routes in Fastify with inert handlers and checks whether the
required legacy ping is registered. It also reproduces the inline-schema
compilation failure using the upstream server AJV. No HTTP exchange, TCP
listener or station command is used.
The unmodified pinned HA client is then exercised against that route inventory.
Its 404 responses are simulated for absent routes, not captured from a live
server. The default shared-schema mode remains a follow-up test.

The expected green result is **successful detection of incompatibility**, not
successful HA integration. A changed route contract fails CI for review rather
than silently unlocking startup. The route inventory is a CI artifact.

Authentication, database migrations, broker health, Hasura schema, persistence,
restore, actual OCPP registration and command acknowledgements remain untested.
No full server or database is started by this suite. These limits are deliberate.

Local fast checks:

```sh
python3 -m unittest discover -s citrineos_server/tests -p test_packaging.py -v
node --test citrineos_server/tests/guard.test.mjs
```

The image and pinned-client tests run in the dedicated CI job. They do not run
the unrelated simulator suites. The container probe uses `--network none`.

## Next stages before installation or activation

1. Prepare a separate client compatibility PR: supported authenticated health
   validation; explicit discovery errors; tested REST/Hasura selection; a genuine
   read-only controller mode; distinguish dispatch from station acceptance.
2. Package private database and broker Apps with exact image digests, separate
   `/data`, unique credentials, health gates, orderly shutdown and restore tests.
   Do not use privileged Compose or expose the database/broker to host ports.
3. Resolve discovery and API authentication with an isolated full-stack CI test.
   Package Hasura only if that path is selected; no console/dev mode by default.
4. Add guarded server activation only after compatibility passes. Require
   dependency readiness, explicit test-isolation acknowledgement, a dedicated
   simulator identity and authenticated listener policy. Do not inherit the
   upstream unauthenticated listener, unknown-station admission, debug port,
   external certificate integrations or sample passwords.
5. Perform a fresh live resource/port preflight and protected backup after
   separate approval. Only then merge/install/restart the approved components.
6. Use a new `SIM-CITRINE-LAB-01` identity for a bounded registration and profile
   test. Do not repoint existing simulators or physical charging stations.

The [upstream Compose example](https://github.com/citrineos/citrineos-core/blob/v2.0.1/docker-compose.yml)
is an architecture reference, not a safe HA installation manifest. This PR
does not package or start its database, RabbitMQ, Hasura or operator UI. It
does not patch the installed HA integration, touch existing OCPP entries,
use real energy-control sensors or integrate BSV settlement.

## Rollback and data

This stage creates no charging database or migration state. Stopping/uninstalling
this disconnected package has no server-side charging data to roll back. Future
stateful stages require tested backup/restore and version-specific migration
rollback instructions; those are not established by this package.
