"""手動新增資料時判斷同一地主：比對規則、伺服器端 API、桌面流程。"""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryptography.fernet import Fernet

from customer_api.postgres_owner_match import OwnerAttachError, PostgreSQLOwnerMatchMixin
from customer_api.postgres_records import PostgreSQLRecordMixin
from customer_api.schemas import RecordWrite
from customer_api.types import AuthenticatedUser
from customer_owner_match import (
    HIGH_MATCH_SCORE,
    addresses_similar,
    candidate_response_item,
    chinese_number_to_int,
    mask_phone,
    normalize_owner_address,
    rank_owner_candidates,
    score_owner_candidate,
)
from customer_postgres_keys import owner_key_for
from customer_security import decrypt_value, encrypt_value, make_fernet


def owner(owner_id, name, external_id="", address="", phones=(), land_count=1):
    return {
        "owner_id": owner_id,
        "owner_name": name,
        "external_id": external_id,
        "address": address,
        "phones": list(phones),
        "land_count": land_count,
        "sample_record_id": owner_id * 10,
    }


class AddressNormalizationTests(unittest.TestCase):
    def test_same_address_written_differently_normalizes_the_same(self):
        variants = [
            "臺北市中正區忠孝東路三段１２號之１　５Ｆ",
            "台北市中正區忠孝東路3段12-1號5樓",
            "台北市 中正區 忠孝東路 3 段 12 之 1 號 5 樓",
            "100台北市中正區忠孝東路參段12號之1 5f",
        ]
        normalized = {normalize_owner_address(value) for value in variants}
        self.assertEqual(normalized, {"台北市中正區忠孝東路3段12-1號5樓"})

    def test_chinese_numbers(self):
        self.assertEqual(chinese_number_to_int("三"), 3)
        self.assertEqual(chinese_number_to_int("十二"), 12)
        self.assertEqual(chinese_number_to_int("二十三"), 23)
        self.assertEqual(chinese_number_to_int("一百零五"), 105)
        self.assertEqual(chinese_number_to_int("一○五"), 105)
        self.assertIsNone(chinese_number_to_int("中正"))

    def test_road_names_with_numerals_are_left_alone(self):
        self.assertEqual(normalize_owner_address("高雄市九如二路"), "高雄市九如二路")

    def test_missing_city_prefix_counts_as_similar(self):
        self.assertTrue(
            addresses_similar("桃園市中壢區中正路23巷5號", "中壢區中正路二十三巷5號")
        )
        self.assertFalse(addresses_similar("桃園市中壢區中正路23巷5號", "新竹市東區光復路1號"))

    def test_phone_mask_keeps_only_the_ends(self):
        self.assertEqual(mask_phone("0912-345-678"), "09*****678")


