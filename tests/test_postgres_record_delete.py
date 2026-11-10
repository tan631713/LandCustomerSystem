import unittest

from customer_api.postgres_records import PostgreSQLRecordMixin
from customer_api.postgres_remote_operations import PostgreSQLRemoteOperationMixin


class _Result:
    def __init__(self, *, one=None, many=None):
        self.one = one
        self.many = list(many or [])

    def fetchone(self):
        return self.one

    def fetchall(self):
        return list(self.many)


class _Connection:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(str(query).split())
        self.calls.append((normalized, params))
        return self.handler(normalized, params)


class _RemoteSource(PostgreSQLRemoteOperationMixin):
    RECORD_SELECT = "SELECT ownership.id FROM ownerships ownership"

    @staticmethod
    def _normalize_ids(values):
        return sorted({int(value) for value in values})


class _DeleteSource(PostgreSQLRecordMixin, PostgreSQLRemoteOperationMixin):
    RECORD_SELECT = "SELECT ownership.id FROM ownerships ownership"

    def __init__(self, connection):
        self.connection = connection

    def _connect(self):
        return self.connection

    @staticmethod
    def _normalize_ids(values):
        return sorted({int(value) for value in values})

    @staticmethod
    def _capture_record_snapshot(_conn, record_id):
        return {"record": {"id": int(record_id)}, "related": {}}


class _User:
    id = 7
    username = "admin"


class PostgreSQLRecordDeleteTests(unittest.TestCase):
    def test_snapshot_captures_field_visit_item_and_status_history(self):
        field_item = {
            "id": 41,
            "route_id": 5,
            "owner_id": 8,
            "ownership_id": 12,
            "land_id": 9,
            "route_order": 1,
        }
        history = {
            "id": 51,
            "route_item_id": 41,
            "old_status": "planned",
            "new_status": "completed",
        }

        def handler(query, _params):
            if query.startswith(_RemoteSource.RECORD_SELECT):
                return _Result(one={"id": 12})
            if "FROM field_visit_route_items" in query:
                return _Result(many=[field_item])
            if "FROM field_visit_status_history" in query:
                return _Result(many=[history])
            return _Result(many=[])

        snapshot = _RemoteSource()._capture_record_snapshot(
            _Connection(handler), 12
        )

        self.assertEqual(
            snapshot["related"]["field_visit_route_items"], [field_item]
        )
        self.assertEqual(
            snapshot["related"]["field_visit_status_history"], [history]
        )

    def test_delete_removes_field_visit_links_before_ownership(self):
        def handler(query, _params):
            if query.startswith(_DeleteSource.RECORD_SELECT):
                return _Result(
                    one={
                        "id": 12,
                        "district": "中壢區",
                        "section": "中路段",
                        "subsection": "",
                        "land_number": "1-3",
                    }
                )
            if query.startswith("DELETE FROM field_visit_route_items"):
                return _Result(many=[{"id": 41}])
            return _Result()

        connection = _Connection(handler)
        source = _DeleteSource(connection)

        self.assertTrue(source.delete_record(_User(), 12))

        statements = [query for query, _params in connection.calls]
        route_delete = next(
            index
            for index, query in enumerate(statements)
            if query.startswith("DELETE FROM field_visit_route_items")
        )
        ownership_delete = next(
            index
            for index, query in enumerate(statements)
            if query.startswith("DELETE FROM ownerships")
        )
        self.assertLess(route_delete, ownership_delete)
        self.assertTrue(
            any("INSERT INTO recycle_bin" in query for query in statements)
        )

    def test_restore_recreates_field_visit_item_and_history(self):
        def handler(query, _params):
            if query.startswith("SELECT 1 FROM field_visit_routes"):
                return _Result(one={"exists": 1})
            if query.startswith("SELECT 1 FROM field_visit_route_items"):
                return _Result(one=None)
            if query.startswith("INSERT INTO field_visit_route_items"):
                return _Result(one={"id": 41})
            return _Result()

        connection = _Connection(handler)
        related = {
            "field_visit_route_items": [
                {
                    "id": 41,
                    "route_id": 5,
                    "owner_id": 8,
                    "ownership_id": 12,
                    "land_id": 9,
                    "route_order": 1,
                    "status": "completed",
                }
            ],
            "field_visit_status_history": [
                {
                    "id": 51,
                    "route_item_id": 41,
                    "old_status": "planned",
                    "new_status": "completed",
                    "user_id": 7,
                }
            ],
        }

        restored = _RemoteSource._restore_field_visit_snapshot(
            connection, related, 12
        )

        self.assertEqual(restored, {41})
        statements = [query for query, _params in connection.calls]
        self.assertTrue(
            any(query.startswith("INSERT INTO field_visit_route_items") for query in statements)
        )
        self.assertTrue(
            any(query.startswith("INSERT INTO field_visit_status_history") for query in statements)
        )


if __name__ == "__main__":
    unittest.main()
