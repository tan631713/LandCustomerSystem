import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from customer_api.postgres_schema import IDENTITY_TABLES, ensure_postgres_schema


ROOT = Path(__file__).resolve().parents[1]


class OwnerContactSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = (ROOT / "postgres" / "schema.sql").read_text(
            encoding="utf-8"
        )
        self.phase_rollback = (
            ROOT / "postgres" / "migrations" / "009_owner_contacts_rollback.sql"
        ).read_text(encoding="utf-8")
        self.enhancement_rollback = (
            ROOT
            / "postgres"
            / "migrations"
            / "010_owner_contacts_enhancement_rollback.sql"
        ).read_text(encoding="utf-8")
        self.identity_rollback = (
            ROOT
            / "postgres"
            / "migrations"
            / "011_owner_contact_identity_rollback.sql"
        ).read_text(encoding="utf-8")

    def test_additive_schema_contains_tables_foreign_keys_and_version(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS contacts", self.schema)
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS owner_contact_relations", self.schema
        )
        self.assertIn(
            "owner_id BIGINT NOT NULL REFERENCES owners(id) ON DELETE RESTRICT",
            self.schema,
        )
        self.assertIn(
            "contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT",
            self.schema,
        )
        self.assertIn(
            "VALUES (9, 'owner related contacts and reversible relations')",
            self.schema,
        )
        self.assertIn(
            "VALUES (10, 'owner contact addresses phone lookup and deactivation metadata')",
            self.schema,
        )
        self.assertIn(
            "VALUES (11, 'encrypted owner contact identity number')",
            self.schema,
        )
        self.assertIn(
            "ALTER TABLE contacts\nADD COLUMN IF NOT EXISTS external_id TEXT",
            self.schema,
        )
        for column in (
            "registered_address",
            "contact_address",
            "work_address",
            "identity_note",
            "deactivated_at",
            "deactivated_by",
        ):
            self.assertIn(column, self.schema)

    def test_indexes_and_partial_uniqueness_are_present(self):
        for name in (
            "idx_contacts_name",
            "idx_contacts_mobile_phone",
            "idx_contacts_home_phone",
            "idx_contacts_is_active",
            "idx_owner_contact_relations_owner",
            "idx_owner_contact_relations_contact",
            "idx_owner_contact_relations_owner_active",
            "idx_owner_contact_relations_sort",
            "uq_owner_contact_relations_active",
            "uq_owner_contact_primary_active",
            "idx_contacts_registered_address",
            "idx_contacts_contact_address",
            "idx_contacts_mobile_phone_normalized",
            "idx_contacts_home_phone_normalized",
            "idx_owner_contact_relations_deactivated_by",
        ):
            self.assertIn(name, self.schema)
        self.assertIn("WHERE is_active = TRUE;", self.schema)
        self.assertIn(
            "WHERE is_primary = TRUE AND is_active = TRUE;", self.schema
        )

    def test_migration_does_not_alter_existing_business_tables(self):
        # Versions 9-11 are the owner-contacts phase covered by the numbered
        # rollback scripts in postgres/migrations/. Version 12 (birth year)
        # is a separate, later addition with no rollback script of its own
        # -- it deliberately does touch owners (see schema.sql's Version 12
        # comment), so it sits outside this phase's boundary.
        phase = self.schema[
            self.schema.index("-- Version 9:") : self.schema.index("-- Version 12:")
        ]
        for table_name in ("owners", "lands", "ownerships"):
            self.assertNotIn(f"ALTER TABLE {table_name}", phase)
            self.assertNotIn(f"DROP TABLE {table_name}", phase)

    def test_rollback_drops_relation_before_contact(self):
        relation_position = self.phase_rollback.index(
            "DROP TABLE IF EXISTS owner_contact_relations"
        )
        contact_position = self.phase_rollback.index(
            "DROP TABLE IF EXISTS contacts"
        )
        self.assertLess(relation_position, contact_position)
        self.assertIn("BEGIN;", self.phase_rollback)
        self.assertIn("COMMIT;", self.phase_rollback)

    def test_enhancement_rollback_restores_legacy_address_and_metadata(self):
        self.assertIn(
            "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS address TEXT",
            self.enhancement_rollback,
        )
        self.assertIn(
            "DROP COLUMN IF EXISTS deactivated_by",
            self.enhancement_rollback,
        )
        self.assertIn(
            "DELETE FROM schema_migrations WHERE version = 10",
            self.enhancement_rollback,
        )

    def test_identity_rollback_only_removes_contact_identity_column(self):
        self.assertIn(
            "ALTER TABLE contacts\nDROP COLUMN IF EXISTS external_id",
            self.identity_rollback,
        )
        self.assertIn(
            "DELETE FROM schema_migrations WHERE version = 11",
            self.identity_rollback,
        )
        self.assertNotIn("ALTER TABLE owners", self.identity_rollback)

    def test_enhancement_migration_tolerates_missing_legacy_address_column(self):
        version_ten = self.schema[self.schema.index("-- Version 10:") :]
        self.assertIn("information_schema.columns", version_ten)
        self.assertIn("column_name = 'address'", version_ten)
        self.assertIn(
            "DO $owner_contact_address_migration$",
            version_ten,
        )
        self.assertNotIn(
            "\nUPDATE contacts\nSET registered_address = address",
            version_ten,
        )

    def test_identity_repair_includes_new_tables(self):
        self.assertIn("contacts", IDENTITY_TABLES)
        self.assertIn("owner_contact_relations", IDENTITY_TABLES)

    def test_schema_framework_applies_version_nine_in_one_connection_context(self):
        class Connection:
            def __init__(self):
                self.statements = []
                self.committed = False
                self.rolled_back = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, _exc, _traceback):
                self.committed = exc_type is None
                self.rolled_back = exc_type is not None
                return False

            def execute(self, statement, _parameters=()):
                self.statements.append(str(statement))
                if "SELECT COALESCE(MAX(version), 0)" in str(statement):
                    return type("Result", (), {"fetchone": lambda _self: (11,)})()
                return type("Result", (), {"fetchone": lambda _self: None})()

        connection = Connection()
        fake_psycopg = SimpleNamespace(connect=lambda *_args, **_kwargs: connection)
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}), patch(
            "customer_api.postgres_schema.repair_postgres_identity_sequences",
            return_value={},
        ):
            version = ensure_postgres_schema("test-dsn")
        self.assertEqual(version, 11)
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        executed = "\n".join(connection.statements)
        self.assertIn("CREATE TABLE IF NOT EXISTS contacts", executed)
        self.assertIn("CREATE TABLE IF NOT EXISTS owner_contact_relations", executed)

    def test_schema_framework_rolls_back_when_migration_statement_fails(self):
        class Connection:
            def __init__(self):
                self.rolled_back = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, _exc, _traceback):
                self.rolled_back = exc_type is not None
                return False

            def execute(self, statement, _parameters=()):
                if "CREATE TABLE IF NOT EXISTS contacts" in str(statement):
                    raise RuntimeError("simulated migration failure")
                return type("Result", (), {"fetchone": lambda _self: None})()

        connection = Connection()
        fake_psycopg = SimpleNamespace(connect=lambda *_args, **_kwargs: connection)
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}), self.assertRaises(
            RuntimeError
        ):
            ensure_postgres_schema("test-dsn")
        self.assertTrue(connection.rolled_back)


if __name__ == "__main__":
    unittest.main()
