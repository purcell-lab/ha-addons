"""Packaging invariants for the CitrineOS Operator UI App."""
from pathlib import Path
import re
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
CORE = "1a83638c31eebdb1dd8d6cdb0f5b8a9f142a1372"


class Packaging(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((ROOT / "config.yaml").read_text())
        self.docker = (ROOT / "Dockerfile").read_text()

    def test_least_privilege_ingress_only(self):
        c = self.config
        self.assertEqual(c["arch"], ["aarch64", "amd64"])
        self.assertEqual(c["image"], "ghcr.io/purcell-lab/{arch}-citrineos-operator-ui")
        self.assertEqual(c["boot"], "manual")
        self.assertIs(c["ingress"], True)
        self.assertEqual(c["ingress_port"], 8099)
        for field in ("hassio_api", "homeassistant_api", "docker_api", "host_network"):
            self.assertIs(c[field], False)
        for field in ("ports", "map", "privileged", "devices", "full_access", "host_pid"):
            self.assertNotIn(field, c)
        self.assertEqual(c["options"], {"gateway_url": "", "operator_token": "", "commands_enabled": False})
        self.assertEqual(c["schema"]["operator_token"], "password")

    def test_pinned_upstream_and_bases(self):
        self.assertIn(f"ARG CORE_COMMIT={CORE}", self.docker)
        self.assertIn('test "$(git rev-parse HEAD)" = "${CORE_COMMIT}"', self.docker)
        for image in re.findall(r"^ARG (?:BUILD|RUN)_IMAGE=(\S+)", self.docker, re.M):
            self.assertRegex(image, r"^node:24\.16\.0(-slim)?@sha256:[a-f0-9]{64}$")
        self.assertIn("pnpm install --frozen-lockfile", self.docker)
        self.assertIn("git apply --check /tmp/operator-ui.patch", self.docker)
        # The upstream development .env files are never built in or shipped.
        self.assertIn("rm -f apps/operator-ui/.env apps/operator-ui/.env.*", self.docker)
        self.assertIn("-name '.env*' -prune -exec rm -rf {} +", self.docker)

    def test_browser_bundle_uses_the_same_origin_proxy(self):
        for setting in ("NEXT_PUBLIC_BASE_PATH=/__ha_ingress_base__",
                        "NEXT_PUBLIC_API_URL=/__ha_ingress_base__/hasura/v1/graphql",
                        "NEXT_PUBLIC_CITRINE_CORE_URL=/__ha_ingress_base__/core",
                        "NEXT_PUBLIC_TRUSTED_PROXY_AUTH=true", "NEXT_PUBLIC_WS_URL= "):
            self.assertIn(setting, self.docker)
        self.assertNotIn("HASURA_ADMIN_SECRET", self.docker)
        self.assertNotRegex(self.docker, r"NEXT_PUBLIC_\w+=https?://")

    def test_patch_scope(self):
        patch = (ROOT / "operator-ui.patch").read_text()
        files = set(re.findall(r"^\+\+\+ b/(\S+)", patch, re.M))
        self.assertEqual(files, {
            "apps/operator-ui/next.config.mjs",
            "apps/operator-ui/src/lib/utils/config.ts",
            "apps/operator-ui/src/lib/providers/index.tsx",
            "apps/operator-ui/src/lib/providers/live-provider/index.ts",
            "apps/operator-ui/src/lib/providers/data-provider/index.ts",
            "apps/operator-ui/src/lib/providers/auth-provider/generic-auth-provider/index.tsx",
        })


if __name__ == "__main__":
    unittest.main()
