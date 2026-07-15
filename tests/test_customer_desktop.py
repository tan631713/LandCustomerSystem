import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from customer_desktop import open_local_path, open_path_or_web_url


class CustomerDesktopTests(unittest.TestCase):
    def test_missing_local_path_shows_visible_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.pdf"
            with patch("customer_desktop.QMessageBox.warning") as warning:
                opened = open_local_path(missing, item_label="附件")
        self.assertFalse(opened)
        warning.assert_called_once()

    def test_windows_open_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "existing.pdf"
            existing.write_bytes(b"test")
            with (
                patch("customer_desktop.QDesktopServices.openUrl", return_value=False),
                patch("customer_desktop.QMessageBox.warning") as warning,
            ):
                opened = open_local_path(existing, item_label="附件")
        self.assertFalse(opened)
        warning.assert_called_once()

    def test_existing_local_path_can_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "existing.pdf"
            existing.write_bytes(b"test")
            with patch("customer_desktop.QDesktopServices.openUrl", return_value=True):
                opened = open_local_path(existing, item_label="附件")
        self.assertTrue(opened)

    def test_http_and_https_urls_open_with_system_browser(self):
        for url in ("http://example.com/path", "https://taobao.tycg.gov.tw/Normal"):
            with self.subTest(url=url):
                with patch("customer_desktop.QDesktopServices.openUrl", return_value=True) as open_url:
                    opened = open_path_or_web_url(url, item_label="附件")
                self.assertTrue(opened)
                self.assertEqual(open_url.call_args.args[0].toString(), url)

    def test_unsafe_or_invalid_external_urls_are_rejected(self):
        for url in ("javascript:alert(1)", "file:///C:/private.txt", "https:/missing-host"):
            with self.subTest(url=url):
                with (
                    patch("customer_desktop.QDesktopServices.openUrl") as open_url,
                    patch("customer_desktop.QMessageBox.warning") as warning,
                ):
                    opened = open_path_or_web_url(url, item_label="附件")
                self.assertFalse(opened)
                open_url.assert_not_called()
                warning.assert_called_once()

    def test_path_or_web_url_keeps_local_file_support(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            existing = Path(temp_dir) / "existing.pdf"
            existing.write_bytes(b"test")
            with patch("customer_desktop.QDesktopServices.openUrl", return_value=True) as open_url:
                opened = open_path_or_web_url(existing, item_label="附件")
        self.assertTrue(opened)
        self.assertTrue(open_url.call_args.args[0].isLocalFile())


if __name__ == "__main__":
    unittest.main()
