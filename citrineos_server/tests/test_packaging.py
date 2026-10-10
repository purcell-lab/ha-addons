import json
from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class PackagingSafety(unittest.TestCase):
    def test_supervisor_privileges_and_ports_are_absent(self):
        config = yaml.safe_load((ROOT / "config.yaml").read_text())
        self.assertEqual(config["arch"], ["amd64"])
        self.assertEqual(config["boot"], "manual")
        for field in ("host_network", "hassio_api", "homeassistant_api",
                      "docker_api", "ingress"):
            self.assertIs(config[field], False)
        for field in ("ports", "map", "devices", "privileged", "services", "image"):
            self.assertNotIn(field, config)
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

    def test_dependencies_are_private_and_pinned(self):
        for app in ("citrineos_database", "citrineos_broker", "citrineos_hasura"):
            root = ROOT.parent / app
            config = yaml.safe_load((root / "config.yaml").read_text())
            self.assertEqual(config["boot"], "manual")
            for field in ("ports", "map", "privileged", "host_pid", "image"):
                self.assertNotIn(field, config)
            for field in ("host_network", "hassio_api", "homeassistant_api", "docker_api"):
                self.assertFalse(config[field])
            self.assertRegex((root / "Dockerfile").read_text().splitlines()[0], r"@sha256:[a-f0-9]{64}$")

    def test_metadata_has_no_write_permissions_or_sensitive_columns(self):
        metadata = json.loads((ROOT / "rootfs/metadata.json").read_text())
        tables = metadata["sources"][0]["tables"]
        self.assertEqual(len(tables), 7)
        for table in tables:
            self.assertFalse(set(table) & {"insert_permissions", "update_permissions", "delete_permissions"})
            p = table["select_permissions"][0]["permission"]
            self.assertEqual(p["filter"], {"tenantId": {"_eq": "X-Hasura-Tenant-Id"}})
            self.assertLessEqual(p["limit"], 501)
            self.assertNotIn("*", p["columns"])


if __name__ == "__main__":
    unittest.main()
