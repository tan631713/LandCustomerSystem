import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import build_data_guard


class BuildDataGuardTests(unittest.TestCase):
    def test_preserves_database_and_backups_across_dist_replacement(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            deployed = root / "dist" / build_data_guard.APP_FOLDER_NAME
            deployed.mkdir(parents=True)
            database_path = deployed / "customers.db"
            conn = sqlite3.connect(database_path)
            try:
                conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, value TEXT)")
                conn.execute("INSERT INTO customers (value) VALUES ('kept')")
                conn.commit()
            finally:
                conn.close()
            backup_dir = deployed / "backups"
            backup_dir.mkdir()
            (backup_dir / "old.db").write_bytes(b"backup marker")
            log_dir = deployed / "logs"
            log_dir.mkdir()
            (log_dir / "application-error.log").write_text("error marker", encoding="utf-8")
            attachment_dir = deployed / "attachments" / "7"
            attachment_dir.mkdir(parents=True)
            (attachment_dir / "managed.pdf").write_bytes(b"managed attachment")

            build_data_guard.save(root)
            shutil.rmtree(root / "dist")
            (root / "dist" / build_data_guard.APP_FOLDER_NAME).mkdir(parents=True)
            build_data_guard.restore(root)

            conn = sqlite3.connect(database_path)
            try:
                value = conn.execute("SELECT value FROM customers").fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(value, "kept")
            self.assertEqual((backup_dir / "old.db").read_bytes(), b"backup marker")
            self.assertEqual(
                (log_dir / "application-error.log").read_text(encoding="utf-8"),
                "error marker",
            )
            self.assertEqual(
                (attachment_dir / "managed.pdf").read_bytes(),
                b"managed attachment",
            )
            self.assertFalse((root / build_data_guard.STAGING_FOLDER_NAME).exists())


if __name__ == "__main__":
    unittest.main()
