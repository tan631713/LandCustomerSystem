import sqlite3
import tempfile
import unittest
import urllib.error
import urllib.request
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import customer_ui_qt as app
import customer_mobile_share as mobile_share
from customer_database import CustomerDatabase
from customer_backup_status import inspect_backup_status
from customer_repository import CustomerRepository


class DatabaseSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir_context = tempfile.TemporaryDirectory()
        self.temp_dir = Path(self.temp_dir_context.name)
        self.original_db_path = app.DB_PATH
        self.original_backup_dir = app.BACKUP_DIR
        self.original_database = app.DATABASE
        self.original_repository = app.REPOSITORY
        app.DB_PATH = self.temp_dir / "customers.db"
        app.BACKUP_DIR = self.temp_dir / "backups"
        app.DATABASE = CustomerDatabase(app.DB_PATH, app.BACKUP_DIR)
        app.REPOSITORY = CustomerRepository(
            app.DATABASE,
            app.SCHEMA_PATH,
            app.SEED_PATH,
            app.LAND_FIELDS,
        )
        self.create_database(app.DB_PATH, "original")

    def tearDown(self):
        app.DB_PATH = self.original_db_path
        app.BACKUP_DIR = self.original_backup_dir
        app.DATABASE = self.original_database
        app.REPOSITORY = self.original_repository
        self.temp_dir_context.cleanup()

    def create_database(self, path, owner_name):
        conn = sqlite3.connect(path)
        try:
            conn.executescript(app.SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO users (username, password_salt, password_hash) VALUES (?, ?, ?)",
                ("admin", "00" * 16, "00" * 32),
            )
            conn.execute(
                "INSERT INTO customers (district, section, land_number, owner_name) "
                "VALUES (?, ?, ?, ?)",
                ("D", "S", "1", owner_name),
            )
            conn.commit()
        finally:
            conn.close()

    def read_owner(self, path):
        conn = sqlite3.connect(path)
        try:
            return conn.execute("SELECT owner_name FROM customers").fetchone()[0]
        finally:
            conn.close()

    def test_backup_uses_valid_sqlite_snapshot(self):
        backup_path = app.backup_database("test")

        self.assertTrue(backup_path.is_file())
        self.assertTrue(app.validate_database_file(backup_path))
        self.assertEqual(self.read_owner(backup_path), "original")

    def test_zip_backup_is_valid_and_can_restore_directly(self):
        app.DATABASE.configure_backup_policy(
            compress_backups=True,
            retention_days=90,
            max_count=30,
        )
        backup_path = app.backup_database("zip-test")

        self.assertEqual(backup_path.suffix, ".zip")
        self.assertTrue(app.DATABASE.validate_backup_file(backup_path))
        self.assertFalse(backup_path.with_suffix(".db").exists())

        with app.connect() as conn:
            conn.execute("UPDATE customers SET owner_name = ?", ("changed",))
        safety_backup = app.restore_database(backup_path)

        self.assertEqual(self.read_owner(app.DB_PATH), "original")
        self.assertEqual(safety_backup.suffix, ".zip")
        self.assertTrue(app.DATABASE.validate_backup_file(safety_backup))

    def test_existing_backups_can_be_compressed_without_losing_restore_data(self):
        backup_path = app.backup_database("legacy")
        original_size = backup_path.stat().st_size

        result = app.DATABASE.compress_existing_backups()
        archive_path = backup_path.with_suffix(".zip")

        self.assertEqual(result.compressed_count, 1)
        self.assertFalse(backup_path.exists())
        self.assertTrue(archive_path.exists())
        self.assertLess(archive_path.stat().st_size, original_size)
        self.assertTrue(app.DATABASE.validate_backup_file(archive_path))

    def test_backup_cleanup_respects_expiry_count_and_minimum_safety_copies(self):
        now = datetime(2026, 7, 13, 12, 0, 0)
        backups = [app.backup_database(f"cleanup-{index}") for index in range(6)]
        for index, backup_path in enumerate(backups):
            timestamp = (now - timedelta(days=100 - index)).timestamp()
            os.utime(backup_path, (timestamp, timestamp))

        result = app.DATABASE.prune_backups(retention_days=30, max_count=4, now=now)

        self.assertEqual(result.deleted_count, 3)
        remaining = app.DATABASE.list_backup_files()
        self.assertEqual(len(remaining), 3)
        self.assertEqual(set(remaining), set(backups[-3:]))

    def test_backup_cleanup_preserves_invalid_candidate_for_manual_recovery(self):
        now = datetime(2026, 7, 13, 12, 0, 0)
        valid_backups = [app.backup_database(f"valid-{index}") for index in range(3)]
        invalid_path = app.BACKUP_DIR / "customers-invalid-20200101-000000.db"
        invalid_path.write_bytes(b"damaged backup")
        old_timestamp = (now - timedelta(days=100)).timestamp()
        os.utime(invalid_path, (old_timestamp, old_timestamp))

        result = app.DATABASE.prune_backups(retention_days=30, max_count=3, now=now)

        self.assertEqual(result.deleted_count, 0)
        self.assertIn(invalid_path, result.failed_paths)
        self.assertTrue(invalid_path.exists())
        self.assertTrue(all(path.exists() for path in valid_backups))

    def test_backup_status_detects_missing_recent_and_stale_backups(self):
        now = datetime(2026, 7, 8, 12, 0, 0)
        missing = inspect_backup_status(app.DATABASE, now=now)
        self.assertTrue(missing.database_healthy)
        self.assertEqual(missing.backup_count, 0)
        self.assertFalse(missing.healthy)

        backup_path = app.backup_database("manual")
        recent_timestamp = now.timestamp()
        os.utime(backup_path, (recent_timestamp, recent_timestamp))
        recent = inspect_backup_status(app.DATABASE, now=now)
        self.assertTrue(recent.healthy)

        stale_timestamp = (now - timedelta(days=8)).timestamp()
        os.utime(backup_path, (stale_timestamp, stale_timestamp))
        stale = inspect_backup_status(app.DATABASE, now=now)
        self.assertTrue(stale.backup_stale)
        self.assertFalse(stale.healthy)

    def test_restore_validates_and_preserves_previous_database(self):
        source_path = self.temp_dir / "replacement.db"
        self.create_database(source_path, "replacement")

        safety_backup = app.restore_database(source_path)

        self.assertEqual(self.read_owner(app.DB_PATH), "replacement")
        self.assertEqual(self.read_owner(safety_backup), "original")

    def test_invalid_restore_is_rejected_without_touching_current_data(self):
        invalid_path = self.temp_dir / "invalid.db"
        invalid_path.write_bytes(b"not a sqlite database")

        with self.assertRaises(ValueError):
            app.restore_database(invalid_path)

        self.assertEqual(self.read_owner(app.DB_PATH), "original")

    def test_connection_enables_safety_pragmas(self):
        with app.connect() as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("PRAGMA busy_timeout").fetchone()[0],
                app.DATABASE.busy_timeout_ms,
            )

    def test_mobile_share_is_token_protected_and_sends_security_headers(self):
        with patch.object(mobile_share, "get_lan_ip_address", return_value="127.0.0.1"):
            server = mobile_share.TemporaryShareServer("<html>private</html>")
        try:
            with urllib.request.urlopen(server.url, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
                self.assertEqual(response.headers["X-Frame-Options"], "DENY")
                self.assertIn("default-src 'none'", response.headers["Content-Security-Policy"])
                self.assertIn(b"private", response.read())

            invalid_url = server.url.rsplit("/", 1)[0] + "/wrong-token"
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(invalid_url, timeout=2)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        finally:
            server.stop()

    def test_mobile_share_html_escapes_customer_content(self):
        page = mobile_share.build_mobile_share_html(
            [{"display": {"owner_name": "<script>alert(1)</script>"}}],
            [("owner_name", "姓名")],
        )
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>alert(1)</script>", page)


if __name__ == "__main__":
    unittest.main()
