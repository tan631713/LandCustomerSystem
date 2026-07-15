import unittest
from dataclasses import dataclass

from customer_messages import (
    backup_status_guidance,
    backup_status_warning_message,
    database_save_failure_message,
    login_failed_message,
    login_locked_message,
    restore_confirmation_message,
)


@dataclass
class FakeBackupStatus:
    database_healthy: bool = True
    backup_count: int = 1
    backup_stale: bool = False
    short_text: str = "備份正常"


class CustomerMessageTests(unittest.TestCase):
    def test_operation_error_message_includes_guidance_and_technical_detail(self):
        message = database_save_failure_message(ValueError("duplicate land number"))

        self.assertIn("儲存資料時發生問題", message)
        self.assertIn("建議處理", message)
        self.assertIn("技術訊息：duplicate land number", message)

    def test_login_messages_are_user_friendly(self):
        self.assertIn("admin", login_failed_message())
        self.assertIn("30 秒", login_locked_message(30))

    def test_restore_confirmation_explains_safety_backup(self):
        message = restore_confirmation_message()

        self.assertIn("覆蓋目前資料庫", message)
        self.assertIn("安全備份", message)
        self.assertIn("關閉程式", message)

    def test_backup_status_guidance_matches_health_state(self):
        missing = FakeBackupStatus(backup_count=0, short_text="尚無備份")
        warning = backup_status_warning_message(missing)

        self.assertIn("尚無備份", warning)
        self.assertIn("立即備份", backup_status_guidance(missing))

        unhealthy = FakeBackupStatus(database_healthy=False, short_text="資料庫異常")
        self.assertIn("完整性檢查未通過", backup_status_guidance(unhealthy))


if __name__ == "__main__":
    unittest.main()
