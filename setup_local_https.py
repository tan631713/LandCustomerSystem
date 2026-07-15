"""Create a private local CA and HTTPS certificate for the iPhone web app.

The CA key and server key stay under the current Windows user's LocalAppData.
Only the public ``.cer`` file needs to be installed and trusted on the iPhone.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


APP_DIRECTORY_NAME = "LandCustomerSystem"
CERTIFICATE_DIRECTORY_NAME = "certificates"
DEFAULT_PORT = 8732
NETBIRD_IPV4_NETWORK = ipaddress.ip_network("100.64.0.0/10")


@dataclass(frozen=True)
class CertificatePaths:
    directory: Path
    ca_certificate_pem: Path
    ca_certificate_der: Path
    ca_private_key: Path
    server_certificate: Path
    server_private_key: Path
    report: Path


def default_certificate_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return root / APP_DIRECTORY_NAME / CERTIFICATE_DIRECTORY_NAME


def certificate_paths(directory: Path | str | None = None) -> CertificatePaths:
    root = Path(directory or default_certificate_directory()).resolve()
    return CertificatePaths(
        directory=root,
        ca_certificate_pem=root / "land-customer-local-ca.pem",
        ca_certificate_der=root / "land-customer-local-ca.cer",
        ca_private_key=root / "land-customer-local-ca-key.pem",
        server_certificate=root / "land-customer-server-cert.pem",
        server_private_key=root / "land-customer-server-key.pem",
        report=root / "local-https-report.json",
    )


def local_ip_address() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
    except OSError:
        address = socket.gethostbyname(socket.gethostname())
    finally:
        probe.close()
    return address


def netbird_cli_path() -> Path | None:
    candidates = [
        shutil.which("netbird.exe"),
        shutil.which("netbird"),
        str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NetBird" / "netbird.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def netbird_ipv4_addresses() -> list[str]:
    """Return this device's stable NetBird IPv4 addresses when connected."""

    executable = netbird_cli_path()
    if executable is None:
        return []
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [str(executable), "status", "--ipv4"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []
    addresses: list[str] = []
    for line in completed.stdout.splitlines():
        try:
            address = ipaddress.ip_address(line.strip())
        except ValueError:
            continue
        if address.version == 4 and address in NETBIRD_IPV4_NETWORK:
            value = str(address)
            if value not in addresses:
                addresses.append(value)
    return addresses


def lan_ipv4_addresses(*, prefer_vpn: bool = False) -> list[str]:
    """Return usable IPv4 addresses, preferring the interface with the default route.

    A notebook can retain addresses from Wi-Fi, Ethernet, VPN and a phone hotspot at
    the same time.  Printing and certifying every usable address avoids presenting a
    stale Wi-Fi address after the user switches to a hotspot.
    """

    addresses: list[str] = []

    def add(candidate) -> None:
        try:
            address = ipaddress.ip_address(str(candidate).strip())
        except ValueError:
            return
        if (
            address.version != 4
            or address.is_loopback
            or address.is_unspecified
            or address.is_link_local
            or address.is_multicast
        ):
            return
        value = str(address)
        if value not in addresses:
            addresses.append(value)

    try:
        add(local_ip_address())
    except OSError:
        pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(item[4][0])
    except OSError:
        pass
    vpn_addresses = netbird_ipv4_addresses()
    for address in vpn_addresses:
        add(address)
    if prefer_vpn and vpn_addresses:
        vpn_set = set(vpn_addresses)
        addresses = [*vpn_addresses, *(item for item in addresses if item not in vpn_set)]
    return addresses


def certificate_names(*, prefer_vpn: bool = False) -> tuple[list[str], list[ipaddress.IPv4Address]]:
    dns_names = {"localhost", socket.gethostname().strip()}
    ip_addresses = {ipaddress.ip_address("127.0.0.1")}
    for address in lan_ipv4_addresses(prefer_vpn=prefer_vpn):
        ip_addresses.add(ipaddress.ip_address(address))
    return sorted(name for name in dns_names if name), sorted(ip_addresses, key=str)


def _write_private_key(path: Path, key) -> None:
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _new_ca(paths: CertificatePaths, now: datetime):
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Land Customer System"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Land Customer System Local CA"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    _write_private_key(paths.ca_private_key, key)
    paths.ca_certificate_pem.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    paths.ca_certificate_der.write_bytes(certificate.public_bytes(serialization.Encoding.DER))
    return key, certificate


def _load_or_create_ca(paths: CertificatePaths, now: datetime):
    if paths.ca_private_key.exists() and paths.ca_certificate_pem.exists():
        try:
            key = serialization.load_pem_private_key(paths.ca_private_key.read_bytes(), password=None)
            certificate = x509.load_pem_x509_certificate(paths.ca_certificate_pem.read_bytes())
            certificate.extensions.get_extension_for_class(x509.AuthorityKeyIdentifier)
            if certificate.not_valid_after_utc > now + timedelta(days=30):
                paths.ca_certificate_der.write_bytes(certificate.public_bytes(serialization.Encoding.DER))
                return key, certificate, False
        except (OSError, ValueError, TypeError, x509.ExtensionNotFound):
            pass
    key, certificate = _new_ca(paths, now)
    return key, certificate, True


def create_local_https_certificate(
    directory: Path | str | None = None,
    *,
    port=DEFAULT_PORT,
    prefer_vpn: bool = False,
) -> dict:
    paths = certificate_paths(directory)
    paths.directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ca_key, ca_certificate, ca_created = _load_or_create_ca(paths, now)
    dns_names, ip_addresses = certificate_names(prefer_vpn=prefer_vpn)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Land Customer System"),
            x509.NameAttribute(NameOID.COMMON_NAME, dns_names[0]),
        ]
    )
    san_names = [x509.DNSName(name) for name in dns_names]
    san_names.extend(x509.IPAddress(address) for address in ip_addresses)
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_certificate.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_private_key(paths.server_private_key, server_key)
    paths.server_certificate.write_bytes(server_certificate.public_bytes(serialization.Encoding.PEM))

    lan_addresses = lan_ipv4_addresses(prefer_vpn=prefer_vpn)
    vpn_addresses = netbird_ipv4_addresses()
    preferred_ip = lan_addresses[0] if lan_addresses else "127.0.0.1"
    report = {
        "status": "ok",
        "ca_created": ca_created,
        "created_at": now.isoformat(),
        "expires_at": server_certificate.not_valid_after_utc.isoformat(),
        "iphone_url": f"https://{preferred_ip}:{int(port)}/mobile/",
        "iphone_urls": [
            f"https://{address}:{int(port)}/mobile/" for address in lan_addresses
        ],
        "vpn_urls": [
            f"https://{address}:{int(port)}/mobile/" for address in vpn_addresses
        ],
        "netbird_ipv4_addresses": vpn_addresses,
        "local_url": f"https://127.0.0.1:{int(port)}/mobile/",
        "dns_names": dns_names,
        "ip_addresses": [str(address) for address in ip_addresses],
        "ca_certificate_for_iphone": str(paths.ca_certificate_der),
        "server_certificate": str(paths.server_certificate),
        "server_private_key": str(paths.server_private_key),
    }
    paths.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="建立土地資料系統區網 HTTPS 憑證")
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--prefer-vpn", action="store_true", help="優先顯示 NetBird 私人 VPN IP")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    report = create_local_https_certificate(
        args.directory,
        port=args.port,
        prefer_vpn=args.prefer_vpn,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\n請將 ca_certificate_for_iphone 指向的 .cer 檔安裝並在 iPhone 啟用完整信任。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
