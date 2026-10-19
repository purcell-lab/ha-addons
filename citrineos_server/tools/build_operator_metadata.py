"""Build rootfs/metadata-operator.json from upstream CitrineOS Hasura metadata.

The Operator UI needs upstream's full GraphQL schema (all tables and their
relationships). This script converts the pinned upstream metadata directory
(apps/ocpp-server/db/hasura-metadata at the release in
compatibility-lock.json) into one replace_metadata document and makes it
read-only:

- upstream's "user" role becomes "operator_ro" with select permissions only
  (every insert, update and delete permission is dropped), still filtered
  by tenant;
- secrets stay hidden: BasicAuthPassword and other password/key variables,
  OCPI credential profiles, and webhook subscriptions;
- the lab's existing "ha_reader" permissions (rootfs/metadata.json) are
  merged in unchanged, so the CitrineOS-HA integration sees exactly what it
  saw before;
- actions, remote schemas, event triggers and cron triggers are not copied.

Usage (from the repository root):

    git -C /tmp/core checkout 1a83638c31eebdb1dd8d6cdb0f5b8a9f142a1372
    python3 citrineos_server/tools/build_operator_metadata.py \
        /tmp/core/apps/ocpp-server/db/hasura-metadata

The test suite checks the committed output's invariants; regenerate it
whenever the upstream release changes.
"""
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "rootfs/metadata-operator.json"
BASE = ROOT / "rootfs/metadata.json"
ROLE = "operator_ro"

# Rows or columns the read-only operator view never exposes.
HIDDEN_TABLES = {"Subscriptions"}
# Hasura's '*' cannot exclude a column, so these tables list theirs. The
# OCPI credential profiles (serverProfileOCPI, partnerProfileOCPI) are left out.
VISIBLE_COLUMNS = {
    "Tenants": ["id", "name", "url", "partyId", "countryCode", "isUserTenant",
                "maxChargingStations", "tenantWebsocketServerPath", "createdAt", "updatedAt"],
    "TenantPartners": ["id", "partyId", "countryCode", "tenantId", "createdAt", "updatedAt"],
}
SECRET_VARIABLE = {"_not": {"Variable": {"_or": [
    {"name": {"_ilike": "%password%"}},
    {"name": {"_ilike": "%secret%"}},
    {"name": {"_ilike": "%key%"}},
]}}}


class Loader(yaml.SafeLoader):
    pass


def _include(loader, node):
    path = Path(loader.name).parent / loader.construct_scalar(node)
    with open(path) as f:
        return yaml.load(f, Loader)  # noqa: S506 - restricted SafeLoader subclass


Loader.add_constructor("!include", _include)


def load(path):
    with open(path) as f:
        return resolve(yaml.load(f, Loader), Path(path).parent)  # noqa: S506


def resolve(value, here):
    """Hasura CLI also accepts a quoted '!include <file>' string."""
    if isinstance(value, str) and value.startswith("!include "):
        target = here / value[len("!include "):]
        return load(target)
    if isinstance(value, list):
        return [resolve(v, here) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, here) for k, v in value.items()}
    return value


def convert(upstream_dir):
    upstream = Path(upstream_dir)
    sources = load(upstream / "databases/databases.yaml")
    assert len(sources) == 1 and sources[0]["name"] == "default", "unexpected upstream sources"
    base = json.loads(BASE.read_text())
    base_source = base["sources"][0]
    ha_reader = {t["table"]["name"]: t for t in base_source["tables"]}

    tables = []
    for t in sources[0]["tables"]:
        name = t["table"]["name"]
        out = {"table": t["table"]}
        for key in ("object_relationships", "array_relationships", "computed_fields", "configuration"):
            if t.get(key):
                out[key] = t[key]
        perms = []
        if name not in HIDDEN_TABLES:
            for p in t.get("select_permissions", []):
                if p["role"] != "user":
                    continue
                perm = dict(p["permission"])
                if name in VISIBLE_COLUMNS:
                    perm["columns"] = VISIBLE_COLUMNS[name]
                if name == "VariableAttributes":
                    perm["filter"] = {"_and": [perm["filter"], SECRET_VARIABLE]}
                perm["allow_aggregations"] = True
                perms.append({"role": ROLE, "permission": perm})
        if name in ha_reader:
            mine = ha_reader.pop(name)
            # ha_reader relationships use upstream's names and definitions,
            # so one GraphQL query works with either metadata file.
            for kind in ("object_relationships", "array_relationships"):
                theirs = {r["name"]: r for r in out.get(kind, [])}
                for rel in mine.get(kind, []):
                    assert theirs.get(rel["name"]) == rel, f"{name}.{rel['name']} differs from upstream"
            perms += mine["select_permissions"]
        if perms:
            out["select_permissions"] = perms
        tables.append(out)
    assert not ha_reader, f"ha_reader tables missing upstream: {sorted(ha_reader)}"

    source = {k: v for k, v in base_source.items() if k != "tables"}
    source["tables"] = tables
    return {"version": 3, "sources": [source]}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_operator_metadata.py <upstream hasura-metadata dir>")
    doc = convert(sys.argv[1])
    OUT.write_text(json.dumps(doc, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(doc['sources'][0]['tables'])} tables")
