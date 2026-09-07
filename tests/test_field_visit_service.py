import unittest
from datetime import date, datetime, timezone

from customer_api.field_visit_permissions import (
    FIELD_VISIT_ADMIN,
    FIELD_VISIT_ATTACHMENT_DELETE_ALL,
    FIELD_VISIT_CREATE,
    FIELD_VISIT_VIEW,
    FieldVisitPermissionDenied,
    can_delete_field_visit_attachment,
    field_visit_capabilities,
)
from customer_api.field_visit_service import (
    FieldVisitItemInput,
    FieldVisitPlanConflict,
    FieldVisitService,
    FieldVisitTransitionError,
    field_visit_request_hash,
    location_address_fingerprint,
    normalize_location_address,
    normalize_item_inputs,
    validate_status_transition,
)
from customer_api.types import AuthenticatedUser


class _Source:
    def __init__(self):
        self.calls = []
        self.candidates = {
            "id": 1,
            "start_latitude": None,
            "start_longitude": None,
            "total_distance_km": None,
            "items": [
                {
                    "id": 1,
                    "status": "completed",
                    "priority": 0,
                    "route_order": 1,
                    "is_order_locked": False,
                    "estimated_distance_km": 1.0,
                    "latitude": 25.001,
                    "longitude": 121.5,
                    "updated_at": "2026-07-24T09:00:00+08:00",
                    "location_updated_at": "2026-07-24T08:00:00+08:00",
                },
                {
                    "id": 2,
                    "status": "planned",
                    "priority": 0,
                    "route_order": 2,
                    "is_order_locked": False,
                    "estimated_distance_km": None,
                    "latitude": 25.03,
                    "longitude": 121.5,
                    "updated_at": "2026-07-24T09:00:00+08:00",
                    "location_updated_at": "2026-07-24T08:00:00+08:00",
                },
                {
                    "id": 3,
                    "status": "planned",
                    "priority": 10,
                    "route_order": 3,
                    "is_order_locked": False,
                    "estimated_distance_km": None,
                    "latitude": 25.02,
                    "longitude": 121.5,
                    "updated_at": "2026-07-24T09:00:00+08:00",
                    "location_updated_at": "2026-07-24T08:00:00+08:00",
                },
                {
                    "id": 4,
                    "status": "postponed",
                    "priority": 99,
                    "route_order": 4,
                    "is_order_locked": False,
                    "estimated_distance_km": None,
                    "latitude": None,
                    "longitude": None,
                    "updated_at": "2026-07-24T09:00:00+08:00",
                    "location_updated_at": None,
                },
            ],
        }

    def get_today_field_visit(self, user, visit_date):
        self.calls.append(("today", user.id, visit_date))
        return {"id": 1}

    def list_unresolved_field_visit_items(self, user, mine_only=False):
        self.calls.append(("unresolved", user.id, mine_only))
        return [{"id": 1, "status": "planned"}]

    def list_visit_calendar_items(self, user, start_date, end_date, mine_only=False):
        self.calls.append(("calendar", user.id, start_date, end_date, mine_only))
        return [{"id": 1, "calendar_status": "scheduled"}]

    def get_field_visit_route(self, user, route_id):
        self.calls.append(("get", user.id, route_id))
        return {"id": route_id}

    def create_field_visit_route(self, user, values, **options):
        self.calls.append(("create", user.id, values, options))
        return {"id": 1, "created": True}

    def add_field_visit_items(self, user, route_id, items, **options):
        self.calls.append(("add", user.id, route_id, items, options))
        return {"route_id": route_id, "added_count": len(items)}

    def transition_field_visit_item(
        self, user, item_id, new_status, **options
    ):
        self.calls.append(("transition", user.id, item_id, new_status, options))
        return {"item_id": item_id, "new_status": new_status, "changed": True}

    def update_field_visit_item(self, user, item_id, **options):
        self.calls.append(("update_item", user.id, item_id, options))
        return {
            "item_id": item_id,
            "priority": options.get("priority"),
            "is_order_locked": options.get("is_order_locked"),
            "changed": True,
        }

    def get_field_visit_route_candidates(self, user, route_id):
        self.calls.append(("candidates", user.id, route_id))
        result = dict(self.candidates)
        result["items"] = [dict(item) for item in self.candidates["items"]]
        return result

    def apply_field_visit_route_order(
        self, user, route_id, plan_items, **options
    ):
        self.calls.append(("apply_order", user.id, route_id, plan_items, options))
        return {
            "route_id": route_id,
            "applied": True,
            "updated_count": len(plan_items),
            "items": plan_items,
        }


