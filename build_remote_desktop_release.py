"""Build a company-laptop desktop client that connects to the home API over NetBird."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from customer_version import APP_VERSION, BUILD_DATE
from setup_local_https import NETBIRD_IPV4_NETWORK, certificate_paths, netbird_ipv4_addresses


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
RELEASES = ROOT / "releases"
DESKTOP_DIST = DIST / "LandCustomerSystem"
CLIENT_FILES = (
    "start_company_laptop_desktop.bat",
    "setup_netbird_client.bat",
    "company_client_preflight.ps1",
    "公司筆電遠端使用說明.txt",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def validate_server_ip(value: str) -> str:
    address = ipaddress.ip_address(str(value).strip())
    if address.version != 4 or address not in NETBIRD_IPV4_NETWORK:
        raise ValueError("Home server IP must be a NetBird IPv4 address in 100.64.0.0/10")
    return str(address)


def resolve_server_ip(explicit: str | None) -> str:
    if explicit:
        return validate_server_ip(explicit)
    addresses = netbird_ipv4_addresses()
    if not addresses:
        raise RuntimeError("NetBird is not connected; provide --server-ip explicitly")
    return validate_server_ip(addresses[0])


def package_remote_client(server_ip: str) -> tuple[Path, Path]:
    server_ip = validate_server_ip(server_ip)
    if not DESKTOP_DIST.is_dir():
        raise FileNotFoundError("Build the desktop EXE before packaging the remote client")
    for name in CLIENT_FILES:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(f"Missing remote client file: {name}")

    ca_source = certificate_paths().ca_certificate_pem
    if not ca_source.is_file():
        raise FileNotFoundError("The public local CA certificate has not been created")
    ca_bytes = ca_source.read_bytes()
    if b"BEGIN CERTIFICATE" not in ca_bytes or b"PRIVATE KEY" in ca_bytes:
        raise RuntimeError("Remote client CA payload is not a public-only PEM certificate")

    RELEASES.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    release_name = f"LandCustomerSystem-CompanyLaptopClient-v{APP_VERSION}-{timestamp}"
    with tempfile.TemporaryDirectory(prefix="land-customer-client-", dir=RELEASES) as temporary:
        bundle = Path(temporary) / release_name
        shutil.copytree(DESKTOP_DIST, bundle / "LandCustomerSystem")
        for name in CLIENT_FILES:
            shutil.copy2(ROOT / name, bundle / name)
        (bundle / "home_server_ip.txt").write_text(server_ip + "\n", encoding="ascii")
        (bundle / "land-customer-local-ca.pem").write_bytes(ca_bytes)
        (bundle / "LandCustomerSystem" / "company-client-config.json").write_text(
            json.dumps(
                {
                    "api_url": f"https://{server_ip}:8732",
                    "ca_certificate": "../land-customer-local-ca.pem",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        manifest = {
            "product": "LandCustomerSystem Company Laptop Client",
            "version": APP_VERSION,
            "build_date": BUILD_DATE,
            "packaged_at": datetime.now().astimezone().isoformat(),
            "home_server_ip": server_ip,
            "api_url": f"https://{server_ip}:8732",
            "desktop_executable": "LandCustomerSystem/LandCustomerSystem.exe",
            "database_included": False,
            "postgresql_credentials_included": False,
            "server_executable_included": False,
            "private_keys_included": False,
            "public_ca_included": True,
            "direct_exe_click_forces_remote_mode": True,
        }
        (bundle / "client-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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
    parser.add_argument("--server-ip")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    server_ip = resolve_server_ip(args.server_ip)
    directory, zip_path = package_remote_client(server_ip)
    print(
        json.dumps(
            {
                "server_ip": server_ip,
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
