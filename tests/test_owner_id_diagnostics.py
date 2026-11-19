"""地主身分證撞號診斷：統計正確、只讀不寫、只輸出數字。"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from cryptography.fernet import Fernet

from customer_owner_id_diagnostics import (
    DiagnosticError,
    ReadOnlyConnection,
    collect_statistics,
    format_report,
    run_diagnostics,
)
from customer_security import (
    derive_encryption_key,
    encrypt_value,
    hash_password,
    make_fernet,
)

PASSWORD = "admin-password"


class _Result:
    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeDatabase:
    """Plays the three tables the diagnostic reads; records every statement."""

    def __init__(self, role="admin", read_only_answer="on"):
        self.data_key = Fernet.generate_key()
        fernet = make_fernet(self.data_key)
        password_salt, password_hash = hash_password(PASSWORD)
        encryption_salt = os.urandom(16).hex()
        wrapped = make_fernet(derive_encryption_key(PASSWORD, encryption_salt)).encrypt(
            self.data_key
        )
        self.users = [
            {
                "id": 1, "username": "admin", "role": role, "active": True,
                "password_salt": password_salt, "password_hash": password_hash,
                "encryption_salt": encryption_salt,
                "wrapped_data_key": wrapped.decode("ascii"),
            }
        ]

        def enc(value):
            return encrypt_value(fernet, value) if value else None

        # owner 1: H2211 shared by 邱小姐 and 陳先生 (merged by owner_key)
        # owner 2: full ID, one name; owner 3: blank ID; owner 4: odd length
        # owner 5: H221345671 -> key H2211, another person (林先生)
        self.owners = [
            {"id": 1, "owner_name": enc("邱小姐"), "external_id": enc("H2211")},
            {"id": 2, "owner_name": enc("王大明"), "external_id": enc("A123456789")},
            {"id": 3, "owner_name": enc("張三"), "external_id": None},
            {"id": 4, "owner_name": enc("李四"), "external_id": enc("B12")},
            {"id": 5, "owner_name": enc("林先生"), "external_id": enc("H221345671")},
        ]
        self.ownerships = [
            {"id": 11, "owner_id": 1, "owner_name_override": enc("邱小姐"), "external_id_override": enc("H2211")},
            {"id": 12, "owner_id": 1, "owner_name_override": enc("陳先生"), "external_id_override": enc("H2211")},
            {"id": 13, "owner_id": 1, "owner_name_override": enc("邱 小姐"), "external_id_override": None},
            {"id": 21, "owner_id": 2, "owner_name_override": None, "external_id_override": None},
            {"id": 22, "owner_id": 2, "owner_name_override": enc("王大明"), "external_id_override": None},
            {"id": 31, "owner_id": 3, "owner_name_override": None, "external_id_override": None},
            {"id": 51, "owner_id": 5, "owner_name_override": None, "external_id_override": None},
        ]
        self.read_only = False
        self.read_only_answer = read_only_answer
        self.statements = []
        self.rolled_back = False
        self.closed = False

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.statements.append(text)
        if text == "SHOW transaction_read_only":
            answer = self.read_only_answer if self.read_only else "off"
            return _Result([{"transaction_read_only": answer}])
        if text.startswith("SELECT id, username, role"):
            return _Result([u for u in self.users if u["username"] == params[0]])
        if text == "SELECT id, owner_name, external_id FROM owners":
            return _Result(self.owners)
        if text.startswith("SELECT id, owner_id, owner_name_override"):
            return _Result(self.ownerships)
        raise AssertionError(f"unexpected SQL: {text}")

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


class OwnerIdDiagnosticsTests(unittest.TestCase):
    def run_report(self, db, password=PASSWORD):
        with tempfile.TemporaryDirectory() as folder:
            path, stats = run_diagnostics(
                "postgresql://fake", "admin", password,
                output_dir=folder, connect=lambda _dsn: db, version="1.9.47",
            )
            text = path.read_text(encoding="utf-8-sig")
            self.assertTrue(path.name.startswith("owner-id-diagnostics-"))
        return stats, text

    def test_statistics_are_counted_correctly(self):
        db = FakeDatabase()
        stats, _text = self.run_report(db)
        self.assertEqual(stats["owner_total"], 5)
        self.assertEqual(stats["owners_with_land"], 4)
        self.assertEqual(stats["ownership_total"], 7)
        self.assertEqual(
            stats["identity_lengths"], {"blank": 1, "five": 1, "ten": 2, "other": 1}
        )
        # Owner 1 carries 邱小姐 and 陳先生 (邱 小姐 is the same after normalizing).
        self.assertEqual(stats["owners_with_several_names"], 1)
        self.assertEqual(stats["ownerships_of_those_owners"], 3)
        # Key H2211: 邱小姐, 陳先生 (owner 1) and 林先生 (owner 5).
        self.assertEqual(stats["five_key_groups_with_several_names"], 1)
        self.assertEqual(stats["ownerships_in_those_groups"], 4)
        self.assertEqual(stats["decryption_failures"], 0)

    def test_only_reads_and_leaves_the_transaction_rolled_back(self):
        db = FakeDatabase()
        self.run_report(db)
        self.assertTrue(db.read_only)
        self.assertTrue(db.statements)
        for statement in db.statements:
            self.assertRegex(statement, r"^(SELECT|SHOW)\b")
        self.assertTrue(db.rolled_back)
        self.assertTrue(db.closed)

    def test_write_statements_are_refused_before_reaching_the_database(self):
        db = FakeDatabase()
        guarded = ReadOnlyConnection(db)
        for statement in (
            "UPDATE users SET last_login_at = now()",
            "INSERT INTO owners VALUES (1)",
            "DELETE FROM owners",
            "  update owners set owner_key = ''",
        ):
            with self.subTest(statement=statement):
                with self.assertRaises(DiagnosticError):
                    guarded.execute(statement)
        self.assertEqual(db.statements, [])

    def test_every_query_of_the_tool_is_a_select(self):
        import customer_owner_id_diagnostics as tool

        for query in (tool.USER_QUERY, tool.OWNER_QUERY, tool.OWNERSHIP_QUERY):
            self.assertTrue(query.strip().upper().startswith("SELECT"))
            for keyword in ("INSERT", "UPDATE", "DELETE", "ALTER", "DROP", "TRUNCATE"):
                self.assertNotIn(keyword, query.upper())

    def test_report_has_numbers_but_no_names_or_identity_numbers(self):
        _stats, text = self.run_report(FakeDatabase())
        for secret in ("邱", "陳先生", "林先生", "王大明", "H2211", "A123456789", "H221345671"):
            self.assertNotIn(secret, text)
        self.assertIn("5 碼：1", text)
        self.assertIn("疑似被錯誤合併）：1", text)

    def test_needs_an_admin_and_the_right_password(self):
        with self.assertRaises(DiagnosticError):
            self.run_report(FakeDatabase(), password="wrong")
        with self.assertRaises(DiagnosticError):
            self.run_report(FakeDatabase(role="editor"))

    def test_stops_when_the_session_is_not_read_only(self):
        db = FakeDatabase(read_only_answer="off")
        with self.assertRaises(DiagnosticError):
            self.run_report(db)
        self.assertFalse(any(s.startswith("SELECT id, owner_name") for s in db.statements))

    def test_launcher_flag(self):
        import start_api_server

        args = start_api_server.build_parser().parse_args(
            ["--diagnose-owner-ids", "--report-dir", "x"]
        )
        self.assertTrue(args.diagnose_owner_ids)
        db = FakeDatabase()
        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(report_dir=folder)
            from unittest.mock import patch

            import customer_owner_id_diagnostics as tool

            def fake_run(dsn, username, password, **kwargs):
                return run_diagnostics(
                    dsn, username, password, connect=lambda _dsn: db, **kwargs
                )

            with patch.object(tool, "run_diagnostics", fake_run), patch(
                "builtins.print"
            ):
                code = start_api_server.run_owner_id_diagnostics(
                    args,
                    load_dsn=lambda: "postgresql://fake",
                    ask=lambda _prompt: "",
                    ask_secret=lambda _prompt: PASSWORD,
                )
            self.assertEqual(code, 0)
            self.assertEqual(len(list(Path(folder).glob("owner-id-diagnostics-*.txt"))), 1)

    def test_format_report_mentions_read_only(self):
        stats = {
            "owner_total": 0, "owners_with_land": 0, "ownership_total": 0,
            "decryption_failures": 0,
            "identity_lengths": {"blank": 0, "five": 0, "ten": 0, "other": 0},
            "owners_with_several_names": 0, "ownerships_of_those_owners": 0,
            "five_key_groups_with_several_names": 0, "ownerships_in_those_groups": 0,
        }
        self.assertIn("唯讀", format_report(stats))


if __name__ == "__main__":
    unittest.main()
