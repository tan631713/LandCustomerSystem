import unittest

from customer_api.postgres_tags import PostgreSQLTagMixin


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self, existing_ids):
        self.existing_ids = set(existing_ids)
        self.requested_ids = None

    def execute(self, _query, params):
        self.requested_ids = list(params[0])
        return _Rows(
            [{"id": value} for value in self.requested_ids if value in self.existing_ids]
        )


class PostgreSQLIdValidationTests(unittest.TestCase):
    def test_require_ids_deduplicates_repeated_record_ids(self):
        connection = _Connection({7})

        PostgreSQLTagMixin._require_ids(
            connection, "ownerships", [7, 7, 7]
        )

        self.assertEqual(connection.requested_ids, [7])

    def test_require_ids_still_rejects_a_missing_id(self):
        connection = _Connection({7})

        with self.assertRaises(KeyError):
            PostgreSQLTagMixin._require_ids(
                connection, "ownerships", [7, 8]
            )


if __name__ == "__main__":
    unittest.main()
