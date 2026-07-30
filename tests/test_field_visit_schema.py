import re
import unittest
from pathlib import Path

from customer_api.postgres_schema import IDENTITY_TABLES, split_postgres_statements


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "postgres" / "schema.sql"
ROLLBACK_PATH = ROOT / "postgres" / "migrations" / "008_field_visits_rollback.sql"


class FieldVisitSchemaTests(unittest.TestCase):
    def test_postgres_schema_splitter_preserves_semicolons_in_comments_and_quotes(self):
        statements = split_postgres_statements(
            """
            -- This explanation contains a semicolon; it must remain a comment.
            CREATE TABLE example (value TEXT DEFAULT 'a;b');
            /* A block comment; also must not split. */
            INSERT INTO example (value) VALUES ('c;d');
            """
        )

        self.assertEqual(len(statements), 2)
        self.assertIn("CREATE TABLE example", statements[0])
        self.assertIn("'a;b'", statements[0])
        self.assertIn("INSERT INTO example", statements[1])
        self.assertIn("'c;d'", statements[1])

    def test_bundled_postgres_schema_does_not_emit_bare_comment_fragments(self):
        statements = split_postgres_statements(self.schema)

        self.assertTrue(any("CREATE TABLE IF NOT EXISTS field_visit_routes" in item for item in statements))
        self.assertFalse(
            any(item.lstrip().startswith("the response is reused") for item in statements)
        )

    @classmethod
    def setUpClass(cls):
        cls.schema = SCHEMA_PATH.read_text(encoding="utf-8")
        cls.rollback = ROLLBACK_PATH.read_text(encoding="utf-8")
        cls.version_eight = (
            cls.schema.split("-- Version 8:", 1)[1]
            .split("-- Version 9:", 1)[0]
        )

    def test_migration_is_registered_as_schema_version_eight(self):
        self.assertIn(
            "VALUES (8, 'mobile field visit routes status history and geocode metadata')",
            self.version_eight,
        )
        self.assertIn("ON CONFLICT (version) DO NOTHING", self.version_eight)

    def test_required_tables_and_identity_sequences_are_registered(self):
        for table_name in (
            "field_visit_routes",
            "field_visit_route_items",
            "field_visit_status_history",
        ):
            with self.subTest(table_name=table_name):
                self.assertIn(
                    f"CREATE TABLE IF NOT EXISTS {table_name}",
                    self.version_eight,
                )
                self.assertIn(table_name, IDENTITY_TABLES)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS field_visit_idempotency_keys",
            self.version_eight,
        )

    def test_route_item_foreign_keys_uniqueness_and_status_constraints_exist(self):
        required = (
            "REFERENCES field_visit_routes(id) ON DELETE CASCADE",
            "REFERENCES owners(id) ON DELETE RESTRICT",
            "REFERENCES ownerships(id) ON DELETE RESTRICT",
            "REFERENCES lands(id) ON DELETE RESTRICT",
            "UNIQUE (route_id, ownership_id)",
            "UNIQUE (route_id, route_order) DEFERRABLE INITIALLY DEFERRED",
            "'planned', 'in_progress', 'completed', 'skipped', 'postponed', 'cancelled'",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.version_eight)

    def test_required_indexes_exist(self):
        for index_name in (
            "idx_field_visit_routes_visit_date_user",
            "idx_field_visit_route_items_route_order",
            "idx_field_visit_route_items_status",
            "idx_field_visit_route_items_owner",
            "idx_field_visit_route_items_ownership",
            "idx_field_visit_status_history_item_created",
            "idx_field_visit_idempotency_expires",
        ):
            with self.subTest(index_name=index_name):
                self.assertIn(
                    f"CREATE INDEX IF NOT EXISTS {index_name}",
                    self.version_eight,
                )

    def test_geocode_metadata_is_additive_and_existing_coordinates_are_preserved(self):
        for column in (
            "geocode_status",
            "geocode_source",
            "geocoded_at",
            "geocode_error",
            "address_fingerprint",
        ):
            with self.subTest(column=column):
                self.assertRegex(
                    self.version_eight,
                    rf"ADD COLUMN IF NOT EXISTS {column}\b",
                )
        self.assertNotIn("DROP COLUMN", self.version_eight)
        self.assertNotIn("DROP TABLE", self.version_eight)
        self.assertNotIn("TRUNCATE", self.version_eight)

    def test_existing_contact_and_attachment_links_are_nullable_additions(self):
        self.assertIn(
            "ALTER TABLE contact_logs\nADD COLUMN IF NOT EXISTS field_visit_route_item_id",
            self.version_eight,
        )
        self.assertIn(
            "ALTER TABLE attachments\nADD COLUMN IF NOT EXISTS contact_log_id",
            self.version_eight,
        )
        self.assertIn(
            "ALTER TABLE attachments\nADD COLUMN IF NOT EXISTS field_visit_route_item_id",
            self.version_eight,
        )

    def test_all_schema_statements_are_safe_to_split_with_current_runner(self):
        statements = [
            statement.strip()
            for statement in self.schema.split(";")
            if statement.strip()
        ]
        self.assertGreater(len(statements), 1)
        self.assertTrue(all("DO $$" not in statement for statement in statements))
        self.assertEqual(
            sum(
                1
                for statement in statements
                if re.search(r"INSERT INTO schema_migrations.*VALUES \(8,", statement, re.S)
            ),
            1,
        )

    def test_manual_rollback_is_explicit_and_transactional(self):
        self.assertTrue(self.rollback.lstrip().startswith("-- Manual rollback"))
        self.assertIn("BEGIN;", self.rollback)
        self.assertIn("DELETE FROM schema_migrations WHERE version = 8;", self.rollback)
        self.assertTrue(self.rollback.rstrip().endswith("COMMIT;"))
        for table_name in (
            "field_visit_status_history",
            "field_visit_route_items",
            "field_visit_routes",
        ):
            self.assertIn(f"DROP TABLE IF EXISTS {table_name};", self.rollback)


if __name__ == "__main__":
    unittest.main()
