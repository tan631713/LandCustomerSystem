import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cryptography.fernet import Fernet

from customer_security import derive_encryption_key, hash_password, make_fernet
import tempfile
from pathlib import Path

from server_console_admin import (
    run_admin_bootstrap,
    run_admin_list,
    run_admin_recover,
    run_migration_import,
)


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row


class _ConsoleAdminConnection:
    def __init__(
        self, *, account_count, account=None, sample="", admin_exists=True,
        admins=(), target_row=None,
    ):
        self.admins = list(admins)
        self.target_row = target_row
        self.update_parameters = None
        self.account_count = account_count
        self.account = account
        self.sample = sample
        self.admin_exists = admin_exists
        self.admin_inserted = False
        self.audit_logged = False
        self.updated = False
        self.insert_parameters = None
        self.insert_statement = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=()):
        normalized = " ".join(statement.split())
        if "SELECT COUNT(*) FROM users" in normalized:
            return _Result((self.account_count,))
        if "pg_advisory_xact_lock" in normalized:
            return _Result((None,))
        if "WHERE role = 'admin' AND active" in normalized:
            return _Result([(name,) for name in self.admins])
        if normalized.startswith("SELECT id, role FROM users WHERE lower(username)"):
            return _Result([self.target_row] if self.target_row else [])
        if "FROM users WHERE lower(username) = lower(%s)" in normalized:
            account = self.account
            return _Result(
                [
                    (
                        2,
                        account["username"],
                        account["role"],
                        account["active"],
                        account["password_salt"],
                        account["password_hash"],
                        account["encryption_salt"],
                        account["wrapped_data_key"],
                    )
                ]
            )
        if "FROM owners" in normalized and "LIKE" in normalized:
            return _Result((self.sample,))
        if "SELECT id FROM users WHERE lower(username) = 'admin'" in normalized:
            return _Result([(1,)] if self.admin_exists else [])
        if normalized.startswith("UPDATE users"):
            self.updated = True
            self.update_parameters = parameters
        if normalized.startswith("INSERT INTO operation_logs"):
            self.audit_logged = True
        if normalized.startswith("INSERT INTO users"):
            self.admin_inserted = True
            self.insert_parameters = parameters
            self.insert_statement = normalized
        return _Result(None)


def _run_with_stdin(func, payload):
    stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
    stdout = io.StringIO()
    with patch("sys.stdin", stdin), redirect_stdout(stdout):
        exit_code = func()
    return exit_code, json.loads(stdout.getvalue())


