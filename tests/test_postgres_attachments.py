import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from customer_api.field_visit_permissions import FieldVisitPermissionDenied
from customer_api.postgres_attachments import PostgreSQLAttachmentMixin
from customer_api.types import AuthenticatedUser


def _user(user_id, role):
    return AuthenticatedUser(
        id=user_id,
        username=f"{role}-{user_id}",
        display_name=role,
        role=role,
        data_key=b"x" * 32,
    )


class _Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class _Connection:
    def __init__(self, row):
        self.row = dict(row)
        self.calls = []

    def execute(self, query, parameters=()):
        normalized = " ".join(str(query).split())
        self.calls.append((normalized, tuple(parameters)))
        if normalized.startswith("SELECT id, ownership_id AS customer_id"):
            return _Result([dict(self.row)] if self.row else [])
        if normalized.startswith("SELECT storage_path, status, created_by"):
            return _Result([dict(self.row)] if self.row else [])
        if normalized.startswith("DELETE FROM attachments"):
            deleted = dict(self.row) if self.row else None
            self.row = {}
            return _Result([deleted] if deleted else [])
        if normalized.startswith("INSERT INTO attachments"):
            return _Result([{"id": 8}])
        return _Result()


class _Source(PostgreSQLAttachmentMixin):
    def __init__(self, row, attachment_directory):
        self.connection = _Connection(row)
        self.link_calls = []
        self.cached_result = None
        self.idempotency_locks = []
        self.idempotency_saves = []
        self.settings = SimpleNamespace(
            attachment_directory=Path(attachment_directory)
        )

    @contextmanager
    def _connect(self):
        yield self.connection

    @staticmethod
    def _require_ids(_conn, _table_name, _ids):
        return None

    @staticmethod
    def _record_attachment_links(_conn, _record_id):
        return 21, 31

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


class PostgreSQLAttachmentPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp_context = tempfile.TemporaryDirectory()
        self.row = {
            "id": 7,
            "customer_id": 11,
            "ownership_id": 11,
            "file_path": "managed.txt",
            "storage_path": "",
            "original_name": "managed.txt",
            "description": None,
            "category": None,
            "media_type": "text/plain",
            "sha256": "abc",
            "size_bytes": 3,
            "status": "managed",
            "version": 1,
            "contact_log_id": None,
            "field_visit_route_item_id": None,
            "created_by": 2,
            "created_at": "2026-07-27T12:00:00+08:00",
        }

    def tearDown(self):
        self.temp_context.cleanup()

    def test_list_exposes_decision_but_not_uploader_id(self):
        source = _Source(self.row, self.temp_context.name)

        owner_item = source.list_attachments(_user(2, "editor"), 11)[0]
        other_item = source.list_attachments(_user(3, "editor"), 11)[0]
        admin_item = source.list_attachments(_user(1, "admin"), 11)[0]

        self.assertTrue(owner_item["can_delete"])
        self.assertFalse(other_item["can_delete"])
        self.assertTrue(admin_item["can_delete"])
        self.assertNotIn("created_by", owner_item)

    def test_non_uploader_is_rejected_before_delete(self):
        source = _Source(self.row, self.temp_context.name)

        with self.assertRaises(FieldVisitPermissionDenied):
            source.delete_attachment(_user(3, "editor"), 11, 7)

        self.assertTrue(source.connection.row)
        self.assertFalse(
            any(
                query.startswith("DELETE FROM attachments")
                for query, _parameters in source.connection.calls
            )
        )

    def test_admin_can_delete_another_users_attachment(self):
        source = _Source(self.row, self.temp_context.name)

        self.assertTrue(source.delete_attachment(_user(1, "admin"), 11, 7))
        self.assertFalse(source.connection.row)
        self.assertTrue(
            any(
                query.startswith("INSERT INTO audit_logs")
                for query, _parameters in source.connection.calls
            )
        )

    def test_managed_upload_persists_field_visit_context(self):
        source = _Source(self.row, self.temp_context.name)
        upload = Path(self.temp_context.name) / "field-photo.jpg"
        upload.write_bytes(b"field-photo")

        attachment_id = source.import_managed_attachment(
            _user(2, "editor"),
            11,
            upload,
            "field-photo.jpg",
            category="現場照片",
            field_visit_route_item_id=9,
        )

        self.assertEqual(attachment_id, 8)
        self.assertEqual(source.link_calls[0][2:], (11, 9))
        insert_query, insert_params = next(
            call
            for call in source.connection.calls
            if call[0].startswith("INSERT INTO attachments")
        )
        self.assertIn("field_visit_route_item_id", insert_query)
        self.assertEqual(insert_params[-2], 9)

    def test_managed_upload_retry_removes_temporary_copy_and_uses_cached_result(self):
        source = _Source(self.row, self.temp_context.name)
        source.cached_result = {"id": 44}
        upload = Path(self.temp_context.name) / "retry-photo.jpg"
        upload.write_bytes(b"same-photo")

        attachment_id = source.import_managed_attachment(
            _user(2, "editor"),
            11,
            upload,
            "retry-photo.jpg",
            idempotency_key="mobile-attachment-retry",
            request_hash="same-request",
        )

        self.assertEqual(attachment_id, 44)
        self.assertFalse(
            any(
                query.startswith("INSERT INTO attachments")
                for query, _parameters in source.connection.calls
            )
        )
        copied_files = list((Path(self.temp_context.name) / "11").glob("*"))
        self.assertEqual(copied_files, [])


if __name__ == "__main__":
    unittest.main()
