import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import serialization

import backup_postgresql
import setup_local_https


class LocalHttpsCertificateTests(unittest.TestCase):
    def test_certificate_chain_covers_localhost_and_lan_ip(self):
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(setup_local_https, "local_ip_address", return_value="192.168.50.20"),
                patch.object(setup_local_https, "netbird_ipv4_addresses", return_value=[]),
                patch.object(setup_local_https.socket, "getaddrinfo", return_value=[]),
                patch.object(setup_local_https.socket, "gethostname", return_value="Land-PC"),
            ):
                first = setup_local_https.create_local_https_certificate(directory)
                second = setup_local_https.create_local_https_certificate(directory)

            paths = setup_local_https.certificate_paths(directory)
            ca_certificate = x509.load_pem_x509_certificate(paths.ca_certificate_pem.read_bytes())
            server_certificate = x509.load_pem_x509_certificate(paths.server_certificate.read_bytes())
            san = server_certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value

            self.assertTrue(first["ca_created"])
            self.assertFalse(second["ca_created"])
            self.assertEqual(server_certificate.issuer, ca_certificate.subject)
            self.assertIn("localhost", san.get_values_for_type(x509.DNSName))
            self.assertIn("192.168.50.20", [str(value) for value in san.get_values_for_type(x509.IPAddress)])
            self.assertEqual(first["iphone_url"], "https://192.168.50.20:8732/mobile/")
            self.assertTrue(paths.ca_certificate_der.exists())
            self.assertTrue(paths.report.exists())
            serialization.load_pem_private_key(paths.server_private_key.read_bytes(), password=None)

    def test_lan_addresses_prefer_route_and_exclude_link_local(self):
        with (
            patch.object(setup_local_https, "local_ip_address", return_value="172.20.10.2"),
            patch.object(setup_local_https, "netbird_ipv4_addresses", return_value=[]),
            patch.object(
                setup_local_https.socket,
                "getaddrinfo",
                return_value=[
                    (None, None, None, None, ("192.168.1.156", 0)),
                    (None, None, None, None, ("169.254.20.30", 0)),
                    (None, None, None, None, ("172.20.10.2", 0)),
                ],
            ),
        ):
            addresses = setup_local_https.lan_ipv4_addresses()

        self.assertEqual(addresses, ["172.20.10.2", "192.168.1.156"])

    def test_netbird_address_is_detected_and_preferred_for_vpn(self):
        with (
            patch.object(setup_local_https, "netbird_cli_path", return_value=Path("netbird.exe")),
            patch.object(
                setup_local_https.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="100.101.102.103\n"),
            ),
            patch.object(setup_local_https, "local_ip_address", return_value="172.20.10.2"),
            patch.object(setup_local_https.socket, "getaddrinfo", return_value=[]),
        ):
            self.assertEqual(setup_local_https.netbird_ipv4_addresses(), ["100.101.102.103"])
            self.assertEqual(
                setup_local_https.lan_ipv4_addresses(prefer_vpn=True),
                ["100.101.102.103", "172.20.10.2"],
            )


class PostgreSQLBackupMaintenanceTests(unittest.TestCase):
    def test_pruning_always_keeps_latest_three_compressed_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = time.time()
            for index in range(7):
                path = root / f"{backup_postgresql.BACKUP_PREFIX}{index}.zip"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("manifest.json", "{}")
                old_time = now - index * 24 * 60 * 60
                os.utime(path, (old_time, old_time))

            deleted = backup_postgresql.prune_backups(
                root,
                retention_days=1,
                max_count=3,
            )
            remaining = backup_postgresql.list_backups(root)
            self.assertEqual(len(remaining), 3)
            self.assertEqual(len(deleted), 4)
            self.assertEqual(backup_postgresql.backup_status(root)["backup_count"], 3)

    def test_pg_dump_command_does_not_expose_password(self):
        command = backup_postgresql._pg_dump_command(
            Path("pg_dump.exe"),
            {
                "host": "127.0.0.1",
                "port": "5432",
                "user": "land_app",
                "password": "secret-password",
                "dbname": "land_customer",
            },
            Path("database.dump"),
        )
        self.assertNotIn("secret-password", command)
        self.assertIn("--no-password", command)


