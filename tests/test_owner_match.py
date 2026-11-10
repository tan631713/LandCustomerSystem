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


class IdentityKeyTests(unittest.TestCase):
    def test_match_key(self):
        from customer_owner_match import identity_match_key

        self.assertEqual(identity_match_key("H221345671"), "H2211")
        self.assertEqual(identity_match_key("h2211"), "H2211")
        self.assertEqual(identity_match_key("H221*****1"), "H2211")
        self.assertEqual(identity_match_key("Ｈ２２１１"), "H2211")
        self.assertIsNone(identity_match_key("H22*1"))
        self.assertIsNone(identity_match_key("H2211X"))  # other lengths
        self.assertIsNone(identity_match_key("H221"))
        self.assertIsNone(identity_match_key(""))


ADDRESS = "330桃園市桃園區國信街四十一號三樓"
ADDRESS_TYPED = "桃園市桃園區國信街41號3F"


class CandidateTierTests(unittest.TestCase):
    """One test per level of the 姓名／身分證／地址 scoring."""

    def score(self, query, stored):
        return score_owner_candidate(query, stored)

    def test_100_two_identical_complete_numbers_whatever_the_name(self):
        score, reasons = self.score(
            {"owner_name": "陳大文", "external_id": "H221987651"},
            owner(2, "陳先生", "H221987651"),
        )
        self.assertEqual(score, 100)
        self.assertIn("身分證完全相同", reasons)

    def test_95_name_identity_and_address(self):
        for typed_id in ("H221345671", "H2211", "H221*****1"):
            with self.subTest(typed_id=typed_id):
                score, reasons = self.score(
                    {"owner_name": "邱小姐", "external_id": typed_id, "address": ADDRESS_TYPED},
                    owner(1, "邱小姐", "H2211", ADDRESS),
                )
                self.assertEqual(score, 95)
                self.assertEqual(reasons[0], "姓名✓ 身分證✓ 地址✓")
                self.assertGreaterEqual(score, HIGH_MATCH_SCORE)

    def test_70_name_and_identity_but_another_address(self):
        for typed_address in ("台北市信義區松仁路1號", ""):
            with self.subTest(address=typed_address):
                score, reasons = self.score(
                    {"owner_name": "邱小姐", "external_id": "H2211", "address": typed_address},
                    owner(1, "邱小姐", "H2211", ADDRESS),
                )
                self.assertEqual(score, 70)
                self.assertIn("地址不同（可能搬家）", reasons)
                self.assertGreaterEqual(score, HIGH_MATCH_SCORE)
        self.assertEqual(
            self.score(
                {"owner_name": "邱小姐", "external_id": "H2211", "address": "台北市信義區松仁路1號"},
                owner(1, "邱小姐", "H2211", ADDRESS),
            )[1][0],
            "姓名✓ 身分證✓ 地址✗",
        )

    def test_75_name_and_address_without_identity_to_compare(self):
        for stored_id, typed_id in (("", ""), ("H2211", ""), ("", "H2211")):
            with self.subTest(stored=stored_id, typed=typed_id):
                score, reasons = self.score(
                    {"owner_name": "林美麗", "external_id": typed_id,
                     "address": "台北市中正區忠孝東路3段12-1號5F"},
                    owner(7, "林美麗", stored_id, "臺北市中正區忠孝東路三段12號之1五樓"),
                )
                self.assertEqual(score, 75)
                self.assertEqual(reasons[0], "姓名✓ 身分證— 地址✓")

    def test_50_name_and_similar_address_is_shown_only(self):
        score, reasons = self.score(
            {"owner_name": "林美麗", "address": "中壢區中正路23巷5號"},
            owner(7, "林美麗", "", "桃園市中壢區中正路二十三巷5號"),
        )
        self.assertEqual(score, 50)
        self.assertEqual(reasons[0], "姓名✓ 身分證— 地址≈")
        self.assertLess(score, HIGH_MATCH_SCORE)

    def test_same_name_different_identity_is_not_offered(self):
        self.assertIsNone(
            self.score(
                {"owner_name": "邱小姐", "external_id": "H2212", "address": ADDRESS_TYPED},
                owner(1, "邱小姐", "H2211", ADDRESS),
            )
        )
        self.assertIsNone(
            self.score(
                {"owner_name": "王大明", "external_id": "C123456789"},
                owner(1, "王大明", "A123456789"),
            )
        )

    def test_30_name_only(self):
        score, reasons = self.score({"owner_name": "陳一"}, owner(3, "陳 一"))
        self.assertEqual(score, 30)
        self.assertEqual(reasons, ["姓名✓ 身分證— 地址—"])
        score, reasons = self.score(
            {"owner_name": "陳一", "address": "新竹市東區光復路2號"},
            owner(3, "陳一", "", "桃園市中壢區中正路1號"),
        )
        self.assertEqual(score, 30)
        self.assertEqual(reasons, ["姓名✓ 身分證— 地址✗", "地址不同"])
        self.assertIsNone(self.score({"owner_name": "陳二"}, owner(3, "陳一")))

    def test_20_same_address_other_name(self):
        score, reasons = self.score(
            {"owner_name": "邱美鈴", "address": ADDRESS_TYPED},
            owner(1, "邱小姐", "", ADDRESS),
        )
        self.assertEqual(score, 20)
        self.assertEqual(
            reasons, ["姓名✗ 身分證— 地址✓", "地址相同、姓名不同（可能是家人或姓名打錯）"]
        )
        score, reasons = self.score({"address": ADDRESS_TYPED}, owner(1, "邱小姐", "", ADDRESS))
        self.assertEqual(score, 20)
        self.assertIn("地址相同（尚未輸入姓名）", reasons)

    def test_same_identity_key_under_another_name_needs_the_address(self):
        query = {"owner_name": "林先生", "external_id": "H2211"}
        self.assertIsNone(self.score(query, owner(1, "邱小姐", "H2211", ADDRESS)))
        score, _reasons = self.score(
            {**query, "address": ADDRESS_TYPED}, owner(1, "邱小姐", "H2211", ADDRESS)
        )
        self.assertEqual(score, 20)

    def test_phone_without_identity(self):
        score, reasons = self.score(
            {"owner_name": "張三", "phone": "0912-345-678"},
            owner(2, "張三", "", "", phones=["0912345678"]),
        )
        self.assertEqual(score, 70)
        self.assertIn("電話相同", reasons)

    def test_ranking_order(self):
        owners = [
            owner(1, "張三", "", "新竹市東區光復路2號"),              # 30
            owner(2, "張三", "", "桃園市中壢區中正路1號"),            # 75
            owner(3, "張三", "H1239", "桃園市中壢區中正路1號"),       # 95
            owner(4, "張三", "H1239", "台北市信義區松仁路1號"),       # 70
            owner(5, "李四", "", "桃園市中壢區中正路一號"),           # 20
            owner(6, "張三", "Z9999", "桃園市中壢區中正路1號"),       # not offered
        ]
        ranked = rank_owner_candidates(
            {"owner_name": "張三", "external_id": "H123*****9", "address": "桃園市中壢區中正路一號"},
            owners,
        )
        self.assertEqual([item["owner_id"] for item in ranked], [3, 2, 4, 1, 5])
        self.assertEqual([item["score"] for item in ranked], [95, 75, 70, 30, 20])
        high = [candidate_response_item(item)["high_match"] for item in ranked]
        self.assertEqual(high, [True, True, True, False, False])

    def test_address_only_is_capped_at_five_and_respects_rejections(self):
        owners = [owner(1, "王一", "", "台中市西區民權路1號")]
        owners += [
            owner(10 + index, f"家人{index}", "", "台中市西區民權路1號")
            for index in range(8)
        ]
        ranked = rank_owner_candidates(
            {"owner_name": "王一", "address": "臺中市西區民權路一號"}, owners
        )
        self.assertEqual(ranked[0]["owner_id"], 1)
        self.assertEqual(sum(1 for item in ranked if item["score"] == 20), 5)
        self.assertTrue(candidate_response_item(ranked[-1])["address_only"])
        self.assertEqual(
            rank_owner_candidates(
                {"owner_name": "某甲", "address": "台中市西區民權路1號"},
                [owner(1, "某乙", "", "台中市西區民權路1號")],
                ignored_owner_ids={1},
            ),
            [],
        )

    def test_rejected_owners_are_left_out_and_response_is_masked(self):
        owners = [owner(1, "王五", "A123456789", phones=["0912345678"])]
        self.assertEqual(
            rank_owner_candidates({"owner_name": "王五"}, owners, ignored_owner_ids={1}),
            [],
        )
        item = candidate_response_item(rank_owner_candidates({"owner_name": "王五"}, owners)[0])
        self.assertEqual(item["external_id_masked"], "A123*****9")
        self.assertEqual(item["phones_masked"], ["09*****678"])
        self.assertNotIn("A123456789", repr(item))

    def test_ranking_twenty_thousand_owners_stays_fast(self):
        import random
        import time

        rng = random.Random(7)
        roads = ["中正路", "民權路", "國信街", "中山北路", "復興路", "建國路"]
        owners = [
            owner(
                index,
                f"測{index % 997}",
                f"H{rng.randint(1000, 2999)}" if index % 2 else "",
                f"桃園市桃園區{rng.choice(roads)}{rng.randint(1, 9)}段"
                f"{rng.randint(1, 300)}巷{rng.randint(1, 80)}號{rng.randint(1, 15)}樓",
            )
            for index in range(20000)
        ]
        for item in owners:
            item["_name_norm"] = item["owner_name"]
            item["_address_norm"] = normalize_owner_address(item["address"])
        started = time.perf_counter()
        rank_owner_candidates(
            {"owner_name": "測5", "external_id": "H1235",
             "address": "桃園市桃園區中正路3段120巷8號5樓"},
            owners,
        )
        self.assertLess(time.perf_counter() - started, 1.0)


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

    def test_address_only_query_finds_owners_under_other_names(self):
        result = self.source.owner_candidates(
            self.user, {"address": "新竹市東區光復路二號"}
        )
        self.assertEqual([item["owner_id"] for item in result["items"]], [2])
        self.assertTrue(result["items"][0]["address_only"])
        self.assertIsNone(result["exact_owner_id"])
        # Decrypted owners are reused by the next lookup.
        with patch("customer_api.postgres_owner_match.decrypt_value") as decrypt:
            self.source.owner_candidates(self.user, {"address": "新竹市東區光復路2號"})
        decrypt.assert_not_called()

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

    def test_choosing_folds_the_list_into_one_line_and_cancel_unfolds_it(self):
        self.type_new_owner()
        panel = self.window.owner_match_panel
        panel.choose_button.click()
        self.assertFalse(panel.isHidden())
        self.assertTrue(panel.table.isHidden())
        self.assertTrue(panel.choose_button.isHidden())
        self.assertTrue(panel.new_owner_button.isHidden())
        self.assertTrue(panel.title_label.isHidden())
        self.assertFalse(panel.clear_choice_button.isHidden())
        self.assertEqual(
            panel.chosen_label.text(),
            "已選擇既有地主：王大明3（A100****3，1 筆土地），儲存時會加到這位地主名下",
        )
        panel.clear_choice_button.click()
        self.assertIsNone(panel.chosen)
        self.assertFalse(panel.table.isHidden())
        self.assertFalse(panel.choose_button.isHidden())
        self.assertFalse(panel.new_owner_button.isHidden())
        self.assertTrue(panel.clear_choice_button.isHidden())
        self.assertEqual(panel.chosen_label.text(), "")
        # The masked ID the choice filled in goes away with it.
        self.assertEqual(self.window.get_field_text("external_id"), "")

    def test_panel_hides_after_save_new_record_and_decline(self):
        panel = self.window.owner_match_panel
        self.type_new_owner()
        panel.choose_button.click()
        self.save()
        self.assertTrue(panel.isHidden())
        self.assertIsNone(panel.chosen)

        self.type_new_owner()
        self.assertFalse(panel.isHidden())
        panel.choose_button.click()
        self.window.new_record()  # 「新增」 clears the form
        self.assertTrue(panel.isHidden())
        self.assertIsNone(panel.chosen)

        self.type_new_owner()
        self.assertFalse(panel.isHidden())
        panel.new_owner_button.click()
        self.assertTrue(panel.isHidden())

    def test_address_field_alone_triggers_the_lookup(self):
        window = self.window
        window.new_record()
        window.set_field_text("address", "桃園市中壢區某路123號")
        window.field_widgets["address"].editingFinished.emit()
        self.assertEqual(len(self.server.candidate_queries), 1)
        query = self.server.candidate_queries[0][0]
        self.assertEqual(query["owner_name"], "")
        self.assertEqual(query["address"], "桃園市中壢區某路123號")
        self.assertFalse(window.owner_match_panel.isHidden())

    def test_identity_field_alone_triggers_the_lookup(self):
        window = self.window
        window.new_record()
        window.set_field_text("external_id", "H2211")
        window.current_external_id_plain = "H2211"
        window.field_widgets["external_id"].editingFinished.emit()
        self.assertEqual(len(self.server.candidate_queries), 1)
        self.assertEqual(self.server.candidate_queries[0][0]["external_id"], "H2211")
        self.assertEqual(self.server.candidate_queries[0][0]["owner_name"], "")

    def test_empty_fields_do_not_look_up(self):
        self.window.new_record()
        for key in ("owner_name", "external_id", "address"):
            self.window.field_widgets[key].editingFinished.emit()
        self.assertEqual(self.server.candidate_queries, [])

    def test_no_more_lookups_after_choosing(self):
        self.type_new_owner()
        self.window.owner_match_panel.choose_button.click()
        before = len(self.server.candidate_queries)
        self.window.set_field_text("address", "另一個地址1號")
        self.window.field_widgets["address"].editingFinished.emit()
        self.window.field_widgets["owner_name"].editingFinished.emit()
        self.assertEqual(len(self.server.candidate_queries), before)

    def test_address_only_match_is_shown_but_never_prompts_on_save(self):
        self.server.candidates = [
            {
                **CANDIDATE,
                "owner_name": "邱小姐",
                "score": 10,
                "reasons": ["地址相同、姓名不同（可能是家人或姓名打錯）"],
                "address_only": True,
                "high_match": False,
            }
        ]
        self.type_new_owner("邱美鈴")
        self.assertFalse(self.window.owner_match_panel.isHidden())
        with patch.object(self.window, "ask_owner_match_decision") as ask:
            self.save()
        ask.assert_not_called()
        self.assertEqual(len(self.server.created_values), 1)
        self.assertNotIn("owner_id", self.server.created_values[0])

    def test_choosing_an_address_only_owner_uses_that_owners_name(self):
        self.server.candidates = [
            {**CANDIDATE, "owner_name": "邱小姐", "score": 10,
             "reasons": ["地址相同、姓名不同（可能是家人或姓名打錯）"],
             "address_only": True, "high_match": False}
        ]
        self.type_new_owner("邱美鈴")
        self.window.owner_match_panel.choose_button.click()
        self.assertEqual(self.window.get_field_text("owner_name"), "邱小姐")
        self.save()
        self.assertEqual(self.server.created_values[-1]["owner_id"], 3)
        self.assertEqual(self.server.created_values[-1]["owner_name"], "邱小姐")

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
