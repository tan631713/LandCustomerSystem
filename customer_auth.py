"""Authentication dialog kept independent from the main application window."""

import math
import time

from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from customer_responsive_dialog import ResponsiveDialog as QDialog
from customer_ui_loader import find_child, install_ui

from customer_messages import (
    fixed_admin_account_message,
    login_failed_message,
    login_locked_message,
)

ADMIN_USERNAME = "admin"
CREATE_ADMIN_USER = None
AUTHENTICATE_USER = None
MIN_PASSWORD_LENGTH = 10
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 30


def validate_new_password(password):
    if len(str(password or "")) < MIN_PASSWORD_LENGTH:
        return f"密碼至少需要 {MIN_PASSWORD_LENGTH} 個字元。"
    return None


class LoginAttemptLimiter:
    def __init__(self, max_attempts=MAX_FAILED_ATTEMPTS, lockout_seconds=LOCKOUT_SECONDS, clock=None):
        self.max_attempts = max(1, int(max_attempts))
        self.lockout_seconds = max(1, int(lockout_seconds))
        self.clock = clock or time.monotonic
        self.failures = 0
        self.locked_until = 0.0

    def remaining_lock_seconds(self):
        remaining = self.locked_until - self.clock()
        return max(0, math.ceil(remaining))

    def register_failure(self):
        if self.remaining_lock_seconds():
            return self.remaining_lock_seconds()
        self.failures += 1
        if self.failures < self.max_attempts:
            return 0
        self.failures = 0
        self.locked_until = self.clock() + self.lockout_seconds
        return self.lockout_seconds

    def register_success(self):
        self.failures = 0
        self.locked_until = 0.0


LOGIN_ATTEMPT_LIMITER = LoginAttemptLimiter()


def configure_auth_dialog(*, admin_username, create_admin_user, authenticate_user):
    global ADMIN_USERNAME, CREATE_ADMIN_USER, AUTHENTICATE_USER
    ADMIN_USERNAME = admin_username
    CREATE_ADMIN_USER = create_admin_user
    AUTHENTICATE_USER = authenticate_user


class AuthDialog(QDialog):
    # Layout: ui/dialogs/auth_dialog.ui (the 確認密碼 row only shows in setup mode).
    ui_file = "dialogs/auth_dialog.ui"
    ui_object_names = (
        "topLabel",
        "usernameEdit",
        "passwordEdit",
        "confirmLabel",
        "confirmEdit",
        "submitButton",
    )
    SETUP_EXTRA_HEIGHT = 30

    def __init__(self, setup_mode=False, parent=None, attempt_limiter=None):
        super().__init__(parent)
        self.setup_mode = setup_mode
        self.encryption_key = None
        self.attempt_limiter = attempt_limiter or LOGIN_ATTEMPT_LIMITER

        self.setModal(True)
        self.create_layout()

    def create_layout(self):
        content = install_ui(self, self.ui_file, self.ui_object_names)
        if self.setup_mode:
            self.setWindowTitle("設定密碼")
            self.setFixedSize(
                self.minimumWidth(), self.minimumHeight() + self.SETUP_EXTRA_HEIGHT
            )

        self.username_edit = find_child(content, "usernameEdit", QLineEdit)
        self.username_edit.setText(ADMIN_USERNAME if self.setup_mode else "")
        self.password_edit = find_child(content, "passwordEdit", QLineEdit)
        self.confirm_edit = find_child(content, "confirmEdit", QLineEdit)
        find_child(content, "confirmLabel", QLabel).setVisible(self.setup_mode)
        self.confirm_edit.setVisible(self.setup_mode)

        if self.setup_mode:
            find_child(content, "topLabel", QLabel).setText("第一次啟動，請設定 admin 密碼")
        submit_button = find_child(content, "submitButton", QPushButton)
        if self.setup_mode:
            submit_button.setText("建立密碼")
        submit_button.clicked.connect(self.submit)

        self.password_edit.returnPressed.connect(self.submit)
        self.confirm_edit.returnPressed.connect(self.submit)
        self.password_edit.setFocus()

    def submit(self):
        username = self.username_edit.text().strip()
        password = self.password_edit.text()

        if self.setup_mode:
            if username != ADMIN_USERNAME:
                QMessageBox.warning(self, "帳號錯誤", fixed_admin_account_message(ADMIN_USERNAME))
                return
            policy_error = validate_new_password(password)
            if policy_error:
                QMessageBox.warning(self, "密碼太短", policy_error)
                return
            if password != self.confirm_edit.text():
                QMessageBox.warning(self, "密碼不一致", "兩次輸入的密碼不一致。")
                return
            CREATE_ADMIN_USER(password)
            self.encryption_key = AUTHENTICATE_USER(username, password)
            self.accept()
            return

        remaining_lock = self.attempt_limiter.remaining_lock_seconds()
        if remaining_lock:
            QMessageBox.warning(
                self,
                "登入暫時鎖定",
                login_locked_message(remaining_lock),
            )
            return

        encryption_key = AUTHENTICATE_USER(username, password)
        if not encryption_key:
            lock_seconds = self.attempt_limiter.register_failure()
            if lock_seconds:
                QMessageBox.warning(
                    self,
                    "登入暫時鎖定",
                    login_locked_message(lock_seconds),
                )
            else:
                QMessageBox.warning(self, "登入失敗", login_failed_message())
            return

        self.attempt_limiter.register_success()
        self.encryption_key = encryption_key
        self.accept()
