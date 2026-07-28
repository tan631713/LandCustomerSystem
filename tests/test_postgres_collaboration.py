import unittest
from contextlib import contextmanager

from customer_api.postgres_collaboration import PostgreSQLCollaborationMixin
from customer_api.types import AuthenticatedUser


class _Result:
    def __init__(self, value=None):
        self.value = value

    def fetchone(self):
        return self.value

    def fetchall(self):
        return list(self.value or [])


class _Connection:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=()):
        normalized = " ".join(str(query).split())
        self.calls.append((normalized, tuple(params)))
        if normalized.startswith("SELECT 1 FROM ownerships"):
            return _Result({"exists": 1})
        if normalized.startswith("INSERT INTO contact_logs"):
            return _Result({"id": 17})
        return _Result()


class _Source(PostgreSQLCollaborationMixin):
    def __init__(self):
        self.connection = _Connection()
        self.link_calls = []
        self.cached_result = None
        self.idempotency_locks = []
        self.idempotency_saves = []

    @contextmanager
    def _connect(self):
        yield self.connection

    def _require_field_visit_item_link(
        self, connection, user, record_id, item_id
    ):
        self.link_calls.append((connection, user.id, record_id, item_id))
        return int(item_id)

    def _lock_idempotency_key(self, connection, user_id, key):
        self.idempotency_locks.append((connection, user_id, key))

    def _cached_idempotency_result(
        self, connection, user_id, key, request_hash
    ):
        return self.cached_result

    def _save_idempotency_result(
        self, connection, user_id, key, request_hash, response, *, status_code
    ):
        self.idempotency_saves.append(
            (connection, user_id, key, request_hash, response, status_code)
        )


USER = AuthenticatedUser(
    id=2,
    username="editor",
    display_name="Editor",
    role="editor",
    data_key=b"x" * 32,
)


class PostgreSQLCollaborationTests(unittest.TestCase):
    def test_contact_log_persists_field_visit_and_location_context(self):
        source = _Source()

        contact_id = source.add_contact_log(
            USER,
            101,
            {
                "method": "visit",
                "result": "contacted",
                "latitude": 25.01,
                "longitude": 121.51,
                "field_visit_route_item_id": 9,
            },
        )

        self.assertEqual(contact_id, 17)
        self.assertEqual(source.link_calls[0][2:], (101, 9))
        insert_query, insert_params = next(
            call
            for call in source.connection.calls
            if call[0].startswith("INSERT INTO contact_logs")
        )
        self.assertIn("latitude, longitude, field_visit_route_item_id", insert_query)
        self.assertEqual(insert_params[6:9], (25.01, 121.51, 9))

    def test_contact_log_retry_returns_cached_result_without_duplicate_insert(self):
        source = _Source()
        source.cached_result = {"id": 33}

        contact_id = source.add_contact_log(
            USER,
            101,
            {"method": "visit", "result": "contacted"},
            idempotency_key="mobile-contact-retry",
            request_hash="same-request",
        )

        self.assertEqual(contact_id, 33)
        self.assertEqual(source.idempotency_locks[0][1:], (2, "mobile-contact-retry"))
        self.assertFalse(
            any(
                query.startswith("INSERT INTO contact_logs")
                for query, _params in source.connection.calls
            )
        )


if __name__ == "__main__":
    unittest.main()
