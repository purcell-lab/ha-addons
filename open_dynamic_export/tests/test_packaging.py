"""Packaging safety and pinning for the Open Dynamic Export App."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text())
DOCKERFILE = (ROOT / "Dockerfile").read_text()
PATCH = (ROOT / "ingress.patch").read_text()
PUBLISH = (REPO / ".github/workflows/ode-publish.yml").read_text()
PR = (REPO / ".github/workflows/ode.yml").read_text()
COMMIT = "bc807abbc4c58be3294257ee76f0348dc87c4945"  # upstream v0.20.0


class ConfigTest(unittest.TestCase):
    def test_least_privilege(self):
        self.assertEqual(CONFIG["arch"], ["aarch64", "amd64"])
        self.assertEqual(CONFIG["boot"], "manual")
        for field in ("hassio_api", "homeassistant_api", "docker_api", "host_network"):
            self.assertIs(CONFIG[field], False)
        for field in ("privileged", "devices", "full_access", "host_pid", "auth_api"):
            self.assertNotIn(field, CONFIG)
        self.assertEqual(CONFIG["map"], ["addon_config:rw"])

    def test_ui_behind_ingress_and_lan_port_off_by_default(self):
        self.assertIs(CONFIG["ingress"], True)
        self.assertEqual(CONFIG["ingress_port"], 3000)
        self.assertEqual(CONFIG["ports"], {"3000/tcp": None})

    def test_prebuilt_image(self):
        self.assertEqual(CONFIG["image"], "ghcr.io/purcell-lab/{arch}-open-dynamic-export")
        self.assertEqual(CONFIG["schema"]["influxdb_token"], "password?")


class PinningTest(unittest.TestCase):
    def test_upstream_commit_and_base_image_are_pinned(self):
        self.assertIn(f"ARG ODE_COMMIT={COMMIT}\n", DOCKERFILE)
        self.assertIn('test "$(git rev-parse HEAD)" = "${ODE_COMMIT}"', DOCKERFILE)
        node = re.search(r"^ARG NODE_IMAGE=(\S+)$", DOCKERFILE, re.M).group(1)
        self.assertRegex(node, r"^node:24-alpine3\.22@sha256:[0-9a-f]{64}$")
        self.assertIn("pnpm install --frozen-lockfile", DOCKERFILE)
        self.assertNotIn("latest", DOCKERFILE)

    def test_patch_is_applied_and_limited_to_ingress(self):
        self.assertIn("git apply --check /tmp/ingress.patch", DOCKERFILE)
        files = set(re.findall(r"^diff --git a/(\S+) ", PATCH, re.M))
        self.assertEqual(files, {"index.html", "src/app.ts", "src/ui/client.ts",
                                 "src/ui/config/site.ts", "src/ui/ingress.ts",
                                 "src/ui/main.tsx", "vite.config.ts"})

    def test_logs_kept_off_persistent_storage(self):
        self.assertIn("ln -s /tmp/ode-logs /app/logs", DOCKERFILE)


class WorkflowTest(unittest.TestCase):
    def test_publish_is_tag_or_manual_and_never_overwrites(self):
        self.assertIn('      - "open_dynamic_export-v*"', PUBLISH)
        self.assertIn("workflow_dispatch:", PUBLISH)
        self.assertNotIn("pull_request", PUBLISH)
        self.assertIn("Refuse to overwrite a published version", PUBLISH)
        self.assertNotIn(":latest", PUBLISH)
        self.assertEqual(PUBLISH.count("docker push "), 1)
        self.assertLess(PUBLISH.index("sh open_dynamic_export/tests/ci_image_checks.sh"),
                        PUBLISH.index("docker push "))
        self.assertIn("ubuntu-24.04-arm", PUBLISH)

    def test_pr_ci_runs_the_same_checks_and_gates_merge_on_publication(self):
        self.assertIn("sh open_dynamic_export/tests/ci_image_checks.sh", PR)
        self.assertIn("published-image:", PR)
        self.assertNotIn("docker push", PR)
        self.assertNotIn("docker login", PR)


if __name__ == "__main__":
    unittest.main()
