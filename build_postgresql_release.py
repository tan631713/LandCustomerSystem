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

from customer_version import APP_VERSION, BUILD_DATE


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
RELEASES = ROOT / "releases"
DESKTOP_DIST = DIST / "LandCustomerSystem"
SERVER_DIST = DIST / "LandCustomerServer"

LAUNCHERS = (
    "setup_local_postgresql.bat",
    "start_land_customer_system_postgresql.bat",
    "start_mobile_server_https.bat",
    "start_api_server_postgresql.bat",
    "setup_local_https.bat",
    "install_iphone_certificate.bat",
    "allow_private_network_firewall.bat",
    "allow_netbird_vpn_firewall.bat",
    "configure_netbird_firewall.ps1",
    "start_mobile_server_vpn.bat",
    "start_home_server_vpn.bat",
    "setup_netbird_vpn.bat",
    "backup_postgresql_now.bat",
)
DOCUMENTS = (
    "iPhone連線說明.txt",
    "私人VPN連線說明.txt",
    "公司筆電遠端使用說明.txt",
    "API伺服器說明.md",
    "交付說明.txt",
    "簡短版變更紀錄.txt",
    "完整版變更紀錄.txt",
    "README.md",
    "release-acceptance-report.json",
    f"release-acceptance-exe-v{APP_VERSION}.json",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


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
        str(ROOT / "start_api_server.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    executable = SERVER_DIST / "LandCustomerServer.exe"
    if not executable.is_file():
        raise RuntimeError("LandCustomerServer.exe was not created")


def _copy_desktop(destination: Path) -> None:
    if not DESKTOP_DIST.is_dir():
        raise FileNotFoundError("請先執行 build_exe.bat 建立桌面程式")

    def ignore(_directory, names):
        device_data = {"customers.db", "backups", "attachments", "logs", ".build-preserved-data"}
        return [name for name in names if name in device_data]

    shutil.copytree(DESKTOP_DIST, destination, ignore=ignore)


def package_release() -> tuple[Path, Path]:
    if not SERVER_DIST.is_dir():
        raise FileNotFoundError("LandCustomerServer 尚未建立")
    RELEASES.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    release_name = f"LandCustomerSystem-PostgreSQL-v{APP_VERSION}-{timestamp}"
    with tempfile.TemporaryDirectory(prefix="land-customer-package-", dir=RELEASES) as temporary:
        bundle = Path(temporary) / release_name
        bundle.mkdir()
        _copy_desktop(bundle / "LandCustomerSystem")
        shutil.copytree(SERVER_DIST, bundle / "LandCustomerServer")
        for name in (*LAUNCHERS, *DOCUMENTS):
            source = ROOT / name
            if source.exists():
                shutil.copy2(source, bundle / name)

        manifest = {
            "product": "LandCustomerSystem PostgreSQL",
            "version": APP_VERSION,
            "build_date": BUILD_DATE,
            "packaged_at": datetime.now().astimezone().isoformat(),
            "official_data_source": "postgresql",
            "desktop_executable": "LandCustomerSystem/LandCustomerSystem.exe",
            "server_executable": "LandCustomerServer/LandCustomerServer.exe",
            "database_included": False,
            "protected_dsn_included": False,
            "private_keys_included": False,
        }
        (bundle / "release-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
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
    if not args.skip_server_build:
        build_server(sys.executable)
    directory, zip_path = package_release()
    print(json.dumps({"release_directory": str(directory), "release_zip": str(zip_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
