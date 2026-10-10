import json
from pathlib import Path
import tempfile
import unittest
from summarize import summarize

ROOT = Path(__file__).parent

class HarnessTests(unittest.TestCase):
    def test_pins_are_immutable_and_match_build(self):
        pins = json.loads((ROOT / "pins.json").read_text())
        docker = (ROOT / "Dockerfile").read_text()
        for key in ("node_build", "node_runtime"):
            self.assertIn("FROM " + pins["next"][key], docker)
            self.assertRegex(pins["next"][key], r"@sha256:[a-f0-9]{64}$")
        for key in ("release", "next"):
            self.assertRegex(pins[key]["commit"], r"^[a-f0-9]{40}$")
        self.assertFalse(pins["deployment_allowed"])
        self.assertNotIn("latest", docker)

    def test_missing_reports_never_become_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                summarize(Path(directory), json.loads((ROOT / "pins.json").read_text()))

    def test_no_installable_manifest_or_server_start(self):
        self.assertFalse((ROOT / "config.yaml").exists())
        workflow = (ROOT.parent / ".github/workflows/citrineos-comparison.yml").read_text()
        self.assertIn("--network none", workflow)
        self.assertIn("--entrypoint node", workflow)
        self.assertNotIn("packages: write", workflow)
        self.assertNotIn("docker push", workflow)

if __name__ == "__main__":
    unittest.main()
