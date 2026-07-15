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
    def test_official_launchers_use_postgresql_and_https(self):
        root = Path(__file__).resolve().parent.parent
        desktop = (root / "start_land_customer_system_postgresql.bat").read_text(encoding="utf-8")
        mobile = (root / "start_mobile_server_https.bat").read_text(encoding="utf-8")
        api = (root / "start_api_server_postgresql.bat").read_text(encoding="utf-8")

        self.assertIn("LAND_CUSTOMER_DESKTOP_BACKEND=postgresql", desktop)
        self.assertIn("LAND_CUSTOMER_API_URL=https://127.0.0.1:8732", desktop)
        self.assertIn("start_mobile_server_https.bat", desktop)
        self.assertIn("start_api_server.py --postgres --lan", mobile)
        self.assertIn("--ssl-certfile", mobile)
        self.assertIn("backup_postgresql.py --label auto --if-due-hours 24", mobile)
        self.assertIn("backup_postgresql.py --label auto --if-due-hours 24", api)

        firewall = (root / "allow_private_network_firewall.bat").read_text(encoding="utf-8")
        self.assertIn("profile=any", firewall)
        self.assertIn("remoteip=localsubnet", firewall)
        self.assertNotIn("localport=5432", firewall)

        vpn_firewall = (root / "allow_netbird_vpn_firewall.bat").read_text(encoding="utf-8")
        vpn_firewall_script = (root / "configure_netbird_firewall.ps1").read_text(encoding="utf-8")
        self.assertIn("configure_netbird_firewall.ps1", vpn_firewall)
        self.assertIn("NetBird\\netbird.exe", vpn_firewall_script)
        self.assertIn("-LocalPort $rule.Port", vpn_firewall_script)
        self.assertIn("Port = 8732", vpn_firewall_script)
        self.assertNotIn("Port = 5432", vpn_firewall_script)

        vpn_launcher = (root / "start_mobile_server_vpn.bat").read_text(encoding="utf-8")
        self.assertIn("netbird.exe", vpn_launcher)
        self.assertIn("--prefer-vpn", vpn_launcher)
        self.assertIn("--postgres --lan", vpn_launcher)

        home_launcher = (root / "start_home_server_vpn.bat").read_text(encoding="utf-8-sig")
        self.assertIn("start_mobile_server_vpn.bat", home_launcher)
        self.assertIn("setup_netbird_vpn.bat", home_launcher)
        self.assertIn("home_server_preflight.ps1", home_launcher)
        self.assertIn("setup_local_postgresql.bat", home_launcher)
        self.assertIn("--prepared", home_launcher)

        home_preflight = (root / "home_server_preflight.ps1").read_text(encoding="utf-8")
        self.assertIn("Get-Service -Name 'postgresql*'", home_preflight)
        self.assertIn("configure_netbird_firewall.ps1", home_preflight)
        self.assertIn("-Verb RunAs", home_preflight)
        self.assertIn("Port = 8732", home_preflight)
        self.assertNotIn("Port = 5432", home_preflight)

        postgres_setup = (root / "setup_local_postgresql.bat").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("LandCustomerServer\\LandCustomerServer.exe", postgres_setup)
        self.assertIn("--setup-postgresql", postgres_setup)
        self.assertIn("--no-pause", postgres_setup)

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
        self.assertIn("Test-NetConnection", company_preflight)
        self.assertIn("Port = 8732", company_preflight)
        self.assertNotIn("5432", company_preflight)


if __name__ == "__main__":
    unittest.main()
