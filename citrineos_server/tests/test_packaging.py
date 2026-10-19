import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class PackagingSafety(unittest.TestCase):
    def test_supervisor_privileges_and_ports_are_absent(self):
        config = yaml.safe_load((ROOT / "config.yaml").read_text())
        self.assertEqual(config["arch"], ["aarch64", "amd64"])
        self.assertEqual(config["boot"], "manual")
        for field in ("host_network", "hassio_api", "homeassistant_api",
                      "docker_api", "ingress"):
            self.assertIs(config[field], False)
        for field in ("map", "devices", "privileged", "services", "image"):
            self.assertNotIn(field, config)
        # Only the opt-in Plugfest listeners may be published, and only by an
        # operator-set host port (null by default).
        self.assertEqual(config["ports"],
                         {f"{port}/tcp": None for port in [8083, *range(8100, 8106)]})
        self.assertIs(config["options"]["plugfest_enabled"], False)
        self.assertIs(config["options"]["plugfest_open_admission"], False)
        self.assertEqual(config["options"]["plugfest_stations"], [])
        self.assertEqual(config["schema"]["plugfest_stations"][0]["password"], "password")
        self.assertEqual(config["options"]["mode"], "disconnected")
        self.assertEqual(config["schema"]["mode"], "list(disconnected|isolated)")

    def test_pinned_image_and_no_upstream_startup(self):
        lock = json.loads((ROOT / "compatibility-lock.json").read_text())
        docker = (ROOT / "Dockerfile").read_text()
        self.assertIn("FROM " + lock["server"]["image"], docker)
        self.assertRegex(lock["server"]["image"], r"@sha256:[a-f0-9]{64}$")
        self.assertIn('ENTRYPOINT ["node", "/opt/citrine-ha/launch.mjs"]', docker)
        self.assertIn("process.setuid(1000)", (ROOT / "rootfs/launch.mjs").read_text())
        self.assertNotIn("latest", docker)
        self.assertFalse(lock["assessment"]["runtime_activation_allowed"])
        self.assertEqual(lock["assessment"]["status"], "blocked")
        self.assertFalse(lock["assessment"]["full_stack_verified"])
        # The upstream reconnect race patch (#67) is applied and verified at build.
        self.assertIn("RUN node /opt/citrine-ha/patch-reconnect.mjs \\\n"
                      "    && node /opt/citrine-ha/patch-reconnect.mjs --check", docker)

    def test_dependencies_are_private_and_pinned(self):
        for app in ("citrineos_database", "citrineos_broker", "citrineos_hasura"):
            root = ROOT.parent / app
            config = yaml.safe_load((root / "config.yaml").read_text())
            self.assertEqual(config["boot"], "manual")
            for field in ("ports", "map", "privileged", "host_pid", "image"):
                self.assertNotIn(field, config)
            for field in ("host_network", "hassio_api", "homeassistant_api", "docker_api"):
                self.assertFalse(config[field])
            self.assertEqual(config["arch"], ["aarch64", "amd64"])
            stages = set()
            for line in (root / "Dockerfile").read_text().splitlines():
                if not line.startswith("FROM "):
                    continue
                parts = line.split()
                if len(parts) == 4 and parts[2] == "AS":
                    stages.add(parts[3])
                ref = parts[1]
                # External bases are pinned by digest; scratch and per-arch
                # local stages are the only exceptions.
                if ref != "scratch" and ref.replace("${TARGETARCH}", "amd64") not in stages:
                    self.assertRegex(ref, r"@sha256:[a-f0-9]{64}$")
            docker = (root / "Dockerfile").read_text()
            for line in docker.splitlines():
                if line.startswith("COPY --from=") and "@" in line.split()[1]:
                    self.assertRegex(line.split()[1], r"@sha256:[a-f0-9]{64}$")
                if line.startswith("ADD ") and "https://" in line:
                    self.assertRegex(line, r"^ADD --checksum=sha256:[a-f0-9]{64} https://")
            if "jq" in docker:
                self.assertIn("FROM jq-${TARGETARCH} AS jq", docker)
                self.assertIn("jq-linux-amd64", docker)
                self.assertIn("jq-linux-arm64", docker)

    def test_operator_metadata_is_read_only_and_keeps_ha_reader(self):
        operator = json.loads((ROOT / "rootfs/metadata-operator.json").read_text())
        base = json.loads((ROOT / "rootfs/metadata.json").read_text())
        self.assertEqual(set(operator) - {"version", "sources"}, set())
        tables = {t["table"]["name"]: t for t in operator["sources"][0]["tables"]}
        self.assertEqual({k: v for k, v in operator["sources"][0].items() if k != "tables"},
                         {k: v for k, v in base["sources"][0].items() if k != "tables"})
        for name, table in tables.items():
            for key in ("insert_permissions", "update_permissions", "delete_permissions", "event_triggers"):
                self.assertNotIn(key, table, name)
            for p in table.get("select_permissions", []):
                self.assertIn(p["role"], {"operator_ro", "ha_reader"})
                # Every row is scoped to the caller's tenant.
                self.assertIn("x-hasura-tenant-id", json.dumps(p["permission"]["filter"]).lower(), name)
        self.assertNotIn("select_permissions", tables["Subscriptions"])
        for name in ("Tenants", "TenantPartners"):
            cols = tables[name]["select_permissions"][0]["permission"]["columns"]
            self.assertIsInstance(cols, list)
            self.assertFalse({"serverProfileOCPI", "partnerProfileOCPI"} & set(cols))
        self.assertIn("password", json.dumps(tables["VariableAttributes"]["select_permissions"][0]["permission"]["filter"]))
        for mine in base["sources"][0]["tables"]:
            theirs = tables[mine["table"]["name"]]
            reader = [p for p in theirs["select_permissions"] if p["role"] == "ha_reader"]
            self.assertEqual(reader, mine["select_permissions"])
        rbac = json.loads((ROOT / "rootfs/rbac-rules.json").read_text())["1"]
        for route, methods in rbac.items():
            for roles in methods.values():
                self.assertTrue(set(roles) <= {"lab-reader", "lab-controller", "lab-operator"}, route)

    def test_metadata_has_no_write_permissions_or_sensitive_columns(self):
        metadata = json.loads((ROOT / "rootfs/metadata.json").read_text())
        tables = metadata["sources"][0]["tables"]
        self.assertEqual(len(tables), 12)
        tenant = {"tenantId": {"_eq": "X-Hasura-Tenant-Id"}}
        for table in tables:
            self.assertFalse(set(table) & {"insert_permissions", "update_permissions", "delete_permissions"})
            self.assertEqual(len(table["select_permissions"]), 1)
            p = table["select_permissions"][0]["permission"]
            # Tenant scope first; the device model tables add the variable allow-list.
            self.assertIn(p["filter"], (tenant, {"_and": [tenant, *p["filter"].get("_and", [])[1:]]}))
            self.assertLessEqual(p["limit"], 501)
            self.assertNotIn("*", p["columns"])

    def test_device_model_and_charging_needs_for_ha_reader(self):
        """The Home Assistant contract (DOCS.md, Device model and charging needs)."""
        metadata = json.loads((ROOT / "rootfs/metadata.json").read_text())
        tables = {t["table"]["name"]: t for t in metadata["sources"][0]["tables"]}
        def perm(name):
            return tables[name]["select_permissions"][0]["permission"]
        def rels(name):
            return sorted(r["name"] for r in tables[name].get("object_relationships", []))
        self.assertEqual(perm("VariableAttributes")["columns"],
                         ["id", "stationId", "evseDatabaseId", "componentId", "variableId", "type", "value", "updatedAt"])
        self.assertEqual(perm("Components")["columns"], ["id", "name", "instance", "evseDatabaseId"])
        self.assertEqual(perm("Variables")["columns"], ["id", "name", "instance"])
        self.assertEqual(perm("VariableCharacteristics")["columns"], ["id", "variableId", "maxLimit", "minLimit", "unit"])
        self.assertEqual(perm("ChargingNeeds")["columns"],
                         ["id", "evseId", "transactionDatabaseId", "acChargingParameters", "dcChargingParameters",
                          "requestedEnergyTransfer", "departureTime", "createdAt", "updatedAt"])
        self.assertEqual(rels("VariableAttributes"), ["ChargingStation", "Component", "Variable"])
        self.assertEqual(rels("Variables"), ["VariableCharacteristic"])
        self.assertEqual(rels("VariableCharacteristics"), ["Variable"])
        self.assertEqual(rels("ChargingNeeds"), ["Evse", "Transaction"])
        allowed = ["Power", "DischargePower", "MaxDischargePower", "PowerDischarge", "V2XMaxDischargePower"]
        names = {"_or": [{"name": {"_in": allowed}}, {"name": {"_ilike": "%discharge%power%"}}]}
        secret = {"_or": [{"name": {"_ilike": "%password%"}}, {"name": {"_ilike": "%secret%"}},
                          {"name": {"_ilike": "%key%"}}]}
        tenant = {"tenantId": {"_eq": "X-Hasura-Tenant-Id"}}
        # Only rating variables, never a password, secret or key variable
        # (BasicAuthPassword), whatever the allow-list becomes.
        self.assertEqual(perm("Variables")["filter"], {"_and": [tenant, names, {"_not": secret}]})
        for name in ("VariableAttributes", "VariableCharacteristics"):
            self.assertEqual(perm(name)["filter"],
                             {"_and": [tenant, {"Variable": names}, {"_not": {"Variable": secret}}]}, name)
        for name in ("Components", "ChargingNeeds"):
            self.assertEqual(perm(name)["filter"], tenant, name)


if __name__ == "__main__":
    unittest.main()
