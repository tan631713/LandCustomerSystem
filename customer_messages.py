"""Human-readable messages shown by the desktop UI.

Keeping user-facing wording here makes error handling more consistent and keeps
low-level exception text from leaking into dialogs without context.
"""


def _detail_text(error):
    text = str(error or "").strip()
    return text or error.__class__.__name__


def _path_text(path):
    return str(path) if path else "未產生備份檔"


def operation_error_message(action, error, suggestion):
    return (
        f"{action}時發生問題。\n\n"
        f"建議處理：{suggestion}\n\n"
        f"技術訊息：{_detail_text(error)}"
    )


def fixed_admin_account_message(admin_username="admin"):
    return f"這套系統目前使用固定管理帳號「{admin_username}」。請保留帳號不變，只設定密碼即可。"


def login_failed_message():
    return "帳號或密碼不正確。請確認是否使用 admin 帳號，以及密碼是否輸入正確。"


def login_locked_message(seconds):
    return f"登入失敗次數過多，系統已暫時鎖定。請等待 {seconds} 秒後再試。"


def startup_backup_notice(path):
    return (
        "系統今天已自動建立資料庫備份。\n\n"
        f"備份位置：{_path_text(path)}\n\n"
        "你可以繼續使用系統；這只是安全提醒。"
    )


def backup_status_guidance(status):
    if not status.database_healthy:
        return "資料庫完整性檢查未通過。請先不要大量修改資料，建議立即確認備份或聯絡維護人員。"
    if status.backup_count == 0:
        return "目前還沒有任何備份。建議到「設定 → 立即備份」先建立一份備份。"
    if status.backup_stale:
        return "最近一次備份已超過建議天數。建議現在立即備份一次。"
    return "資料庫與備份狀態正常。"


def backup_status_warning_message(status):
    return f"備份提醒：{status.short_text}。{backup_status_guidance(status)}"


def backup_success_message(path):
    return (
        "備份已完成。\n\n"
        f"備份位置：{_path_text(path)}\n\n"
        "建議保留這份檔案，不要手動改名或刪除。"
    )


def backup_failure_message(error):
    return operation_error_message(
        "建立備份",
        error,
        "請確認磁碟空間是否足夠、備份資料夾是否可寫入，然後再試一次。",
    )


def backup_management_failure_message(error):
    return operation_error_message(
        "執行備份管理",
        error,
        "原有備份會保留。請確認磁碟空間與 backups 資料夾權限後再試一次。",
    )


def safety_backup_failure_message(error):
    return operation_error_message(
        "建立自動安全備份",
        error,
        "系統會繼續執行，但建議先手動備份後再進行大量修改或刪除。",
    )


def restore_confirmation_message():
    return (
        "還原後會用選取的備份檔覆蓋目前資料庫。\n\n"
        "系統會先替目前資料建立一份安全備份，還原完成後會關閉程式。\n\n"
        "確定要繼續還原嗎？"
    )


def restore_success_message(current_backup_path):
    return (
        "備份已還原完成。\n\n"
        f"還原前的目前資料已備份到：{_path_text(current_backup_path)}\n\n"
        "請重新開啟系統後再登入使用。"
    )


def restore_failure_message(error):
    return operation_error_message(
        "還原備份",
        error,
        "請確認選取的是系統產生的 .db 或 .zip 備份檔；目前資料庫尚未被替換。",
    )


def database_save_failure_message(error):
    return operation_error_message(
        "儲存資料",
        error,
        "請檢查欄位內容是否重複或格式異常；若持續發生，請先立即備份。",
    )


def password_change_failure_message(error):
    return operation_error_message(
        "修改密碼",
        error,
        "請確認目前密碼正確；若仍失敗，請先備份資料庫後再重試。",
    )


def password_changed_message(backup_path):
    backup_text = f"\n\n密碼變更前已建立備份：{backup_path}" if backup_path else ""
    return f"登入密碼已更新。{backup_text}"