class CandidateScoringTests(unittest.TestCase):
    def test_same_name_different_people(self):
        owners = [
            owner(1, "王大明", "A123456789", "桃園市中壢區中正路1號"),
            owner(2, "王大明", "B223456780", "新竹市東區光復路2號"),
        ]
        ranked = rank_owner_candidates(
            {"owner_name": "王大明", "external_id": "A123456789"}, owners
        )
        self.assertEqual([item["owner_id"] for item in ranked], [1])
        self.assertEqual(ranked[0]["score"], 100)
        # A different complete ID under the same name is another person.
        ranked = rank_owner_candidates(
            {"owner_name": "王大明", "external_id": "C123456789"}, owners
        )
        self.assertEqual(ranked, [])
        # Name only: both offered, neither is a high match.
        ranked = rank_owner_candidates({"owner_name": "王大明"}, owners)
        self.assertEqual({item["owner_id"] for item in ranked}, {1, 2})
        self.assertTrue(all(item["score"] < HIGH_MATCH_SCORE for item in ranked))

    def test_same_person_with_differently_written_address(self):
        owners = [owner(7, "林美麗", "", "臺北市中正區忠孝東路三段12號之1五樓", land_count=3)]
        score, reasons = score_owner_candidate(
            {"owner_name": "林美麗", "address": "台北市中正區忠孝東路3段12-1號5F"},
            owners[0],
        )
        self.assertGreaterEqual(score, HIGH_MATCH_SCORE)
        self.assertIn("地址相同（寫法不同）", reasons)

    def test_name_only(self):
        score, reasons = score_owner_candidate({"owner_name": "陳一"}, owner(3, "陳 一"))
        self.assertEqual(score, 20)
        self.assertEqual(reasons, ["姓名相同"])
        self.assertIsNone(score_owner_candidate({"owner_name": "陳二"}, owner(3, "陳一")))

    def test_ranking_order_identity_partial_phone_address(self):
        owners = [
            owner(1, "張三", "", "桃園市中壢區中正路1號"),
            owner(2, "張三", "", "", phones=["0912345678"]),
            owner(3, "張三", "H123456789"),
            owner(4, "張三", "H123456789".replace("H1", "Z9")),
        ]
        ranked = rank_owner_candidates(
            {
                "owner_name": "張三",
                "external_id": "H12****789",
                "address": "桃園市中壢區中正路一號",
                "phone": "0912-345-678",
            },
            owners,
        )
        self.assertEqual([item["owner_id"] for item in ranked[:3]], [3, 2, 1])
        self.assertIn("身分證前3碼與後3碼相同", ranked[0]["reasons"])

    def test_partial_stored_identity_from_transcript(self):
        score, reasons = score_owner_candidate(
            {"owner_name": "李四", "external_id": "S221912345"}, owner(5, "李四", "S2219")
        )
        self.assertEqual(score, 75)
        self.assertIn("身分證前段相符", reasons)

    def test_rejected_owners_are_left_out_and_response_is_masked(self):
        owners = [owner(1, "王五", "A123456789", phones=["0912345678"])]
        self.assertEqual(
            rank_owner_candidates({"owner_name": "王五"}, owners, ignored_owner_ids={1}),
            [],
        )
        item = candidate_response_item(rank_owner_candidates({"owner_name": "王五"}, owners)[0])
        self.assertEqual(item["external_id_masked"], "A123*****9")
        self.assertEqual(item["phones_masked"], ["09*****678"])
        self.assertNotIn("external_id", item)
        self.assertNotIn("A123456789", repr(item))


class _Result:
    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class FakeOwnerConnection:
    """Answers just the statements the owner-match and save paths run."""

    def __init__(self, fernet, data_key):
        self.fernet = fernet
        self.data_key = data_key
        self.owners = {}
        self.ownerships = {}
        self.reviews = []
        self.statements = []

    def add_owner(self, owner_id, name, external_id="", address="", key_values=None):
        self.owners[owner_id] = {
            "id": owner_id,
            "owner_key": owner_key_for(
                key_values
                or {"owner_name": name, "external_id": external_id, "address": address},
                self.data_key,
            ),
            "owner_name": encrypt_value(self.fernet, name),
            "external_id": encrypt_value(self.fernet, external_id) or None,
            "address": encrypt_value(self.fernet, address) or None,
            "phone": None,
            "birth_year": None,
        }

    def add_ownership(self, ownership_id, owner_id):
        self.ownerships[ownership_id] = {"id": ownership_id, "owner_id": owner_id}

    def execute(self, sql, params=()):
        text = " ".join(str(sql).split())
        self.statements.append((text, params))
        if text.startswith("SELECT owner.id AS owner_id"):
            rows = []
            for owner_id, row in self.owners.items():
                owned = [o for o in self.ownerships.values() if o["owner_id"] == owner_id]
                if owned:
                    rows.append(
                        {
                            **row,
                            "owner_id": owner_id,
                            "land_count": len(owned),
                            "sample_record_id": min(o["id"] for o in owned),
                        }
                    )
            return _Result(rows)
        if "FROM owner_contact_relations" in text:
            return _Result([])
        if text.startswith("SELECT ownership.owner_id, land.district"):
            return _Result([])
        if "FROM duplicate_reviews review JOIN ownerships left_ownership" in text:
            owner_id = params[0]
            found = []
            for left, right in self.reviews:
                left_owner = self.ownerships[left]["owner_id"]
                right_owner = self.ownerships[right]["owner_id"]
                if owner_id in (left_owner, right_owner):
                    found.append(
                        {"other_owner_id": right_owner if left_owner == owner_id else left_owner}
                    )
            return _Result(found)
        if "FROM duplicate_reviews review JOIN ownerships other" in text:
            ids = set(params[0])
            found = []
            for left, right in self.reviews:
                if left in ids:
                    found.append({"owner_id": self.ownerships[right]["owner_id"]})
                elif right in ids:
                    found.append({"owner_id": self.ownerships[left]["owner_id"]})
            return _Result(found)
        if text.startswith("SELECT id, owner_name, external_id, address, birth_year FROM owners"):
            row = self.owners.get(int(params[0]))
            return _Result([row] if row else [])
        if text.startswith("INSERT INTO owners ("):
            new_id = max(self.owners or {0: None}) + 1
            self.owners[new_id] = {"id": new_id, "owner_key": params[0]}
            return _Result([{"id": new_id}])
        if text.startswith("SELECT id FROM lands"):
            return _Result([])
        if text.startswith("INSERT INTO lands"):
            return _Result([{"id": 500}])
        if text.startswith("INSERT INTO ownerships"):
            new_id = max(self.ownerships or {0: None}) + 1
            self.ownerships[new_id] = {"id": new_id, "owner_id": params[0], "params": params}
            return _Result([{"id": new_id}])
        if text.startswith("INSERT INTO audit_logs"):
            return _Result([])
        raise AssertionError(f"unexpected SQL: {text}")


