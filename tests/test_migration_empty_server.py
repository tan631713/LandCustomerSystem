import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import customer_migration_package as migration_package
from migrate_sqlite_to_postgresql import MigrationPlan


def _reports(source_counts):
    empty = {
        "schema_version": 3,
        "counts": {name: 0 for name in migration_package.TARGET_MUST_BE_EMPTY},
        "mirrored_source_counts": {
            name: int(source_counts.get(name) or 0)
            for name in migration_package.SOURCE_TARGET_COUNT_QUERIES
        },
        "orphan_counts": {},
    }
    return empty, dict(empty)


class EmptyServerImportTests(unittest.TestCase):
    def _run(self, *, role="admin", server_accounts=0, authenticated=b"source-key"):
        source_counts = {name: 0 for name in migration_package.SOURCE_COUNT_TABLES}
        source_counts["users"] = 2
        source_counts["customers"] = 1
        manifest = {"source_counts": source_counts}
        repository = Mock()
        repository.authenticate_user.return_value = authenticated
        repository.last_authenticated_user = {"username": "chen.office", "role": role}
        initial, final = _reports(source_counts)
        backup_creator = Mock(return_value={"status": "ok", "backup_path": "pre.zip"})
        plan = MigrationPlan(1, 1, 1, 1, 0, 1, 0)
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "customers.db"
            database_path.write_bytes(b"placeholder")
            with (
                patch.object(migration_package, "extract_migration_package",
                             return_value=(manifest, database_path)),
                patch.object(migration_package, "build_source",
                             return_value=(Mock(), repository)),
                patch.object(migration_package, "collect_source_counts",
                             return_value=source_counts),
                patch.object(migration_package, "read_plain_records",
                             return_value=[{"id": 1}]),
                patch.object(migration_package, "_server_account_count",
                             return_value=server_accounts),
                patch.object(migration_package, "verify_postgres",
                             side_effect=[initial, final]),
                patch.object(migration_package, "analyze_records", return_value=plan),
                patch.object(migration_package, "apply_migration",
                             return_value={"ownerships": 1}) as apply_migration,
            ):
                try:
                    result = migration_package.import_migration_package_into_empty_server(
                        Path(directory) / f"t{migration_package.PACKAGE_SUFFIX}",
                        "postgresql://protected",
                        source_username="chen.office",
                        source_password="source-password",
                        backup_creator=backup_creator,
                    )
                except Exception as exc:  # noqa: BLE001 - asserted by callers
                    return exc, apply_migration, backup_creator
        return result, apply_migration, backup_creator

    def test_source_admin_becomes_server_admin_and_keeps_source_key(self):
        result, apply_migration, backup_creator = self._run()
        self.assertEqual(result["mode"], "empty_server")
        self.assertTrue(result["source_users_copied"])
        self.assertFalse(result["server_accounts_preserved"])
        backup_creator.assert_called_once_with(label="pre-migration")
        kwargs = apply_migration.call_args.kwargs
        # 使用者帳號在交易內由 callback 複製，不是在交易外先行 copy_users。
        self.assertFalse(kwargs["copy_users"])
        self.assertNotIn("target_data_key", kwargs)
        self.assertEqual(apply_migration.call_args.args[2], b"source-key")
        self.assertTrue(callable(kwargs["before_migration_callback"]))

    def test_non_admin_source_account_is_refused_before_backup_or_writes(self):
        result, apply_migration, backup_creator = self._run(role="editor")
        self.assertIsInstance(result, PermissionError)
        apply_migration.assert_not_called()
        backup_creator.assert_not_called()

    def test_server_that_already_has_accounts_is_refused(self):
        result, apply_migration, _backup = self._run(server_accounts=2)
        self.assertIsInstance(result, ValueError)
        self.assertIn("一般匯入", str(result))
        apply_migration.assert_not_called()

    def test_wrong_source_password_is_refused(self):
        result, apply_migration, _backup = self._run(authenticated=None)
        self.assertIsInstance(result, ValueError)
        self.assertIn("單機版帳號或密碼錯誤", str(result))
        apply_migration.assert_not_called()


class CopyUsersCallbackTests(unittest.TestCase):
    class FakeConnection:
        def __init__(self, existing):
            self.existing = existing
            self.statements = []

        def execute(self, statement, parameters=()):
            self.statements.append(" ".join(statement.split()))
            return SimpleNamespace(fetchone=lambda: (self.existing,))

    def test_users_are_copied_only_when_still_empty_under_the_lock(self):
        connection = self.FakeConnection(existing=0)
        with (
            patch.object(migration_package, "_copy_users") as copy_users,
            patch.object(migration_package, "_prepare_target_for_import",
                         return_value={"recycle_bin_preserved": True}) as prepare,
        ):
            outcome = migration_package._copy_source_users_into_empty_server("sqlite")(connection)
        self.assertIn("pg_advisory_xact_lock", connection.statements[0])
        copy_users.assert_called_once_with("sqlite", connection)
        prepare.assert_called_once_with(connection)
        self.assertEqual(outcome, {"recycle_bin_preserved": True})

    def test_a_user_that_appeared_meanwhile_aborts_before_any_copy(self):
        connection = self.FakeConnection(existing=1)
        with patch.object(migration_package, "_copy_users") as copy_users:
            with self.assertRaisesRegex(ValueError, "已經出現帳號"):
                migration_package._copy_source_users_into_empty_server("sqlite")(connection)
        copy_users.assert_not_called()


if __name__ == "__main__":
    unittest.main()
