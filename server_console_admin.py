"""Local-only admin/migration subcommands for LandCustomerServer.exe.

These exist only for LandCustomerServerConsole.exe to call on the home
server itself: never over the network, and never with a password on the
command line. Input is one JSON object on stdin (or nothing at all for
admin-list) and the reply is a single JSON line, so the console never has to
scrape human-readable text or risk a password reaching a log file.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from pathlib import Path

from customer_api.local_postgres import load_postgres_dsn
from customer_recovery_account import recover_admin_password
from customer_security import hash_password


_ADMIN_LOCK_KEY = 741_202_607  # same advisory-lock key used by recover_admin_password
MIN_PASSWORD_LENGTH = 10
MAX_USERNAME_LENGTH = 100
MIGRATION_SUFFIX = ".lcs-migration.zip"


def _read_stdin_json():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("輸入格式不正確，未執行任何操作。") from exc
    if not isinstance(payload, dict):
        raise ValueError("輸入格式不正確，未執行任何操作。")
    return payload


def _emit(status, message, **extra):
    print(json.dumps({"status": status, "message": message, **extra}, ensure_ascii=False))
    return 0 if status == "ok" else 1


def _account_count(dsn):
    import psycopg

    with psycopg.connect(dsn, connect_timeout=5) as connection:
        row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
        return int(row[0])


def _clean_username(value):
    username = str(value or "").strip()
    if not username:
        return None, "管理員帳號不可空白。"
    if len(username) > MAX_USERNAME_LENGTH:
        return None, f"管理員帳號最多 {MAX_USERNAME_LENGTH} 個字元。"
    if any(ord(character) < 32 for character in username):
        return None, "管理員帳號不可包含控制字元。"
    return username, None


def run_admin_list(argv=None):
    import psycopg

    try:
        dsn = load_postgres_dsn()
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            account_count = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            rows = connection.execute(
                """
                SELECT username FROM users
                WHERE role = 'admin' AND active
                ORDER BY CASE WHEN lower(username) = 'admin' THEN 0 ELSE 1 END, username
                """
            ).fetchall()
        return _emit(
            "ok", "", account_count=account_count, admins=[str(row[0]) for row in rows]
        )
    except Exception as exc:  # noqa: BLE001 - single JSON contract for the console
        return _emit("error", f"無法讀取帳號清單：{exc}")


def run_admin_recover(argv=None):
    try:
        payload = _read_stdin_json()
        target_username = str(payload.get("target_username") or "admin").strip() or "admin"
        verify_username = str(payload.get("verify_username") or "").strip()
        verify_password = str(payload.get("verify_password") or "")
        new_password = str(payload.get("new_password") or "")
        if not verify_username or not verify_password or not new_password:
            return _emit("error", "驗證帳號、驗證密碼與新密碼皆為必填，未執行任何操作。")
        if len(new_password) < MIN_PASSWORD_LENGTH:
            return _emit("error", "新的管理員密碼至少需要 10 個字元，未執行任何操作。")
        dsn = load_postgres_dsn()
        if _account_count(dsn) == 0:
            return _emit(
                "error",
                "資料庫目前沒有任何帳號，無法用「驗證既有帳號」的方式恢復。"
                "請改用「建立第一個管理員」，或先匯入遷移包。",
            )
        try:
            recover_admin_password(
                dsn, verify_username, verify_password, new_password, target_username
            )
        except ValueError as exc:
            message = str(exc)
            # unwrap_account_data_key() 的措辭是為帳號恢復檔匯入寫的（「新帳號」），
            # 用在這裡的「驗證帳號」情境會誤導使用者，只在這個新增的子命令層
            # 換一個更貼切的說法；底層驗證邏輯與訊息本身完全不變。
            if message.startswith("新帳號密碼不正確"):
                message = "驗證密碼錯誤，原密碼與所有正式資料均未修改。"
            return _emit("error", message)
        return _emit("ok", f"管理員「{target_username}」的密碼已安全重設。")
    except Exception as exc:  # noqa: BLE001
        return _emit("error", f"管理員密碼恢復失敗：{exc}")


def run_admin_bootstrap(argv=None):
    import psycopg

    try:
        payload = _read_stdin_json()
        username, username_error = _clean_username(payload.get("username") or "admin")
        if username_error:
            return _emit("error", username_error)
        password = str(payload.get("password") or "")
        if len(password) < MIN_PASSWORD_LENGTH:
            return _emit("error", "新的管理員密碼至少需要 10 個字元，未執行任何操作。")
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
                ) VALUES (%s, %s, 'admin', TRUE, %s, %s, %s)
                """,
                (username, "系統管理員", password_salt, password_hash, encryption_salt),
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
                    "資料庫原本沒有任何帳號；已在本機控制台建立第一個管理員帳號。",
                    username,
                ),
            )
        return _emit("ok", f"已建立第一個管理員帳號「{username}」。", username=username)
    except Exception as exc:  # noqa: BLE001
        return _emit("error", f"建立第一個管理員失敗：{exc}")


def run_migration_import(argv=None):
    """One JSON in, one JSON out, replacing the old piped-prompt approach.

    A database with zero accounts takes the "empty server" path (only the
    standalone admin account is needed and it becomes the server admin);
    otherwise the unchanged normal import runs and needs the server admin.
    """

    try:
        payload = _read_stdin_json()
        package = Path(str(payload.get("package") or ""))
        source_username = str(payload.get("source_username") or "").strip()
        source_password = str(payload.get("source_password") or "")
        server_username = str(payload.get("server_username") or "").strip()
        server_password = str(payload.get("server_password") or "")
        if not package.name.lower().endswith(MIGRATION_SUFFIX) or not package.is_file():
            return _emit("error", f"找不到遷移包，或副檔名不是 {MIGRATION_SUFFIX}。")
        if not source_username or not source_password:
            return _emit("error", "單機版帳號與密碼為必填，未匯入任何資料。")
        dsn = load_postgres_dsn()
        empty_server = _account_count(dsn) == 0
        if not empty_server and (not server_username or not server_password):
            return _emit("error", "家中伺服器管理員帳號與密碼為必填，未匯入任何資料。")

        from customer_migration_package import (
            import_migration_package,
            import_migration_package_into_empty_server,
        )

        # 匯入流程內部若有任何 print，不能污染這個指令「只回覆一行 JSON」的約定。
        with contextlib.redirect_stdout(io.StringIO()):
            if empty_server:
                result = import_migration_package_into_empty_server(
                    package, dsn,
                    source_username=source_username, source_password=source_password,
                )
            else:
                result = import_migration_package(
                    package, dsn,
                    source_username=source_username, source_password=source_password,
                    server_username=server_username, server_password=server_password,
                )
        imported = (result or {}).get("result") or {}
        return _emit(
            "ok",
            "單機資料已匯入並通過筆數與關聯驗證。",
            mode="empty_server" if empty_server else "normal",
            ownerships=imported.get("ownerships"),
            backup=str((result or {}).get("pre_migration_backup") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return _emit("error", f"匯入遷移包失敗：{exc}")


SUBCOMMANDS = {
    "admin-list": run_admin_list,
    "admin-recover": run_admin_recover,
    "admin-bootstrap": run_admin_bootstrap,
    "migration-import": run_migration_import,
}