class _Source(PostgreSQLRecordMixin, PostgreSQLOwnerMatchMixin):
    def __init__(self, conn):
        self.conn = conn

    def _connect(self):
        conn = self.conn

        class _Context:
            def __enter__(self):
                return conn

            def __exit__(self, *_exc):
                return False

        return _Context()


class PostgreSQLOwnerMatchTests(unittest.TestCase):
    def setUp(self):
        self.data_key = Fernet.generate_key()
        self.fernet = make_fernet(self.data_key)
        self.user = AuthenticatedUser(1, "admin", "管理者", "admin", self.data_key)
        self.conn = FakeOwnerConnection(self.fernet, self.data_key)
        self.conn.add_owner(1, "王大明", "A123456789", "桃園市中壢區中正路三段12號")
        self.conn.add_ownership(11, 1)
        self.conn.add_ownership(12, 1)
        self.conn.add_owner(2, "王大明", "", "新竹市東區光復路2號")
        self.conn.add_ownership(21, 2)
        self.source = _Source(self.conn)

    def new_values(self, **overrides):
        values = RecordWrite(
            district="中壢區", section="中正段", land_number="100",
            owner_name="王大明", **overrides,
        ).normalized_values()
        return values

    def test_candidates_are_ranked_masked_and_encrypted_fields_stay_server_side(self):
        result = self.source.owner_candidates(
            self.user,
            {"owner_name": "王大明", "address": "桃園市中壢區中正路3段12號"},
        )
        items = result["items"]
        self.assertEqual([item["owner_id"] for item in items], [1, 2])
        self.assertTrue(items[0]["high_match"])
        self.assertEqual(items[0]["land_count"], 2)
        self.assertEqual(items[0]["sample_record_id"], 11)
        self.assertEqual(items[0]["external_id_masked"], "A123*****9")
        self.assertNotIn("A123456789", repr(result))
        self.assertIsNone(result["exact_owner_id"])

    def test_exact_owner_key_is_reported(self):
        result = self.source.owner_candidates(
            self.user, {"owner_name": "王大明", "address": "新竹市東區光復路2號"}
        )
        self.assertEqual(result["exact_owner_id"], 2)

    def test_rejected_pair_is_not_suggested_again(self):
        # 「都不是」 recorded between the new owner 2's land and owner 1's land.
        self.conn.reviews.append((11, 21))
        result = self.source.owner_candidates(
            self.user, {"owner_name": "王大明", "address": "新竹市東區光復路2號"}
        )
        self.assertEqual([item["owner_id"] for item in result["items"]], [2])
        # Same while the new record is not saved yet (desktop passes its ids).
        result = self.source.owner_candidates(
            self.user, {"owner_name": "王大明"}, rejected_record_ids=[21]
        )
        self.assertNotIn(1, [item["owner_id"] for item in result["items"]])

    def test_choosing_an_existing_owner_does_not_create_a_new_one(self):
        owners_before = dict(self.conn.owners)
        values = self.new_values(external_id="A123*****9", owner_id=1)
        record_id = self.source._save_record_with_conn(self.conn, self.user, values)
        self.assertEqual(self.conn.ownerships[record_id]["owner_id"], 1)
        self.assertEqual(self.conn.owners, owners_before)
        self.assertFalse(
            any(text.startswith("INSERT INTO owners (") for text, _ in self.conn.statements)
        )
        params = self.conn.ownerships[record_id]["params"]
        # owner_name_override, external_id_override, address_override
        self.assertEqual(decrypt_value(self.fernet, params[12]), "A123456789")
        self.assertEqual(
            decrypt_value(self.fernet, params[13]), "桃園市中壢區中正路三段12號"
        )

    def test_a_different_complete_identity_is_refused(self):
        values = self.new_values(external_id="B223456780", owner_id=1)
        with self.assertRaises(OwnerAttachError):
            self.source._save_record_with_conn(self.conn, self.user, values)

    def test_without_a_choice_the_old_owner_key_rule_still_applies(self):
        values = self.new_values(address="台北市某路1號")
        record_id = self.source._save_record_with_conn(self.conn, self.user, values)
        self.assertNotIn(self.conn.ownerships[record_id]["owner_id"], (1, 2))

    def test_editing_ignores_owner_id(self):
        self.conn.ownerships[30] = {"id": 30, "owner_id": 2}
        values = self.new_values(owner_id=1)
        with patch.object(
            _Source, "_save_owner_and_land", return_value=(2, 500, {})
        ) as save_owner, patch.object(
            _Source, "_record_address_before_update", return_value=""
        ), patch.object(_Source, "_synchronize_location_address"):
            calls = []
            original = self.conn.execute

            def execute(sql, params=()):
                text = " ".join(str(sql).split())
                if text.startswith("SELECT 1 FROM ownerships") or text.startswith("UPDATE ownerships"):
                    calls.append(text)
                    return _Result([{"?column?": 1}])
                return original(sql, params)

            self.conn.execute = execute
            self.source._save_record_with_conn(self.conn, self.user, values, record_id=30)
        save_owner.assert_called_once()
        self.assertNotIn("owner_id", save_owner.call_args.args[2])


