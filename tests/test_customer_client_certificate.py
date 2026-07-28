import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

import setup_local_https
from customer_client_certificate import (
    ClientCertificateError,
    download_server_ca,
    ensure_trusted_server_ca,
)


class _CertificateResponse:
    def __init__(self, payload, final_url):
        self.payload = bytes(payload)
        self.final_url = str(final_url)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]

    def geturl(self):
        return self.final_url


class ClientCertificateBootstrapTests(unittest.TestCase):
    API_URL = "https://100.101.102.103:8732"
    CERT_URL = "http://100.101.102.103:8733/land-customer-local-ca.cer"

    @staticmethod
    def _certificate_bytes(directory):
        setup_local_https.create_local_https_certificate(directory)
        return setup_local_https.certificate_paths(directory).ca_certificate_der.read_bytes()

    def test_download_validates_land_customer_ca_and_reports_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            certificate_bytes = self._certificate_bytes(Path(directory) / "server")

            info = download_server_ca(
                self.API_URL,
                urlopen_fn=lambda _request, timeout: _CertificateResponse(
                    certificate_bytes, self.CERT_URL
                ),
            )

        self.assertEqual(info.server_ip, "100.101.102.103")
        self.assertEqual(len(info.fingerprint_sha256), 64)
        self.assertIn(b"BEGIN CERTIFICATE", info.pem_bytes)

    def test_first_connection_requires_confirmation_then_reuses_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            certificate_bytes = self._certificate_bytes(root / "server")
            confirmations = []

            def opener(_request, timeout):
                return _CertificateResponse(certificate_bytes, self.CERT_URL)

            destination = ensure_trusted_server_ca(
                self.API_URL,
                confirm_callback=lambda downloaded, existing: confirmations.append(
                    (downloaded, existing)
                ) or True,
                storage_directory=root / "client",
                urlopen_fn=opener,
            )
            reused = ensure_trusted_server_ca(
                self.API_URL,
                confirm_callback=lambda *_args: self.fail(
                    "unchanged pinned certificate should not prompt again"
                ),
                storage_directory=root / "client",
                urlopen_fn=opener,
            )

            stored = x509.load_pem_x509_certificate(destination.read_bytes())

        self.assertEqual(destination, reused)
        self.assertEqual(len(confirmations), 1)
        self.assertIsNone(confirmations[0][1])
        self.assertEqual(
            stored.public_bytes(serialization.Encoding.DER), certificate_bytes
        )

    def test_rejects_invalid_or_redirected_certificate_download(self):
        with self.assertRaises(ClientCertificateError):
            download_server_ca(
                self.API_URL,
                urlopen_fn=lambda _request, timeout: _CertificateResponse(
                    b"not a certificate", self.CERT_URL
                ),
            )
        with tempfile.TemporaryDirectory() as directory:
            certificate_bytes = self._certificate_bytes(Path(directory) / "server")
            with self.assertRaises(ClientCertificateError):
                download_server_ca(
                    self.API_URL,
                    urlopen_fn=lambda _request, timeout: _CertificateResponse(
                        certificate_bytes,
                        "http://100.99.99.99:8733/land-customer-local-ca.cer",
                    ),
                )


if __name__ == "__main__":
    unittest.main()