def _user(role):
    return AuthenticatedUser(
        id={"admin": 1, "editor": 2, "viewer": 3}[role],
        username=role,
        display_name=role,
        role=role,
        data_key=b"x" * 32,
    )


class FieldVisitServiceTests(unittest.TestCase):
    def test_role_capabilities_are_server_side_and_least_privilege(self):
        self.assertIn(FIELD_VISIT_VIEW, field_visit_capabilities("viewer"))
        self.assertNotIn(FIELD_VISIT_CREATE, field_visit_capabilities("viewer"))
        self.assertIn(FIELD_VISIT_CREATE, field_visit_capabilities("editor"))
        self.assertNotIn(
            FIELD_VISIT_ATTACHMENT_DELETE_ALL,
            field_visit_capabilities("editor"),
        )
        self.assertIn(FIELD_VISIT_ADMIN, field_visit_capabilities("admin"))
        self.assertEqual(field_visit_capabilities("unknown"), frozenset())

    def test_attachment_delete_permission_requires_owner_or_admin(self):
        self.assertTrue(can_delete_field_visit_attachment(_user("editor"), 2))
        self.assertFalse(can_delete_field_visit_attachment(_user("editor"), 99))
        self.assertFalse(can_delete_field_visit_attachment(_user("editor"), None))
        self.assertFalse(can_delete_field_visit_attachment(_user("viewer"), 3))
        self.assertTrue(can_delete_field_visit_attachment(_user("admin"), 99))
        self.assertTrue(can_delete_field_visit_attachment(_user("admin"), None))

    def test_status_transition_rules(self):
        allowed = (
            ("planned", "in_progress"),
            ("planned", "skipped"),
            ("in_progress", "completed"),
            ("postponed", "planned"),
            ("skipped", "postponed"),
            ("cancelled", "planned"),
            ("completed", "completed"),
        )
        for old_status, new_status in allowed:
            with self.subTest(old_status=old_status, new_status=new_status):
                validate_status_transition(old_status, new_status)

        rejected = (
            ("planned", "completed"),
            ("completed", "planned"),
            ("cancelled", "in_progress"),
            ("unknown", "planned"),
        )
        for old_status, new_status in rejected:
            with self.subTest(old_status=old_status, new_status=new_status):
                with self.assertRaises(FieldVisitTransitionError):
                    validate_status_transition(old_status, new_status)

    def test_request_hash_is_stable_but_changes_with_payload(self):
        first = field_visit_request_hash(
            "create",
            {"date": date(2026, 7, 24), "title": "A", "nested": {"b": 2, "a": 1}},
        )
        reordered = field_visit_request_hash(
            "create",
            {"nested": {"a": 1, "b": 2}, "title": "A", "date": date(2026, 7, 24)},
        )
        changed = field_visit_request_hash(
            "create",
            {"date": date(2026, 7, 24), "title": "B", "nested": {"a": 1, "b": 2}},
        )
        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)
        self.assertEqual(len(first), 64)

    def test_address_fingerprint_ignores_spacing_but_detects_real_change(self):
        compact = location_address_fingerprint("桃園市 中路 1 號")
        extra_spacing = location_address_fingerprint("  桃園市   中路 1 號  ")
        changed = location_address_fingerprint("桃園市 中路 2 號")

        self.assertEqual(compact, extra_spacing)
        self.assertNotEqual(compact, changed)
        self.assertEqual(
            normalize_location_address(" A  Road\n1 "),
            "a road 1",
        )

    def test_item_inputs_reject_duplicates_and_locked_items_without_order(self):
        normalized = normalize_item_inputs(
            [
                FieldVisitItemInput(ownership_id=7, priority=10),
                {
                    "ownership_id": 8,
                    "route_order": 2,
                    "is_order_locked": True,
                    "note": "優先拜訪",
                },
            ]
        )
        self.assertEqual([item["ownership_id"] for item in normalized], [7, 8])
        self.assertTrue(normalized[1]["is_order_locked"])

        with self.assertRaises(ValueError):
            normalize_item_inputs(
                [FieldVisitItemInput(7), FieldVisitItemInput(7)]
            )
        with self.assertRaises(ValueError):
            normalize_item_inputs(
                [{"ownership_id": 7, "is_order_locked": True}]
            )

    def test_viewer_can_read_but_cannot_create_or_change(self):
        source = _Source()
        service = FieldVisitService(source)
        viewer = _user("viewer")

        self.assertEqual(service.get_today(viewer, date(2026, 7, 24)), {"id": 1})
        self.assertEqual(
            service.list_unresolved(viewer, mine_only=True),
            [{"id": 1, "status": "planned"}],
        )
        self.assertEqual(source.calls[-1], ("unresolved", viewer.id, True))
        self.assertEqual(
            service.list_calendar_items(
                viewer, start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), mine_only=True
            ),
            [{"id": 1, "calendar_status": "scheduled"}],
        )
        self.assertEqual(
            source.calls[-1],
            ("calendar", viewer.id, date(2026, 8, 1), date(2026, 8, 31), True),
        )
        with self.assertRaises(FieldVisitPermissionDenied):
            service.create_route(viewer, visit_date=date(2026, 7, 24))
        with self.assertRaises(FieldVisitPermissionDenied):
            service.transition_item(viewer, 1, "skipped")

    def test_editor_create_add_and_transition_are_normalized_before_repository(self):
        source = _Source()
        service = FieldVisitService(source)
        editor = _user("editor")

        created = service.create_route(
            editor,
            visit_date=date(2026, 7, 24),
            title="  今日中路段  ",
            start_latitude="25.01",
            start_longitude="121.51",
            idempotency_key=" route-20260724 ",
        )
        self.assertTrue(created["created"])
        create_call = source.calls[-1]
        self.assertEqual(create_call[2]["title"], "今日中路段")
        self.assertEqual(create_call[2]["start_latitude"], 25.01)
        self.assertEqual(create_call[3]["idempotency_key"], "route-20260724")
        self.assertEqual(len(create_call[3]["request_hash"]), 64)

        service.add_items(
            editor,
            1,
            [FieldVisitItemInput(ownership_id=7, priority=5)],
            idempotency_key="add-7",
        )
        add_call = source.calls[-1]
        self.assertEqual(add_call[3][0]["ownership_id"], 7)

        postponed_until = datetime(2026, 7, 24, 15, 0, tzinfo=timezone.utc)
        service.transition_item(
            editor,
            9,
            "postponed",
            latitude=25.02,
            longitude=121.52,
            note="地主下午才在家",
            postponed_until=postponed_until,
            idempotency_key="postpone-9",
        )
        transition_call = source.calls[-1]
        self.assertEqual(transition_call[3], "postponed")
        self.assertEqual(transition_call[4]["latitude"], 25.02)
        self.assertEqual(transition_call[4]["postponed_until"], postponed_until)

    def test_partial_gps_is_rejected_before_repository_call(self):
        source = _Source()
        service = FieldVisitService(source)
        with self.assertRaises(ValueError):
            service.transition_item(
                _user("editor"),
                1,
                "skipped",
                latitude=25.0,
                longitude=None,
            )
        self.assertEqual(source.calls, [])

    def test_editor_can_set_priority_and_unlock_item(self):
        source = _Source()
        service = FieldVisitService(source)
        result = service.update_item(
            _user("editor"),
            7,
            priority=10,
            is_order_locked=False,
            idempotency_key="priority-item-007",
        )

        self.assertTrue(result["changed"])
        call = source.calls[-1]
        self.assertEqual(call[:3], ("update_item", 2, 7))
        self.assertEqual(call[3]["priority"], 10)
        self.assertFalse(call[3]["is_order_locked"])
        self.assertEqual(call[3]["idempotency_key"], "priority-item-007")
        self.assertEqual(len(call[3]["request_hash"]), 64)

    def test_priority_rejects_viewer_invalid_range_and_empty_change(self):
        source = _Source()
        service = FieldVisitService(source)
        with self.assertRaises(FieldVisitPermissionDenied):
            service.update_item(
                _user("viewer"),
                7,
                priority=10,
                idempotency_key="priority-viewer-007",
            )
        with self.assertRaises(ValueError):
            service.update_item(
                _user("editor"),
                7,
                priority=101,
                idempotency_key="priority-invalid-007",
            )
        with self.assertRaises(ValueError):
            service.update_item(
                _user("editor"),
                7,
                idempotency_key="priority-empty-007",
            )

    def test_optimization_preview_preserves_excluded_slots_and_orders_groups(self):
        source = _Source()
        service = FieldVisitService(source)
        preview = service.preview_optimization(
            _user("editor"),
            1,
            current_latitude=25.0,
            current_longitude=121.5,
            keep_current_item_first=False,
        )

        self.assertEqual(preview["excluded_item_ids"], [1])
        self.assertEqual(
            [item["item_id"] for item in preview["items"]],
            [3, 2, 4],
        )
        self.assertEqual(
            [item["route_order"] for item in preview["items"]],
            [2, 3, 4],
        )
        self.assertEqual(len(preview["plan_token"]), 64)
        self.assertIsNone(preview["items"][-1]["estimated_distance_km"])

    def test_reoptimization_keeps_current_item_and_excludes_finished_items(self):
        source = _Source()
        source.candidates["items"][1]["status"] = "in_progress"
        source.candidates["items"][2]["status"] = "skipped"
        service = FieldVisitService(source)

        preview = service.preview_optimization(
            _user("editor"),
            1,
            current_latitude=25.0,
            current_longitude=121.5,
            keep_current_item_first=True,
            current_item_id=2,
        )

        self.assertEqual(preview["current_item_id"], 2)
        self.assertEqual(preview["excluded_item_ids"], [1, 3])
        self.assertEqual(
            [item["item_id"] for item in preview["items"]],
            [2, 4],
        )
        self.assertEqual(
            [item["route_order"] for item in preview["items"]],
            [2, 4],
        )

    def test_optimization_requires_matching_preview_token(self):
        source = _Source()
        service = FieldVisitService(source)
        editor = _user("editor")
        preview = service.preview_optimization(
            editor,
            1,
            current_latitude=25.0,
            current_longitude=121.5,
            keep_current_item_first=False,
        )
        result = service.apply_optimization(
            editor,
            1,
            current_latitude=25.0,
            current_longitude=121.5,
            plan_token=preview["plan_token"],
            keep_current_item_first=False,
            idempotency_key="apply-plan-001",
        )
        self.assertTrue(result["applied"])
        apply_call = source.calls[-1]
        self.assertEqual(apply_call[0], "apply_order")
        self.assertEqual(
            apply_call[4]["action_type"],
            "api_optimize_field_visit_route",
        )

        source.candidates["items"][1]["status"] = "skipped"
        with self.assertRaises(FieldVisitPlanConflict) as context:
            service.apply_optimization(
                editor,
                1,
                current_latitude=25.0,
                current_longitude=121.5,
                plan_token=preview["plan_token"],
                keep_current_item_first=False,
                idempotency_key="apply-plan-002",
            )
        self.assertIn("changed", str(context.exception))

    def test_manual_order_uses_remaining_slots_and_locks_items(self):
        source = _Source()
        service = FieldVisitService(source)
        result = service.apply_manual_order(
            _user("editor"),
            1,
            [
                {"item_id": 2, "is_order_locked": True},
                {"item_id": 4, "is_order_locked": False},
                {"item_id": 3, "is_order_locked": True},
            ],
            idempotency_key="manual-order-001",
        )
        self.assertTrue(result["applied"])
        plan_items = source.calls[-1][3]
        self.assertEqual(
            [(item["item_id"], item["route_order"]) for item in plan_items],
            [(2, 2), (4, 3), (3, 4)],
        )
        self.assertEqual(
            [item["is_order_locked"] for item in plan_items],
            [True, False, True],
        )

    def test_manual_order_rejects_missing_remaining_item(self):
        service = FieldVisitService(_Source())
        with self.assertRaises(FieldVisitPlanConflict):
            service.apply_manual_order(
                _user("editor"),
                1,
                [{"item_id": 2}, {"item_id": 3}],
                idempotency_key="manual-order-002",
            )

    def test_cancel_requires_planned_source_status(self):
        source = _Source()
        service = FieldVisitService(source)

        result = service.transition_item(
            _user("editor"),
            2,
            "cancelled",
            note="從今日行程移除",
            idempotency_key="cancel-planned-001",
            allowed_old_statuses={"planned"},
        )

        self.assertTrue(result["changed"])
        options = source.calls[-1][4]
        self.assertEqual(options["allowed_old_statuses"], {"planned"})


if __name__ == "__main__":
    unittest.main()
