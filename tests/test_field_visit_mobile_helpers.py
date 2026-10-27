import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests" / "js" / "field_visit_helpers.test.js"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for mobile helper tests")
class FieldVisitMobileHelperTests(unittest.TestCase):
    def test_field_visit_helpers(self):
        result = subprocess.run(
            ["node", str(SCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
