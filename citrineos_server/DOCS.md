# CitrineOS isolated laboratory

This App runs pinned CitrineOS **v2.0.1**, not an OCPP protocol version.
Its companion Apps provide dedicated PostgreSQL/PostGIS, RabbitMQ and Hasura.
Nothing binds a host port. No OCPP listener is enabled in this first deployment.
Existing physical chargers, simulators, Home Assistant OCPP entries and payments
are not used or redirected.

## Installation

Install `citrineos_database`, `citrineos_broker`, `citrineos_hasura` and
`citrineos_server` from this repository. Keep manual boot and automatic updates off.
Use the actual Supervisor-discovered hostnames, not guessed IP addresses.

Generate four distinct 32-byte random values encoded as 64 lowercase hexadecimal
characters for database, broker, Hasura admin and gateway credentials. Enter them
only in the corresponding App options. Do not commit them or include them in logs.
The server uses all four; Hasura uses database and Hasura credentials; the other
Apps use only their own password. Supervisor administrators can read options.
Backups therefore contain secrets and must be protected.

Start the database, broker and Hasura first. Configure the server's dependency
hostnames and change `mode` from `disconnected` to `isolated`, then start it.
The server waits for its dedicated dependencies, applies pinned migrations and
partition provisioning, starts the upstream server and installs the lab's
read-only Hasura metadata. Failed readiness fails startup rather than reporting
an empty healthy system.

The compatibility lock retains the **historical** initial client assessment.
The current runtime and authentication evidence comes from the isolated-stack CI.
The old installed HA client is not automatically updated or configured by this App.

## Access and security boundary

The internal gateway listens on port 8080. `/health/ready` is an unprivileged
readiness check. All other supported routes require `Authorization: Bearer TOKEN`:

- `GET /lab/status`: release, read-only mode and zero-listener status.
- `GET /commands/tariff?tenantId=1`: authenticated, tenant-scoped upstream read.
- `POST /v1/graphql`: Hasura discovery through role `ha_reader`, fixed tenant 1.

Other paths and methods are denied. GraphQL has no mutation permissions; its four
tables expose only the staged HA client's explicit discovery fields. Caller
authentication, role and tenant headers are never forwarded to dependencies.

The upstream API binds loopback port 8088 and uses its actual OIDC/JWT provider,
not local authentication bypass. The gateway signs 60-second internal JWTs with
an in-memory RSA key and role `lab-reader`; its loopback JWKS endpoint is port 8091.
RBAC permits only tariff reads for that role. Restart rotates the internal key.
The bearer gateway is a lab credential bridge, not an interactive identity provider.

No HA/Supervisor API token, Docker socket, host network, device or privileged mount
is granted. Server and Hasura processes run as UID 1000 after root-only startup
preparation. Database and broker use upstream privilege-dropping entrypoints.
RabbitMQ's management plugin is disabled.

**Isolation is not a dedicated network firewall.** HA Apps share Supervisor's
container network. Other trusted Apps can reach dependency ports, but need the
distinct credentials. No ports are published to the LAN or internet. This is
single-tenant laboratory packaging, not a production multi-tenant service.

## Data and rollback

Database state is stored in its own `/data/pgdata`; broker state in `/data/mnesia`.
Hasura metadata is stored in the dedicated database. Server runtime files are in
its own `/data/assets`. An upgrade never enables database sync, alter or force.
Only the upstream versioned migration path is used.

Stop in order: server, Hasura, broker, database. Start dependencies before server.
Stopping these four Apps is the rollback for this first installation and leaves
all existing charging systems alone. Do not uninstall or clear data as recovery.
Credential rotation and server upgrades require coordinated review.

CI checks a logical `pg_dump`/`pg_restore` into a disposable second database and
server restart persistence. This does not claim that a full Supervisor disaster
restore has been tested. Take a protected HA backup before deployment.

## Deliberate limits

No charger registration, charging, TxProfile, V2G, operator UI, OCPI, external CA
or BSV settlement is enabled. Simulator attachment and writable control require
a separate bounded test step. The Hasura endpoint works through the read-only
gateway; raw Hasura admin credentials must not be supplied to a user-facing client.

Upstream references:
[server release](https://github.com/citrineos/citrineos-core/releases/tag/v2.0.1),
[deployment architecture](https://github.com/citrineos/citrineos-core/blob/v2.0.1/docker-compose.yml),
[HA-client compatibility PR](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/1).
