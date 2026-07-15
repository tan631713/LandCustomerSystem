import contextlib
import io
import unittest
from unittest.mock import patch

import start_api_server
from customer_api.data_sources import PostgreSQLCustomerDataSource


class _FakePsycopg:
    def __init__(self):
        self.arguments = None

    def connect(self, *args, **kwargs):
        self.arguments = (args, kwargs)
        return "connection"


class PostgreSQLHealthCheckTests(unittest.TestCase):
    def test_postgresql_connections_have_a_short_timeout(self):
        source = PostgreSQLCustomerDataSource.__new__(PostgreSQLCustomerDataSource)
        source.dsn = "postgresql://protected"
        source._dict_row = object()
        source._psycopg = _FakePsycopg()

        self.assertEqual(source._connect(), "connection")
        _args, kwargs = source._psycopg.arguments
        self.assertEqual(kwargs["connect_timeout"], 5)

    def test_check_failure_is_fast_clear_and_does_not_expose_exception_text(self):
        class FailingSource:
            @staticmethod
            def health():
                raise RuntimeError("postgresql://user:secret@private-host/database")

        stderr = io.StringIO()
        with (
            patch.object(start_api_server, "create_data_source", return_value=FailingSource()),
            patch.dict(
                "os.environ",
                {
                    "CUSTOMER_API_BACKEND": "postgresql",
                    "CUSTOMER_API_DATABASE_URL": "postgresql://placeholder",
                },
                clear=False,
            ),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = start_api_server.main(["--postgres", "--check"])

        output = stderr.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("PostgreSQL 檢查失敗", output)
        self.assertNotIn("secret", output)
        self.assertNotIn("private-host", output)

    def test_connection_timeout_message_explains_the_recovery_steps(self):
        connection_timeout = type("ConnectionTimeout", (Exception,), {})
        result = start_api_server.database_check_failure(connection_timeout())

        self.assertIn("5 秒內", result["message"])
        self.assertIn("PostgreSQL 服務", result["message"])
        self.assertIn("setup_local_postgresql.bat", result["message"])

    def test_packaged_server_can_run_local_postgresql_setup(self):
        with patch("setup_local_postgresql.main", return_value=0) as setup_main:
            exit_code = start_api_server.main(["--setup-postgresql"])

        self.assertEqual(exit_code, 0)
        setup_main.assert_called_once_with([])


if __name__ == "__main__":
    unittest.main()