class ProductionLauncherTests(unittest.TestCase):
    def test_official_home_server_launcher_uses_postgresql_https_and_netbird(self):
        root = Path(__file__).resolve().parent.parent
        launcher = (root / "啟動家中伺服器.bat").read_text(encoding="utf-8-sig")
        runtime = (root / "home_server_runtime.ps1").read_text(encoding="utf-8-sig")
        vpn_firewall_script = (root / "configure_netbird_firewall.ps1").read_text(encoding="utf-8")

        self.assertIn("home_server_runtime.ps1", launcher)
        self.assertIn("--postgres', '--check", runtime)
        self.assertIn("--setup-https', '--prefer-vpn", runtime)
        self.assertIn("--backup-if-due-hours', '24", runtime)
        self.assertIn("--postgres', '--lan', '--prefer-vpn", runtime)
        self.assertIn("home-server-diagnostics.json", runtime)
        self.assertIn("Netbird.Netbird", runtime)
        self.assertIn("PostgreSQL.PostgreSQL.18", runtime)
        self.assertIn("Get-PrerequisiteState", runtime)
        self.assertIn("Confirm-PrerequisiteInstallation", runtime)
        self.assertIn("Read-Host '是否現在由系統協助安裝以上軟體？請輸入 Y 或 N'", runtime)
        self.assertIn("install_decision = 'not_required'", runtime)
        self.assertIn("missing_software = @()", runtime)
        self.assertIn("--interactive", runtime)
        self.assertIn("--accept-package-agreements", runtime)
        self.assertIn("使用者選擇不安裝必要軟體", runtime)
        self.assertLess(
            runtime.index("Confirm-PrerequisiteInstallation -Missing"),
            runtime.index("Install-MissingPrerequisites" , runtime.index("try {")),
        )
        self.assertIn("status --ipv4", runtime)
        self.assertIn("100.64.0.0/10", runtime)
        self.assertNotIn("5432', '--lan", runtime)

        self.assertIn("NetBird\\netbird.exe", vpn_firewall_script)
        self.assertIn("-LocalPort $rule.Port", vpn_firewall_script)
        self.assertIn("Port = 8732", vpn_firewall_script)
        self.assertIn("100.64.0.0/10", vpn_firewall_script)
        self.assertNotIn("Port = 5432", vpn_firewall_script)

        home_preflight = (root / "home_server_preflight.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-Service -Name 'postgresql*'", home_preflight)
        self.assertIn("configure_netbird_firewall.ps1", home_preflight)
        self.assertIn("-Verb RunAs", home_preflight)
        self.assertIn("Port = 8732", home_preflight)
        self.assertIn("100.64.0.0/10", home_preflight)
        self.assertNotIn("Port = 5432", home_preflight)

        company_launcher = (root / "start_company_laptop_desktop.bat").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("LAND_CUSTOMER_DESKTOP_BACKEND=postgresql", company_launcher)
        self.assertIn("LAND_CUSTOMER_API_URL=https://%HOME_SERVER_IP%:8732", company_launcher)
        self.assertIn("LAND_CUSTOMER_API_CA_CERT=%CA_CERT%", company_launcher)
        self.assertIn("LandCustomerSystem\\LandCustomerSystem.exe", company_launcher)
        self.assertNotIn("LandCustomerServer", company_launcher)
        self.assertNotIn("--postgres", company_launcher)

        company_preflight = (root / "company_client_preflight.ps1").read_text(encoding="utf-8")
        self.assertIn("ConnectAsync", company_preflight)
        self.assertIn("--client-health-report", company_preflight)
        self.assertIn("[int]$Port = 8732", company_preflight)
        self.assertNotIn("5432", company_preflight)


if __name__ == "__main__":
    unittest.main()
