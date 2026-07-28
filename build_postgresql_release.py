"""Build the packaged PostgreSQL desktop/server delivery ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from customer_version import APP_VERSION, BUILD_DATE, MOBILE_ASSET_VERSION


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
RELEASES = ROOT / "releases"
SERVER_DIST = DIST / "LandCustomerServer"

PRIMARY_LAUNCHER = "啟動家中伺服器.bat"
SUPPORT_FILES = (
    "home_server_runtime.ps1",
    "configure_netbird_firewall.ps1",
    "home_server_preflight.ps1",
)
DOCUMENTS = (
    "伺服器使用說明.txt",
    "公司筆電遠端使用說明.txt",
    "外勤模式使用與驗收說明.txt",
    "交付說明.txt",
    "簡短版變更紀錄.txt",
    "完整版變更紀錄.txt",
    "README.md",
    "release-acceptance-report.json",
    f"release-acceptance-exe-v{APP_VERSION}.json",
)


def validate_acceptance_documents() -> None:
    """Prevent a current release from carrying a stale acceptance report."""

    for name in (
        "release-acceptance-report.json",
        f"release-acceptance-exe-v{APP_VERSION}.json",
    ):
        path = ROOT / name
        if not path.is_file():
            raise RuntimeError(f"正式封裝前缺少驗收報告：{name}")
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"驗收報告無法讀取：{name}") from exc
        if not report.get("success") or str(report.get("version")) != APP_VERSION:
            raise RuntimeError(
                f"驗收報告版本或結果不符：{name}，"
                f"expected={APP_VERSION}, actual={report.get('version')}"
            )


def validate_field_visit_journey() -> None:
    """Require the complete mobile-to-desktop journey before formal packaging."""

    subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.test_field_visit_journey",
            "-q",
        ],
        cwd=ROOT,
        check=True,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def copy_primary_launcher(destination: Path) -> None:
    """Write a CMD-safe launcher regardless of the source checkout line endings."""

    launcher_bytes = (ROOT / PRIMARY_LAUNCHER).read_bytes()
    if launcher_bytes.startswith(b"\xef\xbb\xbf") or not launcher_bytes.isascii():
        raise RuntimeError("伺服器啟動批次檔必須是無 BOM 的 ASCII，避免 CMD 拆壞指令")
    text = launcher_bytes.decode("ascii").replace("\r\n", "\n").replace("\r", "\n")
    destination.write_bytes(text.replace("\n", "\r\n").encode("ascii"))


def build_server(python_executable: str) -> None:
    command = [
        python_executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--console",
        "--name",
        "LandCustomerServer",
        "--icon",
        str(ROOT / "assets" / "app_icon.ico"),
        "--version-file",
        str(ROOT / "version_info.txt"),
        "--collect-all",
        "psycopg",
        "--collect-all",
        "psycopg_binary",
        "--collect-submodules",
        "uvicorn",
        "--add-data",
        f"{ROOT / 'customer_mobile_web'};customer_mobile_web",
        "--add-data",
        f"{ROOT / 'schema.sql'};.",
        "--add-data",
        f"{ROOT / 'seed.sql'};.",
        "--add-data",
        f"{ROOT / 'postgres' / 'schema.sql'};postgres",
        str(ROOT / "start_api_server.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    executable = SERVER_DIST / "LandCustomerServer.exe"
    if not executable.is_file():
        raise RuntimeError("LandCustomerServer.exe was not created")


def audit_server_bundle(bundle: Path) -> None:
    """Refuse ambiguous launchers, customer data, or server secrets."""
    root_launchers = sorted(path.name for path in bundle.glob("*.bat"))
    if root_launchers != [PRIMARY_LAUNCHER]:
        raise RuntimeError(f"伺服器封裝只能有一個啟動檔：{root_launchers}")

    launcher_bytes = (bundle / PRIMARY_LAUNCHER).read_bytes()
    if launcher_bytes.startswith(b"\xef\xbb\xbf") or not launcher_bytes.isascii():
        raise RuntimeError("伺服器啟動批次檔必須是無 BOM 的 ASCII，避免 CMD 拆壞指令")
    if launcher_bytes.count(b"\r\n") != launcher_bytes.count(b"\n"):
        raise RuntimeError("伺服器啟動批次檔必須使用 Windows CRLF 換行")

    required = [
        bundle / PRIMARY_LAUNCHER,
        bundle / "LandCustomerServer" / "LandCustomerServer.exe",
        bundle / "LandCustomerServer" / "_internal" / "postgres" / "schema.sql",
        *(bundle / "_server_support" / name for name in SUPPORT_FILES),
    ]
    missing = [str(path.relative_to(bundle)) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"伺服器封裝缺少必要檔案：{missing}")

    forbidden = []
    forbidden_directories = {"backups", "attachments", "landcustomersystem", ".build-preserved-data"}
    forbidden_names = {
        "customers.db",
        "desktop-client-settings.db",
        "postgres-dsn.dpapi",
        "postgresql-dsn.bin",
        "land-customer-server-key.pem",
    }
    for path in bundle.rglob("*"):
        relative_parts = {part.lower() for part in path.relative_to(bundle).parts}
        if relative_parts & forbidden_directories or path.name.lower() in forbidden_names:
            forbidden.append(str(path.relative_to(bundle)))
            continue
        if path.is_file() and path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}:
            forbidden.append(str(path.relative_to(bundle)))
            continue
        text_or_key_extensions = {
            ".pem", ".key", ".txt", ".json", ".env", ".ini", ".cfg",
            ".py", ".ps1", ".bat", ".md",
        }
        if (
            path.is_file()
            and path.suffix.lower() in text_or_key_extensions
            and path.stat().st_size <= 2 * 1024 * 1024
        ):
            try:
                if b"PRIVATE KEY" in path.read_bytes():
                    forbidden.append(str(path.relative_to(bundle)))
            except OSError:
                forbidden.append(str(path.relative_to(bundle)))
    if forbidden:
        raise RuntimeError(f"伺服器封裝包含禁止內容：{sorted(set(forbidden))}")


def package_release() -> tuple[Path, Path]:
    if not SERVER_DIST.is_dir():
        raise FileNotFoundError("LandCustomerServer 尚未建立")
    RELEASES.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    release_name = f"LandCustomerSystem-PostgreSQL-v{APP_VERSION}-{timestamp}"
    with tempfile.TemporaryDirectory(prefix="land-customer-package-", dir=RELEASES) as temporary:
        bundle = Path(temporary) / release_name
        bundle.mkdir()
        shutil.copytree(SERVER_DIST, bundle / "LandCustomerServer")
        copy_primary_launcher(bundle / PRIMARY_LAUNCHER)
        support = bundle / "_server_support"
        support.mkdir()
        for name in SUPPORT_FILES:
            shutil.copy2(ROOT / name, support / name)
        for name in DOCUMENTS:
            source = ROOT / name
            if source.exists():
                shutil.copy2(source, bundle / name)

        manifest = {
            "product": "LandCustomerSystem PostgreSQL",
            "version": APP_VERSION,
            "build_date": BUILD_DATE,
            "packaged_at": datetime.now().astimezone().isoformat(),
            "channel": "formal",
            "official_data_source": "postgresql",
            "postgresql_schema_version": 8,
            "mobile_asset_version": MOBILE_ASSET_VERSION,
            "field_visit_phase_one": True,
            "server_executable": "LandCustomerServer/LandCustomerServer.exe",
            "primary_launcher": PRIMARY_LAUNCHER,
            "root_launcher_count": 1,
            "prerequisite_check": ["NetBird", "PostgreSQL Server", "pg_dump"],
            "prerequisite_install_requires_confirmation": True,
            "package_source": "winget",
            "netbird_allowed_range": "100.64.0.0/10",
            "diagnostics_file": "%LOCALAPPDATA%/LandCustomerSystem/home-server-diagnostics.json",
            "recovery_account_import": "將 .lcs-account 放在啟動檔旁，開啟唯一啟動檔並確認匯入",
            "standalone_migration_import": "將唯一 .lcs-migration.zip 放在啟動檔旁，關閉舊伺服器後由唯一啟動檔匯入",
            "migration_preserves_server_accounts": True,
            "migration_requires_empty_business_database": True,
            "migration_allows_deleted_test_residue": True,
            "migration_preserves_recycle_bin_and_operation_logs": True,
            "migration_creates_pre_import_backup": True,
            "database_included": False,
            "protected_dsn_included": False,
            "private_keys_included": False,
        }
        (bundle / "release-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        audit_server_bundle(bundle)
        permanent_directory = RELEASES / release_name
        shutil.copytree(bundle, permanent_directory)
        zip_path = RELEASES / f"{release_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(release_name) / path.relative_to(bundle))
    if not zip_path.is_file() or zip_path.stat().st_size < 1024:
        raise RuntimeError("Release ZIP was not created")
    checksum_path = zip_path.with_suffix(".sha256.txt")
    checksum_path.write_text(f"{sha256_file(zip_path)}  {zip_path.name}\n", encoding="ascii")
    return permanent_directory, zip_path


def build_parser():
    parser = argparse.ArgumentParser(description="建立 PostgreSQL 桌面／伺服器正式交付包")
    parser.add_argument("--skip-server-build", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    validate_acceptance_documents()
    validate_field_visit_journey()
    if not args.skip_server_build:
        build_server(sys.executable)
    directory, zip_path = package_release()
    print(json.dumps({"release_directory": str(directory), "release_zip": str(zip_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
