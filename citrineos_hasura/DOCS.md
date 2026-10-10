# CitrineOS lab discovery

Pinned Hasura 2.40.3 with console, development mode and telemetry disabled.
No host ports. Configure the database hostname/password and a distinct 64-hex
admin secret. The server installs restricted lab metadata after migrations.
Clients use the server's bearer-authenticated read-only gateway, not this
administrative endpoint. Metadata persists in the dedicated PostgreSQL database.
See the sibling `citrineos_server/DOCS.md` for the complete access boundary.
