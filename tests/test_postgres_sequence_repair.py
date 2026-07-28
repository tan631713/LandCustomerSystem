import unittest
from unittest.mock import patch

from customer_api.postgres_records import PostgreSQLRecordMixin
from customer_api.postgres_schema import repair_postgres_identity_sequences


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _SequenceConnection:
    def __init__(self, *, max_id=9, last_value=4, is_called=True):
        self.max_id = max_id
        self.last_value = last_value
        self.is_called = is_called
        self.setval_parameters = None

    def execute(self, query, parameters=None):
        sql = str(query)
        if "COALESCE(MAX(id), 0)" in sql:
            return _Result({"max_id": self.max_id})
        if "pg_get_serial_sequence" in sql:
            return _Result({"sequence_name": "public.audit_logs_id_seq"})
        if "SELECT last_value, is_called" in sql:
            return _Result(
                {"last_value": self.last_value, "is_called": self.is_called}
            )
        if "SELECT setval" in sql:
            self.setval_parameters = parameters
            return _Result((parameters[1],))
        raise AssertionError(f"Unexpected SQL: {sql}")


class _UniqueViolation(Exception):
    def __init__(self, constraint_name):
        super().__init__(constraint_name)
        self.diag = type("Diag", (), {"constraint_name": constraint_name})()


class _FakePsycopg:
    class errors:
        UniqueViolation = _UniqueViolation


class _ConnectionContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class _RetryingRecordSource(PostgreSQLRecordMixin):
    _psycopg = _FakePsycopg()

    def __init__(self, constraint_name):
        self.constraint_name = constraint_name
        self.write_attempts = 0
        self.connection_count = 0

    def _connect(self):
        self.connection_count += 1
        return _ConnectionContext()

    def _save_record_with_conn(
        self, conn, user, values, record_id=None, *, write_audit=True
    ):
        self.write_attempts += 1
        if self.write_attempts == 1:
            raise _UniqueViolation(self.constraint_name)
        return 37


class PostgreSQLSequenceRepairTests(unittest.TestCase):
    def test_repair_advances_stale_sequence_and_never_moves_ahead_sequence_back(self):
        stale = _SequenceConnection(max_id=9, last_value=4, is_called=True)
        repaired = repair_postgres_identity_sequences(
            stale, table_names=("audit_logs",)
        )
        self.assertEqual(repaired, {"audit_logs": 9})
        self.assertEqual(
            stale.setval_parameters,
            ("public.audit_logs_id_seq", 9, True),
        )

        ahead = _SequenceConnection(max_id=9, last_value=12, is_called=True)
        repaired = repair_postgres_identity_sequences(
            ahead, table_names=("audit_logs",)
        )
        self.assertEqual(repaired, {"audit_logs": 12})
        self.assertEqual(ahead.setval_parameters[1], 12)

    def test_record_write_repairs_primary_key_sequence_and_retries_once(self):
        source = _RetryingRecordSource("audit_logs_pkey")
        with patch(
            "customer_api.postgres_records.repair_postgres_identity_sequences"
        ) as repair:
            saved_id = source.save_record(None, {}, record_id=11)
        self.assertEqual(saved_id, 37)
        self.assertEqual(source.write_attempts, 2)
        self.assertEqual(source.connection_count, 3)
        repair.assert_called_once()

    def test_record_write_does_not_retry_business_unique_constraint(self):
        source = _RetryingRecordSource(
            "lands_district_section_land_number_key"
        )
        with patch(
            "customer_api.postgres_records.repair_postgres_identity_sequences"
        ) as repair:
            with self.assertRaises(_UniqueViolation):
                source.save_record(None, {}, record_id=11)
        self.assertEqual(source.write_attempts, 1)
        repair.assert_not_called()


if __name__ == "__main__":
    unittest.main()
