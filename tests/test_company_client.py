import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import customer_ui
import customer_ui_qt as desktop_app
import build_remote_desktop_release
from customer_database import CustomerDatabase
from customer_repository import CustomerRepository


class CompanyClientConfigurationTests(unittest.TestCase):
    def test_prompt_accepts_plain_ip_and_returns_https_url(self):
        with patch.object(
            desktop_app.QInputDialog,
            "getText",
            return_value=("100.101.102.103", True),
        ):
            self.assertEqual(
                desktop_app.prompt_server_api_url(),
                "https://100.101.102.103:8732",
            )

    def test_connect_desktop_api_persists_working_address(self):
        healthy_client = object()
        with (
            patch.object(
                desktop_app,
                "get_setting",
                return_value="100.101.102.103",
            ),
            patch.object(
                desktop_app,
                "create_healthy_desktop_api_client",
                return_value=healthy_client,
            ) as health_check,
            patch.object(desktop_app, "prepare_server_ca_for_api") as prepare_ca,
            patch.object(desktop_app, "set_setting") as save_setting,
            patch.dict(os.environ, {}, clear=False),
        ):
            result = desktop_app.connect_desktop_api()
        self.assertIs(result, healthy_client)
        prepare_ca.assert_called_once_with("https://100.101.102.103:8732", None)
        health_check.assert_called_once_with("https://100.101.102.103:8732")
        save_setting.assert_called_once_with(
            desktop_app.SERVER_API_URL_SETTING_KEY,
            "https://100.101.102.103:8732",
        )

    def test_remote_mode_creates_only_device_settings_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_path = root / "desktop-client-settings.db"
            database = CustomerDatabase(database_path, root / "unused-backups")
            repository = CustomerRepository(
                database,
                desktop_app.SCHEMA_PATH,
                desktop_app.SEED_PATH,
                desktop_app.LAND_FIELDS,
            )
            with (
                patch.object(desktop_app, "DB_PATH", database_path),
                patch.object(desktop_app, "DATABASE", database),
                patch.object(desktop_app, "REPOSITORY", repository),
            ):
                desktop_app.init_remote_client_settings()
                with database.connect() as connection:
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                    }
            self.assertEqual(tables, {"app_settings"})

    def test_company_bundle_forces_https_remote_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            runtime = bundle / "LandCustomerSystem"
            runtime.mkdir()
            ca_path = bundle / "land-customer-local-ca.pem"
            ca_path.write_text("PUBLIC CA", encoding="ascii")
            (runtime / "company-client-config.json").write_text(
                json.dumps(
                    {
                        "api_url": "https://100.107.252.170:8732",
                        "ca_certificate": "../land-customer-local-ca.pem",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(customer_ui, "get_runtime_directory", return_value=runtime),
                patch.dict(os.environ, {}, clear=False),
            ):
                result = customer_ui.apply_company_client_config()
                self.assertEqual(
                    os.environ["LAND_CUSTOMER_API_URL"],
                    "https://100.107.252.170:8732",
                )
                self.assertEqual(os.environ["LAND_CUSTOMER_DESKTOP_BACKEND"], "postgresql")
                self.assertEqual(Path(result["ca_certificate"]), ca_path)

    def test_company_bundle_can_require_user_entered_server_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            runtime = bundle / "LandCustomerSystem"
            runtime.mkdir()
            ca_path = bundle / "land-customer-local-ca.pem"
            ca_path.write_text("PUBLIC CA", encoding="ascii")
            (runtime / "company-client-config.json").write_text(
                json.dumps(
                    {
                        "ca_certificate": "../land-customer-local-ca.pem",
                        "server_ip_user_configurable": True,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(customer_ui, "get_runtime_directory", return_value=runtime),
                patch.dict(os.environ, {}, clear=True),
            ):
                result = customer_ui.apply_company_client_config()
                self.assertNotIn("LAND_CUSTOMER_API_URL", os.environ)
                self.assertEqual(os.environ["LAND_CUSTOMER_DESKTOP_BACKEND"], "postgresql")
                self.assertTrue(result["requires_server_ip_input"])
                self.assertEqual(Path(result["ca_certificate"]), ca_path)

    def test_company_bundle_can_bootstrap_ca_from_selected_home_server(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            runtime = bundle / "LandCustomerSystem"
            runtime.mkdir()
            (runtime / "company-client-config.json").write_text(
                json.dumps(
                    {
                        "server_ip_user_configurable": True,
                        "dynamic_server_ca": True,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(customer_ui, "get_runtime_directory", return_value=runtime),
                patch.dict(os.environ, {}, clear=True),
            ):
                result = customer_ui.apply_company_client_config()
                self.assertEqual(result["ca_certificate"], "")
                self.assertNotIn("LAND_CUSTOMER_API_CA_CERT", os.environ)
                self.assertEqual(
                    os.environ["LAND_CUSTOMER_DESKTOP_BACKEND"], "postgresql"
                )

    def test_company_bundle_rejects_plain_http(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "LandCustomerSystem"
            runtime.mkdir()
            (runtime / "company-client-config.json").write_text(
                json.dumps(
                    {
                        "api_url": "http://100.107.252.170:8732",
                        "ca_certificate": "../land-customer-local-ca.pem",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(customer_ui, "get_runtime_directory", return_value=runtime):
                with self.assertRaises(ValueError):
                    customer_ui.apply_company_client_config()

    def test_headless_health_check_writes_safe_diagnostics(self):
        class HealthyClient:
            def __init__(self, *_args, **_kwargs):
                pass

            def health(self):
                return {
                    "status": "ok",
                    "backend": "postgresql",
                    "version": "1.4.0",
                    "schema_version": 3,
                    "record_count": 267,
                }

        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "client-network-diagnostics.json"
            with (
                patch("customer_desktop_api.DesktopApiClient", HealthyClient),
                patch.dict(
                    os.environ,
                    {"LAND_CUSTOMER_API_URL": "https://100.100.100.100:8732"},
                    clear=False,
                ),
            ):
                exit_code = customer_ui.run_company_client_health_check(report_path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["schema_version"], 3)
        self.assertEqual(report["record_count"], 267)
        self.assertNotIn("password", json.dumps(report).casefold())
        self.assertNotIn("token", json.dumps(report).casefold())

    def test_remote_packager_excludes_device_data_and_prior_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "dist"
            destination = root / "client"
            source.mkdir()
            (source / "LandCustomerSystem.exe").write_bytes(b"exe")
            (source / "customers.db").write_bytes(b"customer-data")
            (source / "desktop-client-settings.db").write_bytes(b"settings")
            (source / "company-client-config.json").write_text("old", encoding="utf-8")
            (source / "backups").mkdir()
            (source / "backups" / "old.zip").write_bytes(b"backup")
            with patch.object(build_remote_desktop_release, "DESKTOP_DIST", source):
                build_remote_desktop_release.copy_desktop_client(destination)
            self.assertTrue((destination / "LandCustomerSystem.exe").is_file())
            self.assertFalse((destination / "customers.db").exists())
            self.assertFalse((destination / "desktop-client-settings.db").exists())
            self.assertFalse((destination / "company-client-config.json").exists())
            self.assertFalse((destination / "backups").exists())

    def test_company_launcher_lets_desktop_prompt_for_server_ip(self):
        root = Path(__file__).resolve().parent.parent
        launcher = (root / "start_company_laptop_desktop.bat").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("setup_netbird_client.bat", launcher)
        self.assertIn("LAND_CUSTOMER_DESKTOP_BACKEND=postgresql", launcher)
        self.assertIn("LAND_CUSTOMER_API_CA_CERT=", launcher)
        self.assertIn("取得公開 CA", launcher)
        self.assertIn("程式會要求輸入家中伺服器的 NetBird IP", launcher)
        self.assertNotIn("land-customer-local-ca.pem", launcher)
        self.assertNotIn("home_server_ip.txt", launcher)
        self.assertNotIn("LAND_CUSTOMER_API_URL=", launcher)
        self.assertNotIn("company_client_preflight.ps1", launcher)

    def test_api_mode_operation_log_never_writes_device_customer_tables(self):
        with (
            patch.dict(
                os.environ,
                {desktop_app.DESKTOP_BACKEND_ENV: "postgresql"},
                clear=False,
            ),
            patch.object(
                desktop_app.REPOSITORY,
                "log_operation",
                side_effect=AssertionError("API 客戶端不得寫入本機操作資料表"),
            ),
        ):
            self.assertIsNone(desktop_app.log_operation("測試", "不應寫入", ""))


if __name__ == "__main__":
    unittest.main()