class RouteTests(unittest.TestCase):
    def test_owner_id_is_optional_and_positive(self):
        self.assertIsNone(
            RecordWrite(district="a", section="b", land_number="1").normalized_values()["owner_id"]
        )
        self.assertEqual(
            RecordWrite(district="a", section="b", land_number="1", owner_id="5").owner_id, 5
        )
        with self.assertRaises(ValueError):
            RecordWrite(district="a", section="b", land_number="1", owner_id=0)

    def test_sqlite_source_reports_unsupported_and_refuses_owner_id(self):
        from fastapi.testclient import TestClient

        from customer_api.app import create_app
        from customer_api.config import ApiSettings
        from customer_api.sqlite_source import SQLiteCustomerDataSource

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_root = Path(__file__).resolve().parents[1]
            settings = ApiSettings(
                backend="sqlite",
                sqlite_database_path=root / "customers.db",
                backup_directory=root / "backups",
                attachment_directory=root / "attachments",
                schema_path=project_root / "schema.sql",
                seed_path=root / "missing-seed.sql",
                session_ttl_seconds=3600,
                max_page_size=100,
            )
            source = SQLiteCustomerDataSource(settings)
            source.repository.create_admin_user("admin-password")
            with TestClient(create_app(settings=settings, data_source=source)) as client:
                token = client.post(
                    "/api/v1/auth/login",
                    json={"username": "admin", "password": "admin-password"},
                ).json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}
                response = client.get(
                    "/api/v1/owner-candidates",
                    params={"owner_name": "王大明", "rejected_record_id": [1, 2]},
                    headers=headers,
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["supported"], False)
                response = client.post(
                    "/api/v1/records",
                    json={"district": "a", "section": "b", "land_number": "1",
                          "owner_name": "王", "owner_id": 1},
                    headers=headers,
                )
                self.assertEqual(response.status_code, 409, response.text)


