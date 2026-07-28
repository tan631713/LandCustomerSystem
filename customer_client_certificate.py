"""Trust-on-first-use certificate setup for the remote desktop client."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from customer_client_connection import normalize_server_api_url


CERTIFICATE_PORT = 8733
CERTIFICATE_PATH = "/land-customer-local-ca.cer"
MAX_CERTIFICATE_BYTES = 64 * 1024
EXPECTED_CA_COMMON_NAME = "Land Customer System Local CA"


class ClientCertificateError(RuntimeError):
    """The server CA could not be downloaded, validated, or trusted."""


@dataclass(frozen=True)
class ServerCertificateInfo:
    server_ip: str
    fingerprint_sha256: str
    pem_bytes: bytes
    der_bytes: bytes
    subject: str
    expires_at: str

    @property
    def display_fingerprint(self):
        return " ".join(
            self.fingerprint_sha256[index : index + 4]
            for index in range(0, len(self.fingerprint_sha256), 4)
        )


def default_client_certificate_directory():
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    return local_app_data / "LandCustomerSystem" / "desktop-client" / "certificates"


def _server_ip(api_url):
    parsed = urlparse(normalize_server_api_url(api_url))
    return str(parsed.hostname)


def stored_server_ca_path(api_url, directory=None):
    server_ip = _server_ip(api_url)
    root = Path(directory or default_client_certificate_directory()).resolve()
    return root / f"land-customer-ca-{server_ip.replace('.', '-')}.pem"


def _validate_certificate(certificate, server_ip, der_bytes):
    try:
        common_name = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        basic_constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
        key_usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    except (IndexError, x509.ExtensionNotFound) as exc:
        raise ClientCertificateError("伺服器公開憑證缺少必要的 CA 資訊。") from exc

    if common_name != EXPECTED_CA_COMMON_NAME:
        raise ClientCertificateError("下載內容不是土地資料系統的公開 CA 憑證。")
    if certificate.subject != certificate.issuer:
        raise ClientCertificateError("伺服器公開 CA 不是自我簽署憑證。")
    if not basic_constraints.ca or not key_usage.key_cert_sign:
        raise ClientCertificateError("伺服器公開憑證沒有 CA 簽署權限。")

    now = datetime.now(timezone.utc)
    if not (certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc):
        raise ClientCertificateError("伺服器公開 CA 尚未生效或已過期。")

    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise ClientCertificateError("伺服器公開 CA 使用了不支援的金鑰格式。")
    try:
        public_key.verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            padding.PKCS1v15(),
            certificate.signature_hash_algorithm,
        )
    except Exception as exc:
        raise ClientCertificateError("伺服器公開 CA 的自我簽章驗證失敗。") from exc

    return ServerCertificateInfo(
        server_ip=server_ip,
        fingerprint_sha256=hashlib.sha256(der_bytes).hexdigest().upper(),
        pem_bytes=certificate.public_bytes(serialization.Encoding.PEM),
        der_bytes=bytes(der_bytes),
        subject=certificate.subject.rfc4514_string(),
        expires_at=certificate.not_valid_after_utc.isoformat(),
    )


def certificate_info_from_bytes(payload, server_ip):
    payload = bytes(payload)
    if not payload or len(payload) > MAX_CERTIFICATE_BYTES:
        raise ClientCertificateError("伺服器公開憑證大小不正確。")
    try:
        if b"-----BEGIN CERTIFICATE-----" in payload:
            certificate = x509.load_pem_x509_certificate(payload)
        else:
            certificate = x509.load_der_x509_certificate(payload)
    except ValueError as exc:
        raise ClientCertificateError("伺服器回傳的公開憑證格式不正確。") from exc
    der_bytes = certificate.public_bytes(serialization.Encoding.DER)
    return _validate_certificate(certificate, str(server_ip), der_bytes)


def download_server_ca(api_url, *, urlopen_fn=None, timeout_seconds=6):
    server_ip = _server_ip(api_url)
    certificate_url = f"http://{server_ip}:{CERTIFICATE_PORT}{CERTIFICATE_PATH}"
    opener = urlopen_fn or urlopen
    request = Request(
        certificate_url,
        headers={"Accept": "application/x-x509-ca-cert"},
        method="GET",
    )
    try:
        with opener(request, timeout=max(1, int(timeout_seconds))) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else certificate_url
            final = urlparse(final_url)
            if (
                final.scheme != "http"
                or final.hostname != server_ip
                or (final.port or 80) != CERTIFICATE_PORT
                or final.path != CERTIFICATE_PATH
            ):
                raise ClientCertificateError("公開憑證下載被重新導向到非預期位置。")
            payload = response.read(MAX_CERTIFICATE_BYTES + 1)
    except ClientCertificateError:
        raise
    except Exception as exc:
        raise ClientCertificateError(
            f"無法從家中伺服器取得公開 CA（{server_ip}:{CERTIFICATE_PORT}）：{exc}"
        ) from exc
    return certificate_info_from_bytes(payload, server_ip)


def _read_stored_certificate(path, server_ip):
    try:
        return certificate_info_from_bytes(path.read_bytes(), server_ip)
    except (OSError, ClientCertificateError):
        return None


def ensure_trusted_server_ca(
    api_url,
    *,
    confirm_callback,
    storage_directory=None,
    urlopen_fn=None,
):
    """Download and pin the home server CA after an explicit user confirmation."""

    server_ip = _server_ip(api_url)
    destination = stored_server_ca_path(api_url, storage_directory)
    existing = _read_stored_certificate(destination, server_ip) if destination.is_file() else None
    try:
        downloaded = download_server_ca(api_url, urlopen_fn=urlopen_fn)
    except ClientCertificateError:
        if existing is not None:
            return destination
        raise

    if existing and existing.fingerprint_sha256 == downloaded.fingerprint_sha256:
        return destination
    if not confirm_callback(downloaded, existing):
        raise ClientCertificateError("使用者取消信任家中伺服器公開憑證。")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(downloaded.pem_bytes)
    temporary.replace(destination)
    return destination
