import json
import unittest
from pathlib import Path

from customer_version import APP_VERSION, DESKTOP_CLIENT_VERSION


ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "docs" / "v2"
BASELINE = V2 / "baseline" / "v1.8.9-baseline.json"


class V2PlanningBaselineTests(unittest.TestCase):
    def test_phase_one_deliverables_exist(self):
        expected = (
            "README.md",
            "V2_SPECIFICATION.md",
            "API_V2_CONTRACT.md",
            "SCHEMA_V2_DRAFT.sql",
            "PERMISSION_MATRIX.md",
            "COMPATIBILITY_ROLLBACK.md",
            "TEST_BASELINE.md",
            "PHASE1_REPORT.md",
        )
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue((V2 / name).is_file())

    def test_baseline_versions_and_route_counts_are_frozen(self):
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(data["versions"]["server"], "1.8.9")
        self.assertGreaterEqual(
            tuple(int(part) for part in APP_VERSION.split(".")),
            (1, 8, 9),
        )
        self.assertEqual(data["versions"]["desktop_client"], "1.8.2")
        self.assertGreaterEqual(
            tuple(int(part) for part in DESKTOP_CLIENT_VERSION.split(".")),
            tuple(
                int(part)
                for part in data["versions"]["desktop_client"].split(".")
            ),
        )
        self.assertEqual(data["versions"]["line_bot"]["version"], "0.30.0")
        self.assertEqual(data["api"]["api_v1_route_count"], 92)
        self.assertEqual(data["api"]["operational_route_count"], 94)
        self.assertEqual(data["schemas"]["postgresql"]["schema_version"], 7)
        self.assertEqual(data["schemas"]["sqlite_compatibility"]["schema_version"], 8)
        self.assertFalse(data["production_data_opened"])

    def test_v2_contract_includes_safety_boundaries(self):
        api = (V2 / "API_V2_CONTRACT.md").read_text(encoding="utf-8")
        permissions = (V2 / "PERMISSION_MATRIX.md").read_text(encoding="utf-8")
        rollback = (V2 / "COMPATIBILITY_ROLLBACK.md").read_text(encoding="utf-8")
        draft = (V2 / "SCHEMA_V2_DRAFT.sql").read_text(encoding="utf-8")

        self.assertIn("GET /api/v2/system/capabilities", api)
        self.assertIn("LCS_CONFLICT", api)
        self.assertIn("If-Match", api)
        self.assertIn("LINE Basic", permissions)
        self.assertIn("整庫還原", permissions)
        self.assertIn("立即停止條件", rollback)
        self.assertIn("RAISE EXCEPTION", draft)
        self.assertTrue(draft.rstrip().endswith("ROLLBACK;"))


if __name__ == "__main__":
    unittest.main()
