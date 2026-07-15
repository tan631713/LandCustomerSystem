import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from customer_error_handler import (
    build_exception_handler,
    get_error_log_path,
    install_exception_handler,
)


class CustomerErrorHandlerTests(unittest.TestCase):
    def test_unhandled_exception_is_logged_and_shown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fallback = Mock()
            handler = build_exception_handler(temp_dir, fallback)
            try:
                raise RuntimeError("dialog contract failed")
            except RuntimeError:
                exception_info = sys.exc_info()

            with patch(
                "customer_error_handler._show_exception_message",
                return_value=True,
            ) as show_message:
                handler(*exception_info)

            log_path = get_error_log_path(temp_dir)
            self.assertTrue(log_path.is_file())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("RuntimeError: dialog contract failed", log_text)
            show_message.assert_called_once()
            fallback.assert_called_once()

    def test_error_log_path_is_kept_inside_application_directory(self):
        app_directory = Path("C:/example/LandCustomerSystem")
        self.assertEqual(
            get_error_log_path(app_directory),
            app_directory / "logs" / "application-error.log",
        )

    def test_installation_is_idempotent(self):
        original_handler = sys.excepthook
        try:
            first = install_exception_handler("C:/example")
            second = install_exception_handler("C:/different")
            self.assertIs(first, second)
            self.assertIs(sys.excepthook, first)
        finally:
            sys.excepthook = original_handler


if __name__ == "__main__":
    unittest.main()
