"""Urban plan (都市計畫) support in the home server: SQL logic, routes and schemas."""

import unittest
from datetime import datetime

from fastapi.testclient import TestClient
from pydantic import ValidationError

from customer_api.app import create_app
from customer_api.config import ApiSettings
from customer_api.postgres_schema import (
    IDENTITY_TABLES,
    POSTGRES_SCHEMA_PATH,
    split_postgres_statements,
)
from customer_api.postgres_urban_plans import (
    PostgreSQLUrbanPlanMixin,
    apply_record_urban_plan,
    assign_imported_lands,
)
from customer_api.schemas import RecordImportBatch, RecordWrite, UrbanPlanAssignment
from customer_api.types import AuthenticatedUser


class _Result:
    def __init__(self, one=None, many=None):
        self.one = one
        self.many = list(many or [])

    def fetchone(self):
        return self.one

    def fetchall(self):
        return list(self.many)


class _Connection:
    """Records every statement and answers through `handler(sql, params)`."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        sql = " ".join(str(query).split())
        self.calls.append((sql, params))
        return self.handler(sql, params)

    def statements(self, fragment):
        return [(sql, params) for sql, params in self.calls if fragment in sql]


class _Source(PostgreSQLUrbanPlanMixin):
    def __init__(self, connection):
        self.connection = connection
        self.connects = 0

    def _connect(self):
        self.connects += 1
        return self.connection


USER = AuthenticatedUser(id=1, username="admin", display_name="Admin", role="admin", data_key=b"x" * 32)


class PlanListTests(unittest.TestCase):
    def test_lists_plans_with_counts_and_the_unassigned_group(self):
        def handler(sql, params):
            if sql.startswith("SELECT plan.id, plan.name"):
                return _Result(many=[
                    {"id": 1, "name": "龍岡都市計畫", "created_at": datetime(2026, 10, 1),
                     "land_count": 3, "ownership_count": 7, "owner_count": 5},
                ])
            if "WHERE land.urban_plan_id IS NULL" in sql:
                return _Result(one={"land_count": 2, "ownership_count": 4, "owner_count": 3})
            raise AssertionError(sql)

        result = _Source(_Connection(handler)).list_urban_plans(USER)
        self.assertEqual(result["items"][0]["plan_id"], 1)
        self.assertEqual(result["items"][0]["name"], "龍岡都市計畫")
        self.assertEqual(result["items"][0]["land_count"], 3)
        self.assertIsInstance(result["items"][0]["created_at"], str)
        self.assertEqual(result["unassigned"], {"land_count": 2, "ownership_count": 4, "owner_count": 3})


class PlanSaveTests(unittest.TestCase):
    def source(self, handler):
        connection = _Connection(handler)
        return _Source(connection), connection

    def test_invalid_names_are_refused_before_touching_the_database(self):
        source, connection = self.source(lambda sql, params: _Result())
        for name, fragment in (("   ", "不可空白"), ("未分類", "保留"), ("字" * 101, "100")):
            with self.subTest(name=name[:4]):
                with self.assertRaises(ValueError) as caught:
                    source.save_urban_plan(USER, name)
                self.assertIn(fragment, str(caught.exception))
        self.assertEqual(source.connects, 0)

    def test_a_duplicate_name_is_refused_case_insensitively(self):
        def handler(sql, params):
            if "LOWER(name) = LOWER(%s)" in sql:
                return _Result(one={"id": 9})
            raise AssertionError(sql)

        source, _connection = self.source(handler)
        with self.assertRaises(ValueError) as caught:
            source.save_urban_plan(USER, "龍岡都市計畫")
        self.assertIn("已有相同名稱", str(caught.exception))

    def test_create_collapses_whitespace_and_writes_an_audit_row(self):
        def handler(sql, params):
            if "LOWER(name) = LOWER(%s)" in sql:
                return _Result(one=None)
            if sql.startswith("INSERT INTO urban_plans"):
                return _Result(one={"id": 5})
            return _Result()

        source, connection = self.source(handler)
        self.assertEqual(source.save_urban_plan(USER, "  龍岡   都市計畫 "), 5)
        self.assertEqual(connection.statements("INSERT INTO urban_plans")[0][1], ("龍岡 都市計畫",))
        audit = connection.statements("INSERT INTO audit_logs")[0][1]
        self.assertEqual(audit[:3], (1, "admin", "api_create_urban_plan"))

    def test_rename_of_a_missing_plan_raises_key_error(self):
        def handler(sql, params):
            if "LOWER(name) = LOWER(%s)" in sql:
                return _Result(one=None)
            if sql.startswith("UPDATE urban_plans"):
                return _Result(one=None)
            raise AssertionError(sql)

        source, _connection = self.source(handler)
        with self.assertRaises(KeyError):
            source.save_urban_plan(USER, "大湳都市計畫", 42)


class PlanDeleteTests(unittest.TestCase):
    def test_missing_plan_returns_none_without_deleting(self):
        connection = _Connection(lambda sql, params: _Result(one=None))
        self.assertIsNone(_Source(connection).delete_urban_plan(USER, 3))
        self.assertEqual(connection.statements("DELETE FROM urban_plans"), [])

    def test_delete_reports_how_many_lands_were_released(self):
        def handler(sql, params):
            if sql.startswith("SELECT id, name FROM urban_plans"):
                return _Result(one={"id": 3, "name": "大湳都市計畫"})
            if sql.startswith("SELECT COUNT(*)"):
                return _Result(one={"count": 96})
            return _Result()

        connection = _Connection(handler)
        result = _Source(connection).delete_urban_plan(USER, 3)
        self.assertEqual(result, {"deleted": True, "released_land_count": 96})
        self.assertEqual(connection.statements("DELETE FROM urban_plans")[0][1], (3,))
        self.assertEqual(connection.statements("INSERT INTO audit_logs")[0][1][2], "api_delete_urban_plan")


class AssignLandsTests(unittest.TestCase):
    @staticmethod
    def handler(*, existing=(1, 2), plan=None, updated=(), kept=()):
        def run(sql, params):
            if sql.startswith("SELECT id FROM lands"):
                return _Result(many=[{"id": value} for value in existing])
            if sql.startswith("SELECT id, name FROM urban_plans"):
                return _Result(one=plan)
            if sql.startswith("UPDATE lands"):
                return _Result(many=[{"id": value} for value in updated])
            if "JOIN urban_plans plan" in sql:
                return _Result(many=list(kept))
            return _Result()

        return run

    def test_no_lands_means_no_database_work(self):
        source = _Source(_Connection(self.handler()))
        result = source.set_lands_urban_plan(USER, [], 3)
        self.assertEqual(result, {"updated_land_ids": [], "updated_count": 0, "kept_lands": []})
        self.assertEqual(source.connects, 0)

    def test_unknown_lands_or_plan_raise_key_error(self):
        with self.assertRaises(KeyError):
            _Source(_Connection(self.handler(existing=(1,)))).set_lands_urban_plan(USER, [1, 2], 3)
        with self.assertRaises(KeyError):
            _Source(_Connection(self.handler(plan=None))).set_lands_urban_plan(USER, [1, 2], 3)

    def test_only_unassigned_leaves_lands_of_other_plans_alone_and_reports_them(self):
        kept_row = {"id": 2, "district": "中壢區", "section": "忠福段", "subsection": "",
                    "land_number": "307-0000", "urban_plan_name": "大湳都市計畫"}
        connection = _Connection(self.handler(
            plan={"id": 3, "name": "龍岡都市計畫"}, updated=(1,), kept=(kept_row,)))
        result = _Source(connection).set_lands_urban_plan(USER, [2, 1, 1], 3)
        update_sql = connection.statements("UPDATE lands")[0][0]
        self.assertIn("urban_plan_id IS NULL", update_sql)
        self.assertNotIn("DISTINCT", update_sql)
        self.assertEqual(connection.statements("UPDATE lands")[0][1], (3, [1, 2]))
        self.assertEqual(result["updated_land_ids"], [1])
        self.assertEqual(result["kept_lands"][0]["urban_plan_name"], "大湳都市計畫")

    def test_explicit_override_moves_lands_even_from_another_plan(self):
        connection = _Connection(self.handler(plan={"id": 3, "name": "龍岡都市計畫"}, updated=(1, 2)))
        result = _Source(connection).set_lands_urban_plan(USER, [1, 2], 3, only_unassigned=False)
        self.assertIn("IS DISTINCT FROM", connection.statements("UPDATE lands")[0][0])
        self.assertEqual(connection.statements("JOIN urban_plans plan"), [])
        self.assertEqual(result["updated_count"], 2)
        self.assertEqual(result["kept_lands"], [])

    def test_plan_zero_releases_lands_to_unassigned(self):
        connection = _Connection(self.handler(updated=(1,)))
        result = _Source(connection).set_lands_urban_plan(USER, [1, 2], 0)
        self.assertIn("SET urban_plan_id = NULL", connection.statements("UPDATE lands")[0][0])
        self.assertEqual(connection.statements("SELECT id, name FROM urban_plans"), [])
        self.assertEqual(result["updated_land_ids"], [1])


class RecordPlanHelperTests(unittest.TestCase):
    def test_none_keeps_the_plan_and_does_no_work(self):
        connection = _Connection(lambda sql, params: _Result())
        apply_record_urban_plan(connection, 5, None)
        self.assertEqual(connection.calls, [])

    def test_zero_clears_the_plan_of_the_land(self):
        connection = _Connection(lambda sql, params: _Result())
        apply_record_urban_plan(connection, 5, 0)
        sql, params = connection.calls[0]
        self.assertIn("UPDATE lands", sql)
        self.assertEqual(params, (None, 5, None))

    def test_an_id_moves_the_land_after_checking_the_plan_exists(self):
        connection = _Connection(lambda sql, params: _Result(one={"found": 1}))
        apply_record_urban_plan(connection, 5, 3)
        self.assertEqual(connection.calls[-1][1], (3, 5, 3))
        with self.assertRaises(ValueError):
            apply_record_urban_plan(_Connection(lambda sql, params: _Result(one=None)), 5, 3)

    def test_import_assigns_only_unassigned_lands_and_counts_the_ones_kept(self):
        def handler(sql, params):
            if sql.startswith("SELECT id, name FROM urban_plans"):
                return _Result(one={"id": 3, "name": "龍岡都市計畫"})
            if sql.startswith("SELECT DISTINCT land_id"):
                return _Result(many=[{"land_id": 10}, {"land_id": 11}, {"land_id": 12}])
            if sql.startswith("UPDATE lands"):
                return _Result(many=[{"id": 10}, {"id": 11}])
            if "JOIN urban_plans plan" in sql:
                return _Result(many=[{"id": 12, "district": "中壢區", "section": "忠福段",
                                      "subsection": "", "land_number": "314-0000",
                                      "urban_plan_name": "大湳都市計畫"}])
            if sql.startswith("SELECT COUNT(*)"):
                return _Result(one={"count": 1})
            return _Result()

        connection = _Connection(handler)
        summary = assign_imported_lands(connection, USER, [101, 102, 103], 3)
        self.assertEqual(summary["assigned_land_count"], 2)
        self.assertEqual(summary["kept_land_count"], 1)
        self.assertEqual(summary["kept_lands"][0]["land_number"], "314-0000")
        self.assertEqual(summary["name"], "龍岡都市計畫")
        self.assertIn("urban_plan_id IS NULL", connection.statements("UPDATE lands")[0][0])

    def test_import_into_a_missing_plan_is_refused(self):
        with self.assertRaises(ValueError):
            assign_imported_lands(_Connection(lambda sql, params: _Result(one=None)), USER, [1], 3)


class SchemaTests(unittest.TestCase):
    def test_schema_version_14_adds_the_plan_table_and_land_column(self):
        text = POSTGRES_SCHEMA_PATH.read_text(encoding="utf-8")
        statements = [" ".join(statement.split()) for statement in split_postgres_statements(text)]
        self.assertEqual(
            sum(1 for statement in statements if "CREATE TABLE IF NOT EXISTS urban_plans (" in statement), 1
        )
        self.assertIn("ADD COLUMN IF NOT EXISTS urban_plan_id BIGINT REFERENCES urban_plans(id) ON DELETE SET NULL", text)
        self.assertIn("VALUES (14, 'urban plans')", text)
        self.assertIn("urban_plans", IDENTITY_TABLES)


class RecordSchemaTests(unittest.TestCase):
    BASE = {"district": "中壢區", "section": "龍岡段", "land_number": "221-0000"}

    def test_urban_plan_id_defaults_to_keep_and_accepts_zero_or_an_id(self):
        self.assertIsNone(RecordWrite(**self.BASE).normalized_values()["urban_plan_id"])
        self.assertEqual(RecordWrite(**self.BASE, urban_plan_id=0).normalized_values()["urban_plan_id"], 0)
        self.assertEqual(RecordWrite(**self.BASE, urban_plan_id=7).normalized_values()["urban_plan_id"], 7)
        self.assertEqual(RecordWrite(**self.BASE, urban_plan_id="7").normalized_values()["urban_plan_id"], 7)
        self.assertIsNone(RecordWrite(**self.BASE, urban_plan_id="").normalized_values()["urban_plan_id"])

    def test_negative_plan_ids_are_rejected(self):
        with self.assertRaises(ValidationError):
            RecordWrite(**self.BASE, urban_plan_id=-1)

    def test_import_batch_plan_id_must_be_a_real_plan(self):
        item = {"record_id": None, "values": self.BASE}
        self.assertEqual(RecordImportBatch(items=[item], urban_plan_id=4).urban_plan_id, 4)
        self.assertIsNone(RecordImportBatch(items=[item]).urban_plan_id)
        with self.assertRaises(ValidationError):
            RecordImportBatch(items=[item], urban_plan_id=0)

    def test_assignment_needs_lands_and_defaults_to_not_overwriting(self):
        assignment = UrbanPlanAssignment(land_ids=[1, 2], urban_plan_id=3)
        self.assertTrue(assignment.only_unassigned)
        with self.assertRaises(ValidationError):
            UrbanPlanAssignment(land_ids=[], urban_plan_id=3)


class _PlanApiSource:
    backend_name = "test"

    def __init__(self):
        self.calls = []
        self.users = {
            role: AuthenticatedUser(id=index, username=role, display_name=role, role=role, data_key=b"x" * 32)
            for index, role in enumerate(("admin", "editor", "viewer"), start=1)
        }

    def health(self):
        return {"status": "ok", "backend": "test", "schema_version": 14}

    def authenticate(self, username, password):
        return self.users.get(username) if password == "correct-password" else None

    def list_urban_plans(self, user):
        self.calls.append(("list", user.role))
        return {"items": [{"id": 1, "plan_id": 1, "name": "龍岡都市計畫", "land_count": 3,
                           "ownership_count": 7, "owner_count": 5}],
                "unassigned": {"land_count": 0, "ownership_count": 0, "owner_count": 0}}

    def save_urban_plan(self, user, name, plan_id=None):
        self.calls.append(("save", user.role, name, plan_id))
        if name == "重複":
            raise ValueError("已有相同名稱的都市計畫")
        if plan_id == 404:
            raise KeyError(plan_id)
        return plan_id or 7

    def delete_urban_plan(self, user, plan_id):
        self.calls.append(("delete", user.role, plan_id))
        return None if plan_id == 404 else {"deleted": True, "released_land_count": 96}

    def set_lands_urban_plan(self, user, land_ids, plan_id, only_unassigned=True):
        self.calls.append(("assign", user.role, list(land_ids), plan_id, only_unassigned))
        if plan_id == 404:
            raise KeyError(plan_id)
        if plan_id == 405:
            raise ValueError("單機版資料來源不支援都市計畫")
        return {"updated_land_ids": [1], "updated_count": 1, "kept_lands": []}


class PlanApiTests(unittest.TestCase):
    def setUp(self):
        self.source = _PlanApiSource()
        self.client = TestClient(
            create_app(settings=ApiSettings(backend="sqlite"), data_source=self.source),
            raise_server_exceptions=False,
        )

    def tearDown(self):
        self.client.close()

    def login(self, role):
        response = self.client.post("/api/v1/auth/login", json={"username": role, "password": "correct-password"})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_every_account_can_read_the_plan_list_but_viewers_cannot_change_it(self):
        viewer = self.login("viewer")
        listed = self.client.get("/api/v1/urban-plans", headers=viewer)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["items"][0]["name"], "龍岡都市計畫")
        for method, path, body in (
            ("post", "/api/v1/urban-plans", {"name": "新的"}),
            ("put", "/api/v1/urban-plans/1", {"name": "改名"}),
            ("delete", "/api/v1/urban-plans/1", None),
            ("put", "/api/v1/urban-plans/assignments", {"land_ids": [1], "urban_plan_id": 1}),
        ):
            with self.subTest(path=path, method=method):
                response = getattr(self.client, method)(path, headers=viewer, **({"json": body} if body else {}))
                self.assertEqual(response.status_code, 403)

    def test_create_rename_and_conflicts(self):
        editor = self.login("editor")
        created = self.client.post("/api/v1/urban-plans", json={"name": "大湳都市計畫"}, headers=editor)
        self.assertEqual((created.status_code, created.json()), (201, {"id": 7}))
        duplicate = self.client.post("/api/v1/urban-plans", json={"name": "重複"}, headers=editor)
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("已有相同名稱", duplicate.json()["detail"])
        self.assertEqual(self.client.put("/api/v1/urban-plans/3", json={"name": "改名"}, headers=editor).json(), {"id": 3})
        self.assertEqual(self.client.put("/api/v1/urban-plans/404", json={"name": "x"}, headers=editor).status_code, 404)
        self.assertEqual(self.client.post("/api/v1/urban-plans", json={"name": ""}, headers=editor).status_code, 422)

    def test_delete_reports_released_lands_or_404(self):
        editor = self.login("editor")
        deleted = self.client.delete("/api/v1/urban-plans/3", headers=editor)
        self.assertEqual(deleted.json(), {"deleted": True, "released_land_count": 96})
        self.assertEqual(self.client.delete("/api/v1/urban-plans/404", headers=editor).status_code, 404)

    def test_assignment_defaults_to_not_overwriting_and_maps_errors(self):
        editor = self.login("editor")
        ok = self.client.put("/api/v1/urban-plans/assignments",
                             json={"land_ids": [1, 2], "urban_plan_id": 3}, headers=editor)
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(self.source.calls[-1], ("assign", "editor", [1, 2], 3, True))
        release = self.client.put("/api/v1/urban-plans/assignments",
                                  json={"land_ids": [1], "urban_plan_id": None, "only_unassigned": False}, headers=editor)
        self.assertEqual(release.status_code, 200)
        self.assertEqual(self.source.calls[-1], ("assign", "editor", [1], None, False))
        for plan_id, status in ((404, 404), (405, 400)):
            with self.subTest(plan_id=plan_id):
                response = self.client.put("/api/v1/urban-plans/assignments",
                                           json={"land_ids": [1], "urban_plan_id": plan_id}, headers=editor)
                self.assertEqual(response.status_code, status)
        empty = self.client.put("/api/v1/urban-plans/assignments", json={"land_ids": []}, headers=editor)
        self.assertEqual(empty.status_code, 422)


if __name__ == "__main__":
    unittest.main()
