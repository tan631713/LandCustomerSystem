import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import customer_migration_package as migration_package
from migrate_sqlite_to_postgresql import MigrationPlan
from start_api_server import build_parser


def create_minimal_database(path: Path, *, attachments=0) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT);
            CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE customer_attachments (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                file_path TEXT
            );
            INSERT INTO users (username) VALUES ('User');
            INSERT INTO customers (name) VALUES ('王大明');
            """
        )
        for index in range(attachments):
            connection.execute(
                "INSERT INTO customer_attachments (customer_id, file_path) VALUES (1, ?)",
                (f"file-{index}.pdf",),
            )
        connection.commit()


class MigrationPackageExportTests(unittest.TestCase):
    def test_export_creates_consistent_encrypted_database_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "customers.db"
            create_minimal_database(source)
            destination = root / f"transfer{migration_package.PACKAGE_SUFFIX}"

            result = migration_package.export_migration_package(source, destination)
            manifest = migration_package.inspect_migration_package(destination)
            extracted_root = root / "extracted"
            _, extracted = migration_package.extract_migration_package(
                destination, extracted_root
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(manifest["source_counts"]["customers"], 1)
            self.assertEqual(manifest["source_counts"]["users"], 1)
            self.assertEqual(manifest["attachment_count"], 0)
            with closing(sqlite3.connect(extracted)) as connection:
                self.assertEqual(
                    connection.execute("SELECT name FROM customers").fetchone()[0],
                    "王大明",
                )

    def test_export_refuses_database_with_attachments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "customers.db"
            create_minimal_database(source, attachments=1)

            with self.assertRaisesRegex(ValueError, "含附件"):
                migration_package.export_migration_package(
                    source, root / f"transfer{migration_package.PACKAGE_SUFFIX}"
                )

    def test_extract_rejects_database_checksum_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "customers.db"
            create_minimal_database(source)
            original = root / f"original{migration_package.PACKAGE_SUFFIX}"
            migration_package.export_migration_package(source, original)
            tampered = root / f"tampered{migration_package.PACKAGE_SUFFIX}"
            with zipfile.ZipFile(original, "r") as archive:
                manifest = archive.read(migration_package.MANIFEST_MEMBER)
            with zipfile.ZipFile(tampered, "w") as archive:
                archive.writestr(migration_package.MANIFEST_MEMBER, manifest)
                archive.writestr(migration_package.DATABASE_MEMBER, b"not sqlite")

            with self.assertRaisesRegex(ValueError, "大小|SHA-256"):
                migration_package.extract_migration_package(tampered, root / "out")

    def test_inspection_rejects_unexpected_archive_member(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"unsafe{migration_package.PACKAGE_SUFFIX}"
            manifest = {
                "format": migration_package.PACKAGE_FORMAT,
                "database_member": migration_package.DATABASE_MEMBER,
                "database_sha256": "0" * 64,
                "attachment_count": 0,
            }
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    migration_package.MANIFEST_MEMBER,
                    json.dumps(manifest),
                )
                archive.writestr(migration_package.DATABASE_MEMBER, b"db")
                archive.writestr("../outside.txt", b"unsafe")

            with self.assertRaisesRegex(ValueError, "不安全"):
                migration_package.inspect_migration_package(path)


class MigrationPackageImportTests(unittest.TestCase):
    def test_target_with_business_data_is_refused(self):
        report = {"counts": {"ownerships": 1, "users": 1}}
        with self.assertRaisesRegex(ValueError, "已有有效正式業務資料"):
            migration_package._validate_target_is_empty(report)

    def test_deleted_test_record_residue_does_not_block_first_import(self):
        report = {
            "counts": {
                "owners": 1,
                "lands": 1,
                "ownerships": 0,
                "recycle_bin": 1,
                "operation_logs": 6,
            }
        }

        migration_package._validate_target_is_empty(report)

    def test_prepare_target_removes_only_orphan_owner_and_land_rows(self):
        class Result:
            @staticmethod
            def fetchone():
                return (1,)

        connection = Mock()
        connection.execute.return_value = Result()

        result = migration_package._prepare_target_for_import(connection)

        sql = "\n".join(call.args[0] for call in connection.execute.call_args_list)
        self.assertEqual(result["removed_orphan_owners"], 1)
        self.assertEqual(result["removed_orphan_lands"], 1)
        self.assertIn("DELETE FROM owners", sql)
        self.assertIn("DELETE FROM lands", sql)
        self.assertNotIn("DELETE FROM recycle_bin", sql)
        self.assertNotIn("DELETE FROM operation_logs", sql)

    def test_import_preserves_server_accounts_and_uses_server_key(self):
        source_counts = {
            name: 0 for name in migration_package.SOURCE_COUNT_TABLES
        }
        source_counts["users"] = 2
        source_counts["customers"] = 1
        manifest = {"source_counts": source_counts}
        source_repository = Mock()
        source_repository.authenticate_user.return_value = b"source-key"
        server_user = SimpleNamespace(role="admin", data_key=b"server-key")
        target_source = Mock()
        target_source.authenticate.return_value = server_user
        empty_report = {
            "schema_version": 3,
            "counts": {name: 0 for name in migration_package.TARGET_MUST_BE_EMPTY},
            "mirrored_source_counts": {
                name: int(source_counts.get(name) or 0)
                for name in migration_package.SOURCE_TARGET_COUNT_QUERIES
            },
            "orphan_counts": {},
        }
        final_report = dict(empty_report)
        plan = MigrationPlan(1, 1, 1, 1, 0, 1, 0)
        backup_creator = Mock(
            return_value={"status": "ok", "backup_path": "pre-migration.zip"}
        )

        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "customers.db"
            database_path.write_bytes(b"placeholder")
            with (
                patch.object(
                    migration_package,
                    "extract_migration_package",
                    return_value=(manifest, database_path),
                ),
                patch.object(
                    migration_package,
                    "build_source",
                    return_value=(Mock(), source_repository),
                ),
                patch.object(
                    migration_package,
                    "collect_source_counts",
                    return_value=source_counts,
                ),
                patch.object(
                    migration_package,
                    "read_plain_records",
                    return_value=[{"id": 1}],
                ),
                patch.object(
                    migration_package,
                    "PostgreSQLCustomerDataSource",
                    return_value=target_source,
                ),
                patch.object(
                    migration_package,
                    "verify_postgres",
                    side_effect=[empty_report, final_report],
                ),
                patch.object(migration_package, "analyze_records", return_value=plan),
                patch.object(
                    migration_package,
                    "apply_migration",
                    return_value={"ownerships": 1},
                ) as apply_migration,
            ):
                result = migration_package.import_migration_package(
                    Path(directory) / f"transfer{migration_package.PACKAGE_SUFFIX}",
                    "postgresql://protected",
                    source_username="User",
                    source_password="source-password",
                    server_username="admin",
                    server_password="server-password",
                    backup_creator=backup_creator,
                )

        self.assertTrue(result["server_accounts_preserved"])
        self.assertFalse(result["source_users_copied"])
        backup_creator.assert_called_once_with(label="pre-migration")
        self.assertFalse(apply_migration.call_args.kwargs["copy_users"])
        self.assertEqual(
            apply_migration.call_args.kwargs["target_data_key"], b"server-key"
        )
        self.assertIs(
            apply_migration.call_args.kwargs["before_migration_callback"],
            migration_package._prepare_target_for_import,
        )

    def test_transaction_verification_rejects_count_mismatch(self):
        class FakeResult:
            def __init__(self, value):
                self.value = value

            def fetchone(self):
                return (self.value,)

        class FakeConnection:
            def execute(self, query):
                if "schema_migrations" in query:
                    return FakeResult(3)
                return FakeResult(0)

        with self.assertRaisesRegex(RuntimeError, "已回滾"):
            migration_package._verify_connection_counts(
                FakeConnection(), {"customers": 1}
            )

    def test_server_parser_accepts_migration_package_action(self):
        args = build_parser().parse_args(
            ["--postgres", "--import-migration-package", "transfer.lcs-migration.zip"]
        )
        self.assertEqual(
            args.import_migration_package, "transfer.lcs-migration.zip"
        )


if __name__ == "__main__":
    unittest.main()
