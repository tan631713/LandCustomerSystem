import contextlib
import io
import tempfile
import unittest
from pathlib import Path
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

    def test_explicit_postgres_mode_ignores_stale_environment_dsn(self):
        parser = start_api_server.build_parser()
        args = parser.parse_args(["--postgres", "--check"])

        with patch.dict(
            start_api_server.os.environ,
            {
                "CUSTOMER_API_BACKEND": "sqlite",
                "CUSTOMER_API_DATABASE_URL": "postgresql://stale-user:secret@old-host/db",
            },
            clear=False,
        ):
            ignored = start_api_server.select_protected_postgres_configuration(args)

            self.assertTrue(ignored)
            self.assertEqual(
                start_api_server.os.environ["CUSTOMER_API_BACKEND"], "postgresql"
            )
            self.assertNotIn("CUSTOMER_API_DATABASE_URL", start_api_server.os.environ)

    def test_explicit_postgres_mode_uses_stable_local_attachment_directory(self):
        parser = start_api_server.build_parser()
        args = parser.parse_args(["--postgres", "--check"])
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(
                start_api_server.os.environ,
                {"LOCALAPPDATA": directory},
                clear=True,
            ):
                start_api_server.select_protected_postgres_configuration(args)
                selected = Path(
                    start_api_server.os.environ["CUSTOMER_API_ATTACHMENT_DIR"]
                )

            self.assertEqual(
                selected,
                Path(directory) / "LandCustomerSystem" / "attachments",
            )

    def test_backup_in_explicit_postgres_mode_also_ignores_stale_dsn(self):
        with (
            patch.dict(
                start_api_server.os.environ,
                {"CUSTOMER_API_DATABASE_URL": "postgresql://stale@old-host/db"},
                clear=False,
            ),
            patch("backup_postgresql.main", return_value=0) as backup_main,
        ):
            exit_code = start_api_server.main(["--postgres", "--backup"])

            self.assertNotIn("CUSTOMER_API_DATABASE_URL", start_api_server.os.environ)

        self.assertEqual(exit_code, 0)
        backup_main.assert_called_once_with(["--label", "manual"])

    def test_backup_failure_returns_control_to_home_server_repair_flow(self):
        with patch("backup_postgresql.main", side_effect=RuntimeError("bad password")):
            exit_code = start_api_server.main(["--postgres", "--backup"])

        self.assertEqual(exit_code, 1)

    def test_connection_timeout_message_explains_the_recovery_steps(self):
        connection_timeout = type("ConnectionTimeout", (Exception,), {})
        result = start_api_server.database_check_failure(connection_timeout())

        self.assertIn("5 秒內", result["message"])
        self.assertIn("PostgreSQL 服務", result["message"])
        self.assertIn("啟動家中伺服器.bat", result["message"])

    def test_packaged_server_can_run_local_postgresql_setup(self):
        with patch("setup_local_postgresql.main", return_value=0) as setup_main:
            exit_code = start_api_server.main(["--setup-postgresql"])

        self.assertEqual(exit_code, 0)
        setup_main.assert_called_once_with([])

    def test_parser_accepts_recovery_account_maintenance_mode(self):
        args = start_api_server.build_parser().parse_args(
            ["--postgres", "--import-recovery-account", "User.lcs-account"]
        )

        self.assertTrue(args.postgres)
        self.assertEqual(args.import_recovery_account, "User.lcs-account")

    def test_parser_accepts_offline_admin_password_recovery(self):
        args = start_api_server.build_parser().parse_args(
            ["--postgres", "--recover-admin-password"]
        )

        self.assertTrue(args.postgres)
        self.assertTrue(args.recover_admin_password)


if __name__ == "__main__":
    unittest.main()
