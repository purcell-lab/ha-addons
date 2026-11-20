"""Focused packaging checks for the Imatra OCPP Bridge App (no build, no network)."""
import re
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[1]


class Packaging(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((APP / "config.yaml").read_text())
        self.dockerfile = (APP / "Dockerfile").read_text()

    def test_no_ports_no_privileges_prebuilt_image(self):
        c = self.config
        self.assertEqual(c["image"], "ghcr.io/purcell-lab/{arch}-imatra-ocpp")
        self.assertNotIn("ports", c)
        for key in ("host_network", "hassio_api", "homeassistant_api", "docker_api", "ingress"):
            self.assertIs(c[key], False, key)
        self.assertEqual(c["boot"], "manual")

    def test_secrets_are_passwords(self):
        self.assertEqual(self.config["schema"]["imatra_api_key"], "password")
        self.assertEqual(self.config["schema"]["csms_password"], "password?")

    def test_pinned_source_and_base(self):
        commit = re.search(r"ARG IMATRA_OCPP_COMMIT=([0-9a-f]{40})", self.dockerfile).group(1)
        self.assertIn(commit[:7], (APP / "CHANGELOG.md").read_text())
        for line in self.dockerfile.splitlines():
            if line.startswith("FROM "):
                self.assertRegex(line, r"@sha256:[0-9a-f]{64}")

    def test_version_matches(self):
        v = self.config["version"]
        self.assertIn(f'io.hass.version="{v}"', self.dockerfile)
        self.assertIn(f"## {v}", (APP / "CHANGELOG.md").read_text())

    def test_runs_as_non_root(self):
        self.assertIn("setpriv --reuid=bridge", (APP / "rootfs/opt/imatra-ocpp/run.sh").read_text())


if __name__ == "__main__":
    unittest.main()
