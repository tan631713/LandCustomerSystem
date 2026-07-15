import json
import tempfile
import unittest
from pathlib import Path

from customer_version import APP_VERSION
from release_acceptance import run_release_acceptance


class ReleaseAcceptanceTests(unittest.TestCase):
    def test_isolated_release_acceptance_passes_and_writes_report(self):
        with tempfile.TemporaryDirectory() as temp_name:
            report_path = Path(temp_name) / "acceptance.json"
            report = run_release_acceptance(report_path)
            self.assertTrue(report["success"], report.get("error"))
            self.assertEqual(len(report["steps"]), 13)
            written = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(written["success"])
            self.assertEqual(written["version"], APP_VERSION)


if __name__ == "__main__":
    unittest.main()
