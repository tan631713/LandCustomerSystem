import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import customer_ui
import customer_ui_qt as desktop_app
from customer_database import CustomerDatabase
from customer_repository import CustomerRepository


class CompanyClientConfigurationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
