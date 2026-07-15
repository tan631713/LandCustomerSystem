import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import customer_auth as auth


class CustomerAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_new_password_policy_requires_ten_characters(self):
        self.assertIsNotNone(auth.validate_new_password("123456789"))
        self.assertIsNone(auth.validate_new_password("1234567890"))

    def test_login_attempt_limiter_locks_and_resets(self):
        now = [100.0]
        limiter = auth.LoginAttemptLimiter(
            max_attempts=3,
            lockout_seconds=30,
            clock=lambda: now[0],
        )
        self.assertEqual(limiter.register_failure(), 0)
        self.assertEqual(limiter.register_failure(), 0)
        self.assertEqual(limiter.register_failure(), 30)
        self.assertEqual(limiter.remaining_lock_seconds(), 30)
        now[0] += 29.2
        self.assertEqual(limiter.remaining_lock_seconds(), 1)
        now[0] += 0.8
        self.assertEqual(limiter.remaining_lock_seconds(), 0)
        limiter.register_failure()
        limiter.register_success()
        self.assertEqual(limiter.failures, 0)
        self.assertEqual(limiter.remaining_lock_seconds(), 0)

    def test_auth_dialog_stops_authentication_while_locked(self):
        now = [200.0]
        limiter = auth.LoginAttemptLimiter(
            max_attempts=2,
            lockout_seconds=30,
            clock=lambda: now[0],
        )
        with (
            patch.object(auth, "AUTHENTICATE_USER", return_value=None) as authenticate,
            patch.object(auth.QMessageBox, "warning"),
        ):
            dialog = auth.AuthDialog(setup_mode=False, attempt_limiter=limiter)
            dialog.password_edit.setText("wrong-password")
            dialog.submit()
            dialog.submit()
            dialog.submit()
            self.assertEqual(authenticate.call_count, 2)
            self.assertEqual(limiter.remaining_lock_seconds(), 30)
            dialog.close()


if __name__ == "__main__":
    unittest.main()
