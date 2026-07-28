import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from customer_recovery_account import (
    create_recovery_package,
    import_recovery_account,
    load_recovery_package,
    prove_data_key_matches_server,
    recover_admin_password,
    unwrap_account_data_key,
    write_recovery_package,
)
from customer_security import derive_encryption_key, hash_password, make_fernet


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.row


class _SampleConnection:
    def __init__(self, sample):
        self.sample = sample

    def execute(self, _statement, _parameters):
        if self.sample:
            sample, self.sample = self.sample, ""
            return _Result((sample,))
        return _Result(None)


class _ImportConnection:
    def __init__(self, sample):
        self.sample = sample
        self.insert_parameters = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=()):
        normalized = " ".join(statement.split())
        if "FROM owners" in normalized and "LIKE" in normalized:
            return _Result((self.sample,))
        if "FROM users WHERE lower(username)" in normalized:
            return _Result([])
        if normalized.startswith("INSERT INTO users"):
            self.insert_parameters = parameters
        return _Result(None)


class _AdminRecoveryConnection:
    def __init__(self, sample, account, *, admin_exists=True):
        self.sample = sample
        self.account = account
        self.admin_exists = admin_exists
        self.updated = False
        self.admin_inserted = False
        self.audit_logged = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, statement, parameters=()):
        normalized = " ".join(statement.split())
        if "FROM users WHERE lower(username) = lower(%s)" in normalized:
            return _Result(
                [
                    (
                        2,
                        self.account["username"],
                        self.account["role"],
                        self.account["active"],
                        self.account["password_salt"],
                        self.account["password_hash"],
                        self.account["encryption_salt"],
                        self.account["wrapped_data_key"],
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
        return _Result(None)


class RecoveryAccountTests(unittest.TestCase):
    password = "new-secure-password"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "customers.db"
        self.data_key = Fernet.generate_key()
        password_salt, password_hash = hash_password(self.password)
        encryption_salt = os.urandom(16).hex()
        wrapped = make_fernet(
            derive_encryption_key(self.password, encryption_salt)
        ).encrypt(self.data_key).decode("ascii")
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                """
                CREATE TABLE users (
                    username TEXT, display_name TEXT, role TEXT, active INTEGER,
                    password_salt TEXT, password_hash TEXT, encryption_salt TEXT,
                    wrapped_data_key TEXT, created_at TEXT
                )
                """
            )
            connection.execute(
                "INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "User",
                    "日常使用者",
                    "editor",
                    1,
                    password_salt,
                    password_hash,
                    encryption_salt,
                    wrapped,
                    "2026-07-17T00:00:00+00:00",
                ),
            )
            connection.commit()

    def tearDown(self):
        self.temporary.cleanup()

    def test_export_contains_wrapped_credentials_but_no_plaintext_secret(self):
        package = create_recovery_package(self.database, "user")
        encoded = json.dumps(package, ensure_ascii=False)

        self.assertEqual(package["account"]["username"], "User")
        self.assertNotIn(self.password, encoded)
        self.assertNotIn(self.data_key.decode("ascii"), encoded)
        self.assertEqual(
            unwrap_account_data_key(package["account"], self.password),
            self.data_key,
        )

    def test_written_package_detects_tampering(self):
        output = self.root / "User.lcs-account"
        write_recovery_package(self.database, "User", output)
        package = json.loads(output.read_text(encoding="utf-8"))
        package["account"]["role"] = "admin"
        output.write_text(json.dumps(package), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "校驗失敗"):
            load_recovery_package(output)

    def test_wrong_password_is_rejected_before_import(self):
        account = create_recovery_package(self.database, "User")["account"]

        with self.assertRaisesRegex(ValueError, "密碼不正確"):
            unwrap_account_data_key(account, "incorrect-password")

    def test_data_key_must_decrypt_existing_server_sample(self):
        token = make_fernet(self.data_key).encrypt("測試地主".encode("utf-8")).decode("ascii")
        connection = _SampleConnection(f"enc:v1:{token}")

        self.assertTrue(prove_data_key_matches_server(connection, self.data_key))
        with self.assertRaisesRegex(ValueError, "資料金鑰與家中伺服器不相符"):
            prove_data_key_matches_server(
                _SampleConnection(f"enc:v1:{token}"), Fernet.generate_key()
            )

    def test_import_adds_only_the_verified_account(self):
        output = self.root / "User.lcs-account"
        write_recovery_package(self.database, "User", output)
        token = make_fernet(self.data_key).encrypt("測試地主".encode("utf-8")).decode("ascii")
        connection = _ImportConnection(f"enc:v1:{token}")

        with patch("psycopg.connect", return_value=connection) as connect:
            result = import_recovery_account(
                output, self.password, "postgresql://protected"
            )

        self.assertEqual(result["status"], "imported")
        self.assertEqual(result["username"], "User")
        self.assertTrue(result["data_key_verified"])
        self.assertIsNotNone(connection.insert_parameters)
        self.assertEqual(connection.insert_parameters[0], "User")
        connect.assert_called_once_with("postgresql://protected", connect_timeout=5)

    def test_offline_admin_recovery_requires_valid_account_and_preserves_data_key(self):
        account = create_recovery_package(self.database, "User")["account"]
        token = make_fernet(self.data_key).encrypt("測試地主".encode("utf-8")).decode("ascii")
        connection = _AdminRecoveryConnection(f"enc:v1:{token}", account)

        with patch("psycopg.connect", return_value=connection):
            result = recover_admin_password(
                "postgresql://protected",
                "User",
                self.password,
                "new-admin-password",
            )

        self.assertEqual(result["status"], "admin_password_reset")
        self.assertEqual(result["verified_by"], "User")
        self.assertTrue(result["data_key_verified"])
        self.assertTrue(connection.updated)
        self.assertTrue(connection.audit_logged)

    def test_offline_admin_recovery_creates_missing_admin_account(self):
        account = create_recovery_package(self.database, "User")["account"]
        token = make_fernet(self.data_key).encrypt("測試地主".encode("utf-8")).decode("ascii")
        connection = _AdminRecoveryConnection(
            f"enc:v1:{token}", account, admin_exists=False
        )

        with patch("psycopg.connect", return_value=connection):
            result = recover_admin_password(
                "postgresql://protected",
                "User",
                self.password,
                "new-admin-password",
            )

        self.assertEqual(result["status"], "admin_account_created")
        self.assertFalse(connection.updated)
        self.assertTrue(connection.admin_inserted)
        self.assertTrue(connection.audit_logged)

    def test_offline_admin_recovery_wrong_password_never_updates_admin(self):
        account = create_recovery_package(self.database, "User")["account"]
        token = make_fernet(self.data_key).encrypt("測試地主".encode("utf-8")).decode("ascii")
        connection = _AdminRecoveryConnection(f"enc:v1:{token}", account)

        with (
            patch("psycopg.connect", return_value=connection),
            self.assertRaisesRegex(ValueError, "密碼不正確"),
        ):
            recover_admin_password(
                "postgresql://protected",
                "User",
                "wrong-password",
                "new-admin-password",
            )

        self.assertFalse(connection.updated)
        self.assertFalse(connection.audit_logged)


if __name__ == "__main__":
    unittest.main()
