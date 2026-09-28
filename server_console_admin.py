"""Local-only admin recovery/bootstrap subcommands for LandCustomerServer.exe.

Both subcommands exist only for LandCustomerServerConsole.exe to call on the
home server itself: never over the network, and never with the password on
the command line. The password is read once from stdin as JSON and the
result is a single JSON line, so the console never has to scrape
human-readable text or risk the password reaching a log file.
"""

from __future__ import annotations

import json
import os
import sys

from customer_api.local_postgres import load_postgres_dsn
from customer_recovery_account import recover_admin_password
from customer_security import hash_password


_ADMIN_LOCK_KEY = 741_202_607  # same advisory-lock key used by recover_admin_password


def _read_stdin_json():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("輸入格式不正確，未執行任何操作。") from exc
    if not isinstance(payload, dict):
        raise ValueError("輸入格式不正確，未執行任何操作。")
    return payload


def _emit(status, message):
    print(json.dumps({"status": status, "message": message}, ensure_ascii=False))
    return 0 if status == "ok" else 1


def _account_count(dsn):
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as connection:
        row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(row[0])


def run_admin_recover(argv=None):
    try:
        payload = _read_stdin_json()
        verify_username = str(payload.get("verify_username") or "").strip()
        verify_password = str(payload.get("verify_password") or "")
        new_password = str(payload.get("new_password") or "")
        if not verify_username or not verify_password or not new_password:
            return _emit("error", "驗證帳號、驗證密碼與新密碼皆為必填，未執行任何操作。")
        if len(new_password) < 10:
            return _emit("error", "新的 admin 密碼至少需要 10 個字元，未執行任何操作。")
        dsn = load_postgres_dsn()
        if _account_count(dsn) == 0:
            return _emit(
                "error",
                "資料庫目前沒有任何帳號，無法用「驗證既有帳號」的方式恢復。"
                "請改用「建立第一個管理員」，或先匯入遷移包／帳號恢復檔。",
            )
        try:
            recover_admin_password(dsn, verify_username, verify_password, new_password)
        except ValueError as exc:
            message = str(exc)
            # unwrap_account_data_key() 的措辭是為帳號恢復檔匯入寫的（「新帳號」），
            # 用在這裡的「驗證帳號」情境會誤導使用者，只在這個新增的子命令層
            # 換一個更貼切的說法；底層驗證邏輯與訊息本身完全不變。
            if message.startswith("新帳號密碼不正確"):
                message = "驗證密碼錯誤，原密碼與所有正式資料均未修改。"
            return _emit("error", message)
        return _emit("ok", "admin 密碼已安全重設。")
    except Exception as exc:  # noqa: BLE001 - single JSON contract for the console
        return _emit("error", f"admin 密碼恢復失敗：{exc}")


def run_admin_bootstrap(argv=None):
    import psycopg

    try:
        payload = _read_stdin_json()
        password = str(payload.get("password") or "")
        if len(password) < 10:
            return _emit("error", "新的 admin 密碼至少需要 10 個字元，未執行任何操作。")
        dsn = load_postgres_dsn()
        password_salt, password_hash = hash_password(password)
        encryption_salt = os.urandom(16).hex()
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (_ADMIN_LOCK_KEY,))
            count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            if count != 0:
                return _emit(
                    "error",
                    "資料庫已經有帳號，為避免覆蓋既有帳號，操作已停止。",
                )
            # 資料金鑰初始化路徑沿用既有的「第一個帳號」慣例（見
            # customer_repository.create_admin_user / authenticate_user）：
            # wrapped_data_key 留空，實際資料金鑰在第一次登入時直接等於
            # derive_encryption_key(password, encryption_salt)，不另外產生
            # 隨機 Fernet 金鑰。
            connection.execute(
                """
                INSERT INTO users (
                    username, display_name, role, active,
                    password_salt, password_hash, encryption_salt
                ) VALUES ('admin', %s, 'admin', TRUE, %s, %s, %s)
                """,
                ("系統管理員", password_salt, password_hash, encryption_salt),
            )
            connection.execute(
                """
                INSERT INTO operation_logs (
                    action_type, summary, detail, actor_username
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    "admin_bootstrap",
                    "本機控制台建立首位管理員",
                    "資料庫原本沒有任何帳號；已在本機控制台建立第一個 admin 帳號。",
                    "admin",
                ),
            )
        return _emit("ok", "已建立第一個管理員帳號 admin。")
    except Exception as exc:  # noqa: BLE001
        return _emit("error", f"建立第一個管理員失敗：{exc}")


SUBCOMMANDS = {
    "admin-recover": run_admin_recover,
    "admin-bootstrap": run_admin_bootstrap,
}
