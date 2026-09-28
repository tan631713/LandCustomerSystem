import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cryptography.fernet import Fernet

from customer_security import derive_encryption_key, hash_password, make_fernet
from server_console_admin import run_admin_bootstrap, run_admin_recover


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row


class _ConsoleAdminConnection:
    def __init__(self, *, account_count, account=None, sample="", admin_exists=True):
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


if __name__ == "__main__":
    unittest.main()
