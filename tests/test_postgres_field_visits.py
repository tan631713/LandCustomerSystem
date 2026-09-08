import unittest
from base64 import urlsafe_b64encode

from customer_api.field_visit_service import (
    FieldVisitIdempotencyConflict,
    FieldVisitPlanConflict,
    FieldVisitTransitionError,
)
from customer_api.postgres_field_visits import PostgreSQLFieldVisitMixin
from customer_api.types import AuthenticatedUser


class _Result:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return self.value

    def fetchall(self):
        return list(self.value or [])


class _Connection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(str(query).split())
        self.calls.append((normalized, params))
        if not self.responses:
            raise AssertionError(f"unexpected SQL call: {normalized}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _Result(response)


class _Source(PostgreSQLFieldVisitMixin):
    def __init__(self, connection):
        self.connection = connection

    def _connect(self):
        return self.connection


USER = AuthenticatedUser(
    id=2,
    username="editor",
    display_name="Editor",
    role="editor",
    data_key=b"x" * 32,
)


class PostgreSQLFieldVisitTests(unittest.TestCase):
    def test_field_visit_link_requires_matching_record_and_route_owner(self):
        connection = _Connection(
            [{"id": 9, "ownership_id": 101, "user_id": USER.id}]
        )

        item_id = _Source(connection)._require_field_visit_item_link(
            connection, USER, 101, 9
        )

        self.assertEqual(item_id, 9)
        self.assertEqual(connection.calls[0][1], (9, 101))
        self.assertIn("item.ownership_id = %s", connection.calls[0][0])

    def test_field_visit_link_rejects_another_users_route(self):
        connection = _Connection(
            [{"id": 9, "ownership_id": 101, "user_id": 99}]
        )

        with self.assertRaises(PermissionError):
            _Source(connection)._require_field_visit_item_link(
                connection, USER, 101, 9
            )

    def test_field_visit_link_rejects_mismatched_record(self):
        connection = _Connection([None])

        with self.assertRaises(ValueError):
            _Source(connection)._require_field_visit_item_link(
                connection, USER, 102, 9
            )

    def test_route_items_include_shared_contact_and_attachment_counts(self):
        route = {
            "id": 4,
            "user_id": 2,
            "visit_date": "2026-07-27",
            "title": "今日外勤",
            "status": "planned",
        }
        item = {
            "id": 9,
            "route_id": 4,
            "ownership_id": 101,
            "contact_log_count": 3,
            "attachment_count": 2,
        }
        user = AuthenticatedUser(
            id=2,
            username="editor",
            display_name="Editor",
            role="editor",
            data_key=urlsafe_b64encode(b"x" * 32),
        )
        connection = _Connection([route, [item]])

        result = _Source(connection).get_field_visit_route(user, 4)

        self.assertEqual(result["items"][0]["ownership_id"], 101)
        self.assertEqual(result["items"][0]["contact_log_count"], 3)
        self.assertEqual(result["items"][0]["attachment_count"], 2)
        route_query = connection.calls[1][0]
        self.assertIn("FROM contact_logs log", route_query)
        self.assertIn("FROM attachments attachment", route_query)
        self.assertIn("AS contact_log_count", route_query)
        self.assertIn("AS attachment_count", route_query)
        self.assertIn(
            "CASE WHEN location.geocode_status IN ('manual', 'success')",
            route_query,
        )

    def test_cached_idempotent_transition_returns_without_writing_again(self):
        cached = {
            "item_id": 9,
            "route_id": 4,
            "old_status": "planned",
            "new_status": "skipped",
            "changed": True,
            "history_id": 11,
        }
        connection = _Connection(
            [
                None,
                None,
                {
                    "request_hash": "same-hash",
                    "response_json": cached,
                    "status_code": 200,
                },
            ]
        )
        result = _Source(connection).transition_field_visit_item(
            USER,
            9,
            "skipped",
            idempotency_key="skip-9",
            request_hash="same-hash",
        )

        self.assertEqual(result, cached)
        self.assertEqual(len(connection.calls), 3)
        self.assertIn("pg_advisory_xact_lock", connection.calls[0][0])
        self.assertIn("field_visit_idempotency_keys", connection.calls[2][0])

    def test_update_priority_is_transactional_audited_and_idempotent(self):
        current = {
            "id": 9,
            "route_id": 4,
            "status": "planned",
            "priority": 0,
            "is_order_locked": True,
            "user_id": 2,
        }
        connection = _Connection([None, None, None, current, None, None, None])

        result = _Source(connection).update_field_visit_item(
            USER,
            9,
            priority=10,
            is_order_locked=False,
            idempotency_key="priority-item-009",
            request_hash="priority-hash",
        )

        self.assertTrue(result["changed"])
        self.assertEqual(result["priority"], 10)
        self.assertFalse(result["is_order_locked"])
        self.assertIn("FOR UPDATE OF item, route", connection.calls[3][0])
        self.assertIn("SET priority = %s", connection.calls[4][0])
        self.assertEqual(connection.calls[4][1], (10, False, 9))
        self.assertIn("INSERT INTO audit_logs", connection.calls[5][0])
        self.assertIn("field_visit_idempotency_keys", connection.calls[6][0])

    def test_update_priority_rejects_finished_item(self):
        current = {
            "id": 9,
            "route_id": 4,
            "status": "completed",
            "priority": 0,
            "is_order_locked": False,
            "user_id": 2,
        }
        connection = _Connection([current])

        with self.assertRaises(FieldVisitTransitionError):
            _Source(connection).update_field_visit_item(
                USER,
                9,
                priority=10,
                request_hash="priority-finished",
            )

        self.assertEqual(len(connection.calls), 1)
        self.assertIn("FOR UPDATE OF item, route", connection.calls[0][0])

    def test_reusing_idempotency_key_for_different_payload_is_rejected(self):
        connection = _Connection(
            [
                None,
                None,
                {
                    "request_hash": "old-hash",
                    "response_json": {"item_id": 9},
                    "status_code": 200,
                },
            ]
        )
        with self.assertRaises(FieldVisitIdempotencyConflict):
            _Source(connection).transition_field_visit_item(
                USER,
                9,
                "skipped",
                idempotency_key="same-key",
                request_hash="new-hash",
            )
        self.assertEqual(len(connection.calls), 3)

    def test_transition_updates_item_history_route_audit_and_idempotency_atomically(self):
        connection = _Connection(
            [
                None,  # advisory transaction lock
                None,  # expired idempotency cleanup
                None,  # no cached response
                {
                    "id": 9,
                    "route_id": 4,
                    "status": "in_progress",
                    "user_id": 2,
                    "ownership_id": 42,
                },
                {
                    "id": 9,
                    "route_id": 4,
                    "status": "completed",
                    "arrived_at": "2026-07-24T10:00:00+08:00",
                    "completed_at": "2026-07-24T10:30:00+08:00",
                    "postponed_until": None,
                    "updated_at": "2026-07-24T10:30:00+08:00",
                },
                {"id": 15},
                {"id": 20},  # auto contact-log insert for the completed status
                None,  # mark route in progress
                {"remaining": 0},
                None,  # complete route
                None,  # audit
                None,  # save idempotency response
            ]
        )
        result = _Source(connection).transition_field_visit_item(
            USER,
            9,
            "completed",
            latitude=25.01,
            longitude=121.51,
            note="已完成拜訪",
            idempotency_key="complete-9",
            request_hash="complete-hash",
        )

        self.assertTrue(result["changed"])
        self.assertEqual(result["history_id"], 15)
        statements = "\n".join(query for query, _params in connection.calls)
        self.assertIn("FOR UPDATE OF item, route", statements)
        self.assertIn("UPDATE field_visit_route_items", statements)
        self.assertIn("INSERT INTO field_visit_status_history", statements)
        self.assertIn("SET status = 'completed'", statements)
        self.assertIn("INSERT INTO audit_logs", statements)
        self.assertIn("INSERT INTO field_visit_idempotency_keys", statements)
        self.assertEqual(connection.responses, [])

    def test_non_owner_cannot_transition_another_users_item(self):
        connection = _Connection(
            [
                {"id": 9, "route_id": 4, "status": "planned", "user_id": 99},
            ]
        )
        with self.assertRaises(PermissionError):
            _Source(connection).transition_field_visit_item(
                USER,
                9,
                "skipped",
                request_hash="hash",
            )
        self.assertEqual(len(connection.calls), 1)
        self.assertIn("FOR UPDATE OF item, route", connection.calls[0][0])

    def test_cancel_rejects_item_that_has_already_started(self):
        connection = _Connection(
            [
                {"id": 9, "route_id": 4, "status": "in_progress", "user_id": 2},
            ]
        )
        with self.assertRaisesRegex(FieldVisitTransitionError, "have not started"):
            _Source(connection).transition_field_visit_item(
                USER,
                9,
                "cancelled",
                allowed_old_statuses={"planned"},
                request_hash="cancel-hash",
            )
        self.assertEqual(len(connection.calls), 1)
        self.assertNotIn(
            "UPDATE field_visit_route_items",
            connection.calls[0][0],
        )

    def test_cancel_clears_postponed_until_with_explicit_timestamp_type(self):
        connection = _Connection(
            [
                {"id": 9, "route_id": 4, "status": "planned", "user_id": 2},
                {
                    "id": 9,
                    "route_id": 4,
                    "status": "cancelled",
                    "arrived_at": None,
                    "completed_at": None,
                    "postponed_until": None,
                    "updated_at": "cancelled",
                },
                {"id": 17},
                None,
                {"remaining": 1},
                None,
            ]
        )

        result = _Source(connection).transition_field_visit_item(
            USER,
            9,
            "cancelled",
            allowed_old_statuses={"planned"},
            note="從今日行程移除",
            request_hash="cancel-hash",
        )

        self.assertEqual(result["new_status"], "cancelled")
        update_query, update_params = connection.calls[1]
        self.assertIn("postponed_until = %s::timestamptz", update_query)
        self.assertNotIn("postponed_until = CASE", update_query)
        self.assertIsNone(update_params[3])
        self.assertEqual(len(update_params), 7)

    def test_restore_reopens_completed_route_and_clears_completion_time(self):
        connection = _Connection(
            [
                {"id": 9, "route_id": 4, "status": "cancelled", "user_id": 2},
                {
                    "id": 9,
                    "route_id": 4,
                    "status": "planned",
                    "arrived_at": None,
                    "completed_at": None,
                    "postponed_until": None,
                    "updated_at": "restored",
                },
                {"id": 16},
                None,
                {"remaining": 1},
                None,
            ]
        )

        result = _Source(connection).transition_field_visit_item(
            USER,
            9,
            "planned",
            allowed_old_statuses={"cancelled"},
            note="恢復至今日行程",
            request_hash="restore-hash",
        )

        self.assertEqual(result["new_status"], "planned")
        route_update, route_params = connection.calls[3]
        self.assertIn("completed_at = CASE", route_update)
        self.assertEqual(route_params, ("planned", "planned", 4))

    def test_apply_order_rejects_candidate_snapshot_changed_after_preview(self):
        route = {
            "id": 4,
            "user_id": 2,
            "visit_date": "2026-07-24",
            "title": "今日外勤",
            "status": "planned",
            "start_latitude": None,
            "start_longitude": None,
            "total_distance_km": None,
            "started_at": None,
            "completed_at": None,
            "created_at": "2026-07-24T08:00:00+08:00",
            "updated_at": "2026-07-24T08:00:00+08:00",
        }
        current = [
            {
                "id": 9,
                "status": "skipped",
                "priority": 0,
                "route_order": 1,
                "is_order_locked": False,
                "estimated_distance_km": None,
                "updated_at": "new-version",
                "latitude": 25.0,
                "longitude": 121.5,
                "location_updated_at": "location-version",
            }
        ]
        expected = [{**current[0], "status": "planned", "updated_at": "old-version"}]
        connection = _Connection([route, current])

        with self.assertRaises(FieldVisitPlanConflict):
            _Source(connection).apply_field_visit_route_order(
                USER,
                4,
                [
                    {
                        "item_id": 9,
                        "route_order": 1,
                        "estimated_distance_km": 1.0,
                    }
                ],
                expected_items=expected,
                request_hash="plan-hash",
            )
        self.assertEqual(len(connection.calls), 2)
        self.assertIn("FOR UPDATE", connection.calls[0][0])
        self.assertIn("FOR UPDATE OF item", connection.calls[1][0])

    def test_apply_order_updates_all_items_route_audit_and_idempotency(self):
        route = {
            "id": 4,
            "user_id": 2,
            "visit_date": "2026-07-24",
            "title": "今日外勤",
            "status": "planned",
            "start_latitude": None,
            "start_longitude": None,
            "total_distance_km": None,
            "started_at": None,
            "completed_at": None,
            "created_at": "2026-07-24T08:00:00+08:00",
            "updated_at": "2026-07-24T08:00:00+08:00",
        }
        current = [
            {
                "id": 9,
                "status": "planned",
                "priority": 0,
                "route_order": 1,
                "is_order_locked": False,
                "estimated_distance_km": None,
                "updated_at": "item-9",
                "latitude": 25.02,
                "longitude": 121.5,
                "location_updated_at": "location-9",
            },
            {
                "id": 10,
                "status": "planned",
                "priority": 0,
                "route_order": 2,
                "is_order_locked": False,
                "estimated_distance_km": None,
                "updated_at": "item-10",
                "latitude": 25.01,
                "longitude": 121.5,
                "location_updated_at": "location-10",
            },
        ]
        plan = [
            {
                "item_id": 10,
                "route_order": 1,
                "estimated_distance_km": 1.1,
            },
            {
                "item_id": 9,
                "route_order": 2,
                "estimated_distance_km": 1.1,
            },
        ]
        connection = _Connection(
            [
                None,
                None,
                None,
                route,
                current,
                None,
                None,
                None,
                None,
                None,
                None,
            ]
        )
        result = _Source(connection).apply_field_visit_route_order(
            USER,
            4,
            plan,
            expected_items=current,
            start_latitude=25.0,
            start_longitude=121.5,
            total_distance_km=2.2,
            idempotency_key="optimize-route-4",
            request_hash="plan-hash",
        )

        self.assertTrue(result["applied"])
        self.assertEqual(result["updated_count"], 2)
        statements = "\n".join(query for query, _params in connection.calls)
        self.assertIn(
            "SET CONSTRAINTS uq_field_visit_route_items_order DEFERRED",
            statements,
        )
        self.assertEqual(statements.count("UPDATE field_visit_route_items"), 2)
        self.assertIn("UPDATE field_visit_routes", statements)
        self.assertIn("INSERT INTO audit_logs", statements)
        self.assertIn("INSERT INTO field_visit_idempotency_keys", statements)
        self.assertEqual(connection.responses, [])


if __name__ == "__main__":
    unittest.main()
