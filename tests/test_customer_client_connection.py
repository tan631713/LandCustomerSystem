import unittest

from customer_client_connection import normalize_server_api_url, server_ip_from_api_url


class CustomerClientConnectionTests(unittest.TestCase):
    def test_accepts_plain_netbird_ip(self):
        self.assertEqual(
            normalize_server_api_url("100.107.252.170"),
            "https://100.107.252.170:8732",
        )

    def test_accepts_canonical_https_url(self):
        self.assertEqual(
            normalize_server_api_url("https://100.100.100.100:8732/"),
            "https://100.100.100.100:8732",
        )
        self.assertEqual(
            server_ip_from_api_url("https://100.100.100.100:8732"),
            "100.100.100.100",
        )

    def test_rejects_non_netbird_or_insecure_addresses(self):
        for value in (
            "192.168.1.20",
            "http://100.100.100.100:8732",
            "https://100.100.100.100:5432",
            "https://example.com:8732",
            "https://100.100.100.100:8732/mobile/",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_server_api_url(value)


if __name__ == "__main__":
    unittest.main()
