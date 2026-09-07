import sqlite3
import tempfile
import unittest
from pathlib import Path

from customer_database import CustomerDatabase
from customer_migrations import LATEST_SCHEMA_VERSION
from customer_repository import CustomerRepository


class CustomerMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.database_path = self.root / "customers.db"
        conn = sqlite3.connect(self.database_path)
        try:
            conn.executescript(
                """
                CREATE TABLE customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL DEFAULT '',
                    customer_code TEXT
                );
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_salt TEXT NOT NULL,
                    password_hash TEXT NOT NULL
                );
                INSERT INTO customers (name, customer_code)
                VALUES ('王小明', 'A123456789');
                CREATE INDEX idx_customers_name ON customers(name);
                CREATE INDEX idx_customers_customer_code ON customers(customer_code);
                """
            )
            conn.commit()
        finally:
            conn.close()

        project_root = Path(__file__).resolve().parents[1]
        self.database = CustomerDatabase(self.database_path, self.root / "backups")
        self.repository = CustomerRepository(
            self.database,
            project_root / "schema.sql",
            self.root / "missing-seed.sql",
            [
                ("district", "地區"),
                ("section", "地段"),
                ("land_number", "地號"),
                ("owner_name", "姓名"),
                ("external_id", "身分證"),
            ],
        )

    def tearDown(self):
        self.temp_context.cleanup()

    def test_legacy_database_is_backed_up_and_migrated_once(self):
        self.repository.init_db()

        with self.database.connect() as conn:
            version = self.repository.migrations.current_version(conn)
            history = conn.execute(
                "SELECT version, name FROM schema_migrations ORDER BY version"
            ).fetchall()
            customer = conn.execute(
                "SELECT owner_name, external_id FROM customers"
            ).fetchone()
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            indexes = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = 'customers'"
                )
            }
            attachment_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(customer_attachments)")
            }

        self.assertEqual(version, LATEST_SCHEMA_VERSION)
        self.assertEqual(
            [row["version"] for row in history],
            list(range(1, LATEST_SCHEMA_VERSION + 1)),
        )
        self.assertEqual(customer["owner_name"], "王小明")
        self.assertEqual(customer["external_id"], "A123456789")
        self.assertTrue(
            {
                "app_settings",
                "watchlist",
                "operation_logs",
                "record_change_logs",
                "follow_up_reminders",
                "cases",
                "case_customers",
                "tags",
                "customer_tags",
                "customer_attachments",
                "custom_fields",
                "customer_custom_values",
                "text_templates",
                "contact_logs",
                "recycle_bin",
                "undo_operations",
                "case_tasks",
                "notifications",
                "import_profiles",
                "report_templates",
                "backup_targets",
                "customer_locations",
                "duplicate_reviews",
            }
            <= tables
        )
        self.assertTrue(
            {"idx_customers_district", "idx_customers_section", "idx_customers_land_number"}
            <= indexes
        )
        self.assertFalse(
            {
                "idx_customers_owner_name",
                "idx_customers_external_id",
                "idx_customers_name",
                "idx_customers_customer_code",
            }
            & indexes
        )
        self.assertIn("category", attachment_columns)
        self.assertIn("created_by", attachment_columns)
        self.assertEqual(len(list((self.root / "backups").glob("customers-pre-migration-*.db"))), 1)

        self.repository.init_db()

        self.assertEqual(len(list((self.root / "backups").glob("customers-pre-migration-*.db"))), 1)

    def test_version_nine_adds_attachment_uploader_to_existing_database(self):
        self.repository.init_db()
        with self.database.connect() as conn:
            # The runner resumes from MAX(version) in schema_migrations, not
            # from the highest *missing* row, so any later version's row
            # (10+) must also be cleared for a resume-from-9 replay to
            # actually happen.
            conn.execute("DELETE FROM schema_migrations WHERE version >= 9")
            conn.execute("ALTER TABLE customer_attachments DROP COLUMN created_by")

        self.repository.init_db()
        with self.database.connect() as conn:
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(customer_attachments)")
            }
            version = self.repository.migrations.current_version(conn)

        self.assertEqual(version, LATEST_SCHEMA_VERSION)
        self.assertIn("created_by", columns)

    def test_legacy_contact_log_shape_is_rebuilt_without_losing_data(self):
        self.repository.init_db()
        with self.database.connect() as conn:
            conn.execute("DELETE FROM schema_migrations WHERE version >= 7")
            conn.execute("DROP TABLE contact_logs")
            conn.executescript(
                """
                CREATE TABLE contact_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    contact_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    method TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    content TEXT,
                    next_follow_up TEXT
                );
                INSERT INTO contact_logs (
                    customer_id, contact_date, method, subject, content, next_follow_up
                ) VALUES (
                    1, '2026-07-01', '電話', '願意再談', '舊版內容', '2026-07-20'
                );
                """
            )

        self.repository.init_db()
        with self.database.connect() as conn:
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(contact_logs)")}
            row = conn.execute("SELECT * FROM contact_logs WHERE id = 1").fetchone()

        self.assertEqual(
            columns,
            {
                "id", "customer_id", "contact_date", "method", "result",
                "next_follow_up", "note", "created_at",
            },
        )
        self.assertEqual(row["result"], "願意再談")
        self.assertEqual(row["note"], "舊版內容")
        self.assertEqual(row["next_follow_up"], "2026-07-20")
        new_id = self.repository.add_contact_log(
            1, "2026-07-02", "面談", "持續追蹤", "2026-07-25", "新版內容"
        )
        self.assertGreater(new_id, 1)


if __name__ == "__main__":
    unittest.main()