class AdminRecoverSubcommandTests(unittest.TestCase):
    password = "verify-account-password"

    def setUp(self):
        self.data_key = Fernet.generate_key()
        password_salt, password_hash = hash_password(self.password)
        encryption_salt = os.urandom(16).hex()
        wrapped = make_fernet(
            derive_encryption_key(self.password, encryption_salt)
        ).encrypt(self.data_key).decode("ascii")
        self.account = {
            "username": "User",
            "role": "editor",
            "active": True,
            "password_salt": password_salt,
            "password_hash": password_hash,
            "encryption_salt": encryption_salt,
            "wrapped_data_key": wrapped,
        }
        token = make_fernet(self.data_key).encrypt("測試地主".encode("utf-8")).decode("ascii")
        self.sample = f"enc:v1:{token}"

    def test_rejects_when_no_accounts_exist(self):
        connection = _ConsoleAdminConnection(account_count=0)
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(
                run_admin_recover,
                {
                    "verify_username": "User",
                    "verify_password": self.password,
                    "new_password": "new-admin-password",
                },
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(reply["status"], "error")
        self.assertIn("沒有任何帳號", reply["message"])
        self.assertFalse(connection.admin_inserted)

    def test_success_resets_admin_password(self):
        connection = _ConsoleAdminConnection(
            account_count=1, account=self.account, sample=self.sample
        )
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(
                run_admin_recover,
                {
                    "verify_username": "User",
                    "verify_password": self.password,
                    "new_password": "new-admin-password",
                },
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(reply["status"], "ok")
        self.assertNotIn(self.password, json.dumps(reply, ensure_ascii=False))
        self.assertNotIn("new-admin-password", json.dumps(reply, ensure_ascii=False))

    def test_wrong_verify_password_message_is_remapped(self):
        connection = _ConsoleAdminConnection(
            account_count=1, account=self.account, sample=self.sample
        )
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(
                run_admin_recover,
                {
                    "verify_username": "User",
                    "verify_password": "totally-wrong-password",
                    "new_password": "new-admin-password",
                },
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(reply["status"], "error")
        self.assertIn("驗證密碼錯誤", reply["message"])
        self.assertNotIn("新帳號", reply["message"])

    def test_missing_fields_rejected_without_touching_database(self):
        with patch("psycopg.connect") as connect:
            exit_code, reply = _run_with_stdin(
                run_admin_recover,
                {"verify_username": "", "verify_password": "", "new_password": ""},
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(reply["status"], "error")
        connect.assert_not_called()

    def test_short_new_password_rejected(self):
        with patch("psycopg.connect") as connect:
            exit_code, reply = _run_with_stdin(
                run_admin_recover,
                {
                    "verify_username": "User",
                    "verify_password": self.password,
                    "new_password": "short",
                },
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("10 個字元", reply["message"])
        connect.assert_not_called()


class AdminBootstrapSubcommandTests(unittest.TestCase):
    def test_creates_first_admin_when_database_is_empty(self):
        connection = _ConsoleAdminConnection(account_count=0)
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(
                run_admin_bootstrap, {"password": "brand-new-admin-password"}
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(reply["status"], "ok")
        self.assertTrue(connection.admin_inserted)
        self.assertTrue(connection.audit_logged)
        # wrapped_data_key 必須留白，沿用既有的「第一個帳號」初始化路徑，
        # 不能另外產生隨機金鑰再自我包裝。
        self.assertNotIn("wrapped_data_key", connection.insert_statement)
        self.assertNotIn("brand-new-admin-password", json.dumps(reply, ensure_ascii=False))

    def test_rejects_when_accounts_already_exist(self):
        connection = _ConsoleAdminConnection(account_count=1)
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(
                run_admin_bootstrap, {"password": "brand-new-admin-password"}
            )
        self.assertEqual(exit_code, 1)
        self.assertEqual(reply["status"], "error")
        self.assertFalse(connection.admin_inserted)

    def test_short_password_rejected_without_touching_database(self):
        with patch("psycopg.connect") as connect:
            exit_code, reply = _run_with_stdin(run_admin_bootstrap, {"password": "short"})
        self.assertEqual(exit_code, 1)
        self.assertIn("10 個字元", reply["message"])
        connect.assert_not_called()

    def test_invalid_stdin_json_is_reported_cleanly(self):
        stdout = io.StringIO()
        with patch("sys.stdin", io.StringIO("not-json")), redirect_stdout(stdout):
            exit_code = run_admin_bootstrap()
        reply = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(reply["status"], "error")


def _verify_account_fixture(password="verify-account-password"):
    data_key = Fernet.generate_key()
    salt, digest = hash_password(password)
    encryption_salt = os.urandom(16).hex()
    wrapped = make_fernet(
        derive_encryption_key(password, encryption_salt)
    ).encrypt(data_key).decode("ascii")
    account = {
        "username": "User", "role": "editor", "active": True, "password_salt": salt,
        "password_hash": digest, "encryption_salt": encryption_salt,
        "wrapped_data_key": wrapped,
    }
    token = make_fernet(data_key).encrypt("測試地主".encode("utf-8")).decode("ascii")
    return account, f"enc:v1:{token}", password


class AdminListSubcommandTests(unittest.TestCase):
    def test_lists_active_admins_and_total_account_count(self):
        connection = _ConsoleAdminConnection(account_count=4, admins=["admin", "chen.office"])
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(run_admin_list, {})
        self.assertEqual(exit_code, 0)
        self.assertEqual(reply["admins"], ["admin", "chen.office"])
        self.assertEqual(reply["account_count"], 4)

    def test_empty_database_reports_zero_accounts(self):
        connection = _ConsoleAdminConnection(account_count=0, admins=[])
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(run_admin_list, {})
        self.assertEqual(exit_code, 0)
        self.assertEqual(reply["admins"], [])
        self.assertEqual(reply["account_count"], 0)


class CustomAdminNameTests(unittest.TestCase):
    def test_bootstrap_uses_the_chosen_username_everywhere(self):
        connection = _ConsoleAdminConnection(account_count=0)
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(
                run_admin_bootstrap,
                {"username": "  chen.office ", "password": "brand-new-admin-password"},
            )
        self.assertEqual(exit_code, 0)
        self.assertEqual(reply["username"], "chen.office")
        self.assertEqual(connection.insert_parameters[0], "chen.office")
        self.assertTrue(connection.audit_logged)

    def test_bootstrap_rejects_bad_usernames_without_touching_database(self):
        with patch("psycopg.connect") as connect:
            for bad in ("   ", "x" * 101, "bad\nname"):
                exit_code, reply = _run_with_stdin(
                    run_admin_bootstrap, {"username": bad, "password": "brand-new-admin-password"}
                )
                self.assertEqual(exit_code, 1, bad)
                self.assertEqual(reply["status"], "error")
        connect.assert_not_called()

    def test_recover_can_target_another_existing_admin(self):
        account, sample, password = _verify_account_fixture()
        connection = _ConsoleAdminConnection(
            account_count=2, account=account, sample=sample, target_row=(7, "admin")
        )
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(
                run_admin_recover,
                {
                    "target_username": "chen.office", "verify_username": "User",
                    "verify_password": password, "new_password": "new-admin-password",
                },
            )
        self.assertEqual(exit_code, 0, reply)
        self.assertIn("chen.office", reply["message"])
        self.assertTrue(connection.updated)
        self.assertEqual(connection.update_parameters[-1], 7)

    def test_recover_refuses_a_target_that_is_not_an_admin(self):
        account, sample, password = _verify_account_fixture()
        connection = _ConsoleAdminConnection(
            account_count=2, account=account, sample=sample, target_row=(9, "viewer")
        )
        with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
             patch("psycopg.connect", return_value=connection):
            exit_code, reply = _run_with_stdin(
                run_admin_recover,
                {
                    "target_username": "some.viewer", "verify_username": "User",
                    "verify_password": password, "new_password": "new-admin-password",
                },
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("不是管理員", reply["message"])
        self.assertFalse(connection.updated)


class MigrationImportSubcommandTests(unittest.TestCase):
    @staticmethod
    def _package(directory):
        path = Path(directory) / "transfer.lcs-migration.zip"
        path.write_bytes(b"placeholder")
        return path

    def test_zero_accounts_takes_the_empty_server_path_without_server_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self._package(directory)
            with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
                 patch("server_console_admin._account_count", return_value=0), \
                 patch("customer_migration_package.import_migration_package_into_empty_server",
                       return_value={"result": {"ownerships": 5}, "pre_migration_backup": "b.zip"}) as empty, \
                 patch("customer_migration_package.import_migration_package") as normal:
                exit_code, reply = _run_with_stdin(
                    run_migration_import,
                    {"package": str(package), "source_username": "admin", "source_password": "x" * 12},
                )
        self.assertEqual(exit_code, 0, reply)
        self.assertEqual(reply["mode"], "empty_server")
        self.assertEqual(reply["ownerships"], 5)
        empty.assert_called_once()
        normal.assert_not_called()

    def test_existing_accounts_require_and_pass_server_admin_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self._package(directory)
            with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
                 patch("server_console_admin._account_count", return_value=3), \
                 patch("customer_migration_package.import_migration_package",
                       return_value={"result": {"ownerships": 2}, "pre_migration_backup": "b.zip"}) as normal:
                missing_exit, missing = _run_with_stdin(
                    run_migration_import,
                    {"package": str(package), "source_username": "User", "source_password": "p" * 12},
                )
                ok_exit, ok = _run_with_stdin(
                    run_migration_import,
                    {
                        "package": str(package), "source_username": "User", "source_password": "p" * 12,
                        "server_username": "chen.office", "server_password": "s" * 12,
                    },
                )
        self.assertEqual(missing_exit, 1)
        self.assertIn("伺服器管理員", missing["message"])
        self.assertEqual(ok_exit, 0, ok)
        self.assertEqual(ok["mode"], "normal")
        self.assertEqual(normal.call_args.kwargs["server_username"], "chen.office")

    def test_bad_package_is_rejected_before_any_database_access(self):
        with patch("server_console_admin.load_postgres_dsn") as dsn:
            exit_code, _reply = _run_with_stdin(
                run_migration_import,
                {"package": "C:/nope/missing.txt", "source_username": "a", "source_password": "b"},
            )
        self.assertEqual(exit_code, 1)
        dsn.assert_not_called()

    def test_reply_never_contains_the_passwords(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self._package(directory)
            with patch("server_console_admin.load_postgres_dsn", return_value="postgresql://protected"), \
                 patch("server_console_admin._account_count", return_value=0), \
                 patch("customer_migration_package.import_migration_package_into_empty_server",
                       side_effect=ValueError("單機版帳號或密碼錯誤，未匯入任何資料。")):
                _exit, reply = _run_with_stdin(
                    run_migration_import,
                    {"package": str(package), "source_username": "admin", "source_password": "SuperSecret123"},
                )
        self.assertNotIn("SuperSecret123", json.dumps(reply, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
