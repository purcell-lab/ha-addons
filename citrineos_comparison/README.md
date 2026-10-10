# Pinned CitrineOS next comparison

CI-only comparison of released v2.0.1 against development commit
`19ef2b452f8dc1e5bcd97cd3c1aac072c821f588`. No branch name or floating image tag
selects the code under test. This folder is not an installable Home Assistant App.

## Test boundaries

- Release: published upstream image pinned by OCI digest.
- Next: exact source checkout, frozen pnpm lockfile, digest-pinned Node build and
  runtime images; compiled using the upstream server build/deploy commands.
- Both: identical component probe with read-only root filesystem, non-root user,
  dropped capabilities and `--network none`. Real compiled API registration and
  upstream AJV are used, with handlers that fail if invoked.
- Both: inline and shared-schema compilation results, legacy `/data` route
  presence, protected tariff-read route and three OCPP SetChargingProfile routes.
- Next: five deadline-helper assertions, including expiry override, zero/no
  expiry, response timeout and exclusion of station-originated messages.
- Both: the staged HA client's exact discovery query checked against source
  model fields and the EVSE relationship. This is not a live GraphQL query.
- Both: record whether source uses the EVSE database key for concurrent
  transaction deactivation. This is not a behavioural transaction test.

The complete server, its startup hooks, Swagger UI, authentication providers,
database, broker, migrations, HA and station connections are NOT started.
Shared-schema findings therefore describe this component harness, not a claim
that production default-mode boot succeeds or fails. HTTP route existence is
not authentication, dispatch, station acceptance or measured charging response.

## Results and interpretation

The workflow uploads raw JSON, image IDs and a generated Markdown comparison.
Known schema failures are recorded as findings; unexpected import/build errors,
missing core routes, invoked handlers, failed deadline assertions, changed query
fields or mismatched source pins fail CI. Missing reports cannot produce a green
comparison. Green means the evidence was captured, not that deployment is safe.

The release App pin, its activation gate and the staged HA-client branch are not
changed. Nothing is merged, published to a container registry or installed.
Updating pins is a reviewed code change; there is no free-form workflow input.

## Run

Open a PR touching this folder or run `CitrineOS pinned next comparison` from a
branch containing this workflow. There are no live-system credentials or HA
tools in the workflow. Container builds may download dependencies, but the
runtime component probes cannot access a network.

Local harness checks:

```sh
python -m unittest discover -s citrineos_comparison -p test_harness.py -v
node --check citrineos_comparison/probe.mjs
```

## References

- [Pinned development source](https://github.com/citrineos/citrineos-core/commit/19ef2b452f8dc1e5bcd97cd3c1aac072c821f588)
- [Release-to-next review](https://github.com/citrineos/citrineos-core/compare/v2.0.1...next)
- [Queued-command expiry and dead-letter changes](https://github.com/citrineos/citrineos-core/pull/1173)
- [EVSE transaction-scoping correction](https://github.com/citrineos/citrineos-core/pull/1172)
- [Staged HA-client PR](https://github.com/purcell-lab/CitrineOS-HA-Integration/pull/1)
- [Staged disconnected App PR](https://github.com/purcell-lab/ha-addons/pull/12)
