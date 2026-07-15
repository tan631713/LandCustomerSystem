import tempfile
import time
import unittest
from pathlib import Path

from customer_database import CustomerDatabase
from customer_repository import CustomerRepository


class SearchPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        project_root = Path(__file__).resolve().parents[1]
        database = CustomerDatabase(
            self.root / "customers.db",
            self.root / "backups",
        )
        self.repository = CustomerRepository(
            database,
            project_root / "schema.sql",
            self.root / "missing-seed.sql",
            [("district", ""), ("section", ""), ("land_number", "")],
        )
        self.repository.init_db()

    def tearDown(self):
        self.temp_context.cleanup()

    def insert_rows(self, start, stop):
        with self.repository.database.connect() as conn:
            conn.executemany(
                "INSERT INTO customers (district, section, land_number) VALUES (?, ?, ?)",
                (
                    (
                        "目標區" if index in {49_999, 99_999} else "一般區",
                        "一段",
                        str(index),
                    )
                    for index in range(start, stop)
                ),
            )

    def test_database_candidate_filter_handles_fifty_and_one_hundred_thousand_rows(self):
        self.insert_rows(0, 50_000)
        for expected_count, total_rows in ((1, 50_000), (2, 100_000)):
            if total_rows == 100_000:
                self.insert_rows(50_000, 100_000)
            started = time.perf_counter()
            rows = self.repository.fetch_search_candidate_rows(
                keyword="目標區",
                filter_field="district",
            )
            elapsed = time.perf_counter() - started
            self.assertEqual(len(rows), expected_count)
            self.assertLess(elapsed, 5.0, f"{total_rows:,} rows took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
