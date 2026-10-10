"""Check staged client query against pinned source fields, without importing HA."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

from graphql import parse

server, client, output = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location(
    "compatibility", client / "custom_components/citrine_ha/compatibility.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
models = {"ChargingStations": "charging-station", "Connectors": "connector",
          "Transactions": "transaction", "Evse": "evse"}
checked = []

def check(selection, model):
    text = (server / "packages/dal/src/db/drizzle/schema" / f"{models[model]}.ts").read_text()
    fields = set(re.findall(r"^\s{4}(\w+):", text, re.MULTILINE))
    for field in selection.selections:
        name = field.name.value
        if field.selection_set:
            assert model == "Connectors" and name == "Evse"
            metadata = (server / "apps/ocpp-server/db/hasura-metadata/databases/default/tables/public_Connectors.yaml").read_text()
            assert "- name: Evse" in metadata and "foreign_key_constraint_on: evseId" in metadata
            check(field.selection_set, name)
        else:
            assert name in fields, f"Missing field: {model}.{name}"
            checked.append(f"{model}.{name}")

for root in parse(module.V2_DISCOVERY_QUERY).definitions[0].selection_set.selections:
    check(root.selection_set, root.name.value)
commit = subprocess.check_output(["git", "-C", str(server), "rev-parse", "HEAD"], text=True).strip()
transaction = (server / "packages/ocpp/src/modules/transactions/transaction-service.ts").read_text()
report = {
    "commit": commit,
    "staged_query_fields_present": True,
    "fields_checked": checked,
    "evse_deactivation_uses_database_key_source_pattern":
        "evseId = connector?.evseId" in transaction and
        "readEvseByStationIdAndOcpp201EvseId" in transaction,
    "scope": "static_source_contract_not_live_graphql_or_transaction_test",
}
output.write_text(json.dumps(report, indent=2))
print(json.dumps({k: v for k, v in report.items() if k != "fields_checked"}))
