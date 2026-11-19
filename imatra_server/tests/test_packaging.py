"""Focused packaging checks for the Imatra App (no build, no network)."""
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[1]
REPO = APP.parent
COMMIT = "c7f030c9d6b03426e0c183139b5a57e0b09e91b7"


class Packaging(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((APP / "config.yaml").read_text())
        self.dockerfile = (APP / "Dockerfile").read_text()

    def test_local_build_only_no_privileges(self):
        c = self.config
        self.assertEqual(c["image"], "ghcr.io/purcell-lab/{arch}-imatra-server")
        self.assertEqual(c["slug"], "imatra_server")
        self.assertEqual(sorted(c["arch"]), ["aarch64", "amd64"])
        for key in ("host_network", "hassio_api", "homeassistant_api", "docker_api", "ingress"):
            self.assertIs(c[key], False, key)
        self.assertNotIn("privileged", c)
        self.assertEqual(c["boot"], "manual")

    def test_ports_unpublished_by_default(self):
        self.assertEqual(self.config["ports"], {"8080/tcp": None, "8883/tcp": None})

    def test_operator_key_required_secret(self):
        self.assertEqual(self.config["schema"]["operator_api_key"], "password")
        self.assertEqual(self.config["options"]["operator_api_key"], "")
        self.assertIn("devices", self.config["schema"])

    def test_version_matches_label_and_changelog(self):
        v = self.config["version"]
        self.assertIn(f'io.hass.version="{v}"', self.dockerfile)
        self.assertIn(f"## {v}", (APP / "CHANGELOG.md").read_text())

    def test_pinned_upstream_and_bases(self):
        self.assertIn(f"ARG IMATRA_COMMIT={COMMIT}", self.dockerfile)
        self.assertIn('test "$(git rev-parse HEAD)" = "${IMATRA_COMMIT}"', self.dockerfile)
        for line in self.dockerfile.splitlines():
            if line.startswith("FROM "):
                self.assertRegex(line, r"@sha256:[0-9a-f]{64}", line)

    def test_internal_listeners_rebound_to_loopback(self):
        self.assertIn("listener 1883 127.0.0.1", self.dockerfile)
        self.assertIn("reverse_proxy 127.0.0.1:8000", self.dockerfile)
        run = (APP / "rootfs/opt/imatra-ha/run.sh").read_text()
        for needle in ("listen_addresses=127.0.0.1", "--bind 127.0.0.1", "--host 127.0.0.1",
                       "HEALTH_ADDR=127.0.0.1:8090", "RELAY_HEALTH_ADDR=127.0.0.1:8091",
                       "PROJECTOR_HEALTH_ADDR=127.0.0.1:8092"):
            self.assertIn(needle, run)

    def test_no_upstream_or_harness_code_in_repo(self):
        # The App holds scaffolding only; the harness (PolyForm Internal Use)
        # is never copied here.
        names = {p.name for p in APP.rglob("*") if p.is_file()}
        for banned in ("pki-init.sh", "mqtt-run.sh", "mosquitto.conf", "Caddyfile", "main.py",
                       "harness.yml", "e2e_watch.py", "evcc_config.json"):
            self.assertNotIn(banned, names)
        for p in APP.rglob("*"):
            if p.is_file() and p != Path(__file__).resolve() and p.suffix in {".py", ".sh", ".md", ".yaml", ""}:
                text = p.read_text(errors="ignore")
                self.assertNotIn("PolyForm Internal Use License", text, p)
                self.assertNotIn("SPDX-License-Identifier: LicenseRef-PolyForm", text, p)

    def test_harness_fetched_at_runtime_only(self):
        wf = (REPO / ".github/workflows/imatra.yml").read_text()
        self.assertIn("repository: Chargetronic/imatra.test_harness", wf)
        self.assertNotRegex(wf, r"docker (push|login)")
        self.assertNotIn("packages: write", wf)


if __name__ == "__main__":
    unittest.main()
