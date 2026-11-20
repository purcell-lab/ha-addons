"""Focused packaging checks for the Imatra Test Harness App (no build, no network)."""
import re
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[1]
RUN = APP / "rootfs/opt/imatra-harness/run.sh"


class Packaging(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((APP / "config.yaml").read_text())
        self.dockerfile = (APP / "Dockerfile").read_text()
        self.run = RUN.read_text()

    def test_never_published(self):
        self.assertNotIn("image", self.config)
        for wf in (APP.parent / ".github/workflows").glob("*.yml"):
            text = wf.read_text()
            if "imatra_harness" in text:
                self.assertNotRegex(text, r"push:\s*true|docker push|ghcr\.io/purcell-lab/\S*harness", wf.name)

    def test_no_harness_code_in_image(self):
        self.assertNotIn("imatra.test_harness", self.dockerfile.replace("no Imatra test harness", ""))
        self.assertNotRegex(self.dockerfile, r"COPY .*(station|ev)/")

    def test_licence_gate_off_by_default(self):
        self.assertIs(self.config["options"]["accept_licence"], False)
        self.assertEqual(self.config["boot"], "manual")
        gate = self.run.index("accept_licence is false")
        self.assertLess(gate, self.run.index("curl "))

    def test_least_privilege(self):
        c = self.config
        self.assertEqual(c["privileged"], ["NET_ADMIN"])
        self.assertEqual(c["map"], ["share:ro"])
        self.assertNotIn("ports", c)
        for key in ("host_network", "hassio_api", "homeassistant_api", "docker_api", "ingress"):
            self.assertIs(c[key], False, key)

    def test_pinned_and_checked(self):
        commit = re.search(r"HARNESS_COMMIT=([0-9a-f]{40})", self.run).group(1)
        self.assertRegex(self.run, r"HARNESS_SHA256=[0-9a-f]{64}")
        self.assertIn("sha256sum -c", self.run)
        self.assertIn(commit[:7], (APP / "CHANGELOG.md").read_text())
        self.assertIn("iso15118==0.31.2", self.dockerfile)


if __name__ == "__main__":
    unittest.main()
