import json
import os
import subprocess
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
import build_postgresql_release
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

    def test_pg_restore_command_does_not_expose_password_and_is_transactional(self):
        command = backup_postgresql._pg_restore_command(
            Path("pg_restore.exe"),
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
        self.assertIn("--single-transaction", command)
        self.assertIn("--exit-on-error", command)

    def test_backup_file_resolution_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                backup_postgresql.resolve_backup_file("../outside.zip", directory)

    def test_sync_backup_targets_copies_and_verifies_server_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root = root / "source"
            target_root = root / "target"
            source_root.mkdir()
            target_root.mkdir()
            archive = source_root / f"{backup_postgresql.BACKUP_PREFIX}offsite.zip"
            archive.write_bytes(b"verified-backup")
            with patch.object(
                backup_postgresql,
                "create_backup",
                return_value={"status": "ok", "backup_path": str(archive)},
            ):
                result = backup_postgresql.sync_backup_targets(
                    [
                        {
                            "id": 7,
                            "name": "USB",
                            "directory_path": str(target_root),
                            "enabled": True,
                        }
                    ],
                    directory=source_root,
                )
            copied = target_root / archive.name
            self.assertEqual(copied.read_bytes(), b"verified-backup")
            self.assertEqual(result["results"][0]["status"], "success")


class ProductionLauncherTests(unittest.TestCase):
    def test_server_packager_rejects_stale_acceptance_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current_report = {"success": True, "version": build_postgresql_release.APP_VERSION}
            (root / "release-acceptance-report.json").write_text(
                json.dumps(current_report), encoding="utf-8"
            )
            executable_report = (
                root
                / f"release-acceptance-exe-v{build_postgresql_release.APP_VERSION}.json"
            )
            executable_report.write_text(
                json.dumps(current_report), encoding="utf-8"
            )
            with patch.object(build_postgresql_release, "ROOT", root):
                build_postgresql_release.validate_acceptance_documents()
                executable_report.write_text(
                    json.dumps({"success": True, "version": "0.0.0"}),
                    encoding="utf-8",
                )
                with self.assertRaises(RuntimeError):
                    build_postgresql_release.validate_acceptance_documents()

    def test_server_packager_normalizes_launcher_to_ascii_crlf(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "launcher.bat"
            build_postgresql_release.copy_primary_launcher(destination)
            content = destination.read_bytes()

        self.assertFalse(content.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(content.isascii())
        self.assertGreater(content.count(b"\r\n"), 0)
        self.assertEqual(content.count(b"\r\n"), content.count(b"\n"))

    def test_packaged_server_launcher_executes_cleanly_in_cmd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            support = root / "_server_support"
            support.mkdir()
            (support / "home_server_runtime.ps1").write_text(
                "exit 0\n", encoding="ascii"
            )
            launcher = root / "start-home-server.bat"
            build_postgresql_release.copy_primary_launcher(launcher)
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "call", str(launcher)],
                input=b"x\r\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )

        output = result.stdout.decode("ascii", errors="replace")
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn("is not recognized", output)
        self.assertIn("Home server stopped normally.", output)

    def test_official_home_server_launcher_uses_postgresql_https_and_netbird(self):
        root = Path(__file__).resolve().parent.parent
        launcher_bytes = (root / "啟動家中伺服器.bat").read_bytes()
        self.assertFalse(launcher_bytes.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(launcher_bytes.isascii())
        launcher = launcher_bytes.decode("ascii")
        runtime = (root / "home_server_runtime.ps1").read_text(encoding="utf-8-sig")
        vpn_firewall_script = (root / "configure_netbird_firewall.ps1").read_text(encoding="utf-8")

        self.assertIn("home_server_runtime.ps1", launcher)
        self.assertIn("--postgres', '--check", runtime)
        self.assertIn("--setup-https', '--prefer-vpn", runtime)
        self.assertIn("'--postgres', '--backup-if-due-hours', '24", runtime)
        self.assertLess(
            runtime.index("'--postgres', '--backup-if-due-hours', '24"),
            runtime.index("'--postgres', '--check'"),
        )
        self.assertIn("既有 PostgreSQL 連線設定無法完成備份", runtime)
        self.assertIn(
            "'--postgres', '--backup', '--backup-label', 'pre-upgrade-repaired'",
            runtime,
        )
        self.assertIn("連線設定已修復，但升級前完整備份仍失敗", runtime)
        self.assertIn("$ErrorActionPreference = 'Continue'", runtime)
        self.assertIn("2>&1 | Out-Host", runtime)
        self.assertIn("*.lcs-account", runtime)
        self.assertIn("--import-recovery-account", runtime)
        self.assertIn("recover-admin-password.request", runtime)
        self.assertIn("--recover-admin-password", runtime)
        self.assertIn("*.lcs-migration.zip", runtime)
        self.assertIn("--import-migration-package", runtime)
        self.assertIn("migration-archives", runtime)
        self.assertIn("伺服器共用金鑰重新加密", runtime)
        self.assertIn("不會覆蓋地主、土地、持分或案件資料", runtime)
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

        packager = (root / "build_postgresql_release.py").read_text(encoding="utf-8")
        self.assertIn("'postgres' / 'schema.sql'", packager)
        self.assertIn('"postgres/migrations/009_owner_contacts_rollback.sql"', packager)
        self.assertIn(
            '"postgres/migrations/010_owner_contacts_enhancement_rollback.sql"',
            packager,
        )
        self.assertIn(
            '"postgres/migrations/011_owner_contact_identity_rollback.sql"',
            packager,
        )
        self.assertIn('"standalone_migration_import"', packager)
        self.assertIn('"migration_preserves_server_accounts": True', packager)

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
        self.assertIn("LAND_CUSTOMER_API_CA_CERT=", company_launcher)
        self.assertIn("取得公開 CA", company_launcher)
        self.assertNotIn("land-customer-local-ca.pem", company_launcher)
        self.assertIn("程式會要求輸入家中伺服器的 NetBird IP", company_launcher)
        self.assertNotIn("home_server_ip.txt", company_launcher)
        self.assertNotIn("LAND_CUSTOMER_API_URL=", company_launcher)
        self.assertNotIn("company_client_preflight.ps1", company_launcher)
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
