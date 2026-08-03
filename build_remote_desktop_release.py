"""Build a company-laptop desktop client that connects to the home API over NetBird."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from customer_version import DESKTOP_CLIENT_BUILD_DATE, DESKTOP_CLIENT_VERSION


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
RELEASES = ROOT / "releases"
DESKTOP_DIST = DIST / "LandCustomerSystem"
CLIENT_FILES = (
    "start_company_laptop_desktop.bat",
    "setup_netbird_client.bat",
    "公司筆電遠端使用說明.txt",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def copy_desktop_client(destination: Path) -> None:
    """Copy the desktop runtime without device-local data or prior package state."""

    excluded_names = {
        "customers.db",
        "desktop-client-settings.db",
        "backups",
        "attachments",
        "logs",
        ".build-preserved-data",
        "company-client-config.json",
    }

    def ignore(_directory, names):
        return [name for name in names if name.casefold() in excluded_names]

    shutil.copytree(DESKTOP_DIST, destination, ignore=ignore)


def audit_client_bundle(bundle: Path) -> None:
    """Refuse to package known customer data, server secrets, or server binaries."""

    forbidden_names = {
        "customers.db",
        "desktop-client-settings.db",
        "land-customer-local-ca.pem",
        "postgresql-dsn.bin",
        "land-customer-server-key.pem",
        "landcustomerserver.exe",
        "home_server_ip.txt",
    }
    forbidden_parts = {"backups", "attachments", ".build-preserved-data"}
    violations = []
    for path in bundle.rglob("*"):
        relative = path.relative_to(bundle)
        lowered_parts = {part.casefold() for part in relative.parts}
        if path.name.casefold() in forbidden_names or lowered_parts & forbidden_parts:
            violations.append(str(relative))
    if violations:
        raise RuntimeError(
            "Company client bundle contains forbidden server/data files: "
            + ", ".join(violations[:10])
        )


def package_remote_client() -> tuple[Path, Path]:
    if not DESKTOP_DIST.is_dir():
        raise FileNotFoundError("Build the desktop EXE before packaging the remote client")
    for name in CLIENT_FILES:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(f"Missing remote client file: {name}")

    RELEASES.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    release_name = (
        "LandCustomerSystem-CompanyLaptopClient-"
        f"v{DESKTOP_CLIENT_VERSION}-{timestamp}"
    )
    with tempfile.TemporaryDirectory(prefix="land-customer-client-", dir=RELEASES) as temporary:
        bundle = Path(temporary) / release_name
        copy_desktop_client(bundle / "LandCustomerSystem")
        for name in CLIENT_FILES:
            shutil.copy2(ROOT / name, bundle / name)
        (bundle / "LandCustomerSystem" / "company-client-config.json").write_text(
            json.dumps(
                {
                    "server_ip_user_configurable": True,
                    "dynamic_server_ca": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        manifest = {
            "product": "LandCustomerSystem Company Laptop Client",
            "version": DESKTOP_CLIENT_VERSION,
            "build_date": DESKTOP_CLIENT_BUILD_DATE,
            "packaged_at": datetime.now().astimezone().isoformat(),
            "server_ip_user_configurable": True,
            "server_ip_storage": "%LOCALAPPDATA%/LandCustomerSystem/desktop-client/desktop-client-settings.db",
            "desktop_executable": "LandCustomerSystem/LandCustomerSystem.exe",
            "database_included": False,
            "postgresql_credentials_included": False,
            "server_executable_included": False,
            "private_keys_included": False,
            "public_ca_included": False,
            "dynamic_server_ca": True,
            "certificate_bootstrap_port": 8733,
            "certificate_requires_user_confirmation": True,
            "direct_exe_click_forces_remote_mode": True,
            "https_health_preflight": True,
            "safe_get_retry": True,
            "diagnostics_file": "%LOCALAPPDATA%/LandCustomerSystem/client-network-diagnostics.json",
        }
        (bundle / "client-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        audit_client_bundle(bundle)
        permanent_directory = RELEASES / release_name
        shutil.copytree(bundle, permanent_directory)
        zip_path = RELEASES / f"{release_name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(release_name) / path.relative_to(bundle))

    checksum_path = zip_path.with_suffix(".sha256.txt")
    checksum_path.write_text(f"{sha256_file(zip_path)}  {zip_path.name}\n", encoding="ascii")
    return permanent_directory, zip_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the NetBird company-laptop client")
    return parser


def main(argv=None) -> int:
    build_parser().parse_args(argv)
    directory, zip_path = package_remote_client()
    print(
        json.dumps(
            {
                "server_ip_user_configurable": True,
                "release_directory": str(directory),
                "release_zip": str(zip_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
