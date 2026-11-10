import unittest
from datetime import date

from fastapi.testclient import TestClient

from customer_api.app import create_app
from customer_api.config import ApiSettings
from customer_api.field_visit_service import (
    FieldVisitIdempotencyConflict,
    FieldVisitTransitionError,
)
from customer_api.types import AuthenticatedUser


class _FieldVisitApiSource:
    backend_name = "test"

    def __init__(self):
        self.calls = []
        self.users = {
            role: AuthenticatedUser(
                id=index,
                username=role,
                display_name=role.title(),
                role=role,
                data_key=b"x" * 32,
            )
            for index, role in enumerate(("admin", "editor", "viewer"), start=1)
        }
        self.route_candidates = {
            "id": 10,
            "start_latitude": None,
            "start_longitude": None,
            "total_distance_km": None,
            "items": [
                {
                    "id": 1,
                    "status": "planned",
                    "priority": 0,
                    "route_order": 1,
                    "is_order_locked": False,
                    "estimated_distance_km": None,
                    "latitude": 25.01,
                    "longitude": 121.51,
                    "updated_at": "2026-07-24T10:00:00+08:00",
                    "location_updated_at": "2026-07-24T09:00:00+08:00",
                },
                {
                    "id": 2,
                    "status": "planned",
                    "priority": 0,
                    "route_order": 2,
                    "is_order_locked": False,
                    "estimated_distance_km": None,
                    "latitude": 25.02,
                    "longitude": 121.52,
                    "updated_at": "2026-07-24T10:00:00+08:00",
                    "location_updated_at": "2026-07-24T09:00:00+08:00",
                },
            ],
        }

    def health(self):
        return {"status": "ok", "backend": "test", "schema_version": 8}

    def authenticate(self, username, password):
        if password != "correct-password":
            return None
        return self.users.get(username)

    def get_today_field_visit(self, user, visit_date):
        self.calls.append(("today", user.role, visit_date))
        return {"id": 10, "visit_date": visit_date.isoformat(), "items": []}

    def list_unresolved_field_visit_items(self, user, mine_only=False):
        self.calls.append(("unresolved", user.role, mine_only))
        return [{"id": 1, "route_id": 10, "status": "planned"}]

    def list_visit_calendar_items(self, user, start_date, end_date, mine_only=False):
        self.calls.append(("calendar", user.role, start_date, end_date, mine_only))
        return [{"id": 1, "calendar_status": "scheduled"}]

    def get_field_visit_route(self, user, route_id):
        self.calls.append(("get", user.role, route_id))
        if route_id == 999:
            raise KeyError(route_id)
        return {"id": route_id, "status": "planned", "items": []}

    def create_field_visit_route(self, user, values, **options):
        self.calls.append(("create", user.role, values, options))
        return {
            "id": 10,
            "visit_date": values["visit_date"].isoformat(),
            "title": values["title"],
            "status": "planned",
            "created": True,
        }

    def add_field_visit_items(self, user, route_id, items, **options):
        self.calls.append(("add", user.role, route_id, items, options))
        if route_id == 999:
            raise KeyError(route_id)
        return {
            "route_id": route_id,
            "added_count": len(items),
            "existing_count": 0,
            "item_ids": list(range(1, len(items) + 1)),
        }

    def transition_field_visit_item(
        self, user, item_id, new_status, **options
    ):
        self.calls.append(
            ("transition", user.role, item_id, new_status, options)
        )
        if item_id == 999:
            raise KeyError(item_id)
        if item_id == 998:
            raise FieldVisitIdempotencyConflict("different request")
        if item_id == 997:
            raise FieldVisitTransitionError("invalid transition")
        if item_id == 996:
            raise PermissionError("other user")
        return {
            "item_id": item_id,
            "route_id": 10,
            "old_status": "planned",
            "new_status": new_status,
            "changed": True,
            "history_id": 50,
        }

    def update_field_visit_item(self, user, item_id, **options):
        self.calls.append(("update_item", user.role, item_id, options))
        if item_id == 999:
            raise KeyError(item_id)
        return {
            "item_id": item_id,
            "route_id": 10,
            "priority": options.get("priority"),
            "is_order_locked": options.get("is_order_locked"),
            "changed": True,
        }

    def get_field_visit_route_candidates(self, user, route_id):
        self.calls.append(("candidates", user.role, route_id))
        if route_id == 999:
            raise KeyError(route_id)
        result = dict(self.route_candidates)
        result["items"] = [dict(item) for item in self.route_candidates["items"]]
        return result

    def apply_field_visit_route_order(
        self, user, route_id, plan_items, **options
    ):
        self.calls.append(
            ("apply_order", user.role, route_id, plan_items, options)
        )
        return {
            "route_id": route_id,
            "applied": True,
            "updated_count": len(plan_items),
            "items": plan_items,
        }


