import faulthandler
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from customer_error_handler import (
    build_exception_handler,
    get_error_log_path,
    get_native_crash_log_path,
    install_exception_handler,
    install_native_crash_tracer,
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

    def test_native_crash_log_path_is_kept_inside_application_directory(self):
        app_directory = Path("C:/example/LandCustomerSystem")
        self.assertEqual(
            get_native_crash_log_path(app_directory),
            app_directory / "logs" / "native-crash-trace.log",
        )

    def test_install_native_crash_tracer_enables_faulthandler_and_writes_marker(self):
        # This is the diagnostic added after a native access-violation crash
        # (Windows Application Error, 0xc0000005) recurred across several
        # fix attempts with only a DLL name and byte offset to go on --
        # never enough to actually locate the cause. faulthandler is the
        # stdlib's own mechanism for turning that into a real Python call
        # stack, but it only helps if it was actually armed before the
        # crash, so this pins down that install_native_crash_tracer() does
        # what it claims: enables faulthandler and leaves the log file open
        # and ready to receive a dump.
        was_enabled = faulthandler.is_enabled()
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                log_file = install_native_crash_tracer(temp_dir)
                try:
                    self.assertTrue(faulthandler.is_enabled())
                    log_path = get_native_crash_log_path(temp_dir)
                    self.assertTrue(log_path.is_file())
                    self.assertIn(
                        "faulthandler enabled for this run",
                        log_path.read_text(encoding="utf-8"),
                    )
                finally:
                    faulthandler.disable()
                    log_file.close()
        finally:
            if was_enabled:
                faulthandler.enable()

    def test_install_native_crash_tracer_rotates_an_oversized_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = get_native_crash_log_path(temp_dir)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("x" * (2 * 1024 * 1024 + 1), encoding="utf-8")

            log_file = install_native_crash_tracer(temp_dir)
            try:
                rotated_path = log_path.with_name("native-crash-trace.previous.log")
                self.assertTrue(rotated_path.is_file())
                # The freshly (re)created log should just hold this run's
                # marker line, not the old oversized content.
                self.assertLess(log_path.stat().st_size, 1024)
            finally:
                faulthandler.disable()
                log_file.close()


if __name__ == "__main__":
    unittest.main()
