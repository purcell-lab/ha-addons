"""Prebuilt-image packaging: HA pulls from GHCR; only CI publishes."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CONFIG = (ROOT / "config.yaml").read_text()
PUBLISH = (REPO / ".github/workflows/microocpp-publish.yml").read_text()
PR = (REPO / ".github/workflows/microocpp.yml").read_text()


class PublishWorkflowTest(unittest.TestCase):
    def test_config_points_at_the_prebuilt_image(self):
        self.assertIn("image: ghcr.io/purcell-lab/{arch}-microocpp-simulator\n", CONFIG)
        self.assertIn("  - aarch64\n  - amd64\n", CONFIG)

    def test_publish_is_tag_or_manual_and_never_overwrites(self):
        self.assertIn('      - "microocpp_simulator-v*"', PUBLISH)
        self.assertIn("workflow_dispatch:", PUBLISH)
        self.assertNotIn("pull_request", PUBLISH)
        self.assertIn("microocpp_simulator) expected=ghcr.io/purcell-lab/{arch}-microocpp-simulator ;;", PUBLISH)
        self.assertIn("Refuse to overwrite a published version", PUBLISH)
        self.assertNotIn(":latest", PUBLISH)
        self.assertEqual(PUBLISH.count("docker push "), 1)
        gate = PUBLISH.index('sh "$APP/tests/ci_image_checks.sh"')
        self.assertLess(gate, PUBLISH.index("docker push "))
        self.assertIn("ubuntu-24.04-arm", PUBLISH)

    def test_pr_ci_runs_the_same_checks_and_gates_merge_on_publication(self):
        self.assertIn("sh microocpp_simulator/tests/ci_image_checks.sh", PR)
        self.assertIn("published-image:", PR)
        self.assertIn("docker manifest inspect", PR)
        self.assertNotIn("docker login", PR)
        self.assertNotIn("docker push", PR)


if __name__ == "__main__":
    unittest.main()