class FieldVisitApiTests(unittest.TestCase):
    def setUp(self):
        self.source = _FieldVisitApiSource()
        self.app = create_app(
            settings=ApiSettings(backend="sqlite"),
            data_source=self.source,
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()

    def login(self, role="editor"):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": role, "password": "correct-password"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_today_requires_login_and_allows_viewer(self):
        unauthorized = self.client.get("/api/v1/field-visits/today")
        self.assertEqual(unauthorized.status_code, 401)

        response = self.client.get(
            "/api/v1/field-visits/today",
            params={"visit_date": "2026-07-24"},
            headers=self.login("viewer"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["item"]["id"], 10)
        self.assertEqual(self.source.calls[-1], ("today", "viewer", date(2026, 7, 24)))

    def test_unresolved_requires_login_and_allows_viewer_with_mine_only(self):
        unauthorized = self.client.get("/api/v1/field-visits/unresolved/items")
        self.assertEqual(unauthorized.status_code, 401)

        response = self.client.get(
            "/api/v1/field-visits/unresolved/items",
            params={"mine_only": "true"},
            headers=self.login("viewer"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(self.source.calls[-1], ("unresolved", "viewer", True))

        default_call = self.client.get(
            "/api/v1/field-visits/unresolved/items",
            headers=self.login("viewer"),
        )
        self.assertEqual(default_call.status_code, 200, default_call.text)
        self.assertEqual(self.source.calls[-1], ("unresolved", "viewer", False))

    def test_calendar_requires_login_and_passes_date_range_through(self):
        unauthorized = self.client.get(
            "/api/v1/field-visits/calendar/items",
            params={"start_date": "2026-08-01", "end_date": "2026-08-31"},
        )
        self.assertEqual(unauthorized.status_code, 401)

        response = self.client.get(
            "/api/v1/field-visits/calendar/items",
            params={
                "start_date": "2026-08-01",
                "end_date": "2026-08-31",
                "mine_only": "true",
            },
            headers=self.login("viewer"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(
            self.source.calls[-1],
            ("calendar", "viewer", date(2026, 8, 1), date(2026, 8, 31), True),
        )

    def test_create_requires_editor_and_idempotency_key(self):
        payload = {"visit_date": "2026-07-24", "title": "今日外勤"}
        viewer = self.client.post(
            "/api/v1/field-visits",
            json=payload,
            headers={
                **self.login("viewer"),
                "Idempotency-Key": "route-key-001",
            },
        )
        self.assertEqual(viewer.status_code, 403)

        missing_key = self.client.post(
            "/api/v1/field-visits",
            json=payload,
            headers=self.login("editor"),
        )
        self.assertEqual(missing_key.status_code, 422)

        headers = {
            **self.login("editor"),
            "Idempotency-Key": "route-key-001",
        }
        response = self.client.post(
            "/api/v1/field-visits",
            json={
                **payload,
                "start_latitude": 25.01,
                "start_longitude": 121.51,
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()["created"])
        call = self.source.calls[-1]
        self.assertEqual(call[0], "create")
        self.assertEqual(call[3]["idempotency_key"], "route-key-001")

    def test_create_rejects_partial_gps(self):
        response = self.client.post(
            "/api/v1/field-visits",
            json={
                "visit_date": "2026-07-24",
                "start_latitude": 25.01,
            },
            headers={
                **self.login("editor"),
                "Idempotency-Key": "route-key-002",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_add_items_validates_duplicates_and_locked_order(self):
        headers = {
            **self.login("editor"),
            "Idempotency-Key": "items-key-001",
        }
        duplicate = self.client.post(
            "/api/v1/field-visits/10/items",
            json={
                "items": [
                    {"ownership_id": 7},
                    {"ownership_id": 7},
                ]
            },
            headers=headers,
        )
        self.assertEqual(duplicate.status_code, 422)

        locked_without_order = self.client.post(
            "/api/v1/field-visits/10/items",
            json={
                "items": [
                    {"ownership_id": 7, "is_order_locked": True},
                ]
            },
            headers=headers,
        )
        self.assertEqual(locked_without_order.status_code, 422)

        response = self.client.post(
            "/api/v1/field-visits/10/items",
            json={
                "items": [
                    {"ownership_id": 7, "priority": 10},
                    {
                        "ownership_id": 8,
                        "route_order": 2,
                        "is_order_locked": True,
                    },
                ]
            },
            headers=headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["added_count"], 2)

    def test_status_endpoints_map_to_expected_domain_status(self):
        expected = {
            "start": "in_progress",
            "complete": "completed",
            "skip": "skipped",
            "postpone": "postponed",
            "cancel": "cancelled",
            "restore": "planned",
        }
        login = self.login("editor")
        for index, (action, status) in enumerate(expected.items(), start=1):
            with self.subTest(action=action):
                response = self.client.post(
                    f"/api/v1/field-visit-items/{index}/{action}",
                    json={
                        "latitude": 25.01,
                        "longitude": 121.51,
                        "note": action,
                    },
                    headers={
                        **login,
                        "Idempotency-Key": f"status-{action}-001",
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["new_status"], status)
                if action == "cancel":
                    self.assertEqual(
                        self.source.calls[-1][4]["allowed_old_statuses"],
                        {"planned"},
                    )
                if action == "restore":
                    self.assertEqual(
                        self.source.calls[-1][4]["allowed_old_statuses"],
                        {"cancelled"},
                    )

    def test_update_item_priority_requires_editor_and_valid_payload(self):
        response = self.client.patch(
            "/api/v1/field-visit-items/7",
            json={"priority": 10, "is_order_locked": False},
            headers={
                **self.login("editor"),
                "Idempotency-Key": "priority-item-007",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["priority"], 10)
        call = self.source.calls[-1]
        self.assertEqual(call[:3], ("update_item", "editor", 7))
        self.assertFalse(call[3]["is_order_locked"])

        viewer = self.client.patch(
            "/api/v1/field-visit-items/7",
            json={"priority": 10},
            headers={
                **self.login("viewer"),
                "Idempotency-Key": "priority-viewer-007",
            },
        )
        self.assertEqual(viewer.status_code, 403)

        invalid = self.client.patch(
            "/api/v1/field-visit-items/7",
            json={"priority": 101},
            headers={
                **self.login("editor"),
                "Idempotency-Key": "priority-invalid-007",
            },
        )
        self.assertEqual(invalid.status_code, 422)

        empty = self.client.patch(
            "/api/v1/field-visit-items/7",
            json={},
            headers={
                **self.login("editor"),
                "Idempotency-Key": "priority-empty-007",
            },
        )
        self.assertEqual(empty.status_code, 422)

    def test_domain_errors_are_safe_http_responses(self):
        login = self.login("editor")
        cases = (
            (999, 404),
            (998, 409),
            (997, 409),
            (996, 403),
        )
        for item_id, expected_status in cases:
            with self.subTest(item_id=item_id):
                response = self.client.post(
                    f"/api/v1/field-visit-items/{item_id}/skip",
                    json={},
                    headers={
                        **login,
                        "Idempotency-Key": f"error-{item_id}-key",
                    },
                )
                self.assertEqual(response.status_code, expected_status, response.text)
                self.assertNotIn("database", response.text.casefold())
                self.assertNotIn("traceback", response.text.casefold())

    def test_missing_route_returns_404(self):
        response = self.client.get(
            "/api/v1/field-visits/999",
            headers=self.login("viewer"),
        )
        self.assertEqual(response.status_code, 404)

    def test_optimize_requires_preview_token_before_apply(self):
        login = self.login("editor")
        preview_response = self.client.post(
            "/api/v1/field-visits/10/optimize/preview",
            json={
                "current_latitude": 25.0,
                "current_longitude": 121.5,
                "keep_current_item_first": False,
            },
            headers=login,
        )
        self.assertEqual(preview_response.status_code, 200, preview_response.text)
        preview = preview_response.json()
        self.assertEqual(len(preview["plan_token"]), 64)
        self.assertEqual(len(preview["items"]), 2)

        missing_key = self.client.post(
            "/api/v1/field-visits/10/optimize",
            json={
                "current_latitude": 25.0,
                "current_longitude": 121.5,
                "keep_current_item_first": False,
                "plan_token": preview["plan_token"],
            },
            headers=login,
        )
        self.assertEqual(missing_key.status_code, 422)

        applied = self.client.post(
            "/api/v1/field-visits/10/optimize",
            json={
                "current_latitude": 25.0,
                "current_longitude": 121.5,
                "keep_current_item_first": False,
                "plan_token": preview["plan_token"],
            },
            headers={
                **login,
                "Idempotency-Key": "optimize-apply-001",
            },
        )
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertTrue(applied.json()["applied"])

    def test_stale_optimization_preview_returns_conflict(self):
        login = self.login("editor")
        preview = self.client.post(
            "/api/v1/field-visits/10/optimize/preview",
            json={
                "current_latitude": 25.0,
                "current_longitude": 121.5,
                "keep_current_item_first": False,
            },
            headers=login,
        ).json()
        self.source.route_candidates["items"][0]["status"] = "skipped"

        response = self.client.post(
            "/api/v1/field-visits/10/optimize",
            json={
                "current_latitude": 25.0,
                "current_longitude": 121.5,
                "keep_current_item_first": False,
                "plan_token": preview["plan_token"],
            },
            headers={
                **login,
                "Idempotency-Key": "optimize-apply-002",
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("重新預覽", response.json()["detail"])

    def test_manual_reorder_is_confirmed_write(self):
        response = self.client.post(
            "/api/v1/field-visits/10/reorder",
            json={
                "items": [
                    {"item_id": 2, "is_order_locked": True},
                    {"item_id": 1, "is_order_locked": True},
                ]
            },
            headers={
                **self.login("editor"),
                "Idempotency-Key": "manual-reorder-001",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["applied"])
        call = self.source.calls[-1]
        self.assertEqual(call[0], "apply_order")
        self.assertEqual(
            [item["item_id"] for item in call[3]],
            [2, 1],
        )


if __name__ == "__main__":
    unittest.main()
