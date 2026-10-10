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
        self.assertEqual(config["options"], {"mode": "disconnected"})
        self.assertEqual(config["schema"], {"mode": "list(disconnected)"})

    def test_pinned_image_and_no_upstream_startup(self):
        lock = json.loads((ROOT / "compatibility-lock.json").read_text())
        docker = (ROOT / "Dockerfile").read_text()
        self.assertIn("FROM " + lock["server"]["image"], docker)
        self.assertRegex(lock["server"]["image"], r"@sha256:[a-f0-9]{64}$")
        self.assertIn('ENTRYPOINT ["node", "/opt/citrine-ha/guard.mjs"]', docker)
        self.assertIn("USER node", docker)
        self.assertNotIn("latest", docker)
        self.assertFalse(lock["assessment"]["runtime_activation_allowed"])
        self.assertEqual(lock["assessment"]["status"], "blocked")
        self.assertFalse(lock["assessment"]["full_stack_verified"])


if __name__ == "__main__":
    unittest.main()
