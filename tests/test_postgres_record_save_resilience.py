import base64
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from customer_api.error_reporting import install_server_error_reporting
from customer_api.postgres_desktop_features import PostgreSQLDesktopFeatureMixin
from customer_api.postgres_records import PostgreSQLRecordMixin
from customer_api.postgres_schema import POSTGRES_SCHEMA_PATH
from customer_api.postgres_source import PostgreSQLCustomerDataSource
from customer_security import encrypt_value, make_fernet


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _LandConnection:
    def __init__(self, existing_id=None):
        self.existing_id = existing_id
        self.calls = []

    def execute(self, query, parameters=None):
        sql = " ".join(str(query).split())
        self.calls.append((sql, parameters))
        if sql.startswith("SELECT id FROM lands"):
            return _Result(
                None if self.existing_id is None else {"id": self.existing_id}
            )
        if sql.startswith("UPDATE lands SET"):
            return _Result({"id": self.existing_id})
        if sql.startswith("INSERT INTO lands"):
            return _Result({"id": 91})
        raise AssertionError(f"Unexpected SQL: {sql}")


class _DatabaseConflict(Exception):
    sqlstate = "23505"

    def __init__(self, constraint_name):
        super().__init__("duplicate key")
        self.diag = type(
            "Diag",
            (),
            {
                "constraint_name": constraint_name,
                "table_name": "lands",
                "column_name": "",
            },
        )()


class _BatchCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def executemany(self, query, entries):
        self.calls.append((str(query), list(entries)))


class _Psycopg3StyleConnection:
    """Connection intentionally has no executemany, like psycopg 3."""

    def __init__(self):
        self.batch_cursor = _BatchCursor()
        self.executed = []

    def cursor(self):
        return self.batch_cursor

    def execute(self, query, parameters=None):
        self.executed.append((str(query), parameters))
        return _Result(None)


class _OwnershipSaveConnection:
    def __init__(self):
        self.calls = []

    def execute(self, query, parameters=None):
        sql = " ".join(str(query).split())
        self.calls.append((sql, parameters))
        if sql.startswith("SELECT 1 FROM ownerships"):
            return _Result({"exists": 1})
        if sql.startswith("SELECT COALESCE(ownership.address_override"):
            return _Result({"address": None})
        if sql.startswith("INSERT INTO owners"):
            return _Result({"id": 12})
        if sql.startswith("SELECT id FROM lands"):
            return _Result({"id": 34})
        if sql.startswith("UPDATE lands SET"):
            return _Result({"id": 34})
        if sql.startswith("UPDATE ownerships SET"):
            return _Result(None)
        if sql.startswith("UPDATE ownership_locations"):
            return _Result(None)
        if sql.startswith("INSERT INTO audit_logs"):
            return _Result(None)
        raise AssertionError(f"Unexpected SQL: {sql}")


class _DesktopFeatureSource(PostgreSQLDesktopFeatureMixin):
    @staticmethod
    def _require_ids(conn, table, ids):
        del conn, table, ids


class _LocationConnection:
    def __init__(self, encrypted_address):
        self.encrypted_address = encrypted_address
        self.calls = []

    def execute(self, query, parameters=None):
        sql = " ".join(str(query).split())
        self.calls.append((sql, parameters))
        if sql.startswith("SELECT COALESCE(ownership.address_override"):
            return _Result({"address": self.encrypted_address})
        if sql.startswith("INSERT INTO ownership_locations"):
            return _Result(None)
        if sql.startswith("INSERT INTO audit_logs"):
            return _Result(None)
        raise AssertionError(f"Unexpected SQL: {sql}")


class _LocationSource(PostgreSQLDesktopFeatureMixin):
    def __init__(self, connection):
        self.connection = connection

    @contextmanager
    def _connect(self):
        yield self.connection


