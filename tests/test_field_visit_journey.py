import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from customer_api.app import create_app
from customer_api.config import ApiSettings
from customer_api.field_visit_service import validate_status_transition
from customer_api.types import AuthenticatedUser


class _FieldVisitJourneySource:
    """Stateful in-memory source for the complete mobile-to-desktop journey."""

    backend_name = "test"

    def __init__(self):
        self.user = AuthenticatedUser(
            id=7,
            username="editor",
            display_name="外勤測試",
            role="editor",
            data_key=b"x" * 32,
        )
        self.route = None
        self.next_item_id = 100
        self.contact_logs = {}
        self.attachments = {}
        self.follow_ups = []
        self.records = {
            1001: {"id": 1001, "owner_name": "優先地主"},
            1002: {"id": 1002, "owner_name": "第二位地主"},
            1003: {"id": 1003, "owner_name": "第三位地主"},
        }
        self.ownerships = {
            101: (1001, 25.001, 121.501),
            102: (1002, 25.004, 121.504),
            103: (1003, 25.008, 121.508),
        }

    def health(self):
        return {"status": "ok", "backend": "test", "schema_version": 8}

    def authenticate(self, username, password):
        if username == "editor" and password == "correct-password":
            return self.user
        return None

    def create_field_visit_route(self, user, values, **options):
        del user, options
        self.route = {
            "id": 10,
            "visit_date": values["visit_date"].isoformat(),
            "title": values["title"],
            "status": "planned",
            "start_latitude": values["start_latitude"],
            "start_longitude": values["start_longitude"],
            "total_distance_km": None,
            "items": [],
        }
        return {**self.route, "created": True}

    def get_today_field_visit(self, user, visit_date):
        del user
        if self.route and self.route["visit_date"] == visit_date.isoformat():
            return self.get_field_visit_route(self.user, self.route["id"])
        return None

    def get_field_visit_route(self, user, route_id):
        del user
        if not self.route or int(route_id) != self.route["id"]:
            raise KeyError(route_id)
        result = dict(self.route)
        result["items"] = [
            dict(item)
            for item in sorted(
                self.route["items"],
                key=lambda value: (value["route_order"], value["id"]),
            )
        ]
        return result

    def add_field_visit_items(self, user, route_id, items, **options):
        del user, options
        if not self.route or int(route_id) != self.route["id"]:
            raise KeyError(route_id)
        existing = {
            int(item["ownership_id"]): item for item in self.route["items"]
        }
        added_ids = []
        for values in items:
            ownership_id = int(values["ownership_id"])
            if ownership_id in existing:
                continue
            if ownership_id not in self.ownerships:
                raise KeyError(ownership_id)
            record_id, latitude, longitude = self.ownerships[ownership_id]
            self.next_item_id += 1
            item = {
                "id": self.next_item_id,
                "route_id": self.route["id"],
                "record_id": record_id,
                "ownership_id": ownership_id,
                "status": "planned",
                "priority": int(values.get("priority") or 0),
                "route_order": values.get("route_order")
                or len(self.route["items"]) + 1,
                "is_order_locked": bool(values.get("is_order_locked")),
                "estimated_distance_km": None,
                "latitude": latitude,
                "longitude": longitude,
                "updated_at": "2026-07-28T12:00:00+08:00",
                "location_updated_at": "2026-07-28T11:00:00+08:00",
            }
            self.route["items"].append(item)
            existing[ownership_id] = item
            added_ids.append(item["id"])
        return {
            "route_id": self.route["id"],
            "added_count": len(added_ids),
            "existing_count": len(items) - len(added_ids),
            "item_ids": added_ids,
        }

    def get_field_visit_route_candidates(self, user, route_id):
        route = self.get_field_visit_route(user, route_id)
        return {
            "id": route["id"],
            "start_latitude": route["start_latitude"],
            "start_longitude": route["start_longitude"],
            "total_distance_km": route["total_distance_km"],
            "items": [dict(item) for item in route["items"]],
        }

    def apply_field_visit_route_order(
        self, user, route_id, plan_items, **options
    ):
        del user
        if not self.route or int(route_id) != self.route["id"]:
            raise KeyError(route_id)
        by_id = {int(item["id"]): item for item in self.route["items"]}
        for planned in plan_items:
            item = by_id[int(planned["item_id"])]
            item["route_order"] = int(planned["route_order"])
            item["estimated_distance_km"] = planned.get(
                "estimated_distance_km"
            )
            if "is_order_locked" in planned:
                item["is_order_locked"] = bool(planned["is_order_locked"])
        self.route["start_latitude"] = options.get("start_latitude")
        self.route["start_longitude"] = options.get("start_longitude")
        self.route["total_distance_km"] = options.get("total_distance_km")
        return {
            "route_id": self.route["id"],
            "applied": True,
            "updated_count": len(plan_items),
            "items": [dict(item) for item in plan_items],
        }

    def transition_field_visit_item(
        self, user, item_id, new_status, **options
    ):
        del user
        item = next(
            (
                candidate
                for candidate in self.route["items"]
                if int(candidate["id"]) == int(item_id)
            ),
            None,
        )
        if item is None:
            raise KeyError(item_id)
        old_status = item["status"]
        allowed = options.get("allowed_old_statuses")
        if allowed and old_status not in allowed:
            raise ValueError("old status is not allowed")
        validate_status_transition(old_status, new_status)
        item["status"] = new_status
        item["updated_at"] = f"2026-07-28T12:{int(item_id) % 60:02d}:00+08:00"
        terminal = {"completed", "skipped", "cancelled"}
        if all(value["status"] in terminal for value in self.route["items"]):
            self.route["status"] = "completed"
        else:
            self.route["status"] = "in_progress"
        return {
            "item_id": int(item_id),
            "route_id": self.route["id"],
            "old_status": old_status,
            "new_status": new_status,
            "changed": True,
            "history_id": int(item_id) + 1000,
        }

    def get_record(self, user, record_id):
        del user
        record = self.records.get(int(record_id))
        return dict(record) if record else None

    def add_contact_log(self, user, record_id, values, **options):
        del user, options
        if int(record_id) not in self.records:
            raise KeyError(record_id)
        log_id = sum(len(items) for items in self.contact_logs.values()) + 1
        self.contact_logs.setdefault(int(record_id), []).append(
            {"id": log_id, "record_id": int(record_id), **dict(values)}
        )
        return log_id

    def list_contact_logs(self, user, record_id):
        del user
        return [
            dict(item) for item in self.contact_logs.get(int(record_id), [])
        ]

    def save_follow_up(self, user, record_id, values):
        del user
        self.follow_ups.append({"record_id": int(record_id), **dict(values)})

    def import_managed_attachment(
        self,
        user,
        record_id,
        temporary_path,
        original_name,
        description,
        media_type,
        category,
        field_visit_route_item_id,
        idempotency_key,
        request_hash,
    ):
        del user, idempotency_key, request_hash
        if int(record_id) not in self.records:
            raise KeyError(record_id)
        content = Path(temporary_path).read_bytes()
        attachment_id = len(self.attachments) + 1
        self.attachments[attachment_id] = {
            "id": attachment_id,
            "record_id": int(record_id),
            "original_name": original_name,
            "description": description,
            "media_type": media_type,
            "category": category,
            "field_visit_route_item_id": field_visit_route_item_id,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "status": "managed",
            "can_delete": True,
        }
        return attachment_id

    def list_attachments(self, user, record_id):
        del user
        if int(record_id) not in self.records:
            raise KeyError(record_id)
        return [
            dict(item)
            for item in self.attachments.values()
            if item["record_id"] == int(record_id)
        ]


class FieldVisitJourneyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.source = _FieldVisitJourneySource()
        self.app = create_app(
            settings=ApiSettings(
                backend="sqlite",
                sqlite_database_path=root / "unused.db",
                backup_directory=root / "backups",
                attachment_directory=root / "attachments",
            ),
            data_source=self.source,
        )
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def _login(self):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": "editor", "password": "correct-password"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return {
            "Authorization": f"Bearer {response.json()['access_token']}"
        }

    def _write_headers(self, authorization, key):
        return {**authorization, "Idempotency-Key": key}

    def _change_status(self, authorization, item_id, action, key):
        response = self.client.post(
            f"/api/v1/field-visit-items/{item_id}/{action}",
            json={
                "latitude": 25.0,
                "longitude": 121.5,
                "note": f"journey-{action}",
            },
            headers=self._write_headers(authorization, key),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_complete_mobile_journey_is_visible_through_shared_desktop_apis(self):
        authorization = self._login()

        created = self.client.post(
            "/api/v1/field-visits",
            json={
                "visit_date": "2026-07-28",
                "title": "完整外勤驗收",
            },
            headers=self._write_headers(authorization, "journey-route-001"),
        )
        self.assertEqual(created.status_code, 201, created.text)
        route_id = created.json()["id"]

        added = self.client.post(
            f"/api/v1/field-visits/{route_id}/items",
            json={
                "items": [
                    {"ownership_id": 101, "priority": 100},
                    {"ownership_id": 102},
                    {"ownership_id": 103},
                ]
            },
            headers=self._write_headers(authorization, "journey-items-001"),
        )
        self.assertEqual(added.status_code, 201, added.text)
        self.assertEqual(added.json()["added_count"], 3)

        today = self.client.get(
            "/api/v1/field-visits/today",
            params={"visit_date": "2026-07-28"},
            headers=authorization,
        )
        self.assertEqual(today.status_code, 200, today.text)
        self.assertEqual(len(today.json()["item"]["items"]), 3)

        preview = self.client.post(
            f"/api/v1/field-visits/{route_id}/optimize/preview",
            json={
                "current_latitude": 25.0,
                "current_longitude": 121.5,
                "keep_current_item_first": False,
            },
            headers=authorization,
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        plan = preview.json()
        applied = self.client.post(
            f"/api/v1/field-visits/{route_id}/optimize",
            json={
                "current_latitude": 25.0,
                "current_longitude": 121.5,
                "keep_current_item_first": False,
                "plan_token": plan["plan_token"],
            },
            headers=self._write_headers(authorization, "journey-optimize-001"),
        )
        self.assertEqual(applied.status_code, 200, applied.text)

        route = self.client.get(
            f"/api/v1/field-visits/{route_id}",
            headers=authorization,
        ).json()
        first, second, third = route["items"]
        self.assertEqual(first["priority"], 100)

        self._change_status(
            authorization, first["id"], "start", "journey-start-001"
        )
        contact = self.client.post(
            f"/api/v1/records/{first['record_id']}/contact-logs",
            json={
                "contact_date": "2026-07-28",
                "method": "面談",
                "result": "有意願",
                "note": "手機外勤新增",
                "latitude": 25.0,
                "longitude": 121.5,
                "field_visit_route_item_id": first["id"],
            },
            headers=self._write_headers(authorization, "journey-contact-001"),
        )
        self.assertEqual(contact.status_code, 201, contact.text)

        attachment = self.client.post(
            f"/api/v1/records/{first['record_id']}/attachments/upload",
            data={
                "description": "現場照片",
                "category": "外勤",
                "field_visit_route_item_id": str(first["id"]),
            },
            files={"file": ("visit.jpg", b"journey-photo", "image/jpeg")},
            headers=self._write_headers(
                authorization, "journey-attachment-001"
            ),
        )
        self.assertEqual(attachment.status_code, 201, attachment.text)
        self._change_status(
            authorization, first["id"], "complete", "journey-complete-001"
        )

        self._change_status(
            authorization, second["id"], "skip", "journey-skip-001"
        )

        remaining_preview = self.client.post(
            f"/api/v1/field-visits/{route_id}/optimize/preview",
            json={
                "current_latitude": 25.002,
                "current_longitude": 121.502,
                "keep_current_item_first": False,
            },
            headers=authorization,
        )
        self.assertEqual(
            remaining_preview.status_code, 200, remaining_preview.text
        )
        remaining_plan = remaining_preview.json()
        self.assertEqual(len(remaining_plan["items"]), 1)
        remaining_applied = self.client.post(
            f"/api/v1/field-visits/{route_id}/optimize",
            json={
                "current_latitude": 25.002,
                "current_longitude": 121.502,
                "keep_current_item_first": False,
                "plan_token": remaining_plan["plan_token"],
            },
            headers=self._write_headers(
                authorization, "journey-optimize-002"
            ),
        )
        self.assertEqual(
            remaining_applied.status_code, 200, remaining_applied.text
        )

        self._change_status(
            authorization, third["id"], "start", "journey-start-003"
        )
        self._change_status(
            authorization, third["id"], "complete", "journey-complete-003"
        )

        finished = self.client.get(
            f"/api/v1/field-visits/{route_id}",
            headers=authorization,
        )
        self.assertEqual(finished.status_code, 200, finished.text)
        self.assertEqual(finished.json()["status"], "completed")
        self.assertEqual(
            {item["status"] for item in finished.json()["items"]},
            {"completed", "skipped"},
        )

        desktop_contacts = self.client.get(
            f"/api/v1/records/{first['record_id']}/contact-logs",
            headers=authorization,
        )
        self.assertEqual(desktop_contacts.status_code, 200)
        self.assertEqual(
            desktop_contacts.json()["items"][0][
                "field_visit_route_item_id"
            ],
            first["id"],
        )
        desktop_attachments = self.client.get(
            f"/api/v1/records/{first['record_id']}/attachments",
            headers=authorization,
        )
        self.assertEqual(desktop_attachments.status_code, 200)
        self.assertEqual(
            desktop_attachments.json()["items"][0][
                "field_visit_route_item_id"
            ],
            first["id"],
        )
        self.assertEqual(
            desktop_attachments.json()["items"][0]["original_name"],
            "visit.jpg",
        )


if __name__ == "__main__":
    unittest.main()