# --- desktop -----------------------------------------------------------------

from PySide6.QtWidgets import QApplication  # noqa: E402

import customer_ui_qt as app  # noqa: E402
from customer_database import CustomerDatabase  # noqa: E402
from customer_desktop_api import DesktopApiRecordRepository  # noqa: E402
from customer_repository import CustomerRepository  # noqa: E402

from tests.test_desktop_save_latency import FakeHomeServer  # noqa: E402


class OwnerMatchHomeServer(FakeHomeServer):
    def __init__(self, count, candidates):
        super().__init__(count)
        self.candidates = candidates
        self.candidate_queries = []
        self.created_values = []
        self.reviews = []

    def owner_candidates(self, query, *, rejected_record_ids=(), limit=10):
        self._hit("owner_candidates")
        self.candidate_queries.append((dict(query), list(rejected_record_ids)))
        return {"supported": True, "exact_owner_id": None, "items": list(self.candidates)}

    def create_record(self, values):
        self.created_values.append(dict(values))
        return super().create_record(values)

    def ignore_duplicate_pair(self, left_id, right_id):
        self.reviews.append((int(left_id), int(right_id)))
        return True


CANDIDATE = {
    "owner_id": 3,
    "owner_name": "王大明3",
    "external_id_masked": "A100****3",
    "has_external_id": True,
    "address": "桃園市中壢區某路 123 號",
    "phones_masked": [],
    "land_count": 1,
    "sample_record_id": 3,
    "lands": ["中壢區段1 0001-0000"],
    "score": 60,
    "reasons": ["姓名相同", "地址相同（寫法不同）"],
    "same_owner_key": False,
    "high_match": True,
}


class DesktopOwnerMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_context.name)
        self.originals = {
            name: getattr(app, name)
            for name in ("DB_PATH", "BACKUP_DIR", "DATABASE", "REPOSITORY")
        }
        app.DB_PATH = self.root / "customers.db"
        app.BACKUP_DIR = self.root / "backups"
        app.DATABASE = CustomerDatabase(app.DB_PATH, app.BACKUP_DIR)
        app.REPOSITORY = CustomerRepository(
            app.DATABASE, app.SCHEMA_PATH, self.root / "missing-seed.sql", app.LAND_FIELDS
        )
        app.init_db()
        app.REPOSITORY.create_admin_user("test-password")
        self.key = app.REPOSITORY.authenticate_user("admin", "test-password")
        self.server = OwnerMatchHomeServer(6, [CANDIDATE])
        repository = DesktopApiRecordRepository(self.server, make_fernet(self.key))
        self.window = app.LandApp(self.key, record_repository=repository, api_mode=True)
        self.window.owner_match_run_inline = True
        self.window.wait_for_background_tasks()
        self.application.processEvents()

    def tearDown(self):
        self.window.wait_for_background_tasks()
        self.window.close()
        self.application.processEvents()
        for name, value in self.originals.items():
            setattr(app, name, value)
        self.temp_context.cleanup()

    def type_new_owner(self, name="王大明3"):
        window = self.window
        window.new_record()
        for key, value in {
            "district": "中壢區", "section": "新段", "land_number": "77-0",
            "owner_name": name, "address": "桃園市中壢區某路123號",
        }.items():
            window.set_field_text(key, value)
        window.field_widgets["owner_name"].editingFinished.emit()

    def save(self):
        with patch.object(app, "QMessageBox") as message_box:
            message_box.Yes = 1
            self.window.save_record()
        self.window.wait_for_background_tasks()
        self.application.processEvents()

    def test_name_focus_out_shows_candidates(self):
        self.type_new_owner()
        panel = self.window.owner_match_panel
        self.assertFalse(panel.isHidden())
        self.assertEqual(panel.table.rowCount(), 1)
        self.assertTrue(panel.table.cellWidget(0, 0).text().startswith("王大明3"))
        self.assertEqual(self.server.candidate_queries[0][0]["owner_name"], "王大明3")

    def test_choosing_an_owner_sends_owner_id_and_no_prompt(self):
        self.type_new_owner()
        self.window.owner_match_panel.choose_button.click()
        self.assertEqual(self.window.get_field_text("external_id"), "A100****3")
        with patch.object(self.window, "ask_owner_match_decision") as ask:
            self.save()
        ask.assert_not_called()
        self.assertEqual(self.server.created_values[-1]["owner_id"], 3)
        self.assertEqual(self.server.reviews, [])
        self.assertTrue(self.window.owner_match_panel.isHidden())

    def test_declining_saves_a_new_owner_and_records_the_review(self):
        self.type_new_owner()
        self.window.owner_match_panel.new_owner_button.click()
        self.assertTrue(self.window.owner_match_panel.isHidden())
        with patch.object(self.window, "ask_owner_match_decision") as ask:
            self.save()
        ask.assert_not_called()
        self.assertNotIn("owner_id", self.server.created_values[-1])
        new_id = self.window.selected_record_id
        self.assertEqual(self.server.reviews, [(new_id, 3)])

    def test_save_prompt_when_a_high_match_was_not_answered(self):
        self.window.new_record()
        for key, value in {"district": "中壢區", "section": "新段", "land_number": "77-0",
                           "owner_name": "王大明3"}.items():
            self.window.set_field_text(key, value)
        with patch.object(self.window, "ask_owner_match_decision", return_value="back"):
            self.save()
        self.assertEqual(self.server.created_values, [])
        self.assertFalse(self.window.owner_match_panel.isHidden())
        with patch.object(self.window, "ask_owner_match_decision", return_value="new"):
            self.save()
        self.assertEqual(len(self.server.created_values), 1)
        self.assertEqual(self.server.reviews, [(self.window.selected_record_id, 3)])

    def test_editing_an_existing_record_never_asks(self):
        self.window.load_record(2)
        self.window.wait_for_background_tasks()
        self.application.processEvents()
        self.window.set_field_text("owner_name", "王大明3")
        self.window.field_widgets["owner_name"].editingFinished.emit()
        with patch.object(self.window, "ask_owner_match_decision") as ask:
            self.save()
        ask.assert_not_called()
        self.assertEqual(self.server.candidate_queries, [])
        self.assertTrue(self.window.owner_match_panel.isHidden())


class DesktopApiClientOwnerCandidateTests(unittest.TestCase):
    def test_older_server_without_the_endpoint_is_unsupported(self):
        from customer_desktop_api import DesktopApiClient, DesktopApiResponseError

        client = DesktopApiClient("http://127.0.0.1:8732")
        with patch.object(
            client, "_request", side_effect=DesktopApiResponseError(404, "Not Found")
        ):
            result = client.owner_candidates({"owner_name": "王"})
        self.assertFalse(result["supported"])

    def test_rejected_ids_are_sent_as_repeated_parameters(self):
        from customer_desktop_api import DesktopApiClient

        client = DesktopApiClient("http://127.0.0.1:8732")
        with patch.object(client, "_request", return_value={"items": []}) as request:
            client.owner_candidates({"owner_name": "王"}, rejected_record_ids=[3, 4])
        params = request.call_args.kwargs["params"]
        self.assertEqual(params["rejected_record_id"], [3, 4])
        self.assertEqual(params["owner_name"], "王")


if __name__ == "__main__":
    unittest.main()