class PostgreSQLRecordSaveResilienceTests(unittest.TestCase):
    VALUES = {
        "district": "桃園區",
        "section": "中路段",
        "subsection": "",
        "land_number": "1-3",
        "area": "100",
        "declared_value": "50000",
    }

    def test_existing_visible_parcel_is_updated_instead_of_inserted_again(self):
        conn = _LandConnection(existing_id=37)
        row = PostgreSQLRecordMixin._save_land(conn, self.VALUES)
        self.assertEqual(row["id"], 37)
        self.assertTrue(any(sql.startswith("UPDATE lands SET") for sql, _ in conn.calls))
        self.assertFalse(any(sql.startswith("INSERT INTO lands") for sql, _ in conn.calls))

    def test_new_parcel_is_inserted(self):
        conn = _LandConnection(existing_id=None)
        row = PostgreSQLRecordMixin._save_land(conn, self.VALUES)
        self.assertEqual(row["id"], 91)
        self.assertTrue(any(sql.startswith("INSERT INTO lands") for sql, _ in conn.calls))

    def test_change_history_batch_uses_psycopg_cursor_executemany(self):
        conn = _Psycopg3StyleConnection()
        source = _DesktopFeatureSource()
        user = type("User", (), {"username": "User"})()
        count = source._add_record_change_logs_with_conn(
            conn,
            user,
            [
                {
                    "record_id": 376,
                    "field_key": "note",
                    "field_label": "備註",
                    "old_value": "舊",
                    "new_value": "新",
                },
                {
                    "record_id": 376,
                    "field_key": "address",
                    "field_label": "地址",
                    "old_value": "甲",
                    "new_value": "乙",
                },
            ],
        )
        self.assertEqual(count, 2)
        self.assertEqual(len(conn.batch_cursor.calls), 1)
        self.assertEqual(len(conn.batch_cursor.calls[0][1]), 2)
        self.assertTrue(
            any("INSERT INTO operation_logs" in query for query, _ in conn.executed)
        )

    def test_record_update_writes_owner_values_to_selected_ownership(self):
        conn = _OwnershipSaveConnection()
        source = PostgreSQLRecordMixin()
        user = type(
            "User",
            (),
            {
                "id": 1,
                "username": "admin",
                "data_key": base64.urlsafe_b64encode(b"x" * 32),
            },
        )()
        values = {
            **self.VALUES,
            "owner_name": "王小明",
            "external_id": "A123456789",
            "address": "桃園市測試路1號",
        }

        saved_id = source._save_record_with_conn(
            conn, user, values, record_id=376
        )

        self.assertEqual(saved_id, 376)
        ownership_sql, parameters = next(
            (sql, parameters)
            for sql, parameters in conn.calls
            if sql.startswith("UPDATE ownerships SET")
        )
        self.assertIn("owner_name_override = %s", ownership_sql)
        self.assertIn("external_id_override = %s", ownership_sql)
        self.assertIn("address_override = %s", ownership_sql)
        self.assertEqual(parameters[-1], 376)
        self.assertTrue(all(parameters[index] for index in (-4, -3, -2)))
        location_sql, location_parameters = next(
            (sql, parameters)
            for sql, parameters in conn.calls
            if sql.startswith("UPDATE ownership_locations SET")
        )
        self.assertIn("geocode_status = 'pending'", location_sql)
        self.assertEqual(location_parameters[-1], 376)

    def test_manual_location_refreshes_geocode_metadata_and_audit(self):
        user = type(
            "User",
            (),
            {
                "id": 7,
                "username": "editor",
                "data_key": base64.urlsafe_b64encode(b"x" * 32),
            },
        )()
        encrypted_address = encrypt_value(
            make_fernet(user.data_key),
            "桃園市中路1號",
        )
        conn = _LocationConnection(encrypted_address)
        source = _LocationSource(conn)

        saved_id = source.set_record_location(
            user,
            376,
            24.991,
            121.302,
        )

        self.assertEqual(saved_id, 376)
        location_sql, parameters = next(
            (sql, parameters)
            for sql, parameters in conn.calls
            if sql.startswith("INSERT INTO ownership_locations")
        )
        self.assertIn("geocode_status", location_sql)
        self.assertIn("address_fingerprint", location_sql)
        self.assertEqual(parameters[1:6], (24.991, 121.302, "manual", "manual", "manual"))
        self.assertEqual(len(parameters[-1]), 64)
        self.assertTrue(
            any(
                sql.startswith("INSERT INTO audit_logs")
                for sql, _parameters in conn.calls
            )
        )

    def test_record_projection_prefers_ownership_specific_owner_values(self):
        select_sql = " ".join(PostgreSQLCustomerDataSource.RECORD_SELECT.split())
        self.assertIn(
            "COALESCE(ownership.owner_name_override, owner.owner_name) AS owner_name",
            select_sql,
        )
        self.assertIn(
            "COALESCE(ownership.external_id_override, owner.external_id) AS external_id",
            select_sql,
        )

    def test_schema_backfills_owner_values_for_existing_ownerships(self):
        schema = POSTGRES_SCHEMA_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "ALTER TABLE ownerships ADD COLUMN IF NOT EXISTS owner_name_override TEXT",
            schema,
        )
        self.assertIn("UPDATE ownerships ownership", schema)
        self.assertIn(
            "VALUES (6, 'ownership-specific owner display values')", schema
        )

    def test_unhandled_database_error_returns_reference_and_writes_local_log(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "server-error.log"
            app = FastAPI()
            install_server_error_reporting(app, log_path)

            @app.get("/boom")
            def boom():
                raise _DatabaseConflict(
                    "lands_district_section_land_number_key"
                )

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/boom")

            self.assertEqual(response.status_code, 409)
            self.assertIn("同一地區、地段與地號已存在", response.json()["detail"])
            self.assertIn("錯誤代碼：", response.json()["detail"])
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("path=/boom", log_text)
            self.assertIn(
                "constraint=lands_district_section_land_number_key",
                log_text,
            )
            for handler in list(app.state.server_error_logger.handlers):
                handler.close()
                app.state.server_error_logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
