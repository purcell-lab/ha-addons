# CitrineOS lab database

Dedicated PostgreSQL 16/PostGIS 3.5, pinned by image digest. No host ports.
Manual startup; data persists at `/data/pgdata`. Configure a generated 64-hex
password, also supplied to the server and discovery Apps. Never use this database
for an existing HA integration. See the sibling `citrineos_server/DOCS.md` for
installation, private-network limits, backup and rollback.
